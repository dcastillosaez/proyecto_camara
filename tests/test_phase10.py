"""Tests for Phase 10: clip recording, Drive upload, and recordings DB."""
from __future__ import annotations

import datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module

# ClipRecorder (decision logic: start/stop by live_count) was retired in Fase 20
# — RecordingWorker now decides when to record, driven by rule-matched events
# with pre/post-buffer context (see tests/test_recording_prepost.py). The pure
# MP4-writing remainder lives in backend.recorder.ClipWriter.
#
# DriveUploader (thread + in-memory queue + enqueue()/on_uploaded/on_failed)
# was retired in the same phase — uploads are now a DB-backed queue driven by
# RecordingRepo.next_pending()/mark_upload(), see tests/test_upload_queue.py.


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
