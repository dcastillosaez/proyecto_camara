"""Tests for backend.observability.sampler.MetricsSampler — worker health -> Prometheus gauges."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.observability.metrics import create_metrics
from backend.observability.sampler import MetricsSampler


def make_pipeline(camera_id="cam1"):
    health = SimpleNamespace(fps=14.9, reconnects=2, last_frame_age_s=0.3, connected=True)
    broker = MagicMock()
    broker.stats.return_value = {"detector": {"dropped": 5, "delivered": 100, "last_seq": 100}}
    detection = MagicMock()
    detection.stats = {"frames_processed": 40, "effective_fps": 8.0}
    recognition = MagicMock()
    recognition.stats = {"effective_fps": 2.0, "identified": 3}
    recording = MagicMock()
    recording.stats = {"prebuffer_bytes": 1024, "requests_queue_depth": 0}
    registry = MagicMock()
    registry.snapshot.return_value = {
        1: SimpleNamespace(person_id=5),
        2: SimpleNamespace(person_id=None),
    }
    return SimpleNamespace(
        camera_id=camera_id, health=health, broker=broker, detection=detection,
        recognition=recognition, recording=recording, registry=registry,
    )


def make_sampler(pipelines):
    metrics = create_metrics()
    camera_manager = MagicMock()
    camera_manager.all.return_value = pipelines
    sampler = MetricsSampler(metrics, camera_manager, interval=5.0)
    return sampler, metrics


def TEST_sample_pipeline_sets_capture_gauges():
    pipeline = make_pipeline()
    sampler, metrics = make_sampler([pipeline])

    sampler._sample_pipeline(pipeline)

    assert metrics.capture_fps.labels(camera="cam1")._value.get() == 14.9
    assert metrics.capture_frame_age_seconds.labels(camera="cam1")._value.get() == 0.3


def TEST_sample_pipeline_mirrors_reconnects_and_dropped():
    pipeline = make_pipeline()
    sampler, metrics = make_sampler([pipeline])

    sampler._sample_pipeline(pipeline)

    assert metrics.capture_reconnects_total.labels(camera="cam1")._value.get() == 2
    assert metrics.frames_dropped_total.labels(camera="cam1", subscriber="detector")._value.get() == 5


def TEST_sample_pipeline_computes_measured_detection_fps():
    pipeline = make_pipeline()
    sampler, metrics = make_sampler([pipeline])

    sampler._sample_pipeline(pipeline)  # first tick: baseline (0 frames since last -> 0 fps... wait first call has no prior)
    pipeline.detection.stats = {"frames_processed": 80, "effective_fps": 8.0}
    sampler._sample_pipeline(pipeline)  # second tick: 40 frames in 5s -> 8 fps

    assert abs(metrics.detection_fps.labels(camera="cam1")._value.get() - 8.0) < 1e-6


def TEST_sample_pipeline_counts_identities():
    pipeline = make_pipeline()
    sampler, metrics = make_sampler([pipeline])

    sampler._sample_pipeline(pipeline)

    assert metrics.identities_confirmed.labels(camera="cam1")._value.get() == 1
    assert metrics.identities_unknown.labels(camera="cam1")._value.get() == 1


async def TEST_sample_once_reads_upload_queue_depth():
    pipeline = make_pipeline()
    sampler, metrics = make_sampler([pipeline])

    repo = MagicMock()

    async def count_by_upload_state(state):
        return 3

    repo.count_by_upload_state = count_by_upload_state
    sampler._recording_repo = repo

    await sampler.sample_once()

    assert metrics.upload_queue_depth._value.get() == 3
