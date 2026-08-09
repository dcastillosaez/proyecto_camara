"""LatencyTracker: end-to-end latency measured in three stages (SPEC_v2.md §8.4).

Always the monotonic clock (time.monotonic) for durations — Frame.captured_at
already travels on this clock since Fase 17. wall_clock is for event timestamps
only, never for measuring elapsed time (21-CONTEXT.md).

A single aggregate number doesn't say WHERE a slowdown lives; three stages do:
  CAPTURE_TO_PROCESS  captured_at -> processed_at   (perception pipeline)
  PROCESS_TO_EVENT    processed_at -> event emitted (event engine)
  EVENT_TO_WS         event emitted -> sent on the WebSocket (delivery)

Percentiles come from a bounded per-stage deque (statistics.quantiles), not the
Prometheus histogram buckets — exact over the recent window and cheap. The
published end-to-end latency is the SUM of each stage's own percentile
(21-CONTEXT.md: "su suma es la latencia end-to-end publicada").
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from enum import Enum
from typing import TYPE_CHECKING

from backend.observability.metrics import Metrics
from backend.observability.metrics import metrics as _default_metrics

if TYPE_CHECKING:
    from backend.pipeline.broker import Frame

_WINDOW = 1000
_PERCENTILES = {"p50": 50, "p95": 95, "p99": 99}


class Stage(str, Enum):
    CAPTURE_TO_PROCESS = "capture_to_process"
    PROCESS_TO_EVENT = "process_to_event"
    EVENT_TO_WS = "event_to_ws"


class LatencyTracker:
    def __init__(self, metrics: Metrics | None = None, window: int = _WINDOW) -> None:
        self._metrics = metrics or _default_metrics
        self._clock = time.monotonic
        self._samples: dict[Stage, deque[float]] = {stage: deque(maxlen=window) for stage in Stage}
        self.anomalies = 0

    def _record(self, stage: Stage, duration: float) -> float:
        if duration < 0:
            self.anomalies += 1
            return duration
        self._samples[stage].append(duration)
        self._metrics.e2e_latency_seconds.labels(stage_pair=stage.value).observe(duration)
        return duration

    def mark_processed(self, frame: "Frame") -> float:
        """captured_at -> now. Returns the CAPTURE_TO_PROCESS stage duration."""
        return self._record(Stage.CAPTURE_TO_PROCESS, self._clock() - frame.captured_at)

    def mark_event(self, frame_captured_at: float, processed_at: float) -> float:
        """processed_at -> now (event emitted). Returns the PROCESS_TO_EVENT stage duration."""
        return self._record(Stage.PROCESS_TO_EVENT, self._clock() - processed_at)

    def mark_ws_sent(self, event_emitted_at: float) -> float:
        """event emitted -> now (sent on the WebSocket). Returns the EVENT_TO_WS stage duration."""
        return self._record(Stage.EVENT_TO_WS, self._clock() - event_emitted_at)

    @staticmethod
    def _percentile(samples: list[float], pct: int) -> float:
        if len(samples) == 1:
            return samples[0]
        quantiles = statistics.quantiles(samples, n=100, method="inclusive")
        return quantiles[min(max(pct - 1, 0), len(quantiles) - 1)]

    def e2e_percentiles(self) -> dict[str, float]:
        """p50/p95/p99 of the published end-to-end latency (sum of each stage's own percentile)."""
        result: dict[str, float] = {}
        for label, pct in _PERCENTILES.items():
            total = 0.0
            for stage in Stage:
                samples = list(self._samples[stage])
                if samples:
                    total += self._percentile(samples, pct)
            result[label] = total
        return result
