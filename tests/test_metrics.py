"""Tests for backend.observability.metrics — Prometheus registry and catalog."""

from __future__ import annotations

import json

from backend.observability import metrics as m

# SPEC_v2.md §8.4 — literal catalog, so a drifted name/label breaks this test loudly.
EXPECTED_METRICS = {
    "capture_fps",
    "capture_reconnects_total",
    "capture_frame_age_seconds",
    "frames_dropped_total",
    "detection_fps",
    "tracking_fps",
    "face_fps",
    "reid_fps",
    "inference_latency_seconds",
    "queue_depth",
    "active_tracks",
    "identities_confirmed",
    "identities_unknown",
    "events_total",
    "recording_queue_depth",
    "upload_queue_depth",
    "upload_failures_total",
    "database_size_bytes",
    "disk_free_bytes",
    "e2e_latency_seconds",
}


def _full_family_names() -> set[str]:
    """prometheus_client strips the _total suffix from Counter family.name — restore it
    so the catalog check compares against the names as declared (and as SPEC_v2.md lists)."""
    names = set()
    for mf in m.REGISTRY.collect():
        names.add(f"{mf.name}_total" if mf.type == "counter" else mf.name)
    return names


def TEST_catalog_complete():
    m._reset_for_tests()
    assert EXPECTED_METRICS <= _full_family_names()


def TEST_naming_convention():
    m._reset_for_tests()
    for name in _full_family_names():
        family_type = next(mf.type for mf in m.REGISTRY.collect() if f"{mf.name}_total" == name or mf.name == name)
        if family_type == "counter":
            assert name.endswith("_total"), f"{name} is a counter but doesn't end in _total"
    for name in ("inference_latency_seconds", "e2e_latency_seconds"):
        assert name.endswith("_seconds")


def TEST_labels_present():
    metrics = m._reset_for_tests()
    metrics.frames_dropped_total.labels(camera="cam1", subscriber="detector").inc()
    metrics.inference_latency_seconds.labels(stage="yolo").observe(0.05)

    families = {mf.name: mf for mf in m.REGISTRY.collect()}
    dropped_sample = next(
        s for s in families["frames_dropped"].samples if s.name == "frames_dropped_total"
    )
    assert set(dropped_sample.labels) == {"camera", "subscriber"}

    latency_family = families["inference_latency_seconds"]
    bucket_sample = next(s for s in latency_family.samples if s.name.endswith("_bucket"))
    assert "stage" in bucket_sample.labels


def TEST_snapshot_returns_json_serializable():
    m._reset_for_tests()
    data = m.snapshot()
    json.dumps(data)  # must not raise
    assert "gauges" in data
    assert "counters" in data
    assert "histograms" in data


def TEST_registry_is_isolated():
    m._reset_for_tests()
    m._reset_for_tests()  # must not raise "Duplicated timeseries"


def TEST_counter_increments():
    metrics = m._reset_for_tests()
    metrics.upload_failures_total.labels(reason="network").inc()
    metrics.upload_failures_total.labels(reason="network").inc()

    data = m.snapshot()
    assert data["counters"]["upload_failures_total"][str({"reason": "network"})] == 2.0

    text = m.generate_latest_text()
    assert "upload_failures_total" in text


def TEST_histogram_observes():
    metrics = m._reset_for_tests()
    metrics.e2e_latency_seconds.labels(stage_pair="capture_to_process").observe(0.3)
    metrics.e2e_latency_seconds.labels(stage_pair="capture_to_process").observe(0.7)

    data = m.snapshot()
    hist = data["histograms"]["e2e_latency_seconds"][str({"stage_pair": "capture_to_process"})]
    assert hist["count"] == 2
    assert abs(hist["sum"] - 1.0) < 1e-6
    assert any(count >= 2 for count in hist["buckets"].values())
