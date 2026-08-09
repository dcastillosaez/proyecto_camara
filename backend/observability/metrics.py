"""Prometheus metrics catalog (SPEC_v2.md §8.4) with an isolated CollectorRegistry.

A dedicated registry (not prometheus_client's global default) avoids "Duplicated
timeseries" collisions when tests re-instantiate the module, and keeps snapshot()
scoped to exactly this project's metrics.

Instrumentation happens once per frame processed, never once per detection — a
histogram observation per bounding box would multiply the hot-loop cost for no
benefit (21-CONTEXT.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

INFERENCE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
E2E_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


@dataclass
class Metrics:
    registry: CollectorRegistry
    capture_fps: Gauge
    capture_reconnects_total: Counter
    capture_frame_age_seconds: Gauge
    frames_dropped_total: Counter
    detection_fps: Gauge
    tracking_fps: Gauge
    face_fps: Gauge
    reid_fps: Gauge
    inference_latency_seconds: Histogram
    queue_depth: Gauge
    active_tracks: Gauge
    identities_confirmed: Gauge
    identities_unknown: Gauge
    events_total: Counter
    recording_queue_depth: Gauge
    upload_queue_depth: Gauge
    upload_failures_total: Counter
    database_size_bytes: Gauge
    disk_free_bytes: Gauge
    e2e_latency_seconds: Histogram


def create_metrics() -> Metrics:
    """Build a fresh, self-contained set of metrics. Never share a registry across instances."""
    registry = CollectorRegistry()
    return Metrics(
        registry=registry,
        capture_fps=Gauge(
            "capture_fps", "FPS real de captura RTSP", ["camera"], registry=registry
        ),
        capture_reconnects_total=Counter(
            "capture_reconnects_total", "Reconexiones RTSP acumuladas", ["camera"], registry=registry
        ),
        capture_frame_age_seconds=Gauge(
            "capture_frame_age_seconds", "Antiguedad del ultimo frame servido", ["camera"], registry=registry
        ),
        frames_dropped_total=Counter(
            "frames_dropped_total", "Frames descartados por el FrameBroker",
            ["camera", "subscriber"], registry=registry,
        ),
        detection_fps=Gauge(
            "detection_fps", "FPS real de deteccion (YOLO + ByteTrack)", ["camera"], registry=registry
        ),
        tracking_fps=Gauge(
            "tracking_fps", "FPS real de tracking", ["camera"], registry=registry
        ),
        face_fps=Gauge(
            "face_fps", "FPS real de reconocimiento facial", ["camera"], registry=registry
        ),
        reid_fps=Gauge(
            "reid_fps", "FPS real de ReID", ["camera"], registry=registry
        ),
        inference_latency_seconds=Histogram(
            "inference_latency_seconds", "Latencia de inferencia por etapa",
            ["stage"], buckets=INFERENCE_BUCKETS, registry=registry,
        ),
        queue_depth=Gauge(
            "queue_depth", "Profundidad de cola", ["queue"], registry=registry
        ),
        active_tracks=Gauge(
            "active_tracks", "Tracks activos", ["camera"], registry=registry
        ),
        identities_confirmed=Gauge(
            "identities_confirmed", "Identidades confirmadas actualmente en escena", ["camera"], registry=registry
        ),
        identities_unknown=Gauge(
            "identities_unknown", "Identidades desconocidas actualmente en escena", ["camera"], registry=registry
        ),
        events_total=Counter(
            "events_total", "Eventos tipados emitidos", ["type", "severity", "camera"], registry=registry
        ),
        recording_queue_depth=Gauge(
            "recording_queue_depth", "Peticiones de clip pendientes de ensamblar", registry=registry
        ),
        upload_queue_depth=Gauge(
            "upload_queue_depth", "Grabaciones pendientes de subir a Drive", registry=registry
        ),
        upload_failures_total=Counter(
            "upload_failures_total", "Fallos de subida a Drive", ["reason"], registry=registry
        ),
        database_size_bytes=Gauge(
            "database_size_bytes", "Tamano del fichero events.db", registry=registry
        ),
        disk_free_bytes=Gauge(
            "disk_free_bytes", "Espacio libre en disco", registry=registry
        ),
        e2e_latency_seconds=Histogram(
            "e2e_latency_seconds", "Latencia end-to-end por tramo",
            ["stage_pair"], buckets=E2E_BUCKETS, registry=registry,
        ),
    )


metrics: Metrics = create_metrics()
REGISTRY: CollectorRegistry = metrics.registry


def _reset_for_tests() -> Metrics:
    """Rebuild metrics against a brand-new registry. Tests need isolation between runs —
    the module-level singleton would otherwise accumulate state across test functions."""
    global metrics, REGISTRY
    metrics = create_metrics()
    REGISTRY = metrics.registry
    return metrics


def _label_key(labels: dict[str, str]) -> str:
    """Stable, JSON-safe key for a label combination — str(dict) round-trips via ast.literal_eval."""
    return str(dict(sorted(labels.items())))


def snapshot() -> dict[str, Any]:
    """JSON-serializable view of every metric: {"gauges": {...}, "counters": {...}, "histograms": {...}}."""
    gauges: dict[str, dict[str, float]] = {}
    counters: dict[str, dict[str, float]] = {}
    histograms: dict[str, dict[str, dict[str, Any]]] = {}

    for family in REGISTRY.collect():
        if family.type == "gauge":
            bucket = gauges.setdefault(family.name, {})
            for sample in family.samples:
                bucket[_label_key(sample.labels)] = sample.value
        elif family.type == "counter":
            # prometheus_client strips the _total suffix from family.name for counters —
            # the samples still carry it, which is the name we actually declared.
            bucket = counters.setdefault(f"{family.name}_total", {})
            for sample in family.samples:
                if sample.name.endswith("_total"):
                    bucket[_label_key(sample.labels)] = sample.value
        elif family.type == "histogram":
            entries = histograms.setdefault(family.name, {})
            per_label: dict[str, dict[str, Any]] = {}
            for sample in family.samples:
                label_labels = {k: v for k, v in sample.labels.items() if k != "le"}
                key = _label_key(label_labels)
                entry = per_label.setdefault(key, {"count": 0.0, "sum": 0.0, "buckets": {}})
                if sample.name.endswith("_count"):
                    entry["count"] = sample.value
                elif sample.name.endswith("_sum"):
                    entry["sum"] = sample.value
                elif sample.name.endswith("_bucket"):
                    entry["buckets"][sample.labels["le"]] = sample.value
            entries.update(per_label)

    return {"gauges": gauges, "counters": counters, "histograms": histograms}


def generate_latest_text() -> str:
    """Prometheus text exposition format (Content-Type: text/plain; version=0.0.4)."""
    return generate_latest(REGISTRY).decode("utf-8")
