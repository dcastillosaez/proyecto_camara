"""MetricsSampler: periodic snapshot of worker health into Prometheus gauges.

Runs every metrics_sample_secs (default 5.0) as an asyncio.Task. FPS is computed
here by dividing a delta of frames processed by elapsed time — never inside a
worker's hot loop (21-CONTEXT.md: "no calcularlos en cada frame"). Everything
this reads (CaptureHealth, DetectionWorker.stats, RingFrameBuffer.bytes_used...)
already existed from Fases 17-20; this module just unifies it into Prometheus.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

from backend.observability.metrics import Metrics
from backend.storage.repositories import RecordingRepo, UploadState

logger = logging.getLogger(__name__)


def _mirror_counter(counter, labels: dict[str, str], value: float) -> None:
    """Set a Counter's exposed value directly, mirroring a cumulative count that's
    already tracked authoritatively elsewhere (CaptureWorker.reconnects, broker
    dropped counts). Counter has no public .set() by design — this is the
    conventional workaround for "external cumulative counter" cases."""
    counter.labels(**labels)._value.set(value)


class MetricsSampler:
    def __init__(
        self,
        metrics: Metrics,
        camera_manager,
        event_bus=None,
        recording_repo: RecordingRepo | None = None,
        db_path: str = "data/events.db",
        interval: float = 5.0,
    ) -> None:
        self._metrics = metrics
        self._camera_manager = camera_manager
        self._event_bus = event_bus
        self._recording_repo = recording_repo
        self._db_path = db_path
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._last_frames_processed: dict[str, int] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.sample_once()
            except Exception:
                logger.exception("MetricsSampler: sample failed")

    async def sample_once(self) -> None:
        for pipeline in self._camera_manager.all():
            self._sample_pipeline(pipeline)

        if self._event_bus is not None:
            self._metrics.queue_depth.labels(queue="event_bus").set(self._event_bus.queue_depth)

        if self._recording_repo is not None:
            pending = await self._recording_repo.count_by_upload_state(UploadState.PENDING)
            self._metrics.upload_queue_depth.set(pending)

        self._sample_system()

    def _sample_pipeline(self, pipeline) -> None:
        camera_id = pipeline.camera_id
        m = self._metrics

        health = pipeline.health
        m.capture_fps.labels(camera=camera_id).set(health.fps)
        _mirror_counter(m.capture_reconnects_total, {"camera": camera_id}, health.reconnects)
        age = health.last_frame_age_s
        m.capture_frame_age_seconds.labels(camera=camera_id).set(age if age != float("inf") else -1.0)

        broker_stats = pipeline.broker.stats()
        for subscriber, sub_stats in broker_stats.items():
            _mirror_counter(
                m.frames_dropped_total, {"camera": camera_id, "subscriber": subscriber},
                sub_stats.get("dropped", 0),
            )

        if pipeline.detection is not None:
            det_stats = pipeline.detection.stats
            processed = det_stats.get("frames_processed", 0)
            key = f"{camera_id}:detection"
            last = self._last_frames_processed.get(key, processed)
            measured_fps = max(0.0, (processed - last) / self._interval)
            self._last_frames_processed[key] = processed
            m.detection_fps.labels(camera=camera_id).set(measured_fps)
            # Tracking (ByteTrack) is fused into the same loop as detection in this
            # architecture — same measured rate, not a placeholder zero.
            m.tracking_fps.labels(camera=camera_id).set(measured_fps)

        if pipeline.recognition is not None:
            rec_stats = pipeline.recognition.stats
            m.face_fps.labels(camera=camera_id).set(rec_stats.get("effective_fps", 0.0))

        identities_confirmed = 0
        identities_unknown = 0
        for track in pipeline.registry.snapshot().values():
            if track.person_id is not None:
                identities_confirmed += 1
            else:
                identities_unknown += 1
        m.identities_confirmed.labels(camera=camera_id).set(identities_confirmed)
        m.identities_unknown.labels(camera=camera_id).set(identities_unknown)

        if pipeline.recording is not None:
            rec_worker_stats = pipeline.recording.stats
            m.prebuffer_bytes.labels(camera=camera_id).set(rec_worker_stats.get("prebuffer_bytes", 0))
            m.recording_queue_depth.set(rec_worker_stats.get("requests_queue_depth", 0))

    def _sample_system(self) -> None:
        m = self._metrics
        try:
            if os.path.exists(self._db_path):
                m.database_size_bytes.set(os.path.getsize(self._db_path))
        except OSError:
            logger.debug("MetricsSampler: could not stat %s", self._db_path)
        try:
            usage = shutil.disk_usage(os.path.dirname(self._db_path) or ".")
            m.disk_free_bytes.set(usage.free)
        except OSError:
            logger.debug("MetricsSampler: could not read disk usage")
