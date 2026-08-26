"""Tests for backend.gdrive.UploadQueue — persistent DB-backed upload queue with backoff."""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.gdrive import UploadQueue, backoff_delay, classify_error
from backend.storage import models
from backend.storage.repositories import RecordingRepo, UploadState


@pytest_asyncio.fixture
async def db(tmp_path):
    db_file = tmp_path / "upload_queue_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield sf
    await engine.dispose()


async def force_retry_now(session_factory, rec_id: int) -> None:
    """Test helper: push next_attempt_at into the past so run_once() retries immediately."""
    async with session_factory() as session:
        async with session.begin():
            row = await session.get(models.Recording, rec_id)
            if row is not None:
                row.next_attempt_at = datetime.datetime.now() - datetime.timedelta(seconds=1)


async def make_pending_recording(repo: RecordingRepo, filename="clip.mp4", camera_id="cam1") -> int:
    rec_id = await repo.create(
        camera_id=camera_id, filename=filename, started_at=datetime.datetime.now(), reason="test",
    )
    await repo.finalize(
        rec_id, ended_at=datetime.datetime.now(), duration_s=5.0, size_bytes=1024,
        sha256="abc", thumbnail_path=None, upload_state=UploadState.PENDING,
    )
    return rec_id


def TEST_backoff_classification():
    assert classify_error(RuntimeError("connection reset")) == "network"
    assert classify_error(RuntimeError("rateLimitExceeded: quota reached")) == "quota"
    assert classify_error(RuntimeError("invalid_grant: token expired")) == "auth"
    assert backoff_delay(0, "quota") > backoff_delay(0, "network")
    assert backoff_delay(1, "network") >= backoff_delay(0, "network")


async def TEST_pending_survives_restart(db):
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo)

    # Simulate a restart: brand-new repo instance over the same DB.
    repo2 = RecordingRepo(db)
    pending = await repo2.next_pending()

    assert any(r.id == rec_id for r in pending)


async def TEST_retry_with_backoff(db):
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo)

    attempts = {"n": 0}

    def flaky_upload(path, folder_id, credentials_path, token_path):
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise RuntimeError("network error")
        return "gdrive-id-1"

    queue = UploadQueue(repo, folder_id="F", credentials_path="creds.json", max_attempts=5, poll_secs=1000)

    with patch("backend.gdrive.upload_file", side_effect=flaky_upload):
        for _ in range(4):
            await queue.run_once()
            await asyncio.sleep(0.05)
            row = await repo.get(rec_id)
            if row["upload_state"] != "done":
                # Force next_attempt_at into the past so run_once() picks it up immediately.
                await force_retry_now(db, rec_id)

    row = await repo.get(rec_id)
    assert attempts["n"] == 4
    assert row["upload_state"] == "done"


async def TEST_token_expired_is_retried(db):
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo)

    calls = {"n": 0}

    def upload_side_effect(path, folder_id, credentials_path, token_path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("invalid_grant: token expired")
        return "gdrive-id-2"

    queue = UploadQueue(repo, folder_id="F", credentials_path="creds.json", max_attempts=5, poll_secs=1000)

    with patch("backend.gdrive.upload_file", side_effect=upload_side_effect):
        await queue.run_once()
        await asyncio.sleep(0.05)
        await force_retry_now(db, rec_id)
        await queue.run_once()
        await asyncio.sleep(0.05)

    row = await repo.get(rec_id)
    assert row["upload_state"] == "done"
    assert calls["n"] == 2


async def TEST_quota_error_backs_off_longer(db):
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo)

    queue = UploadQueue(repo, folder_id="F", credentials_path="creds.json", max_attempts=5, poll_secs=1000)

    with patch("backend.gdrive.upload_file", side_effect=RuntimeError("rateLimitExceeded")):
        await queue.run_once()
        await asyncio.sleep(0.05)

    row = await repo.get(rec_id)
    next_attempt = datetime.datetime.fromisoformat(row["next_attempt_at"]) if row.get("next_attempt_at") else None
    assert next_attempt is not None
    delay = (next_attempt - datetime.datetime.now()).total_seconds()
    assert delay > 60  # quota backoff for attempt 1 is well over a minute


async def TEST_permanent_failure_marks_failed(db):
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo)

    queue = UploadQueue(repo, folder_id="F", credentials_path="creds.json", max_attempts=2, poll_secs=1000)

    with patch("backend.gdrive.upload_file", side_effect=RuntimeError("network error")):
        for _ in range(2):
            await queue.run_once()
            await asyncio.sleep(0.05)
            await force_retry_now(db, rec_id)

    row = await repo.get(rec_id)
    assert row["upload_state"] == "failed"
    assert row["upload_attempts"] == 2


async def TEST_failed_upload_emits_event(db):
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo)

    emitted = []

    async def on_permanent_failure(rid, camera_id, message):
        emitted.append((rid, camera_id, message))

    queue = UploadQueue(
        repo, folder_id="F", credentials_path="creds.json", max_attempts=1, poll_secs=1000,
        on_permanent_failure=on_permanent_failure,
    )

    with patch("backend.gdrive.upload_file", side_effect=RuntimeError("network error")):
        await queue.run_once()
        await asyncio.sleep(0.05)

    assert len(emitted) == 1
    assert emitted[0][0] == rec_id
    assert emitted[0][1] == "cam1"


async def TEST_failed_upload_reports_the_actual_camera_id(db):
    """Fase 36 (SCALE-05): una cola de subida compartida entre camaras debe
    reportar el camera_id real de la grabacion, no asumir siempre 'cam1'."""
    repo = RecordingRepo(db)
    rec_id = await make_pending_recording(repo, filename="clip-cam2.mp4", camera_id="cam2")

    emitted = []

    async def on_permanent_failure(rid, camera_id, message):
        emitted.append((rid, camera_id, message))

    queue = UploadQueue(
        repo, folder_id="F", credentials_path="creds.json", max_attempts=1, poll_secs=1000,
        on_permanent_failure=on_permanent_failure,
    )

    with patch("backend.gdrive.upload_file", side_effect=RuntimeError("network error")):
        await queue.run_once()
        await asyncio.sleep(0.05)

    assert emitted == [(rec_id, "cam2", "network error")]


async def TEST_upload_does_not_block_pipeline(db):
    repo = RecordingRepo(db)
    await make_pending_recording(repo)

    def slow_upload(path, folder_id, credentials_path, token_path):
        import time
        time.sleep(0.3)
        return "gdrive-id-slow"

    queue = UploadQueue(repo, folder_id="F", credentials_path="creds.json", poll_secs=1000)

    with patch("backend.gdrive.upload_file", side_effect=slow_upload):
        start = asyncio.get_event_loop().time()
        await queue.run_once()  # spawns the upload in the background, returns fast
        elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 0.2  # run_once() itself doesn't wait for the slow upload


async def TEST_skipped_never_uploaded(db):
    repo = RecordingRepo(db)
    rec_id = await repo.create(
        camera_id="cam1", filename="clip.mp4", started_at=datetime.datetime.now(), reason="test",
    )
    await repo.finalize(
        rec_id, ended_at=datetime.datetime.now(), duration_s=5.0, size_bytes=1024,
        sha256="abc", thumbnail_path=None, upload_state=UploadState.SKIPPED,
    )

    pending = await repo.next_pending()

    assert all(r.id != rec_id for r in pending)
