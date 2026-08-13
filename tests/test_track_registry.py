"""Tests for backend.pipeline.tracking.TrackRegistry — estado compartido de tracks."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from backend.perception.face.identity import IdentityState
from backend.pipeline.tracking import TrackRegistry


class _FakeTracked:
    """Imita la forma de sv.Detections que consume update_from_detections."""

    def __init__(self, ids: list[int], boxes: list[tuple[int, int, int, int]] | None = None):
        self.tracker_id = np.array(ids)
        n = len(ids)
        self.xyxy = np.array(boxes if boxes else [[0, 0, 10, 10]] * n, dtype=float)
        self.confidence = np.full(n, 0.9)


# ─── Los tracks nuevos se reportan ────────────────────────────────────────────
def test_new_tracks_reported():
    reg = TrackRegistry()
    new_ids = reg.update_from_detections(_FakeTracked([1, 2]), now=0.0)
    assert set(new_ids) == {1, 2}
    # el mismo track no vuelve a reportarse como nuevo
    new_ids2 = reg.update_from_detections(_FakeTracked([1, 2, 3]), now=1.0)
    assert set(new_ids2) == {3}


# ─── snapshot() devuelve una copia ───────────────────────────────────────────
def test_snapshot_is_a_copy():
    reg = TrackRegistry()
    reg.update_from_detections(_FakeTracked([1]), now=0.0)
    snap = reg.snapshot()
    snap[999] = "intruso"
    assert 999 not in reg.snapshot()


# ─── centroid_history esta acotado ───────────────────────────────────────────
def test_centroid_history_is_bounded():
    reg = TrackRegistry(history_len=50)
    for i in range(10_000):
        reg.update_from_detections(_FakeTracked([1], [[i % 100, 0, i % 100 + 10, 10]]), now=float(i))
    ts = reg.get(1)
    assert len(ts.centroid_history) <= 50


# ─── prune elimina tracks caducados ──────────────────────────────────────────
def test_prune_removes_stale_tracks():
    reg = TrackRegistry()
    reg.update_from_detections(_FakeTracked([1]), now=0.0)
    expired = reg.prune(now=100.0, ttl=30.0)
    assert 1 in expired
    assert reg.get(1) is None


# ─── prune conserva tracks activos ───────────────────────────────────────────
def test_prune_keeps_active_tracks():
    reg = TrackRegistry()
    reg.update_from_detections(_FakeTracked([1]), now=0.0)
    expired = reg.prune(now=5.0, ttl=30.0)
    assert expired == []
    assert reg.get(1) is not None


# ─── set_identity es thread-safe ─────────────────────────────────────────────
def test_set_identity_is_thread_safe():
    reg = TrackRegistry()
    reg.update_from_detections(_FakeTracked([1]), now=0.0)

    def _writer(pid: int) -> None:
        for _ in range(200):
            reg.set_identity(1, pid, f"person-{pid}")

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = reg.snapshot()
    assert 1 in snap
    assert snap[1].person_id is not None  # estado consistente, sin corromper


# ─── el registro no crece sin limite con tracks efimeros ─────────────────────
def test_registry_does_not_grow_unbounded():
    reg = TrackRegistry()
    for i in range(1_000):
        reg.update_from_detections(_FakeTracked([i]), now=float(i))
        if i % 10 == 0:
            reg.prune(now=float(i), ttl=5.0)
    reg.prune(now=1_100.0, ttl=5.0)
    assert len(reg.snapshot()) < 20


# ─── identity_state (Fase 24, FACE-08) ────────────────────────────────────────
def TEST_identity_state_defaults_to_unknown():
    reg = TrackRegistry()
    reg.update_from_detections(_FakeTracked([1]), now=0.0)
    ts = reg.get(1)
    assert ts.identity_state is IdentityState.UNKNOWN


def TEST_set_identity_state_updates_track():
    reg = TrackRegistry()
    reg.update_from_detections(_FakeTracked([1]), now=0.0)
    reg.set_identity_state(1, IdentityState.CONFIRMED)
    assert reg.snapshot()[1].identity_state is IdentityState.CONFIRMED


def TEST_set_identity_state_on_missing_track_is_noop():
    reg = TrackRegistry()
    reg.set_identity_state(999, IdentityState.CONFIRMED)
    assert reg.get(999) is None


def TEST_identity_state_serialises_as_string():
    assert IdentityState.CONFIRMED == "CONFIRMED"
    assert str(IdentityState.CONFIRMED.value) == "CONFIRMED"
