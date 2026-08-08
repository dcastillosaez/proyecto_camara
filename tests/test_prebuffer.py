"""Tests for backend.pipeline.prebuffer — RingFrameBuffer capacity, order, memory budget."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from backend.pipeline.broker import Frame
from backend.pipeline.prebuffer import BufferedFrame, RingFrameBuffer


def make_frame(seq: int, wall_clock: datetime, size=(48, 64)) -> Frame:
    image = np.zeros((*size, 3), dtype=np.uint8)
    cv2.putText(image, str(seq), (2, size[0] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return Frame(camera_id="cam1", seq=seq, captured_at=0.0, wall_clock=wall_clock, image=image)


def TEST_holds_configured_seconds():
    buf = RingFrameBuffer(seconds=10, fps=15, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)
    for i in range(300):
        buf.push(make_frame(i, base + timedelta(seconds=i / 15)))

    assert 140 <= len(buf.drain()) <= 151  # ~150 = 10s * 15fps


def TEST_drain_is_chronological():
    buf = RingFrameBuffer(seconds=10, fps=15, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)
    for i in range(50):
        buf.push(make_frame(i, base + timedelta(seconds=i / 15)))

    items = buf.drain()
    seqs = [it.seq for it in items]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def TEST_oldest_discarded_first():
    buf = RingFrameBuffer(seconds=1, fps=10, max_bytes=100_000_000)  # max_frames = 10
    base = datetime(2026, 1, 1)
    for i in range(25):
        buf.push(make_frame(i, base + timedelta(seconds=i / 10)))

    items = buf.drain()
    seqs = {it.seq for it in items}
    assert 24 in seqs
    assert 0 not in seqs


def TEST_respects_byte_budget():
    base = datetime(2026, 1, 1)
    probe = RingFrameBuffer(seconds=100, fps=100, max_bytes=1)
    probe.push(make_frame(0, base))
    one_frame_bytes = probe.bytes_used

    buf = RingFrameBuffer(seconds=100, fps=100, max_bytes=one_frame_bytes * 3)
    for i in range(20):
        buf.push(make_frame(i, base + timedelta(seconds=i / 100)))

    assert buf.bytes_used <= one_frame_bytes * 3 + 1
    assert len(buf.drain()) <= 4


def TEST_bytes_used_is_accurate():
    buf = RingFrameBuffer(seconds=10, fps=15, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)
    for i in range(30):
        buf.push(make_frame(i, base + timedelta(seconds=i / 15)))

    assert buf.bytes_used == sum(len(it.jpeg) for it in buf.drain())


def TEST_span_seconds_reflects_age():
    buf = RingFrameBuffer(seconds=10, fps=15, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)
    for i in range(300):
        buf.push(make_frame(i, base + timedelta(seconds=i / 15)))

    assert 9.0 <= buf.span_seconds <= 10.5


def TEST_clear_empties_buffer():
    buf = RingFrameBuffer(seconds=10, fps=15, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)
    for i in range(10):
        buf.push(make_frame(i, base + timedelta(seconds=i / 15)))

    buf.clear()

    assert buf.bytes_used == 0
    assert buf.drain() == []


def TEST_push_is_thread_safe():
    buf = RingFrameBuffer(seconds=100, fps=100, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)

    def worker(offset: int):
        for i in range(250):
            seq = offset * 250 + i
            buf.push(make_frame(seq, base + timedelta(seconds=seq / 100)))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    items = buf.drain()
    assert buf.bytes_used == sum(len(it.jpeg) for it in items)
    assert len(set(it.seq for it in items)) == len(items)


def TEST_jpeg_roundtrip():
    buf = RingFrameBuffer(seconds=10, fps=15, max_bytes=100_000_000, quality=85)
    base = datetime(2026, 1, 1)
    original = make_frame(0, base, size=(48, 64))
    buf.push(original)

    item = buf.drain()[0]
    decoded = cv2.imdecode(np.frombuffer(item.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert decoded.shape == original.image.shape
