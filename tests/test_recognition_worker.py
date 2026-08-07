"""Tests for backend.pipeline.recognition.RecognitionWorker — reconocimiento con ritmo propio."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.recognition import RecognitionWorker
from backend.pipeline.tracking import TrackRegistry


def _make_frame(seq: int) -> Frame:
    return Frame(
        camera_id="cam1", seq=seq, captured_at=time.monotonic(),
        wall_clock=datetime.now(), image=np.zeros((360, 640, 3), dtype=np.uint8),
    )


class _FakeTracked:
    def __init__(self, ids: list[int]):
        self.tracker_id = np.array(ids)
        n = len(ids)
        self.xyxy = np.array([[10, 10, 80, 200]] * n, dtype=float)
        self.confidence = np.full(n, 0.9)


def _publish_for(broker: FrameBroker, seconds: float, interval: float = 0.02) -> None:
    deadline = time.time() + seconds
    seq = 0
    while time.time() < deadline:
        broker.publish(_make_frame(seq))
        seq += 1
        time.sleep(interval)


@pytest.fixture
def broker():
    return FrameBroker()


# ─── Respeta el FPS objetivo de reconocimiento ──────────────────────────────
def test_recognition_respects_target_fps(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop.return_value = (None, None, False)  # nunca identifica

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=3.0, min_fps=3.0, max_fps=3.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=1.0)   # ~50 FPS de publicacion
    worker.stop()

    # a 3 FPS objetivo durante ~1 s: ni 1 ni 50
    assert 1 <= recognizer.process_crop.call_count <= 8


# ─── Los tracks ya identificados no se reprocesan ───────────────────────────
def test_recognition_skips_identified_tracks(broker):
    registry = TrackRegistry()
    now = time.monotonic()
    registry.update_from_detections(_FakeTracked([1]), now=now - 10)
    registry.set_identity(1, person_id=42, name="David")

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop.return_value = (None, None, False)

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=0.6)
    worker.stop()

    recognizer.process_crop.assert_not_called()


# ─── Al identificar, escribe la identidad en el registry ────────────────────
def test_recognition_sets_identity_on_match(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop.return_value = (42, "David", False)

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    deadline = time.time() + 2.0
    while time.time() < deadline and registry.get(1).person_id is None:
        broker.publish(_make_frame(0))
        time.sleep(0.03)
    worker.stop()

    ts = registry.get(1)
    assert ts.person_id == 42
    assert ts.person_name == "David"


# ─── Una excepcion del reconocedor no mata al worker ────────────────────────
def test_recognition_failure_does_not_kill_worker(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    calls = {"n": 0}

    def _flaky(crop, tid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return (None, None, False)

    recognizer.process_crop.side_effect = _flaky

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=1.0, interval=0.05)
    alive = worker._thread.is_alive()
    worker.stop()

    assert calls["n"] >= 2   # sobrevivio a la excepcion
    assert alive


# ─── La cache del reconocedor se limpia cuando expiran tracks ───────────────
def test_recognition_prunes_cache_on_track_expiry(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop.return_value = (None, None, False)

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(
        sub, registry, recognizer, rate, min_track_age=0.0, prune_interval=0.05
    )
    worker.start()

    _publish_for(broker, seconds=0.4, interval=0.03)
    # el track 1 desaparece del registry (expirado por el DetectionWorker)
    registry.prune(now=time.monotonic() + 1000, ttl=1.0)
    _publish_for(broker, seconds=0.4, interval=0.03)
    worker.stop()

    recognizer.prune.assert_called()
    last_active = recognizer.prune.call_args.args[0]
    assert 1 not in last_active   # el track expirado ya no esta en el set activo


# ─── Sin reconocedor disponible, el worker no hace nada ─────────────────────
def test_unavailable_recognizer_is_noop(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = False

    sub = broker.subscribe("recognition")
    worker = RecognitionWorker(
        sub, registry, recognizer, AdaptiveRate(), min_track_age=0.0
    )
    worker.start()
    _publish_for(broker, seconds=0.3, interval=0.03)
    worker.stop()

    recognizer.process_crop.assert_not_called()
