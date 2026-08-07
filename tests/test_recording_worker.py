"""Tests for backend.pipeline.recording.RecordingWorker — grabacion desde el broker."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.recording import RecordingWorker
from backend.pipeline.tracking import TrackRegistry


def _make_frame(seq: int, value: int = 0) -> Frame:
    return Frame(
        camera_id="cam1", seq=seq, captured_at=time.monotonic(),
        wall_clock=datetime.now(),
        image=np.full((360, 640, 3), value, dtype=np.uint8),
    )


class _FakeTracked:
    def __init__(self, ids: list[int]):
        self.tracker_id = np.array(ids)
        n = len(ids)
        self.xyxy = np.array([[10, 10, 50, 50]] * n, dtype=float)
        self.confidence = np.full(n, 0.9)


@pytest.fixture
def broker():
    return FrameBroker()


# ─── El worker expone al ClipRecorder los frames recibidos del broker ───────
def test_recording_worker_feeds_frames_from_broker(broker):
    sub = broker.subscribe("recording")
    recorder = MagicMock()
    worker = RecordingWorker(sub, TrackRegistry(), recorder_factory=lambda stream: recorder)
    worker.start()

    broker.publish(_make_frame(0, value=7))
    deadline = time.time() + 2.0
    while time.time() < deadline and worker.get_frame() is None:
        time.sleep(0.02)
    frame = worker.get_frame()
    worker.stop()

    assert frame is not None
    assert frame[0, 0, 0] == 7          # es el frame publicado
    assert recorder.start.called         # delega en el ClipRecorder
    assert recorder.stop.called


# ─── live_count sale del registry, no de una deteccion propia ───────────────
def test_live_count_comes_from_registry(broker):
    sub = broker.subscribe("recording")
    registry = TrackRegistry()
    worker = RecordingWorker(sub, registry, recorder_factory=lambda stream: MagicMock())

    assert worker.get_live_count() == 0
    registry.update_from_detections(_FakeTracked([1, 2, 3]), now=time.monotonic())
    assert worker.get_live_count() == 3


# ─── get_frame devuelve una copia, no la referencia interna ─────────────────
def test_get_frame_returns_copy(broker):
    sub = broker.subscribe("recording")
    worker = RecordingWorker(sub, TrackRegistry(), recorder_factory=lambda stream: MagicMock())
    worker.start()

    broker.publish(_make_frame(0, value=5))
    deadline = time.time() + 2.0
    while time.time() < deadline and worker.get_frame() is None:
        time.sleep(0.02)

    first = worker.get_frame()
    first[0, 0, 0] = 99
    second = worker.get_frame()
    worker.stop()

    assert second[0, 0, 0] == 5  # mutar la copia no afecta al estado interno
