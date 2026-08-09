"""Tests for backend.events.engine — EventEngine transition detection and stat aggregation."""

from __future__ import annotations

import asyncio
import datetime

import pytest

from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.types import EventType


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condition not met within {timeout}s")


def make_engine():
    bus = EventBus(loop=asyncio.get_event_loop())
    received: list = []

    async def capture(event):
        received.append(event)

    bus.subscribe("capture", capture)
    engine = EventEngine(bus, camera_id="cam1")
    return engine, received


async def TEST_line_crossing_emits_event():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_line_crossing({"direction": "in", "timestamp": now, "tracker_id": 7, "is_intrusion": False})
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.type == EventType.LINE_CROSSED
    assert event.camera_id == "cam1"
    assert event.track_id == 7
    assert event.payload["direction"] == "in"
    assert event.payload["is_intrusion"] is False


async def TEST_zone_transitions():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_zone("z1", {1, 2}, now)  # both enter
    await wait_until(lambda: len(received) == 2)

    engine.process_zone("z1", {2}, now + datetime.timedelta(seconds=5))  # track 1 exits
    await wait_until(lambda: len(received) == 3)

    entered = [e for e in received if e.type == EventType.ZONE_ENTERED]
    exited = [e for e in received if e.type == EventType.ZONE_EXITED]
    assert {e.track_id for e in entered} == {1, 2}
    assert {e.track_id for e in exited} == {1}


async def TEST_track_lifecycle_events():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_tracks({5}, now)  # appears
    await wait_until(lambda: len(received) == 1)

    engine.process_tracks(set(), now + datetime.timedelta(seconds=3))  # disappears
    await wait_until(lambda: len(received) == 2)

    assert received[0].type == EventType.PERSON_ENTERED
    assert received[0].track_id == 5
    assert received[1].type == EventType.PERSON_EXITED
    assert received[1].track_id == 5


async def TEST_no_duplicate_events_for_same_transition():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_tracks({1, 2}, now)
    await wait_until(lambda: len(received) == 2)

    engine.process_tracks({1, 2}, now + datetime.timedelta(seconds=1))
    engine.process_tracks({1, 2}, now + datetime.timedelta(seconds=2))
    await asyncio.sleep(0.05)

    assert len(received) == 2  # no repeats for a stable state


class FakeStatRepo:
    def __init__(self):
        self.calls = []

    async def upsert_minute(self, camera_id, minute, detections, unique_tracks, avg_confidence, max_concurrent):
        self.calls.append({
            "camera_id": camera_id, "minute": minute, "detections": detections,
            "unique_tracks": unique_tracks, "avg_confidence": avg_confidence,
            "max_concurrent": max_concurrent,
        })


async def TEST_detection_stats_flushed_per_minute():
    engine, _ = make_engine()
    base = datetime.datetime(2026, 4, 16, 12, 0, 0)
    for minute in range(10):
        ts = base + datetime.timedelta(minutes=minute, seconds=10)
        engine.accumulate_detections(ts, {1}, [0.9])

    repo = FakeStatRepo()
    flushed = await engine.flush_stats(repo, base + datetime.timedelta(minutes=11))

    assert flushed == 10
    assert len(repo.calls) == 10


async def TEST_detection_stats_aggregates_correctly():
    engine, _ = make_engine()
    minute = datetime.datetime(2026, 4, 16, 12, 0, 0)

    engine.accumulate_detections(minute + datetime.timedelta(seconds=1), {1, 2}, [0.8, 0.6])
    engine.accumulate_detections(minute + datetime.timedelta(seconds=20), {1, 2, 3}, [0.9])
    engine.accumulate_detections(minute + datetime.timedelta(seconds=40), {1}, [0.7])

    repo = FakeStatRepo()
    await engine.flush_stats(repo, minute + datetime.timedelta(minutes=1))

    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call["detections"] == 2 + 3 + 1  # sum of active tracks observed per tick
    assert call["unique_tracks"] == 3  # {1,2,3}
    assert call["max_concurrent"] == 3


async def TEST_camera_offline_recovered_pair():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.camera_offline(now)
    engine.camera_offline(now + datetime.timedelta(seconds=1))  # idempotent, no duplicate
    await wait_until(lambda: len(received) == 1)

    engine.camera_recovered(now + datetime.timedelta(seconds=10))
    await wait_until(lambda: len(received) == 2)

    assert received[0].type == EventType.CAMERA_OFFLINE
    assert received[1].type == EventType.CAMERA_RECOVERED


async def TEST_publish_always_stamps_emitted_at():
    """_emitted_at (monotonic) must be present even without captured_at/processed_at —
    the WebSocket broadcast handler needs it to measure EVENT_TO_WS (OBS-03)."""
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_tracks({1}, now)
    await wait_until(lambda: len(received) == 1)

    assert "_emitted_at" in received[0].payload
    assert isinstance(received[0].payload["_emitted_at"], float)
    assert "_captured_at" not in received[0].payload


async def TEST_captured_at_reaches_payload_and_latency_tracker():
    import time
    from unittest.mock import MagicMock

    tracker = MagicMock()
    bus = EventBus(loop=asyncio.get_event_loop())
    received = []

    async def capture(event):
        received.append(event)

    bus.subscribe("capture", capture)
    engine = EventEngine(bus, camera_id="cam1", latency_tracker=tracker)

    now = datetime.datetime(2026, 4, 16, 18, 30)
    captured_at = time.monotonic() - 0.05
    processed_at = time.monotonic()
    engine.process_tracks({1}, now, captured_at=captured_at, processed_at=processed_at)
    await wait_until(lambda: len(received) == 1)

    assert received[0].payload["_captured_at"] == captured_at
    tracker.mark_event.assert_called_once_with(captured_at, processed_at)
