"""Tests for backend.pipeline.streaming.StreamingWorker — overlay + JPEG encode."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.streaming import StreamingWorker
from backend.pipeline.tracking import TrackRegistry


def _make_frame(seq: int) -> Frame:
    return Frame(
        camera_id="cam1", seq=seq, captured_at=time.monotonic(),
        wall_clock=datetime.now(), image=np.zeros((360, 640, 3), dtype=np.uint8),
    )


def _tracker_mock() -> MagicMock:
    tracker = MagicMock()
    tracker.annotate.side_effect = lambda frame, tracked, labels=None: frame
    return tracker


@pytest.fixture
def broker():
    return FrameBroker()


# ─── Sin clientes conectados no se encodea (ahorro de CPU) ──────────────────
def test_no_encode_without_clients(broker):
    sub = broker.subscribe("streaming")
    worker = StreamingWorker(sub, TrackRegistry(), _tracker_mock())
    worker.start()

    for i in range(5):
        broker.publish(_make_frame(i))
        time.sleep(0.05)
    encoded = worker.stats["encoded"]
    worker.stop()

    assert encoded == 0


# ─── Con un cliente conectado, get_jpeg devuelve un JPEG valido ─────────────
def test_encodes_with_client(broker):
    sub = broker.subscribe("streaming")
    worker = StreamingWorker(sub, TrackRegistry(), _tracker_mock())
    worker.start()
    worker.client_connected()

    deadline = time.time() + 2.0
    jpeg = None
    while time.time() < deadline and jpeg is None:
        broker.publish(_make_frame(0))
        time.sleep(0.05)
        jpeg = worker.get_jpeg()
    worker.stop()

    assert jpeg is not None
    assert jpeg[:2] == b"\xff\xd8"  # cabecera JPEG


# ─── El modulo no conoce al detector: dibuja desde el registry ──────────────
def test_overlay_uses_registry_not_detector():
    src = Path("backend/pipeline/streaming.py").read_text(encoding="utf-8")
    assert "PersonDetector" not in src
    assert "detect_sv" not in src


# ─── Un encode lento no frena al productor ──────────────────────────────────
def test_slow_encode_does_not_block_broker(broker):
    sub = broker.subscribe("streaming")
    worker = StreamingWorker(sub, TrackRegistry(), _tracker_mock())
    worker.start()
    worker.client_connected()

    def _slow_imencode(ext, img, params=None):
        time.sleep(0.2)
        return True, np.frombuffer(b"\xff\xd8fake", dtype=np.uint8)

    with patch("backend.pipeline.streaming.cv2.imencode", side_effect=_slow_imencode):
        t0 = time.monotonic()
        for i in range(30):
            broker.publish(_make_frame(i))
        elapsed = time.monotonic() - t0
        time.sleep(0.3)
        dropped = broker.stats()["streaming"]["dropped"]
    worker.stop()

    assert elapsed < 0.5      # el productor no se bloqueo
    assert dropped > 0        # el worker lento perdio frames, no el productor


# ─── El contador de clientes nunca baja de cero ─────────────────────────────
def test_client_count_never_negative(broker):
    sub = broker.subscribe("streaming")
    worker = StreamingWorker(sub, TrackRegistry(), _tracker_mock())
    worker.client_disconnected()
    worker.client_disconnected()
    assert worker.stats["clients"] == 0
    worker.client_connected()
    assert worker.stats["clients"] == 1


# ─── Overlay de objetos: color propio, via pull (Fase 27, BEH-06) ────────────
def TEST_object_overlay_drawn_when_boxes_present():
    boxes = [
        {"track_id": 1, "class_id": 56, "class_name": "chair", "bbox": (10, 10, 50, 50)},
    ]
    worker = StreamingWorker(
        MagicMock(), TrackRegistry(), _tracker_mock(), object_boxes=lambda: boxes
    )
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    annotated = worker._annotate(frame)

    assert not np.array_equal(annotated, frame)


def TEST_no_object_overlay_when_provider_returns_empty():
    worker = StreamingWorker(
        MagicMock(), TrackRegistry(), _tracker_mock(), object_boxes=lambda: []
    )
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    annotated = worker._annotate(frame)

    assert np.array_equal(annotated, frame)


def TEST_streaming_worker_without_object_boxes_provider():
    worker = StreamingWorker(MagicMock(), TrackRegistry(), _tracker_mock())
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    annotated = worker._annotate(frame)

    assert np.array_equal(annotated, frame)
