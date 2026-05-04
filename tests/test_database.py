"""Tests for database functions not covered elsewhere: stats, filters, purge."""
from __future__ import annotations

import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module


@pytest_asyncio.fixture
async def isolated_db(tmp_path):
    db_file = tmp_path / "test_db_extra.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    await db_module.init_db()
    yield

    db_module._engine, db_module._session_factory = orig_engine, orig_sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# get_stats_today
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats_today_empty_db(isolated_db):
    """Returns total_today=0 and empty hourly dict when no events exist."""
    stats = await db_module.get_stats_today()
    assert stats["total_today"] == 0
    assert stats["hourly"] == {}


@pytest.mark.asyncio
async def test_get_stats_today_counts_only_todays_events(isolated_db):
    """total_today must not include events from previous days."""
    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(days=1)
    await db_module.insert_event("in", now)
    await db_module.insert_event("out", now)
    await db_module.insert_event("in", yesterday)
    stats = await db_module.get_stats_today()
    assert stats["total_today"] == 2


@pytest.mark.asyncio
async def test_get_stats_today_hourly_keys_are_two_char_strings(isolated_db):
    """hourly dict keys are zero-padded 2-char hour strings like '08', '14'."""
    await db_module.insert_event("in", datetime.datetime.now())
    stats = await db_module.get_stats_today()
    for key in stats["hourly"]:
        assert len(key) == 2, f"Expected 2-char hour key, got {key!r}"


@pytest.mark.asyncio
async def test_get_stats_today_has_required_keys(isolated_db):
    """get_stats_today always returns total_today and hourly keys."""
    stats = await db_module.get_stats_today()
    assert "total_today" in stats
    assert "hourly" in stats


# ---------------------------------------------------------------------------
# get_events_filtered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_filtered_by_direction_in(isolated_db):
    """direction='in' returns only IN events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts)
    await db_module.insert_event("out", ts)
    result = await db_module.get_events_filtered(direction="in")
    assert all(e["direction"] == "in" for e in result)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_events_filtered_by_direction_out(isolated_db):
    """direction='out' returns only OUT events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts)
    await db_module.insert_event("out", ts)
    result = await db_module.get_events_filtered(direction="out")
    assert all(e["direction"] == "out" for e in result)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_events_filtered_by_person_name_partial_match(isolated_db):
    """person_name filter performs case-insensitive partial match."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts, "Alice")
    await db_module.insert_event("in", ts, "Bob")
    result = await db_module.get_events_filtered(person_name="ali")
    assert len(result) == 1
    assert result[0]["person_name"] == "Alice"


@pytest.mark.asyncio
async def test_get_events_filtered_by_intrusion_true(isolated_db):
    """is_intrusion=True returns only intrusion events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts, is_intrusion=True)
    await db_module.insert_event("out", ts, is_intrusion=False)
    result = await db_module.get_events_filtered(is_intrusion=True)
    assert len(result) == 1
    assert result[0]["is_intrusion"] is True


@pytest.mark.asyncio
async def test_get_events_filtered_by_intrusion_false(isolated_db):
    """is_intrusion=False excludes intrusion events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts, is_intrusion=True)
    await db_module.insert_event("out", ts, is_intrusion=False)
    result = await db_module.get_events_filtered(is_intrusion=False)
    assert all(not e["is_intrusion"] for e in result)


@pytest.mark.asyncio
async def test_get_events_filtered_date_range_inclusive(isolated_db):
    """from_dt/to_dt boundaries are inclusive."""
    t1 = datetime.datetime(2026, 1, 1, 10, 0)
    t2 = datetime.datetime(2026, 1, 2, 10, 0)
    t3 = datetime.datetime(2026, 1, 3, 10, 0)
    for ts in (t1, t2, t3):
        await db_module.insert_event("in", ts)
    result = await db_module.get_events_filtered(from_dt=t1, to_dt=t2)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_events_filtered_no_filters_returns_all(isolated_db):
    """With no filters, returns all events up to limit."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    for _ in range(5):
        await db_module.insert_event("in", ts)
    result = await db_module.get_events_filtered(limit=10)
    assert len(result) == 5


@pytest.mark.asyncio
async def test_get_events_filtered_respects_limit(isolated_db):
    """limit parameter caps the number of returned events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    for _ in range(10):
        await db_module.insert_event("in", ts)
    result = await db_module.get_events_filtered(limit=3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_get_events_filtered_event_has_all_keys(isolated_db):
    """Every event dict has all expected keys."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0))
    result = await db_module.get_events_filtered()
    assert {"id", "timestamp", "direction", "person_name", "is_intrusion"} <= set(result[0].keys())


# ---------------------------------------------------------------------------
# purge_old_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_old_events_deletes_old_keeps_recent(isolated_db):
    """purge_old_events removes events beyond retention_days, keeps recent ones."""
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    new = datetime.datetime.now()
    await db_module.insert_event("in", old)
    await db_module.insert_event("in", old)
    await db_module.insert_event("in", new)
    deleted = await db_module.purge_old_events(retention_days=30)
    assert deleted == 2
    remaining = await db_module.get_recent_events(10)
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_purge_old_events_returns_zero_when_nothing_old(isolated_db):
    """purge_old_events returns 0 when all events are within the window."""
    await db_module.insert_event("in", datetime.datetime.now())
    deleted = await db_module.purge_old_events(retention_days=30)
    assert deleted == 0


@pytest.mark.asyncio
async def test_purge_old_events_deletes_all_old(isolated_db):
    """purge_old_events with retention_days=0 deletes everything."""
    old = datetime.datetime.now() - datetime.timedelta(days=1)
    await db_module.insert_event("in", old)
    await db_module.insert_event("out", old)
    deleted = await db_module.purge_old_events(retention_days=0)
    assert deleted == 2


# ---------------------------------------------------------------------------
# purge_old_recordings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_old_recordings_deletes_old_keeps_recent(isolated_db):
    """purge_old_recordings removes old rows and keeps recent ones."""
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    new = datetime.datetime.now()
    await db_module.insert_recording("old.mp4", created_at=old)
    await db_module.insert_recording("new.mp4", created_at=new)
    deleted = await db_module.purge_old_recordings(retention_days=30)
    assert deleted == 1
    remaining = await db_module.get_recent_recordings(10)
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "new.mp4"


@pytest.mark.asyncio
async def test_purge_old_recordings_returns_zero_when_nothing_old(isolated_db):
    """purge_old_recordings returns 0 when all recordings are recent."""
    await db_module.insert_recording("clip.mp4")
    deleted = await db_module.purge_old_recordings(retention_days=30)
    assert deleted == 0


# ---------------------------------------------------------------------------
# delete_events_range
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_events_range_removes_in_range(isolated_db):
    """delete_events_range removes only events within [from_dt, to_dt]."""
    t1 = datetime.datetime(2026, 1, 1, 10, 0)
    t2 = datetime.datetime(2026, 1, 2, 10, 0)
    t3 = datetime.datetime(2026, 1, 3, 10, 0)
    for ts in (t1, t2, t3):
        await db_module.insert_event("in", ts)
    deleted = await db_module.delete_events_range(t1, t2)
    assert deleted == 2
    remaining = await db_module.get_recent_events(10)
    assert len(remaining) == 1
    assert remaining[0]["timestamp"] == t3.isoformat()
