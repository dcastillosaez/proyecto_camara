"""Tests for backend.pipeline.supervisor.WorkerSupervisor — aislamiento y reinicio."""

from __future__ import annotations

import threading
import time

import pytest

from backend.pipeline.supervisor import WorkerStatus, WorkerSupervisor


class _FakeWorker:
    """Worker minimo con el contrato que espera el supervisor."""

    def __init__(self, tag: str = "") -> None:
        self.tag = tag
        self._alive = False
        self.started = 0
        self.stopped = 0
        self.ticks = 0

    def start(self) -> None:
        self._alive = True
        self.started += 1

    def stop(self, timeout: float = 5.0) -> None:
        self._alive = False
        self.stopped += 1

    def is_alive(self) -> bool:
        return self._alive

    def crash(self) -> None:
        self._alive = False


class _Clock:
    """Reloj simulable para probar la ventana de 60 s sin esperar."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ─── El crash de un worker no detiene a los demas ───────────────────────────
def test_worker_crash_does_not_stop_others():
    made: dict[str, list[_FakeWorker]] = {"a": [], "b": []}

    def factory(name):
        def _make():
            w = _FakeWorker(name)
            made[name].append(w)
            return w
        return _make

    sup = WorkerSupervisor(interval=0.05)
    sup.register("a", factory("a"))
    sup.register("b", factory("b"))
    sup.start_all()

    made["a"][-1].crash()
    assert _wait_for(lambda: sup.status()["a"] == WorkerStatus.RUNNING and len(made["a"]) >= 2)
    b_alive = made["b"][-1].is_alive()
    sup.stop_all()

    assert b_alive                      # el worker sano nunca se detuvo
    assert len(made["b"]) == 1          # ni se recreo


# ─── El supervisor reinicia al worker caido ─────────────────────────────────
def test_supervisor_restarts_crashed_worker():
    instances: list[_FakeWorker] = []

    def _make():
        w = _FakeWorker()
        instances.append(w)
        return w

    sup = WorkerSupervisor(interval=0.05)
    sup.register("w", _make)
    sup.start_all()
    instances[-1].crash()

    ok = _wait_for(lambda: len(instances) >= 2 and instances[-1].is_alive())
    status = sup.status()["w"]
    sup.stop_all()

    assert ok
    assert status == WorkerStatus.RUNNING


# ─── Tres crashes en 60 s marcan FAILED y se deja de reintentar ─────────────
def test_three_crashes_in_60s_marks_failed():
    instances: list[_FakeWorker] = []

    def _make():
        w = _FakeWorker()
        instances.append(w)
        return w

    clock = _Clock()
    sup = WorkerSupervisor(interval=0.05, max_restarts=3, window=60.0, clock=clock)
    sup.register("w", _make)
    sup.start_all()

    for _ in range(3):
        instances[-1].crash()
        if not _wait_for(lambda n=len(instances): len(instances) > n or sup.status()["w"] == WorkerStatus.FAILED):
            break

    assert _wait_for(lambda: sup.status()["w"] == WorkerStatus.FAILED)
    created_at_failure = len(instances)
    time.sleep(0.25)   # varios ciclos de supervision mas
    sup.stop_all()

    assert len(instances) == created_at_failure   # dejo de reintentar


# ─── degraded refleja los workers FAILED ────────────────────────────────────
def test_degraded_flag_reflects_failed_workers():
    instances: list[_FakeWorker] = []

    def _make():
        w = _FakeWorker()
        instances.append(w)
        return w

    sup = WorkerSupervisor(interval=0.05, max_restarts=1, window=60.0, clock=_Clock())
    sup.register("w", _make)
    sup.start_all()
    assert sup.degraded is False

    instances[-1].crash()
    assert _wait_for(lambda: sup.status()["w"] == WorkerStatus.FAILED)
    degraded = sup.degraded
    sup.stop_all()

    assert degraded is True


# ─── stop_all deja todo parado ──────────────────────────────────────────────
def test_stop_all_is_clean():
    instances: list[_FakeWorker] = []

    def _make():
        w = _FakeWorker()
        instances.append(w)
        return w

    sup = WorkerSupervisor(interval=0.05)
    sup.register("a", _make)
    sup.register("b", _make)
    sup.start_all()
    time.sleep(0.1)
    sup.stop_all()

    assert all(not w.is_alive() for w in instances)
    assert all(s == WorkerStatus.STOPPED for s in sup.status().values())
    assert not sup._thread.is_alive()


# ─── La ventana de reinicios se olvida con el tiempo ────────────────────────
def test_restart_count_resets_after_window():
    instances: list[_FakeWorker] = []

    def _make():
        w = _FakeWorker()
        instances.append(w)
        return w

    clock = _Clock()
    sup = WorkerSupervisor(interval=0.05, max_restarts=3, window=60.0, clock=clock)
    sup.register("w", _make)
    sup.start_all()

    for _ in range(2):
        n = len(instances)
        instances[-1].crash()
        assert _wait_for(lambda: len(instances) > n)

    clock.advance(120.0)   # los 2 reinicios previos quedan fuera de la ventana

    n = len(instances)
    instances[-1].crash()
    assert _wait_for(lambda: len(instances) > n)
    status = sup.status()["w"]
    sup.stop_all()

    assert status == WorkerStatus.RUNNING   # el tercer crash NO marca FAILED
