"""Fase 4: garantías de grabación (BUG-08, BUG-10, BUG-11) y opciones por regla (DIR-02)."""

from __future__ import annotations

import shutil
import time
from collections import namedtuple
from datetime import datetime, timedelta
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from backend.pipeline.recording import PART_SUFFIX, ClipRequest, _ActiveClip, probe_clip
from tests.test_recording_prepost import make_worker, numbered_frame, wait_until


def _feed(broker, start, count, fps=20.0, sleep=0.01):
    base = datetime.now()
    for i in range(start, start + count):
        broker.publish(numbered_frame(i, base + timedelta(seconds=(i - start) / fps)))
        time.sleep(sleep)


# ─── BUG-08: nombre temporal y nombres únicos ─────────────────────────────────
def TEST_clip_is_written_as_part_and_renamed_on_close(tmp_path):
    broker, worker = make_worker(tmp_path)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    try:
        _feed(broker, 0, 15)
        worker.request_clip(reason="t", trigger_ts=datetime.now())
        _feed(broker, 15, 3)
        assert list(tmp_path.glob(f"*{PART_SUFFIX}")), "durante la grabación existe el .part"
        _feed(broker, 18, 15)
        wait_until(lambda: len(results) == 1)
    finally:
        worker.stop()
    assert not list(tmp_path.glob(f"*{PART_SUFFIX}"))
    assert results[0].path.endswith(".mp4") and not results[0].path.endswith(PART_SUFFIX)
    assert cv2.VideoCapture(results[0].path).read()[0]


def TEST_two_clips_in_the_same_second_do_not_overwrite(tmp_path):
    _, worker = make_worker(tmp_path)
    ts = datetime(2026, 1, 1, 12, 0, 0)
    (tmp_path / "clip_20260101_120000.mp4").write_bytes(b"x")
    assert worker._unique_clip_path(ClipRequest("r", ts)).endswith("clip_20260101_120000_1.mp4")


def TEST_rename_failure_is_reported(tmp_path):
    broker, worker = make_worker(tmp_path)
    failures, results = [], []
    worker._on_failure = failures.append
    worker._on_clip_ready = results.append
    worker.start()
    try:
        _feed(broker, 0, 10)
        with patch("backend.pipeline.recording.os.replace", side_effect=OSError("bloqueado")):
            worker.request_clip(reason="t", trigger_ts=datetime.now())
            _feed(broker, 10, 30)
            wait_until(lambda: failures)
    finally:
        worker.stop()
    assert "no se pudo cerrar" in failures[0]
    assert results == []


# ─── BUG-10: severidad máxima, sin hueco tras el pre-buffer, ritmo real ──────
def TEST_extending_keeps_the_highest_severity(tmp_path):
    _, worker = make_worker(tmp_path)
    worker._active = _ActiveClip(writer=None, started_at=datetime.now(), deadline=0.0,
                                 request=ClipRequest("r", datetime.now(), severity="info"))
    worker._extend_clip(ClipRequest("r2", datetime.now(), severity="critical"))
    worker._extend_clip(ClipRequest("r3", datetime.now(), severity="warning"))
    assert worker._active.request.severity == "critical"


def TEST_no_gap_and_no_duplicates_between_prebuffer_and_live(tmp_path):
    broker, worker = make_worker(tmp_path, fps=20.0)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    try:
        _feed(broker, 0, 20, sleep=0.05)          # ritmo real 20 FPS
        worker.request_clip(reason="t", trigger_ts=datetime.now())
        _feed(broker, 20, 20, sleep=0.05)
        wait_until(lambda: len(results) == 1)
    finally:
        worker.stop()
    cap = cv2.VideoCapture(results[0].path)
    values = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        values.append(int(img[0, 0, 0]))
    cap.release()
    # Los valores de píxel son el número de frame: deben crecer sin saltos grandes.
    steps = [b - a for a, b in zip(values, values[1:])]
    assert all(s >= 0 for s in steps), "frames desordenados o duplicados del pre-buffer"
    assert max(steps) <= 3, f"hueco tras el pre-buffer: salto de {max(steps)} frames"


def TEST_slow_source_is_paced_to_the_declared_fps(tmp_path):
    """Fuente a 10 FPS en un clip declarado a 20: cada frame se escribe dos veces y el
    clip dura lo que duró la escena, no la mitad."""
    _, worker = make_worker(tmp_path, fps=20.0)
    written = []
    active = _ActiveClip(writer=None, started_at=datetime.now(), deadline=0.0,
                         request=ClipRequest("r", datetime.now()))
    t0 = 1000.0
    for i in range(10):                            # 1 s de escena a 10 FPS
        worker._write_paced(active, t0 + i * 0.1, lambda i=i: written.append(i))
    assert 19 <= len(written) <= 21
    assert active.frames == len(written)


def TEST_fast_source_is_decimated(tmp_path):
    _, worker = make_worker(tmp_path, fps=10.0)
    written = []
    active = _ActiveClip(writer=None, started_at=datetime.now(), deadline=0.0,
                         request=ClipRequest("r", datetime.now()))
    for i in range(30):                            # 1 s a 30 FPS
        worker._write_paced(active, 2000.0 + i / 30, lambda: written.append(1))
    assert 9 <= len(written) <= 11


def TEST_long_gap_is_not_filled_with_minutes_of_frozen_frames(tmp_path):
    _, worker = make_worker(tmp_path, fps=10.0)
    written = []
    active = _ActiveClip(writer=None, started_at=datetime.now(), deadline=0.0,
                         request=ClipRequest("r", datetime.now()))
    worker._write_paced(active, 0.5, lambda: written.append(1))
    worker._write_paced(active, 60.5, lambda: written.append(1))    # la cámara se cortó 60 s
    assert len(written) <= 3


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe no está en el PATH")
def TEST_ffprobe_measures_a_real_clip(tmp_path):
    path = str(tmp_path / "c.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
    for i in range(20):
        w.write(np.full((48, 64, 3), i, dtype=np.uint8))
    w.release()
    info = probe_clip(path)
    assert info is not None
    assert info["fps"] == pytest.approx(10.0)
    assert info["frames"] == 20
    assert info["duration_s"] == pytest.approx(2.0, abs=0.2)


def TEST_probe_clip_without_ffprobe_returns_none(tmp_path):
    with patch("backend.pipeline.recording.shutil.which", return_value=None):
        assert probe_clip(str(tmp_path / "x.mp4")) is None


# ─── BUG-11: duración máxima y disco ─────────────────────────────────────────
def TEST_clip_is_closed_at_max_duration(tmp_path):
    broker, worker = make_worker(tmp_path, post_buffer_secs=60.0, max_clip_secs=0.5)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    try:
        _feed(broker, 0, 5)
        worker.request_clip(reason="t", trigger_ts=datetime.now())
        _feed(broker, 5, 60, sleep=0.02)           # 1,2 s con post-buffer de 60 s
        wait_until(lambda: len(results) == 1, timeout=3.0)
    finally:
        worker.stop()
    assert results[0].duration_s < 5.0


Usage = namedtuple("Usage", "total used free")


def TEST_low_disk_stops_recording_and_reports_once(tmp_path):
    broker, worker = make_worker(tmp_path, min_free_mb=1024)
    failures, results = [], []
    worker._on_failure = failures.append
    worker._on_clip_ready = results.append
    with patch("backend.pipeline.recording.shutil.disk_usage", return_value=Usage(1, 1, 10 * 1024 * 1024)):
        worker.start()
        try:
            _feed(broker, 0, 5)
            worker.request_clip(reason="t", trigger_ts=datetime.now())
            worker.request_clip(reason="t2", trigger_ts=datetime.now())
            _feed(broker, 5, 20)
            wait_until(lambda: failures)
            time.sleep(0.3)
        finally:
            worker.stop()
    assert len(failures) == 1 and "disco casi lleno" in failures[0]
    assert results == []
    assert worker.stats["disk_low"] is True


# ─── DIR-02: pre_secs, post_secs y force_upload por regla ────────────────────
def TEST_per_rule_post_secs_overrides_default(tmp_path):
    _, worker = make_worker(tmp_path, post_buffer_secs=10.0)
    req = ClipRequest("r", datetime.now(), post_secs=2.0)
    assert worker._deadline_for(req) <= time.monotonic() + 2.0


def TEST_per_rule_pre_secs_trims_the_prebuffer(tmp_path):
    broker, worker = make_worker(tmp_path, pre_buffer_secs=2.0)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    try:
        _feed(broker, 0, 40, sleep=0.05)           # 2 s de pre-buffer
        worker.request_clip(reason="t", trigger_ts=datetime.now(), pre_secs=0.5)
        _feed(broker, 40, 15, sleep=0.05)
        wait_until(lambda: len(results) == 1)
    finally:
        worker.stop()
    first = int(cv2.VideoCapture(results[0].path).read()[1][0, 0, 0])
    assert first >= 25, f"el clip empieza en el frame {first}: no recortó a 0,5 s"


def TEST_force_upload_marks_low_severity_clip_pending(tmp_path):
    broker, worker = make_worker(tmp_path, upload_min_severity="warning")
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    try:
        _feed(broker, 0, 5)
        worker.request_clip(reason="t", trigger_ts=datetime.now(), severity="info", force_upload=True)
        _feed(broker, 5, 30)
        wait_until(lambda: len(results) == 1)
    finally:
        worker.stop()
    assert results[0].upload_state == "pending"

