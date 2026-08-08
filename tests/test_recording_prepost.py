"""Tests for backend.pipeline.recording.RecordingWorker — pre/post-buffer clip assembly."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.recording import ClipRequest, RecordingWorker
from backend.pipeline.tracking import TrackRegistry


def numbered_frame(seq: int, wall_clock: datetime, size=(48, 64)) -> Frame:
    """A frame whose pixel value IS its sequence number (mod 256) — exactly
    decodable after JPEG/MP4 round-trip, unlike OCR on rendered text."""
    image = np.full((*size, 3), seq % 256, dtype=np.uint8)
    return Frame(camera_id="cam1", seq=seq, captured_at=time.monotonic(), wall_clock=wall_clock, image=image)


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


def make_worker(tmp_path, **overrides):
    broker = FrameBroker()
    sub = broker.subscribe("recording")
    kwargs = dict(
        clips_dir=str(tmp_path),
        fps=20.0,
        pre_buffer_secs=0.5,
        post_buffer_secs=0.5,
        pre_buffer_max_mb=48,
        codec="mp4v",
    )
    kwargs.update(overrides)
    worker = RecordingWorker(sub, TrackRegistry(), **kwargs)
    return broker, worker


def TEST_clip_starts_before_event(tmp_path):
    broker, worker = make_worker(tmp_path)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    base = datetime(2026, 1, 1)

    try:
        # Fill pre-buffer with 40 frames (2s @ 20fps) before the "event".
        for i in range(40):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i / 20)))
            time.sleep(0.01)

        event_ts = base + timedelta(seconds=40 / 20)
        worker.request_clip(reason="test", trigger_ts=event_ts)

        # Keep feeding post-event frames so the assembly thread has live frames to consume.
        for i in range(40, 55):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i / 20)))
            time.sleep(0.01)

        wait_until(lambda: len(results) == 1, timeout=5.0)
    finally:
        worker.stop()

    clip = results[0]
    cap = cv2.VideoCapture(clip.path)
    ok, first_frame = cap.read()
    cap.release()

    assert ok
    first_value = int(first_frame[0, 0, 0])
    assert first_value < 40  # starts inside the pre-buffer window, before the event


def TEST_post_buffer_extends_clip(tmp_path):
    broker, worker = make_worker(tmp_path, post_buffer_secs=0.3)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    base = datetime(2026, 1, 1)

    try:
        broker.publish(numbered_frame(0, base))
        time.sleep(0.05)
        worker.request_clip(reason="test", trigger_ts=base)

        for i in range(1, 10):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i * 0.05)))
            time.sleep(0.05)

        wait_until(lambda: len(results) == 1, timeout=5.0)
    finally:
        worker.stop()

    cap = cv2.VideoCapture(results[0].path)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    assert frame_count > 1  # more than just the trigger frame — post-buffer frames were written


def TEST_assembly_does_not_block_buffer_feed(tmp_path):
    broker, worker = make_worker(tmp_path)
    worker.start()
    base = datetime(2026, 1, 1)

    try:
        with patch(
            "backend.pipeline.recording.ClipWriter.write_jpeg",
            side_effect=lambda jpeg: time.sleep(0.3),
        ):
            worker.request_clip(reason="test", trigger_ts=base)
            before = len(worker._prebuffer.drain())
            for i in range(10):
                broker.publish(numbered_frame(i, base + timedelta(seconds=i * 0.05)))
                time.sleep(0.02)
            after = len(worker._prebuffer.drain())
    finally:
        worker.stop()

    assert after > before  # feed loop kept accepting frames while assembly was "stuck"


def TEST_concurrent_events_do_not_create_duplicate_clips(tmp_path):
    broker, worker = make_worker(tmp_path, post_buffer_secs=0.4)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    base = datetime(2026, 1, 1)

    try:
        broker.publish(numbered_frame(0, base))
        time.sleep(0.05)
        worker.request_clip(reason="first", trigger_ts=base)
        time.sleep(0.1)
        worker.request_clip(reason="second", trigger_ts=base + timedelta(seconds=0.2))

        for i in range(1, 15):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i * 0.05)))
            time.sleep(0.05)

        wait_until(lambda: len(results) >= 1, timeout=5.0)
        time.sleep(0.6)  # give a hypothetical second clip time to appear
    finally:
        worker.stop()

    assert len(results) == 1


def TEST_clip_has_expected_duration(tmp_path):
    broker, worker = make_worker(tmp_path, fps=20.0, pre_buffer_secs=0.3, post_buffer_secs=0.3)
    results = []
    worker._on_clip_ready = results.append
    worker.start()
    base = datetime(2026, 1, 1)

    try:
        for i in range(10):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i / 20)))
            time.sleep(0.01)

        event_ts = base + timedelta(seconds=10 / 20)
        worker.request_clip(reason="test", trigger_ts=event_ts)

        for i in range(10, 20):
            broker.publish(numbered_frame(i, base + timedelta(seconds=i / 20)))
            time.sleep(0.02)

        wait_until(lambda: len(results) == 1, timeout=5.0)
    finally:
        worker.stop()

    cap = cv2.VideoCapture(results[0].path)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    duration = frame_count / fps
    assert duration >= 0.2  # pre + live frames add up to a non-trivial clip


def TEST_recording_failure_emits_event(tmp_path):
    broker, worker = make_worker(tmp_path)
    failures = []
    worker._on_failure = failures.append
    worker.start()

    still_alive = False
    try:
        with patch("backend.pipeline.recording.ClipWriter") as MockWriter:
            MockWriter.return_value.is_opened = False
            worker.request_clip(reason="test", trigger_ts=datetime(2026, 1, 1))
            wait_until(lambda: len(failures) == 1, timeout=3.0)
            still_alive = worker.is_alive()  # worker survives the failed clip attempt
    finally:
        worker.stop()

    assert still_alive
    assert len(failures) == 1
