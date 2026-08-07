"""Tests for backend.pipeline.capture — pure RTSP capture worker."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.pipeline.broker import FrameBroker
from backend.pipeline.capture import CaptureWorker


# ─── publica frames en el broker con seq creciente desde 0 ──────────────────
def test_publishes_frames_to_broker(mock_video_capture):
    broker = FrameBroker()
    sub = broker.subscribe("test")
    worker = CaptureWorker("cam1", "rtsp://fake", broker)
    worker.start()

    last_seq = -1
    deadline = time.time() + 1.0
    seen = 0
    while time.time() < deadline and seen < 3:
        f = sub.get(timeout=0.2)
        if f is not None:
            assert f.seq > last_seq
            last_seq = f.seq
            seen += 1
    worker.stop()
    assert seen >= 1
    assert last_seq >= 0


# ─── el Frame lleva timestamps y camera_id correctos ─────────────────────────
def test_frame_carries_timestamps(mock_video_capture):
    broker = FrameBroker()
    sub = broker.subscribe("test")
    worker = CaptureWorker("cam1", "rtsp://fake", broker)
    worker.start()
    f = sub.get(timeout=1)
    worker.stop()

    assert f is not None
    assert f.captured_at > 0
    assert isinstance(f.wall_clock, datetime)
    assert f.camera_id == "cam1"


# ─── reescala a process_size cuando se especifica ────────────────────────────
def test_resizes_to_process_size(mock_video_capture):
    broker = FrameBroker()
    sub = broker.subscribe("test")
    worker = CaptureWorker("cam1", "rtsp://fake", broker, process_size=(640, 360))
    worker.start()
    f = sub.get(timeout=1)
    worker.stop()

    assert f is not None
    assert f.image.shape[:2] == (360, 640)


# ─── sin process_size, conserva la resolucion nativa ─────────────────────────
def test_no_resize_when_process_size_none(mock_video_capture, fake_frame):
    broker = FrameBroker()
    sub = broker.subscribe("test")
    worker = CaptureWorker("cam1", "rtsp://fake", broker, process_size=None)
    worker.start()
    f = sub.get(timeout=1)
    worker.stop()

    assert f is not None
    assert f.image.shape[:2] == fake_frame.shape[:2]


# ─── reconecta tras fallos de lectura ────────────────────────────────────────
def test_reconnects_on_read_failure(mock_video_capture):
    good_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    cap = mock_video_capture._mock_cap
    cap.read.side_effect = [
        (False, None),
        (False, None),
        (True, good_frame.copy()),
    ] + [(True, good_frame.copy())] * 50

    broker = FrameBroker()
    sub = broker.subscribe("test")
    worker = CaptureWorker("cam1", "rtsp://fake", broker)
    with patch("backend.pipeline.capture.time.sleep"):
        worker.start()
        time.sleep(0.3)
        worker.stop()

    assert mock_video_capture.call_count >= 2
    assert worker.health.reconnects >= 1


# ─── backoff exponencial 1s -> 30s ────────────────────────────────────────────
def test_backoff_is_exponential(mock_video_capture):
    cap = mock_video_capture._mock_cap
    cap.isOpened.return_value = False  # fuerza reconexion continua

    broker = FrameBroker()
    worker = CaptureWorker("cam1", "rtsp://fake", broker)
    delays: list[float] = []

    def _fake_sleep(secs):
        delays.append(secs)
        if len(delays) >= 5:
            worker._running = False

    with patch("backend.pipeline.capture.time.sleep", side_effect=_fake_sleep):
        worker._running = True
        worker._cap = worker._create_capture()
        worker._reconnect()

    assert delays[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]


# ─── stop() libera captura e hilo ────────────────────────────────────────────
def test_stop_releases_capture_and_thread(mock_video_capture):
    broker = FrameBroker()
    worker = CaptureWorker("cam1", "rtsp://fake", broker)
    worker.start()
    time.sleep(0.1)
    worker.stop()

    cap = mock_video_capture._mock_cap
    assert cap.release.called
    assert not worker._thread.is_alive()


# ─── sin fugas de hilos tras ciclos start/stop ───────────────────────────────
def test_no_thread_leak(mock_video_capture):
    baseline = threading.active_count()
    broker = FrameBroker()
    for _ in range(10):
        worker = CaptureWorker("cam1", "rtsp://fake", broker)
        worker.start()
        time.sleep(0.02)
        worker.stop()
    time.sleep(0.1)
    assert threading.active_count() <= baseline + 1


# ─── health reporta fps y edad del ultimo frame ──────────────────────────────
def test_health_reports_fps_and_age(mock_video_capture):
    broker = FrameBroker()
    worker = CaptureWorker("cam1", "rtsp://fake", broker)
    worker.start()
    time.sleep(0.3)
    health = worker.health
    worker.stop()

    assert health.connected is True
    assert health.fps > 0
    assert health.last_frame_age_s < 1.0


# ─── test de arquitectura: CaptureWorker no referencia IA ────────────────────
def test_capture_worker_is_pure():
    src = Path("backend/pipeline/capture.py").read_text(encoding="utf-8").lower()
    for forbidden in ("yolo", "detector", "recogn", "zone", "heatmap", "tracker"):
        assert forbidden not in src, f"CaptureWorker no debe referenciar '{forbidden}'"
