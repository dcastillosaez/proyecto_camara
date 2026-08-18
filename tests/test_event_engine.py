"""Tests for backend.events.engine — EventEngine transition detection and stat aggregation."""

from __future__ import annotations

import asyncio
import datetime

import pytest

from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.types import EventType, Severity
from backend.perception.behavior import BehaviorFinding, BehaviorKind
from backend.perception.face.identity import IdentityState, IdentityTransition
from backend.perception.objects import ObjectFinding, ObjectKind


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


# ─── emit_identity (Fase 24, FACE-09) ─────────────────────────────────────────

async def TEST_identity_confirmed_emits_person_recognized():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)
    transition = IdentityTransition(
        track_id=1, from_state=IdentityState.CANDIDATE, to_state=IdentityState.CONFIRMED,
        person_id=7, confidence=0.82, votes=3, window=8,
    )

    engine.emit_identity(transition, now, person_name="David")
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.type == EventType.PERSON_RECOGNIZED
    assert event.track_id == 1
    assert event.person_id == 7
    assert event.person_name == "David"
    assert event.payload["state"] == "CONFIRMED"
    assert event.payload["votes"] == 3
    assert event.severity == Severity.INFO


async def TEST_identity_candidate_to_unknown_emits_unknown_person():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)
    transition = IdentityTransition(
        track_id=2, from_state=IdentityState.CANDIDATE, to_state=IdentityState.UNKNOWN,
    )

    engine.emit_identity(transition, now)
    await wait_until(lambda: len(received) == 1)

    assert received[0].type == EventType.UNKNOWN_PERSON
    assert received[0].severity == Severity.WARNING


async def TEST_identity_confirmed_to_unknown_emits_identity_lost():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)
    transition = IdentityTransition(
        track_id=3, from_state=IdentityState.CONFIRMED, to_state=IdentityState.UNKNOWN,
        person_id=7,
    )

    engine.emit_identity(transition, now)
    await wait_until(lambda: len(received) == 1)

    assert received[0].type == EventType.IDENTITY_LOST


async def TEST_identity_temporarily_lost_to_unknown_emits_identity_lost():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)
    transition = IdentityTransition(
        track_id=4, from_state=IdentityState.TEMPORARILY_LOST, to_state=IdentityState.UNKNOWN,
        person_id=7,
    )

    engine.emit_identity(transition, now)
    await wait_until(lambda: len(received) == 1)

    assert received[0].type == EventType.IDENTITY_LOST


async def TEST_identity_silent_transition_emits_nothing():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)
    transition = IdentityTransition(
        track_id=5, from_state=IdentityState.CONFIRMED, to_state=IdentityState.UNKNOWN,
        person_id=7, emits=False,
    )

    engine.emit_identity(transition, now)
    await asyncio.sleep(0.2)

    assert received == []


async def TEST_identity_intermediate_states_emit_nothing():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_identity(
        IdentityTransition(track_id=6, from_state=IdentityState.UNKNOWN, to_state=IdentityState.CANDIDATE),
        now,
    )
    engine.emit_identity(
        IdentityTransition(track_id=6, from_state=IdentityState.CONFIRMED, to_state=IdentityState.TEMPORARILY_LOST),
        now,
    )
    await asyncio.sleep(0.2)

    assert received == []


# ─── emit_behavior (Fase 26, BEH-04/BEH-05) ───────────────────────────────────

async def TEST_emit_behavior_translates_the_four_kinds():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_behavior(
        BehaviorFinding(kind=BehaviorKind.LOITERING, track_id=3, zone_id="z1",
                        duration_s=130.0, net_displacement_px=42.0), now,
    )
    engine.emit_behavior(
        BehaviorFinding(kind=BehaviorKind.RUNNING, track_id=4, speed_px_s=250.0), now,
    )
    engine.emit_behavior(
        BehaviorFinding(kind=BehaviorKind.IMMOBILE, track_id=7, duration_s=61.0,
                        net_displacement_px=3.2), now,
    )
    engine.emit_behavior(
        BehaviorFinding(kind=BehaviorKind.CROWD, track_count=6), now,
    )
    await wait_until(lambda: len(received) == 4)

    assert {e.type for e in received} == {
        EventType.LOITERING, EventType.RUNNING, EventType.IMMOBILE, EventType.CROWD_DETECTED,
    }
    crowd = next(e for e in received if e.type == EventType.CROWD_DETECTED)
    assert crowd.track_id is None
    assert crowd.payload["track_count"] == 6
    loitering = next(e for e in received if e.type == EventType.LOITERING)
    assert loitering.zone_id == "z1"


async def TEST_emit_behavior_payload_carries_magnitudes():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_behavior(
        BehaviorFinding(kind=BehaviorKind.IMMOBILE, track_id=7, duration_s=61.0,
                        net_displacement_px=3.2), now,
    )
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.payload["duration_s"] == 61.0
    assert event.payload["net_displacement_px"] == 3.2
    assert "speed_px_s" not in event.payload
    assert "track_count" not in event.payload
    assert all(v is not None for v in event.payload.values())


async def TEST_emit_behavior_keeps_default_info_severity():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    for finding in (
        BehaviorFinding(kind=BehaviorKind.LOITERING, track_id=1, duration_s=130.0),
        BehaviorFinding(kind=BehaviorKind.RUNNING, track_id=2, speed_px_s=250.0),
        BehaviorFinding(kind=BehaviorKind.IMMOBILE, track_id=3, duration_s=61.0),
        BehaviorFinding(kind=BehaviorKind.CROWD, track_count=6),
    ):
        engine.emit_behavior(finding, now)
    await wait_until(lambda: len(received) == 4)

    assert all(e.severity is Severity.INFO for e in received)


# ─── process_zone: tiempo de permanencia en ZONE_EXITED (Fase 26, BEH-04) ─────

async def TEST_zone_dwell_time_in_exited_payload():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_zone("z1", {1}, now, now_monotonic=100.0)
    await wait_until(lambda: len(received) == 1)

    engine.process_zone("z1", set(), now + datetime.timedelta(seconds=12), now_monotonic=112.0)
    await wait_until(lambda: len(received) == 2)

    exited = received[1]
    assert exited.type == EventType.ZONE_EXITED
    assert exited.payload["duration_s"] == 12.0
    assert "duration_s" not in received[0].payload


async def TEST_zone_dwell_absent_without_monotonic_clock():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_zone("z1", {1}, now)
    await wait_until(lambda: len(received) == 1)

    engine.process_zone("z1", set(), now + datetime.timedelta(seconds=5))
    await wait_until(lambda: len(received) == 2)

    assert "duration_s" not in received[1].payload


async def TEST_zone_dwell_entry_is_popped_on_exit():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_zone("z1", {1}, now, now_monotonic=100.0)
    await wait_until(lambda: len(received) == 1)

    engine.process_zone("z1", set(), now + datetime.timedelta(seconds=5), now_monotonic=105.0)
    await wait_until(lambda: len(received) == 2)

    assert 1 not in engine._zone_entry_at["z1"]


# ─── emit_object: la severidad la pone el CATALOGO, no el emisor (Fase 27) ───
# Al reves que los cuatro comportamientos de la Fase 26, que se quedaron en INFO
# a proposito para no disparar subidas a Drive, aqui OBJECT_LEFT es WARNING
# (types.py:55) y por tanto cruza upload_min_severity="warning"
# (config.py:115 -> recording.py:309): CADA OBJECT_LEFT SUBE UN CLIP A GOOGLE
# DRIVE. Es una decision tomada con el usuario (se mantiene el contrato ya
# publicado del catalogo) y este test es el sitio donde queda documentada.
# ─────────────────────────────────────────────────────────────────────────────

async def TEST_emit_object_translates_both_kinds():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_object(
        ObjectFinding(kind=ObjectKind.LEFT, track_id=11, class_name="backpack",
                      duration_s=61.0), now,
    )
    engine.emit_object(
        ObjectFinding(kind=ObjectKind.REMOVED, track_id=12, class_name="backpack",
                      duration_s=90.0), now,
    )
    await wait_until(lambda: len(received) == 2)

    assert {e.type for e in received} == {EventType.OBJECT_LEFT, EventType.OBJECT_REMOVED}


async def TEST_emit_object_payload_carries_magnitudes():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_object(
        ObjectFinding(kind=ObjectKind.LEFT, track_id=11, duration_s=61.0,
                      class_name="backpack", net_displacement_px=12.0), now,
    )
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.payload["duration_s"] == 61.0
    assert event.payload["class_name"] == "backpack"
    assert "person_distance_px" not in event.payload
    assert all(v is not None for v in event.payload.values())


async def TEST_emit_object_severity_comes_from_catalog():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_object(
        ObjectFinding(kind=ObjectKind.LEFT, track_id=11, duration_s=61.0), now,
    )
    engine.emit_object(
        ObjectFinding(kind=ObjectKind.REMOVED, track_id=12, duration_s=90.0), now,
    )
    await wait_until(lambda: len(received) == 2)

    left = next(e for e in received if e.type is EventType.OBJECT_LEFT)
    removed = next(e for e in received if e.type is EventType.OBJECT_REMOVED)
    assert left.severity is Severity.WARNING
    assert removed.severity is Severity.INFO


async def TEST_emit_object_carries_bbox_as_first_class_field():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_object(
        ObjectFinding(kind=ObjectKind.LEFT, track_id=11, duration_s=61.0,
                      bbox=(10.0, 20.0, 30.0, 40.0)), now,
    )
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.bbox == (10.0, 20.0, 30.0, 40.0)
    assert "bbox" not in event.payload


async def TEST_config_changed_is_emitted_with_detail():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.config_changed(now, classes=[0, 24])
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.type is EventType.CONFIG_CHANGED
    assert event.payload["classes"] == [0, 24]
