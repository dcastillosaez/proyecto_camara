"""DET-02: PERSON_EXITED y ZONE_EXITED al expirar el track, no al faltar un frame."""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import MagicMock

import numpy as np
import supervision as sv

from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.types import EventType
from backend.pipeline.detection import DetectionWorker
from backend.tracker import PersonTracker

NOW = datetime.datetime(2026, 4, 16, 18, 30)


def _engine():
    bus = EventBus(loop=asyncio.get_event_loop())
    received: list = []

    async def capture(event):
        received.append(event)

    bus.subscribe("capture", capture)
    return EventEngine(bus, camera_id="cam1"), received


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0.01)


async def TEST_lost_track_is_not_an_exit():
    engine, received = _engine()
    engine.process_tracks({5}, NOW)
    engine.process_tracks(set(), NOW, lost_track_ids={5})      # falla una deteccion
    engine.process_tracks({5}, NOW)                            # ByteTrack lo recupera
    await _settle()
    assert [e.type for e in received] == [EventType.PERSON_ENTERED]


async def TEST_exit_is_emitted_when_the_track_expires():
    engine, received = _engine()
    engine.process_tracks({5}, NOW)
    engine.process_tracks(set(), NOW, lost_track_ids={5})
    engine.process_tracks(set(), NOW, lost_track_ids=set())    # expira
    await _settle()
    assert [e.type for e in received] == [EventType.PERSON_ENTERED, EventType.PERSON_EXITED]
    engine.process_tracks(set(), NOW, lost_track_ids=set())
    await _settle()
    assert len(received) == 2                                  # una sola salida


async def TEST_without_lost_ids_behaviour_is_unchanged():
    engine, received = _engine()
    engine.process_tracks({1}, NOW)
    engine.process_tracks(set(), NOW)
    await _settle()
    assert [e.type for e in received] == [EventType.PERSON_ENTERED, EventType.PERSON_EXITED]


def _dets(boxes):
    if not boxes:
        return sv.Detections.empty()
    return sv.Detections(
        xyxy=np.array(boxes, dtype=np.float32),
        confidence=np.full(len(boxes), 0.9, dtype=np.float32),
        class_id=np.zeros(len(boxes), dtype=int),
    )


def TEST_person_tracker_reports_lost_ids_until_expiry():
    tracker = PersonTracker(frame_rate=30)            # max_time_lost = 60 frames
    box = [[100, 100, 200, 300]]
    for _ in range(3):
        tracked, _ = tracker.update(_dets(box))
    tid = int(tracked.tracker_id[0])
    tracked, _ = tracker.update(_dets([]))            # hueco de un frame
    assert len(tracked) == 0
    assert tid in tracker.lost_ids()
    tracked, _ = tracker.update(_dets(box))           # vuelve con el mismo id
    assert int(tracked.tracker_id[0]) == tid
    assert tid not in tracker.lost_ids()
    for _ in range(70):                               # mas alla de max_time_lost
        tracker.update(_dets([]))
    assert tid not in tracker.lost_ids()


def TEST_zone_membership_survives_a_detection_gap():
    """La zona no emite salida y entrada por un hueco de deteccion."""
    engine = MagicMock()
    worker = DetectionWorker(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                             event_engine=engine)
    worker.set_zones([{"id": "z1", "name": "Z", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}])
    frame_shape = (480, 640, 3)
    tracked = _dets([[100, 100, 200, 300]])
    tracked.tracker_id = np.array([7])
    worker._update_zones_and_heat(tracked, frame_shape)
    assert engine.process_zone.call_args.args[1] == {7}

    worker._lost_ids = {7}
    worker._update_zones_and_heat(sv.Detections.empty(), frame_shape)
    assert engine.process_zone.call_args.args[1] == {7}      # sigue dentro

    worker._lost_ids = set()
    worker._update_zones_and_heat(sv.Detections.empty(), frame_shape)
    assert engine.process_zone.call_args.args[1] == set()    # ahora si sale
