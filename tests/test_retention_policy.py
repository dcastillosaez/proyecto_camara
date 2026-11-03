"""BUG-02: qué borra la retención y qué conserva.

Antes solo se purgaba LINE_CROSSED, las grabaciones se filtraban por un `created_at`
que nadie escribe (no se borraba ninguna), la galería no se purgaba nunca y la
primera pasada llegaba a las 24 h de uptime. Estos tests fijan el contrato nuevo.
"""

from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module
import backend.main as main_module
from backend.events.types import Event, EventType
from backend.storage import models
from backend.storage.repositories import EventRepo, RecordingRepo, UploadState

NOW = datetime.datetime.now()
OLD = NOW - datetime.timedelta(days=40)
RECENT = NOW - datetime.timedelta(days=2)


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retention.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
        await conn.run_sync(db_module.Base.metadata.create_all)   # tabla captures
        # Columnas del ORM heredado que storage/migrations.py garantiza en toda instalacion.
        for col in ("created_at DATETIME", "gdrive_id VARCHAR(100)",
                    "upload_status VARCHAR(20) DEFAULT 'pending'", "duration_secs FLOAT"):
            await conn.execute(text(f"ALTER TABLE recordings ADD COLUMN {col}"))
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    orig = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf
    yield sf
    db_module._engine, db_module._session_factory = orig
    await engine.dispose()


async def _event(sf, type_: EventType, ts: datetime.datetime) -> str:
    ev = Event(type=type_, camera_id="cam1", ts=ts)
    await EventRepo(sf).insert(ev)
    return ev.id


async def _recording(sf, tmp_path, started_at, state, *, trigger=None, name="clip.mp4"):
    clip = tmp_path / name
    clip.write_bytes(b"mp4")
    thumb = tmp_path / f"{name}.jpg"
    thumb.write_bytes(b"jpg")
    repo = RecordingRepo(sf)
    rec_id = await repo.create(camera_id="cam1", filename=str(clip), started_at=started_at,
                               reason="test", trigger_event_id=trigger)
    await repo.finalize(rec_id, ended_at=started_at, duration_s=5.0, size_bytes=3,
                        sha256="x", thumbnail_path=str(thumb), upload_state=state)
    return rec_id, clip, thumb


async def _event_ids(sf) -> set[str]:
    async with sf() as session:
        return set((await session.execute(select(models.Event.id))).scalars().all())


async def _recording_ids(sf) -> set[int]:
    async with sf() as session:
        return set((await session.execute(select(models.Recording.id))).scalars().all())


# ─── eventos ──────────────────────────────────────────────────────────────────
async def TEST_old_events_of_every_type_are_purged_recent_kept(db):
    old_ids = {await _event(db, t, OLD) for t in (
        EventType.LINE_CROSSED, EventType.PERSON_ENTERED, EventType.CAMERA_OFFLINE,
        EventType.UNKNOWN_PERSON,
    )}
    recent = await _event(db, EventType.PERSON_ENTERED, RECENT)
    deleted = await db_module.purge_old_events(30)
    assert deleted == len(old_ids)
    assert await _event_ids(db) == {recent}


async def TEST_old_event_with_recording_follows_the_clip(db, tmp_path):
    with_clip = await _event(db, EventType.UNKNOWN_PERSON, OLD)
    await _recording(db, tmp_path, RECENT, UploadState.DONE, trigger=with_clip)
    await db_module.purge_old_events(30)
    assert with_clip in await _event_ids(db)


async def TEST_event_goes_once_its_recording_row_is_purged(db, tmp_path):
    ev = await _event(db, EventType.UNKNOWN_PERSON, OLD)
    _, clip, thumb = await _recording(db, tmp_path, OLD, UploadState.DONE, trigger=ev)
    settings = SimpleNamespace(
        events_retention_days=30, recordings_retention_days=30, local_retention_days=0,
        snapshot_retention_days=0, captures_retention_days=0, persons_retention_days=0,
        clips_max_total_mb=0,
    )
    # Orden de _run_retention: eventos primero (se conserva), grabaciones despues.
    first = await main_module._run_retention(settings)
    assert first["events"] == 0 and first["recordings"] == 1
    assert not clip.exists() and not thumb.exists()
    second = await main_module._run_retention(settings)
    assert second["events"] == 1
    assert await _event_ids(db) == set()


# ─── grabaciones ──────────────────────────────────────────────────────────────
async def TEST_old_finished_recordings_are_deleted_with_their_files(db, tmp_path):
    done_id, done_clip, done_thumb = await _recording(db, tmp_path, OLD, UploadState.DONE, name="a.mp4")
    failed_id, *_ = await _recording(db, tmp_path, OLD, UploadState.FAILED, name="b.mp4")
    skipped_id, *_ = await _recording(db, tmp_path, OLD, UploadState.SKIPPED, name="c.mp4")
    assert await db_module.purge_old_recordings(30) == 3
    assert not ({done_id, failed_id, skipped_id} & await _recording_ids(db))
    assert not done_clip.exists() and not done_thumb.exists()


async def TEST_pending_and_uploading_recordings_are_never_deleted(db, tmp_path):
    pending_id, pending_clip, _ = await _recording(db, tmp_path, OLD, UploadState.PENDING, name="p.mp4")
    uploading_id, *_ = await _recording(db, tmp_path, OLD, UploadState.PENDING, name="u.mp4")
    await RecordingRepo(db).mark_upload(uploading_id, UploadState.UPLOADING)
    assert await db_module.purge_old_recordings(30) == 0
    assert {pending_id, uploading_id} <= await _recording_ids(db)
    assert pending_clip.exists()


async def TEST_recent_recordings_are_kept(db, tmp_path):
    rec_id, clip, _ = await _recording(db, tmp_path, RECENT, UploadState.DONE)
    assert await db_module.purge_old_recordings(30) == 0
    assert rec_id in await _recording_ids(db) and clip.exists()


# ─── galería ──────────────────────────────────────────────────────────────────
async def TEST_old_gallery_captures_are_deleted_with_their_image(db, tmp_path):
    old_img, new_img = tmp_path / "old.jpg", tmp_path / "new.jpg"
    old_img.write_bytes(b"x")
    new_img.write_bytes(b"x")
    await db_module.insert_capture(1, OLD, str(old_img))
    await db_module.insert_capture(1, RECENT, str(new_img))
    assert await db_module.purge_old_captures(30) == 1
    assert not old_img.exists() and new_img.exists()
    remaining = await db_module.get_captures_for_person(1)
    assert [c["image_path"] for c in remaining] == [str(new_img)]


# ─── orquestación ─────────────────────────────────────────────────────────────
def _all_days(days=30):
    return SimpleNamespace(
        events_retention_days=days, recordings_retention_days=days, local_retention_days=days,
        snapshot_retention_days=days, captures_retention_days=days, persons_retention_days=days,
        clips_max_total_mb=days,
    )


async def TEST_a_failing_step_does_not_stop_the_others(db):
    with patch.object(main_module, "purge_old_events", AsyncMock(side_effect=RuntimeError("bd"))), \
         patch.object(main_module, "purge_old_recordings", AsyncMock(return_value=2)) as recs, \
         patch.object(main_module, "_purge_old_snapshots", AsyncMock(return_value=0)), \
         patch.object(main_module, "rtsp_stream", None):
        done = await main_module._run_retention(_all_days())
    assert done["events"] == -1
    assert done["recordings"] == 2
    recs.assert_awaited_once_with(30)
    assert {"local_clips", "clips_size", "snapshots", "captures", "persons"} <= set(done)


async def TEST_zero_days_disables_every_step(db):
    with patch.object(main_module, "purge_old_events", AsyncMock()) as events:
        done = await main_module._run_retention(_all_days(0))
    assert done == {}
    events.assert_not_awaited()


@pytest.mark.parametrize("now,hour,expected_h", [
    (datetime.datetime(2026, 1, 1, 1, 0), 3, 2.0),
    (datetime.datetime(2026, 1, 1, 3, 0), 3, 24.0),
    (datetime.datetime(2026, 1, 1, 23, 30), 3, 3.5),
])
def TEST_secs_until_hour(now, hour, expected_h):
    assert main_module._secs_until_hour(hour, now) == pytest.approx(expected_h * 3600)


async def TEST_purge_loop_runs_retention_at_startup():
    calls = []

    async def fake_retention(settings):
        calls.append(settings)
        return {}

    async def stop(_secs):
        raise asyncio.CancelledError

    with patch.object(main_module, "_run_retention", fake_retention), \
         patch.object(main_module.asyncio, "sleep", stop):
        with pytest.raises(asyncio.CancelledError):
            await main_module._purge_loop()
    assert len(calls) == 1   # antes de la primera espera, no a las 24 h


# ─── BUG-11: retención por tamaño ────────────────────────────────────────────
async def TEST_size_cap_removes_oldest_finished_clips_first(db, tmp_path):
    big = b"x" * (600 * 1024)
    ids = []
    for i, (age, state) in enumerate([(5, UploadState.DONE), (4, UploadState.PENDING),
                                      (3, UploadState.SKIPPED), (1, UploadState.DONE)]):
        rec_id, clip, _ = await _recording(db, tmp_path, NOW - datetime.timedelta(days=age), state,
                                           name=f"c{i}.mp4")
        clip.write_bytes(big)
        ids.append((rec_id, clip))
    # 4 x 600 KB = 2,4 MB; con cota de 1 MB hay que quitar hasta bajar de ella.
    removed = await main_module._purge_clips_over_size(1)
    assert removed == 3
    assert not ids[0][1].exists() and not ids[2][1].exists() and not ids[3][1].exists()
    assert ids[1][1].exists()                  # pendiente de subir: nunca se toca


async def TEST_size_cap_under_limit_removes_nothing(db, tmp_path):
    _, clip, _ = await _recording(db, tmp_path, OLD, UploadState.DONE)
    assert await main_module._purge_clips_over_size(1024) == 0
    assert clip.exists()


# ─── BUG-08: reconciliación disco/BD al arrancar ─────────────────────────────
async def TEST_reconcile_clips(db, tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "clip_20260101_000000.part.mp4").write_bytes(b"incompleto")
    orphan = clips / "clip_20260101_000001.mp4"
    orphan.write_bytes(b"sin fila")
    pending_id, pending_clip, _ = await _recording(db, clips, RECENT, UploadState.PENDING, name="p.mp4")
    done_id, done_clip, _ = await _recording(db, clips, RECENT, UploadState.DONE, name="d.mp4")
    ok_id, ok_clip, _ = await _recording(db, clips, RECENT, UploadState.DONE, name="ok.mp4")
    pending_clip.unlink()
    done_clip.unlink()

    counts = await main_module._reconcile_clips(str(clips))
    assert counts == {"partial_removed": 1, "missing_failed": 1, "missing_cleared": 1, "orphans": 1}
    repo = RecordingRepo(db)
    assert (await repo.get(pending_id))["upload_state"] == UploadState.FAILED.value
    assert orphan.exists() and ok_clip.exists()
    remaining = {r.id for r in await repo.with_local_files()}
    assert remaining == {ok_id}
