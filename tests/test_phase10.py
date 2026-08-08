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
from backend.gdrive import DriveUploader

# ClipRecorder (decision logic: start/stop by live_count) was retired in Fase 20
# — RecordingWorker now decides when to record, driven by rule-matched events
# with pre/post-buffer context (see tests/test_recording_prepost.py). The pure
# MP4-writing remainder lives in backend.recorder.ClipWriter.


# ---------------------------------------------------------------------------
# DriveUploader
# ---------------------------------------------------------------------------

# ─── on_uploaded se llama con path y Drive ID tras subida exitosa ─────────────
# DriveUploader encola clips y los sube en un hilo separado. Tras una subida
# exitosa, debe llamar a on_uploaded(local_path, gdrive_id) para que main.py
# actualice el estado del recording en BD y emita el evento WebSocket
# 'recording_uploaded' al dashboard.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_044_uploader_calls_on_uploaded_after_success(tmp_path):
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
def TEST_045_uploader_deletes_local_file_after_upload(tmp_path):
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
def TEST_046_uploader_retries_on_failure_then_calls_on_failed(tmp_path):
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
        with patch("backend.gdrive.time.sleep"):
            uploader.start()
            uploader.enqueue(str(clip))
            time.sleep(0.5)
            uploader.stop()
            uploader._thread.join(timeout=3.0)

    assert len(failed) == 1
    assert str(clip) in failed[0]


# ─── Sin credentials.json: on_failed se llama inmediatamente ─────────────────
# Si el fichero credentials.json no existe (Drive no configurado), el uploader
# no debe intentar la subida ni bloquearse esperando OAuth. Debe llamar a
# on_failed de inmediato para que el recording quede marcado como 'failed'
# en lugar de quedarse eternamente en estado 'pending'.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_047_uploader_skips_when_no_credentials(tmp_path):
    """If credentials.json is absent, on_failed is called immediately."""
    clip = tmp_path / "clip_nocreds.mp4"
    clip.write_bytes(b"data")

    failed = []
    uploader = DriveUploader(
        folder_id="F",
        credentials_path=str(tmp_path / "credentials.json"),
        on_failed=lambda p: failed.append(p),
    )

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
async def TEST_048_insert_recording_returns_positive_id(isolated_db):
    """insert_recording returns a positive integer ID."""
    rec_id = await db_module.insert_recording("clip_20260101_120000.mp4")
    assert rec_id > 0


# ─── Nueva grabación se crea con upload_status='pending' ─────────────────────
# El estado inicial 'pending' permite al uploader identificar qué grabaciones
# aún no han sido subidas a Drive. Si se insertara con 'uploaded', el uploader
# las saltaría y nunca se subirían a Google Drive.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_049_insert_recording_default_status_pending(isolated_db):
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
async def TEST_050_update_recording_status_uploaded(isolated_db):
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
async def TEST_051_update_recording_status_failed(isolated_db):
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
async def TEST_052_get_recent_recordings_newest_first(isolated_db):
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
async def TEST_053_api_recordings_returns_list(isolated_db):
    """GET /api/recordings returns a JSON list (possibly empty)."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/recordings")
    assert resp.status_code == 200
    body = resp.json()
    assert "recordings" in body
    assert isinstance(body["recordings"], list)
