"""DET-09: puerta de movimiento (desactivada por defecto)."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.config import Settings
from backend.pipeline.broker import FrameBroker
from backend.pipeline.detection import DetectionWorker
from backend.pipeline.manager import CameraPipeline
from backend.pipeline.motion import MotionGate
from backend.pipeline.tracking import TrackRegistry

STILL = np.full((360, 640, 3), 80, dtype=np.uint8)


def _moved():
    img = STILL.copy()
    img[100:250, 200:330] = 220          # alguien entra
    return img


def TEST_empty_still_scene_drops_to_idle_fps():
    gate = MotionGate(idle_fps=2.0)
    allowed = sum(gate.allow(STILL, t / 8.0, has_tracks=False) for t in range(80))   # 10 s a 8 FPS
    assert 19 <= allowed <= 22          # ~2 FPS, nunca cero
    assert gate.skipped == 80 - allowed


def TEST_motion_lets_frames_through():
    gate = MotionGate(idle_fps=2.0)
    assert gate.allow(STILL, 0.0, has_tracks=False)
    assert gate.allow(_moved(), 0.125, has_tracks=False)


def TEST_active_tracks_keep_full_rate():
    gate = MotionGate(idle_fps=2.0)
    assert all(gate.allow(STILL, t / 8.0, has_tracks=True) for t in range(16))


def TEST_slow_motion_accumulates_against_last_processed_frame():
    """La referencia es el último frame procesado: un cambio lento acaba superando el umbral."""
    gate = MotionGate(idle_fps=0.5, min_changed=0.05)
    assert gate.allow(STILL, 0.0, has_tracks=False)
    results = []
    for step in range(1, 8):
        img = STILL.copy()
        img[:, : step * 20] = 200        # una banda que crece poco a poco
        results.append(gate.allow(img, step * 0.125, has_tracks=False))
    assert any(results)


def TEST_idle_fps_never_zero():
    with pytest.raises(ValueError):
        MotionGate(idle_fps=0)
    with pytest.raises(ValueError):
        Settings(motion_gate_idle_fps=0.0)


def TEST_disabled_by_default():
    assert Settings().motion_gate_enabled is False
    pipeline = CameraPipeline("cam1", "rtsp://x", detector=MagicMock(), tracker=MagicMock())
    worker = pipeline.supervisor._entries["detector"].factory()
    assert worker._motion_gate is None
    assert worker.stats["motion_skipped"] == 0


def TEST_enabled_through_camera_pipeline():
    pipeline = CameraPipeline("cam1", "rtsp://x", detector=MagicMock(), tracker=MagicMock(),
                              motion_gate_enabled=True, motion_gate_idle_fps=1.0)
    worker = pipeline.supervisor._entries["detector"].factory()
    assert isinstance(worker._motion_gate, MotionGate)


def TEST_worker_skips_inference_when_gate_closed():
    broker = FrameBroker()
    detector = MagicMock()
    gate = MagicMock()
    gate.allow.return_value = False
    gate.skipped = 3
    rate = MagicMock()
    rate.should_process.return_value = True
    worker = DetectionWorker(broker.subscribe("detector"), detector, MagicMock(), TrackRegistry(),
                             rate, motion_gate=gate)
    frame = MagicMock(image=STILL)
    sub = MagicMock()
    sub.get.side_effect = [frame, frame, None]
    sub.closed = True
    worker._sub = sub
    worker._running = True
    worker._loop()
    detector.detect_sv.assert_not_called()
    assert gate.allow.call_count == 2
