"""Tests for clip metadata: sha256, thumbnail, and RecordingRepo persistence."""

from __future__ import annotations

import hashlib
import time
import tracemalloc
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.recording import RecordingWorker
from backend.pipeline.tracking import TrackRegistry
from backend.storage import models
from backend.storage.repositories import RecordingRepo, UploadState


def numbered_frame(seq: int, wall_clock: datetime, size=(48, 64)) -> Frame:
    image = np.full((*size, 3), seq % 256, dtype=np.uint8)
    return Frame(camera_id="cam1", seq=seq, captured_at=time.monotonic(), wall_clock=wall_clock, image=image)


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


def make_worker(tmp_path, **overrides):
    broker = FrameBroker()
    sub = broker.subscribe("recording")
    kwargs = dict(
        clips_dir=str(tmp_path / "clips"),
        thumbnails_dir=str(tmp_path / "thumbnails"),
        fps=20.0,
        pre_buffer_secs=0.3,
        post_buffer_secs=0.2,
        pre_buffer_max_mb=48,
        codec="mp4v",
    )
    kwargs.update(overrides)
    worker = RecordingWorker(sub, TrackRegistry(), **kwargs)
    return broker, worker


def record_one_clip(tmp_path, **overrides):
    broker, worker = make_worker(tmp_path, **overrides)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    base = datetime(2026, 1, 1)
    try:
        for i in range(10):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i / 20)))
            time.sleep(0.01)
        event_ts = base + timedelta(seconds=10 / 20)
        worker.request_clip(
            reason="intrusion_nocturna", trigger_ts=event_ts, trigger_event_id="evt-1",
            person_id=7, zone_id="jardin", severity="critical",
        )
        for i in range(10, 20):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i / 20)))
            time.sleep(0.01)
        wait_until(lambda: len(results) == 1, timeout=5.0)
    finally:
        worker.stop()
    return results[0]


@pytest_asyncio.fixture
async def db(tmp_path):
    db_file = tmp_path / "recordings_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield sf
    await engine.dispose()


async def TEST_all_metadata_persisted(tmp_path, db):
    result = record_one_clip(tmp_path)

    repo = RecordingRepo(db)
    rec_id = await repo.create(
        camera_id="cam1", filename=result.path, started_at=result.started_at,
        reason=result.reason, trigger_event_id=result.trigger_event_id,
        person_id=result.person_id, zone_id=result.zone_id,
    )
    await repo.finalize(
        rec_id, ended_at=result.ended_at, duration_s=result.duration_s,
        size_bytes=result.size_bytes, sha256=result.sha256,
        thumbnail_path=result.thumbnail_path, upload_state=UploadState.PENDING,
    )
    row = await repo.get(rec_id)

    for field in (
        "duration_s", "size_bytes", "sha256", "thumbnail_path", "reason",
        "trigger_event_id", "camera_id", "started_at", "ended_at", "upload_state",
    ):
        assert row[field] is not None, f"{field} is None"


def TEST_sha256_matches_file(tmp_path):
    result = record_one_clip(tmp_path)

    h = hashlib.sha256()
    with open(result.path, "rb") as f:
        h.update(f.read())

    assert result.sha256 == h.hexdigest()


def TEST_sha256_is_streamed(tmp_path):
    from backend.pipeline.recording import RecordingWorker as RW

    big_path = tmp_path / "big.bin"
    with open(big_path, "wb") as f:
        f.write(b"\x00" * (4 * 1024 * 1024))  # 4 MB

    tracemalloc.start()
    digest = RW._sha256_file(str(big_path))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    expected = hashlib.sha256(big_path.read_bytes()).hexdigest()
    assert digest == expected
    assert peak < 1 * 1024 * 1024  # well under the 4 MB file — never loaded whole


def TEST_thumbnail_exists_and_is_image(tmp_path):
    import os

    result = record_one_clip(tmp_path)

    assert result.thumbnail_path is not None
    assert os.path.exists(result.thumbnail_path)
    img = cv2.imread(result.thumbnail_path)
    assert img is not None

    cap = cv2.VideoCapture(result.path)
    vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    cap.release()
    assert img.shape[1] <= vid_w


def TEST_reason_records_rule_name(tmp_path):
    result = record_one_clip(tmp_path)
    assert result.reason == "intrusion_nocturna"


async def TEST_trigger_event_linked(tmp_path, db):
    result = record_one_clip(tmp_path)
    assert result.trigger_event_id == "evt-1"

    async with db() as session:
        async with session.begin():
            session.add(models.Event(
                id="evt-1", camera_id="cam1", type="INTRUSION", ts=datetime.now(),
                severity="critical", payload={},
            ))
    repo = RecordingRepo(db)
    rec_id = await repo.create(
        camera_id="cam1", filename=result.path, started_at=result.started_at,
        reason=result.reason, trigger_event_id=result.trigger_event_id,
    )
    row = await repo.get(rec_id)
    async with db() as session:
        event_row = await session.get(models.Event, row["trigger_event_id"])

    assert event_row is not None


async def TEST_person_and_zone_captured(tmp_path, db):
    result = record_one_clip(tmp_path)
    assert result.person_id == 7
    assert result.zone_id == "jardin"

    repo = RecordingRepo(db)
    rec_id = await repo.create(
        camera_id="cam1", filename=result.path, started_at=result.started_at,
        reason=result.reason, person_id=result.person_id, zone_id=result.zone_id,
    )
    row = await repo.get(rec_id)

    assert row["person_id"] == 7
    assert row["zone_id"] == "jardin"
