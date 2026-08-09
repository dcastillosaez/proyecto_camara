"""Tests for backend.observability.latency — three-stage end-to-end latency tracking."""

from __future__ import annotations

import inspect
import statistics
import time
from dataclasses import dataclass

from backend.observability import latency as lat
from backend.observability.metrics import create_metrics


@dataclass
class _FakeFrame:
    captured_at: float


def make_tracker():
    return lat.LatencyTracker(metrics=create_metrics())


def TEST_three_stages_measured():
    tracker = make_tracker()
    clock = [0.0]
    tracker._clock = lambda: clock[0]

    clock[0] = 0.1
    d1 = tracker.mark_processed(_FakeFrame(captured_at=0.0))
    clock[0] = 0.3
    d2 = tracker.mark_event(frame_captured_at=0.0, processed_at=0.1)
    clock[0] = 0.45
    d3 = tracker.mark_ws_sent(event_emitted_at=0.3)

    assert abs(d1 - 0.1) < 1e-9
    assert abs(d2 - 0.2) < 1e-9
    assert abs(d3 - 0.15) < 1e-9

    for stage in lat.Stage:
        assert len(tracker._samples[stage]) == 1


def TEST_uses_monotonic_clock():
    source = inspect.getsource(lat)
    assert "datetime.now" not in source
    assert "time.monotonic" in source


def TEST_injected_2s_latency_appears_in_p95():
    tracker = make_tracker()
    for _ in range(20):
        tracker._record(lat.Stage.CAPTURE_TO_PROCESS, 2.0)
    for _ in range(80):
        tracker._record(lat.Stage.CAPTURE_TO_PROCESS, 0.05)

    pct = tracker.e2e_percentiles()
    assert pct["p95"] > 1.5


def TEST_e2e_is_sum_of_stages():
    tracker = make_tracker()
    clock = [0.0]
    tracker._clock = lambda: clock[0]

    clock[0] = 0.1
    d1 = tracker.mark_processed(_FakeFrame(captured_at=0.0))
    clock[0] = 0.3
    d2 = tracker.mark_event(frame_captured_at=0.0, processed_at=0.1)
    clock[0] = 0.45
    d3 = tracker.mark_ws_sent(event_emitted_at=0.3)

    e2e_direct = clock[0] - 0.0
    assert abs((d1 + d2 + d3) - e2e_direct) < 1e-9


def TEST_percentiles_are_stable():
    tracker = make_tracker()
    samples = [i / 100 for i in range(1, 1001)]  # 0.01 .. 10.00
    for s in samples:
        tracker._record(lat.Stage.PROCESS_TO_EVENT, s)

    expected = statistics.quantiles(samples, n=100, method="inclusive")
    pct = tracker.e2e_percentiles()

    assert abs(pct["p50"] - expected[49]) < 1e-6
    assert abs(pct["p95"] - expected[94]) < 1e-6
    assert abs(pct["p99"] - expected[98]) < 1e-6


def TEST_negative_latency_ignored():
    tracker = make_tracker()
    tracker._record(lat.Stage.EVENT_TO_WS, -1.0)
    tracker._record(lat.Stage.EVENT_TO_WS, 0.2)

    assert tracker.anomalies == 1
    assert len(tracker._samples[lat.Stage.EVENT_TO_WS]) == 1
