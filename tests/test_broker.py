"""Tests for backend.pipeline.broker — fan-out latest-frame distribution."""

from __future__ import annotations

import threading
import time
from datetime import datetime

import numpy as np
import pytest

from backend.pipeline.broker import Frame, FrameBroker


def make_frame(seq: int, camera_id: str = "cam1") -> Frame:
    return Frame(
        camera_id=camera_id,
        seq=seq,
        captured_at=time.monotonic(),
        wall_clock=datetime.now(),
        image=np.full((4, 4, 3), seq % 256, dtype=np.uint8),
    )


# ─── get() devuelve exactamente el frame publicado ───────────────────────────
def test_get_returns_published_frame():
    broker = FrameBroker()
    sub = broker.subscribe("a")
    f = make_frame(0)
    broker.publish(f)
    result = sub.get(timeout=1)
    assert result is f


# ─── publish() nunca bloquea, aunque nadie consuma ───────────────────────────
def test_publish_never_blocks():
    broker = FrameBroker()
    broker.subscribe("idle")  # nunca se consume
    t0 = time.monotonic()
    for i in range(1000):
        broker.publish(make_frame(i))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5


# ─── un suscriptor lento no frena al productor ───────────────────────────────
def test_slow_subscriber_does_not_slow_producer():
    broker = FrameBroker()
    broker.subscribe("slow")  # nunca se consume, simula lentitud extrema
    fast = broker.subscribe("fast")
    received: list[int] = []
    stop = threading.Event()

    def _consume():
        while not stop.is_set():
            f = fast.get(timeout=0.01)
            if f is not None:
                received.append(f.seq)

    t = threading.Thread(target=_consume, daemon=True)
    t.start()

    t0 = time.monotonic()
    for i in range(200):
        broker.publish(make_frame(i))
    elapsed = time.monotonic() - t0
    stop.set()
    t.join(timeout=1)

    assert elapsed < 1.0
    assert received == sorted(received)  # seq creciente


# ─── dropped se cuenta por suscriptor ─────────────────────────────────────────
def test_dropped_counted_per_subscriber():
    broker = FrameBroker()
    sub = broker.subscribe("slow")
    for i in range(5):
        broker.publish(make_frame(i))
    stats = broker.stats()
    assert stats["slow"]["dropped"] == 4
    assert stats["slow"]["delivered"] == 0

    sub.get(timeout=1)
    stats = broker.stats()
    assert stats["slow"]["delivered"] == 1


# ─── el slot solo guarda el último frame ─────────────────────────────────────
def test_latest_frame_wins():
    broker = FrameBroker()
    sub = broker.subscribe("a")
    for i in range(5):
        broker.publish(make_frame(i))
    result = sub.get(timeout=1)
    assert result.seq == 4


# ─── aislamiento: un suscriptor lento no afecta a uno rápido ─────────────────
def test_isolation_between_subscribers():
    broker = FrameBroker()
    fast = broker.subscribe("fast")
    broker.subscribe("slow")
    for i in range(10):
        broker.publish(make_frame(i))
        fast.get(timeout=1)
    stats = broker.stats()
    assert stats["fast"]["dropped"] == 0
    assert stats["slow"]["dropped"] > 0


# ─── get(timeout) devuelve None si no hay frame ──────────────────────────────
def test_get_timeout_returns_none():
    broker = FrameBroker()
    sub = broker.subscribe("a")
    t0 = time.monotonic()
    result = sub.get(timeout=0.05)
    elapsed = time.monotonic() - t0
    assert result is None
    assert 0.0 <= elapsed < 0.3


# ─── close() desbloquea a quien espera ───────────────────────────────────────
def test_close_unblocks_waiter():
    broker = FrameBroker()
    sub = broker.subscribe("a")
    result_holder: list = []

    def _wait():
        result_holder.append(sub.get(timeout=5))

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    time.sleep(0.1)
    sub.close()
    t.join(timeout=1)

    assert not t.is_alive()
    assert result_holder == [None]


# ─── publish tras close() no lanza y el suscriptor desaparece ───────────────
def test_publish_after_close_is_noop():
    broker = FrameBroker()
    sub = broker.subscribe("a")
    sub.close()
    broker.publish(make_frame(0))  # no debe lanzar
    assert "a" not in broker.stats()


# ─── nombre de suscriptor duplicado lanza ValueError ─────────────────────────
def test_duplicate_subscriber_name_raises():
    broker = FrameBroker()
    broker.subscribe("x")
    with pytest.raises(ValueError):
        broker.subscribe("x")
