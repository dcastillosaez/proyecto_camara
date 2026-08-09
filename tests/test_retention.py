"""Tests for local clip retention — never deletes a file before it's uploaded."""

from __future__ import annotations

import datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module
from backend.storage import models
from backend.storage.repositories import RecordingRepo, UploadState


@pytest_asyncio.fixture
async def db(tmp_path):
    """Also patches backend.database's module-level engine/session factory —
    _purge_local_clip_files (backend.main) calls get_session_factory() internally,
    so it must resolve to this same temp DB, not whatever the app would use."""
    db_file = tmp_path / "retention_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf
    yield sf
    db_module._engine, db_module._session_factory = orig_engine, orig_sf
    await engine.dispose()


async def make_recording(repo, tmp_path, started_at, upload_state, name="clip.mp4"):
    clip = tmp_path / name
    clip.write_bytes(b"fake mp4 data")
    thumb = tmp_path / (name + ".thumb.jpg")
    thumb.write_bytes(b"fake jpeg data")

    rec_id = await repo.create(
        camera_id="cam1", filename=str(clip), started_at=started_at, reason="test",
    )
    await repo.finalize(
        rec_id, ended_at=started_at, duration_s=5.0, size_bytes=13,
        sha256="deadbeef", thumbnail_path=str(thumb), upload_state=upload_state,
    )
    return rec_id, clip, thumb


async def TEST_retention_skips_pending_uploads(db, tmp_path):
    from backend.main import _purge_local_clip_files

    repo = RecordingRepo(db)
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    rec_id, clip, thumb = await make_recording(repo, tmp_path, old, UploadState.PENDING)

    await _purge_local_clip_files(retention_days=7)

    assert clip.exists()
    row = await repo.get(rec_id)
    assert row["local_path"] is not None


async def TEST_retention_deletes_expired(db, tmp_path):
    from backend.main import _purge_local_clip_files

    repo = RecordingRepo(db)
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    rec_id, clip, thumb = await make_recording(repo, tmp_path, old, UploadState.DONE)

    await _purge_local_clip_files(retention_days=7)

    assert not clip.exists()
    assert not thumb.exists()


async def TEST_row_survives_file_deletion(db, tmp_path):
    from backend.main import _purge_local_clip_files

    repo = RecordingRepo(db)
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    rec_id, clip, thumb = await make_recording(repo, tmp_path, old, UploadState.DONE)

    await _purge_local_clip_files(retention_days=7)

    row = await repo.get(rec_id)
    assert row is not None
    assert row["local_path"] is None
    assert row["sha256"] == "deadbeef"  # metadata untouched
