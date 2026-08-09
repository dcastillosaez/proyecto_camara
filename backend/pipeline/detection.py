"""DetectionWorker — YOLO + ByteTrack + zonas + heatmap, con ritmo propio.

Porta la parte de deteccion/tracking/zonas/heatmap de
RTSPStream._process_frame (Fase 17) a un worker independiente que
consume del FrameBroker a su propio ritmo, gobernado por AdaptiveRate
en vez del contador fijo detect_every (SPEC_v2.md §5.3, 18-CONTEXT.md).
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import supervision as sv

from backend.observability.metrics import metrics as _metrics
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.detector import PersonDetector
    from backend.events.engine import EventEngine
    from backend.observability.latency import LatencyTracker
    from backend.pipeline.broker import Subscription
    from backend.tracker import PersonTracker

logger = logging.getLogger(__name__)


class DetectionWorker:
    """
    Consume frames del broker, ejecuta YOLO + ByteTrack a su FPS objetivo
    (ajustado por AdaptiveRate segun la latencia real) y publica el
    resultado en un TrackRegistry compartido.

    No conoce a los demas workers: escribe en el registry y en la cola de
    eventos existente; StreamingWorker y RecognitionWorker leen del
    registry por su cuenta (18-CONTEXT.md, "TrackRegistry es el punto de
    encuentro").
    """

    def __init__(
        self,
        sub: Subscription,
        detector: PersonDetector,
        tracker: PersonTracker,
        registry: TrackRegistry,
        rate: AdaptiveRate,
        event_engine: EventEngine | None = None,
        is_intrusion: Any = None,
        camera_id: str = "cam1",
        latency_tracker: LatencyTracker | None = None,
    ) -> None:
        self._sub = sub
        self._detector = detector
        self._tracker = tracker
        self._registry = registry
        self._rate = rate
        self._event_engine = event_engine
        self._camera_id = camera_id
        self._latency_tracker = latency_tracker
        # Callable[[], bool] opcional — decide si un cruce es intrusion
        # (RTSPStream._is_in_schedule). Sin ella, nunca se marca intrusion.
        self._is_intrusion = is_intrusion

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_effective_fps: float | None = None
        self._frames_processed = 0
        self._exceptions = 0

        self._lock = threading.Lock()
        self._zones: list[dict] = []
        self._zones_dirty = True
        self._zone_states: list[dict] = []
        self._zone_frame_size: tuple[int, int] = (0, 0)
        self._heat_mask: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="detection-worker"
        )
        self._thread.start()

    def is_alive(self) -> bool:
        """True si el hilo del worker sigue vivo (lo consulta WorkerSupervisor)."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("DetectionWorker: thread did not stop within %.1fs", timeout)
        self._sub.close()

    @property
    def stats(self) -> dict:
        return {
            "frames_processed": self._frames_processed,
            "exceptions": self._exceptions,
            **self._rate.stats,
        }

    def set_zones(self, zones: list[dict]) -> None:
        """Replace the active interest zones list. Thread-safe."""
        with self._lock:
            self._zones = list(zones)
            self._zones_dirty = True

    def get_zone_stats(self) -> list[dict]:
        with self._lock:
            return [
                {"id": st["id"], "name": st["name"], "current": st["current"], "entries": st["entries"]}
                for st in self._zone_states
            ]

    def compose_heatmap(self, frame: np.ndarray) -> np.ndarray | None:
        """Compose the accumulated activity heat map over *frame*. Heavy — call off the event loop."""
        with self._lock:
            mask = None if self._heat_mask is None else self._heat_mask.copy()
        if mask is None:
            return None
        peak = float(mask.max())
        if peak <= 0:
            return None
        if mask.shape != frame.shape[:2]:
            mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
        temp = np.clip(mask / peak * 255.0, 0, 255).astype(np.uint8)
        temp = cv2.blur(temp, (25, 25))
        colored = cv2.applyColorMap(temp, cv2.COLORMAP_JET)
        blended = cv2.addWeighted(frame, 0.5, colored, 0.5, 0)
        active = temp > 0
        out = frame.copy()
        out[active] = blended[active]
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            if not self._rate.should_process(time.monotonic()):
                continue

            t0 = time.monotonic()
            try:
                sv_dets = self._detector.detect_sv(frame.image)
                tracked, crossings = self._tracker.update(sv_dets)
            except Exception:
                self._exceptions += 1
                logger.exception("DetectionWorker: fallo de inferencia, se salta el frame")
                continue

            inference_latency = time.monotonic() - t0
            self._rate.observe(inference_latency)
            _metrics.inference_latency_seconds.labels(stage="yolo").observe(inference_latency)
            self._frames_processed += 1
            self._sync_tracker_frame_rate()

            if self._latency_tracker is not None:
                self._latency_tracker.mark_processed(frame)

            now = time.monotonic()  # "processed_at" for OBS-03 — right after inference, before event emission
            _metrics.active_tracks.labels(camera=self._camera_id).set(len(tracked))
            self._registry.update_from_detections(tracked, now)
            self._update_zones_and_heat(tracked, frame.image.shape, frame.captured_at, now)
            self._emit_crossings(crossings, frame.captured_at, now)
            self._emit_track_lifecycle(tracked, frame.captured_at, now)
            self._registry.prune(now)

    def _emit_track_lifecycle(self, tracked: Any, captured_at: float, processed_at: float) -> None:
        if self._event_engine is None:
            return
        wall_now = datetime.datetime.now()
        ids = tracked.tracker_id
        active_ids = {int(tid) for tid in ids} if ids is not None else set()
        self._event_engine.process_tracks(active_ids, wall_now, captured_at, processed_at)
        confidences = list(tracked.confidence) if tracked.confidence is not None else []
        self._event_engine.accumulate_detections(wall_now, active_ids, confidences)

    def _sync_tracker_frame_rate(self) -> None:
        """Si AdaptiveRate cambio de escalon, sincroniza ByteTrack (riesgo #1 de la fase)."""
        fps = self._rate.effective_fps
        if fps != self._last_effective_fps:
            self._last_effective_fps = fps
            self._tracker.set_frame_rate(fps)

    def _emit_crossings(self, crossings: list[dict], captured_at: float, processed_at: float) -> None:
        if not crossings or self._event_engine is None:
            return
        is_intrusion = bool(self._is_intrusion()) if self._is_intrusion else False
        for c in crossings:
            self._event_engine.emit_line_crossing(
                {**c, "is_intrusion": is_intrusion}, captured_at, processed_at
            )

    def _update_zones_and_heat(
        self, tracked: Any, shape: tuple, captured_at: float = 0.0, processed_at: float = 0.0
    ) -> None:
        """Trigger the PolygonZones and accumulate the activity heat mask (MEJORAS.md Bajas)."""
        fh, fw = shape[:2]
        with self._lock:
            dirty = self._zones_dirty
            self._zones_dirty = False
            zones_snap = list(self._zones)
        if dirty or self._zone_frame_size != (fw, fh):
            self._zone_frame_size = (fw, fh)
            self._rebuild_zone_states(zones_snap, fw, fh)

        ids = tracked.tracker_id
        for st in self._zone_states:
            mask = st["zone"].trigger(tracked)
            inside = (
                {int(ids[i]) for i in np.flatnonzero(mask)}
                if ids is not None and len(mask)
                else set()
            )
            with self._lock:
                st["entries"] += len(inside - st["inside"])
                st["inside"] = inside
                st["current"] = len(inside)
            if self._event_engine is not None:
                self._event_engine.process_zone(
                    st["id"], inside, datetime.datetime.now(), captured_at, processed_at
                )

        if len(tracked) == 0:
            return
        if self._heat_mask is None or self._heat_mask.shape != (fh, fw):
            self._heat_mask = np.zeros((fh, fw), dtype=np.float32)
        pts_mask = np.zeros((fh, fw), dtype=np.float32)
        for xy in tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER):
            cv2.circle(pts_mask, (int(xy[0]), int(xy[1])), 40, 1, -1)
        self._heat_mask += pts_mask

    def _rebuild_zone_states(self, zones: list[dict], fw: int, fh: int) -> None:
        states: list[dict] = []
        for z in zones:
            if not z.get("enabled", True):
                continue
            try:
                pts = np.array(
                    [[int(p[0] * fw), int(p[1] * fh)] for p in json.loads(z["polygon_json"])],
                    dtype=np.int64,
                )
                if len(pts) < 3:
                    continue
                states.append({
                    "id": z["id"],
                    "name": z["name"],
                    "polygon": pts,
                    "zone": sv.PolygonZone(polygon=pts),
                    "inside": set(),
                    "entries": 0,
                    "current": 0,
                })
            except Exception:
                logger.warning("DetectionWorker: zone %s invalid polygon_json, skipped", z.get("id"))
        with self._lock:
            self._zone_states = states
