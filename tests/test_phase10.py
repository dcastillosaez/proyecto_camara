"""Tests for Phase 10: clip recording, Drive upload, and recordings DB."""
from __future__ import annotations

import datetime
import os
import queue
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import cv2
import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module
from backend.recorder import ClipRecorder
from backend.gdrive import DriveUploader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_stream(live_count: int = 1, frame: np.ndarray | None = None):
    s = MagicMock()
    s.get_live_count.return_value = live_count
    s.get_frame.return_value = frame if frame is not None else np.zeros((720, 1280, 3), dtype=np.uint8)
    return s


# ---------------------------------------------------------------------------
# ClipRecorder
# ---------------------------------------------------------------------------


# ─── Se crea un fichero .mp4 al detectar una persona ─────────────────────────
# ClipRecorder monitorea get_live_count(). Cuando live_count > 0 abre un
# VideoWriter y escribe frames. Al bajar a 0, espera tail_secs y finaliza el
# clip llamando a on_clip_ready. Este test verifica el flujo completo:
# start → detección → fin de detección → clip listo.
# ─────────────────────────────────────────────────────────────────────────────
def test_recorder_creates_clip_when_person_detected(tmp_path):
    """A .mp4 file appears in clips_dir when live_count > 0."""
    clips_dir = str(tmp_path / "clips")
    stream = _fake_stream(live_count=1)
    ready = threading.Event()
    received = []

    def on_ready(path):
        received.append(path)
        ready.set()

    rec = ClipRecorder(stream, clips_dir=clips_dir, fps=15.0, tail_secs=0.1, on_clip_ready=on_ready)
    rec.start()
    time.sleep(0.3)
    # Drop live count → trigger tail → finalise
    stream.get_live_count.return_value = 0
    ready.wait(timeout=3.0)
    rec.stop()

    assert ready.is_set(), "on_clip_ready was never called"
    assert len(received) == 1
    assert received[0].endswith(".mp4")


# ─── Una sesión continua produce exactamente un clip ─────────────────────────
# Mientras live_count permanezca > 0, el grabador debe seguir escribiendo en
# el mismo VideoWriter sin crear nuevos clips. on_clip_ready debe llamarse
# exactamente una vez al finalizar esa sesión de detección.
# ─────────────────────────────────────────────────────────────────────────────
def test_recorder_calls_on_clip_ready_once_per_session(tmp_path):
    """One continuous detection session produces exactly one clip."""
    clips_dir = str(tmp_path / "clips")
    stream = _fake_stream(live_count=1)
    count = {"n": 0}
    done = threading.Event()

    def on_ready(path):
        count["n"] += 1
        done.set()

    rec = ClipRecorder(stream, clips_dir=clips_dir, fps=15.0, tail_secs=0.1, on_clip_ready=on_ready)
    rec.start()
    time.sleep(0.3)
    stream.get_live_count.return_value = 0
    done.wait(timeout=3.0)
    rec.stop()

    assert count["n"] == 1


# ─── Clips demasiado pequeños se descartan sin llamar on_clip_ready ───────────
# Si get_frame() devuelve None (cámara no disponible), el VideoWriter produce
# un fichero vacío o casi vacío (< 4 KB). Subir ese clip a Drive sería un
# desperdicio y generaría grabaciones corruptas en el historial.
# El grabador verifica el tamaño y descarta clips por debajo del umbral.
# ─────────────────────────────────────────────────────────────────────────────
def test_recorder_discards_empty_clip(tmp_path):
    """Clips too small (<4 KB) do not trigger on_clip_ready."""
    clips_dir = str(tmp_path / "clips")
    # Return None frames so VideoWriter writes nothing useful
    stream = MagicMock()
    stream.get_live_count.side_effect = [1] * 3 + [0] * 100
    stream.get_frame.return_value = None  # no frame → writer writes nothing
    called = []

    rec = ClipRecorder(stream, clips_dir=clips_dir, fps=15.0, tail_secs=0.05, on_clip_ready=lambda p: called.append(p))
    rec.start()
    time.sleep(0.5)
    rec.stop()

    assert called == [], "on_clip_ready should not fire for empty clips"


# ─── stop() libera el VideoWriter sin lanzar excepción ───────────────────────
# Si el servidor se detiene mientras hay una grabación en curso (tail_secs
# largo o detección activa), stop() debe llamar a _finalise() para cerrar
# el VideoWriter correctamente. Sin release(), el fichero .mp4 quedaría
# corrupto e ilegible.
# ─────────────────────────────────────────────────────────────────────────────
def test_recorder_stop_releases_writer(tmp_path):
    """stop() releases any open VideoWriter without crashing."""
    clips_dir = str(tmp_path / "clips")
    stream = _fake_stream(live_count=1)

    rec = ClipRecorder(stream, clips_dir=clips_dir, fps=15.0, tail_secs=10.0)
    rec.start()
    time.sleep(0.2)
    rec.stop()  # must not raise


# ---------------------------------------------------------------------------
# DriveUploader
# ---------------------------------------------------------------------------


# ─── on_uploaded se llama con path y Drive ID tras subida exitosa ─────────────
# DriveUploader encola clips y los sube en un hilo separado. Tras una subida
# exitosa, debe llamar a on_uploaded(local_path, gdrive_id) para que main.py
# actualice el estado del recording en BD y emita el evento WebSocket
# 'recording_uploaded' al dashboard.
# ─────────────────────────────────────────────────────────────────────────────
def test_uploader_calls_on_uploaded_after_success(tmp_path):
    """on_uploaded is called with the local path and Drive ID on success."""
    clip = tmp_path / "clip_test.mp4"
    clip.write_bytes(b"fake video data")

    uploaded = []
    uploader = DriveUploader(
        folder_id="FOLDER",
        credentials_path=str(tmp_path / "credentials.json"),
        on_uploaded=lambda p, gid: uploaded.append((p, gid)),
    )
    uploader._creds_available = True

    with patch("backend.gdrive.upload_file", return_value="gdrive_abc123"):
        uploader.start()
        uploader.enqueue(str(clip))
        time.sleep(0.5)
        uploader.stop()

    assert len(uploaded) == 1
    assert uploaded[0][1] == "gdrive_abc123"


# ─── El fichero local se elimina tras subida exitosa ─────────────────────────
# Los clips .mp4 pueden ocupar varios MB. Una vez subidos a Drive, el fichero
# local debe borrarse para no agotar el espacio en disco del servidor.
# Si el fichero persiste, tras semanas de grabación el disco se llenaría.
# ─────────────────────────────────────────────────────────────────────────────
def test_uploader_deletes_local_file_after_upload(tmp_path):
    """Local clip is removed after successful upload."""
    clip = tmp_path / "clip_del.mp4"
    clip.write_bytes(b"data")

    uploader = DriveUploader(folder_id="F", credentials_path=str(tmp_path / "creds.json"))
    uploader._creds_available = True

    with patch("backend.gdrive.upload_file", return_value="id_xyz"):
        uploader.start()
        uploader.enqueue(str(clip))
        time.sleep(0.5)
        uploader.stop()

    assert not clip.exists(), "Local file should be deleted after upload"


# ─── Reintentos con backoff y llamada a on_failed tras MAX_RETRIES fallos ─────
# La red puede fallar transitoriamente. DriveUploader reintenta hasta
# MAX_RETRIES=3 veces con backoff. Tras agotar los reintentos, llama a
# on_failed(path) para que main.py marque el recording como 'failed' en BD
# y notifique al dashboard sin bloquear indefinidamente.
# ─────────────────────────────────────────────────────────────────────────────
def test_uploader_retries_on_failure_then_calls_on_failed(tmp_path):
    """Calls on_failed after MAX_RETRIES consecutive failures."""
    clip = tmp_path / "clip_fail.mp4"
    clip.write_bytes(b"data")

    failed = []
    uploader = DriveUploader(
        folder_id="F",
        credentials_path=str(tmp_path / "creds.json"),
        on_failed=lambda p: failed.append(p),
    )
    uploader._creds_available = True

    with patch("backend.gdrive.upload_file", side_effect=RuntimeError("network error")):
        with patch("backend.gdrive.time.sleep"):  # skip backoff delays
            uploader.start()
            uploader.enqueue(str(clip))
            time.sleep(0.5)
            uploader.stop()
            uploader._thread.join(timeout=3.0)  # wait inside patch context

    assert len(failed) == 1
    assert str(clip) in failed[0]


# ─── Sin credentials.json: on_failed se llama inmediatamente ─────────────────
# Si el fichero credentials.json no existe (Drive no configurado), el uploader
# no debe intentar la subida ni bloquearse esperando OAuth. Debe llamar a
# on_failed de inmediato para que el recording quede marcado como 'failed'
# en lugar de quedarse eternamente en estado 'pending'.
# ─────────────────────────────────────────────────────────────────────────────
def test_uploader_skips_when_no_credentials(tmp_path):
    """If credentials.json is absent, on_failed is called immediately."""
    clip = tmp_path / "clip_nocreds.mp4"
    clip.write_bytes(b"data")

    failed = []
    uploader = DriveUploader(
        folder_id="F",
        credentials_path=str(tmp_path / "credentials.json"),  # does not exist
        on_failed=lambda p: failed.append(p),
    )
    # _creds_available is False by default when file doesn't exist

    uploader.start()
    uploader.enqueue(str(clip))
    time.sleep(0.3)
    uploader.stop()

    assert len(failed) == 1


# ---------------------------------------------------------------------------
# Database — recordings table
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def isolated_db(tmp_path):
    db_file = tmp_path / "test_rec.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    await db_module.init_db()
    yield

    db_module._engine, db_module._session_factory = orig_engine, orig_sf
    await engine.dispose()


# ─── insert_recording devuelve un ID positivo ─────────────────────────────────
# _on_clip_ready en main.py usa el ID devuelto para llamar luego a
# update_recording(rec_id, ...) y asociar el gdrive_id. Un ID None o negativo
# causaría que la actualización no encontrara la fila correcta en BD.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_insert_recording_returns_positive_id(isolated_db):
    """insert_recording returns a positive integer ID."""
    rec_id = await db_module.insert_recording("clip_20260101_120000.mp4")
    assert rec_id > 0


# ─── Nueva grabación se crea con upload_status='pending' ─────────────────────
# El estado inicial 'pending' permite al uploader identificar qué grabaciones
# aún no han sido subidas a Drive. Si se insertara con 'uploaded', el uploader
# las saltaría y nunca se subirían a Google Drive.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_insert_recording_default_status_pending(isolated_db):
    """Newly inserted recording has upload_status='pending'."""
    rec_id = await db_module.insert_recording("clip_test.mp4")
    recs = await db_module.get_recent_recordings(10)
    rec = next(r for r in recs if r["id"] == rec_id)
    assert rec["upload_status"] == "pending"


# ─── update_recording establece estado 'uploaded' con gdrive_id ──────────────
# Tras una subida exitosa, main.py llama a update_recording(id, 'uploaded',
# gdrive_id). El dashboard usa gdrive_id para construir el enlace de descarga
# de Google Drive. Se verifica que ambos campos se persisten correctamente.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_update_recording_status_uploaded(isolated_db):
    """update_recording sets status to 'uploaded' with gdrive_id."""
    rec_id = await db_module.insert_recording("clip_upd.mp4")
    await db_module.update_recording(rec_id, "uploaded", "drive_xyz")
    recs = await db_module.get_recent_recordings(10)
    rec = next(r for r in recs if r["id"] == rec_id)
    assert rec["upload_status"] == "uploaded"
    assert rec["gdrive_id"] == "drive_xyz"


# ─── update_recording puede marcar una grabación como 'failed' ───────────────
# Cuando on_failed se dispara (sin credenciales o tras MAX_RETRIES fallos),
# main.py llama a update_recording(id, 'failed'). El dashboard muestra un
# icono de error para esa grabación. gdrive_id debe quedar como None.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_update_recording_status_failed(isolated_db):
    """update_recording can set status to 'failed'."""
    rec_id = await db_module.insert_recording("clip_fail.mp4")
    await db_module.update_recording(rec_id, "failed")
    recs = await db_module.get_recent_recordings(10)
    rec = next(r for r in recs if r["id"] == rec_id)
    assert rec["upload_status"] == "failed"
    assert rec["gdrive_id"] is None


# ─── get_recent_recordings devuelve las grabaciones más nuevas primero ────────
# El dashboard muestra el historial de clips ordenado de más reciente a más
# antiguo (DESC por created_at). Un orden incorrecto confundiría al usuario
# al buscar la grabación de la última detección.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_recent_recordings_newest_first(isolated_db):
    """get_recent_recordings returns recordings ordered newest first."""
    for i in range(3):
        await db_module.insert_recording(f"clip_{i:02d}.mp4", datetime.datetime(2026, 1, i + 1, 12, 0))
    recs = await db_module.get_recent_recordings(10)
    assert recs[0]["filename"] == "clip_02.mp4"
    assert recs[-1]["filename"] == "clip_00.mp4"


# ---------------------------------------------------------------------------
# API — GET /api/recordings
# ---------------------------------------------------------------------------

import httpx
from httpx import ASGITransport

import backend.main as main_module


# ─── GET /api/recordings devuelve JSON con lista de grabaciones ───────────────
# El dashboard consulta este endpoint al cargar la página para poblar el
# historial de clips. Debe devolver 200 con un objeto JSON que tenga la clave
# 'recordings' con un array (posiblemente vacío si no hay clips aún).
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_api_recordings_returns_list(isolated_db):
    """GET /api/recordings returns a JSON list (possibly empty)."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/recordings")
    assert resp.status_code == 200
    body = resp.json()
    assert "recordings" in body
    assert isinstance(body["recordings"], list)
