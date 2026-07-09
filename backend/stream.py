"""RTSP stream capture with drain thread and auto-reconnection."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from backend.config import get_settings

if TYPE_CHECKING:
    from backend.detector import Detection, PersonDetector
    from backend.recognizer import PersonRecognizer
    from backend.tracker import PersonTracker

logger = logging.getLogger(__name__)


class RTSPStream:
    """Captures RTSP frames in a daemon thread, keeping only the latest.

    Uses a drain pattern: a background thread reads frames as fast as
    possible, discarding all but the most recent one.  This prevents the
    OpenCV internal buffer from accumulating stale frames and introducing
    progressive latency.

    Reconnection uses exponential backoff (1 s to 30 s) when the camera
    becomes unreachable.

    Pipeline (when both *detector* and *tracker* are supplied):
        raw frame → detect_sv → ByteTrack + LineZone → annotate
    When only *detector* is supplied, falls back to the Phase-3 pipeline.

    Face recognition runs in a dedicated worker thread (MEJORAS.md punto
    10): the capture thread only gates and enqueues person crops, so the
    100-500 ms dlib pass never blocks capture — no dropped frames, no
    MJPEG stutter, no ByteTrack track losses while identifying.
    """

    # Padding (px) around the person bbox for recognition/gallery crops.
    CROP_PAD = 20
    # Cache pruning cadence (frames) and age after which a tracker_id is
    # considered gone (MEJORAS.md punto 12). ByteTrack ids are monotonic,
    # so per-track dicts leak without this.
    PRUNE_EVERY = 300
    PRUNE_AGE = 600

    def __init__(
        self,
        url: str,
        detector: PersonDetector | None = None,
        tracker: PersonTracker | None = None,
        recognizer: PersonRecognizer | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
        event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> None:
        self._url = url
        self._detector = detector
        self._tracker = tracker
        self._recognizer = recognizer
        self._event_loop = event_loop
        self._event_queue = event_queue
        self._frame: np.ndarray | None = None
        self._detections: list[Detection] = []
        self._live_count: int = 0
        self._process_size: tuple[int, int] | None = None  # (w, h) or None = native
        self._lock = threading.Lock()
        self._running = False
        self._cap: cv2.VideoCapture | None = None
        self._frame_num = 0
        # tracker_id → (person_id, name) for the current session
        self._person_cache: dict[int, tuple[int, str | None]] = {}
        self._settings = get_settings()
        # person_id → unix timestamp of last gallery capture
        self._last_capture: dict[int, float] = {}
        # active interest zones loaded from DB (updated via set_zones)
        self._zones: list[dict] = []
        self._fps_times: deque[float] = deque()
        self._fps: float = 0.0
        # Recognition worker (MEJORAS.md punto 10): capture thread enqueues
        # (crop, tracker_id); worker runs dlib and updates _person_cache.
        # Bounded queue — under load, dropping an attempt is harmless (the
        # recognizer's own gating retries on the next interval).
        self._recog_queue: queue.Queue[tuple[np.ndarray, int]] = queue.Queue(maxsize=8)
        self._recog_thread: threading.Thread | None = None
        # Run YOLO 1 of every N frames (MEJORAS.md punto 11); on skipped
        # frames the last tracked detections are re-used for annotation.
        self._detect_every = max(1, self._settings.detect_every)
        self._last_tracked: Any | None = None
        # tracker_id → last frame number it was seen in (for cache pruning)
        self._tid_last_seen: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background capture thread (and the recognition worker)."""
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        if self._recognizer is not None and self._recognizer.available:
            self._recog_thread = threading.Thread(
                target=self._recognition_worker, daemon=True
            )
            self._recog_thread.start()

    def stop(self) -> None:
        """Signal the capture thread to stop and release resources."""
        self._running = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def get_frame(self) -> np.ndarray | None:
        """Return a *copy* of the latest (possibly annotated) frame, or ``None``."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def get_detections(self) -> list[Detection]:
        """Return the bounding boxes from the last detection pass."""
        with self._lock:
            return list(self._detections)

    def get_live_count(self) -> int:
        """Return the number of persons visible in the current frame."""
        with self._lock:
            return self._live_count

    def get_fps(self) -> float:
        """Return the measured processing FPS over the last 5 seconds."""
        with self._lock:
            return self._fps

    def get_native_resolution(self) -> tuple[int, int]:
        """Return native camera resolution (w, h) from the capture, or (0, 0)."""
        cap = self._cap
        if cap is None or not cap.isOpened():
            return (0, 0)
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def set_process_size(self, w: int, h: int) -> None:
        """Change the processing resolution (resize applied before YOLO). Thread-safe."""
        with self._lock:
            self._process_size = (w, h) if (w > 0 and h > 0) else None

    def get_process_size(self) -> tuple[int, int]:
        """Return current processing size as (w, h), or (0, 0) if native."""
        with self._lock:
            return self._process_size if self._process_size is not None else (0, 0)

    def get_counts(self) -> dict[str, int]:
        """Return cumulative line-crossing counts from the tracker, or zeros."""
        if self._tracker is None:
            return {"in": 0, "out": 0, "total": 0}
        return self._tracker.get_counts()

    def set_zones(self, zones: list[dict]) -> None:
        """Replace the active interest zones list. Thread-safe."""
        with self._lock:
            self._zones = list(zones)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_in_schedule(self) -> bool:
        """Return True if current time falls within the configured access schedule."""
        import datetime as _dt
        s = self._settings
        if not s.schedule_enabled:
            return True
        now = _dt.datetime.now()
        if now.weekday() not in s.schedule_days:
            return False
        sh, sm = map(int, s.schedule_start.split(":"))
        eh, em = map(int, s.schedule_end.split(":"))
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        return start <= now <= end

    def _try_save_capture(self, crop: np.ndarray, person_id: int) -> None:
        """Save a person crop to the gallery (throttled). Runs in the worker."""
        import datetime as _dt
        now = time.time()
        if now - self._last_capture.get(person_id, 0) < self._settings.gallery_throttle_secs:
            return
        self._last_capture[person_id] = now
        if len(self._last_capture) > 256:
            expired = now - self._settings.gallery_throttle_secs
            for pid in [p for p, t in self._last_capture.items() if t < expired]:
                del self._last_capture[pid]

        if crop.size == 0:
            return

        gallery_dir = os.path.join(self._settings.gallery_dir, str(person_id))
        os.makedirs(gallery_dir, exist_ok=True)
        ts = _dt.datetime.now()
        image_path = os.path.join(gallery_dir, f"{ts.strftime('%Y%m%d_%H%M%S')}.jpg")
        cv2.imwrite(image_path, crop)

        if self._event_loop is not None:
            import asyncio as _asyncio
            from backend.database import insert_capture as _ic
            _asyncio.run_coroutine_threadsafe(_ic(person_id, ts, image_path), self._event_loop)

    def _capture_loop(self) -> None:
        """Read frames in a tight loop, keeping only the newest."""
        self._cap = self._create_capture()
        _diag_counter = 0
        while self._running:
            cap = self._cap
            if cap is None or not cap.isOpened():
                self._reconnect()
                continue
            ret, frame = cap.read()
            if not ret:
                self._reconnect()
                continue

            with self._lock:
                proc_size = self._process_size
            if proc_size is not None:
                frame = cv2.resize(frame, proc_size)

            if self._detector is not None and self._tracker is not None:
                # Full pipeline: YOLO → ByteTrack → LineZone → recognition worker
                self._frame_num += 1
                run_detection = (
                    self._detect_every == 1
                    or self._frame_num % self._detect_every == 1
                    or self._last_tracked is None
                )
                if run_detection:
                    sv_dets = self._detector.detect_sv(frame)
                    tracked, crossings = self._tracker.update(sv_dets)
                    self._last_tracked = tracked
                else:
                    # Skipped frame (MEJORAS.md punto 11): re-use the last
                    # tracked boxes for the overlay. The tracker and line
                    # zone only advance on detection frames, so counts
                    # never double-fire from stale boxes.
                    tracked = self._last_tracked
                    crossings = []

                # Snapshot once per frame — the recognition worker mutates
                # _person_cache concurrently.
                with self._lock:
                    cache_snap = dict(self._person_cache)

                if crossings and self._event_loop and self._event_queue:
                    is_intrusion = not self._is_in_schedule()
                    for c in crossings:
                        tid_c = c.get("tracker_id")
                        person_name = None
                        if tid_c is not None and tid_c in cache_snap:
                            pid_c, name_c = cache_snap[tid_c]
                            person_name = name_c if name_c else f"P{pid_c}"
                        self._event_loop.call_soon_threadsafe(
                            self._event_queue.put_nowait,
                            {**c, "person_name": person_name, "is_intrusion": is_intrusion},
                        )

                # Face recognition (MEJORAS.md punto 10): the capture thread
                # only gates and enqueues crops; the dlib pass runs in
                # _recognition_worker and publishes into _person_cache.
                labels: list[str] = []
                if tracked.tracker_id is not None:
                    for i, tid in enumerate(tracked.tracker_id):
                        tid = int(tid)
                        conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
                        self._tid_last_seen[tid] = self._frame_num

                        if (
                            run_detection
                            and self._recognizer is not None
                            and self._recognizer.should_attempt(tid, self._frame_num)
                        ):
                            x1, y1, x2, y2 = map(int, tracked.xyxy[i])
                            p = self.CROP_PAD
                            fh, fw = frame.shape[:2]
                            crop = frame[
                                max(0, y1 - p):min(fh, y2 + p),
                                max(0, x1 - p):min(fw, x2 + p),
                            ].copy()
                            if crop.size:
                                try:
                                    self._recog_queue.put_nowait((crop, tid))
                                except queue.Full:
                                    # Worker saturated — drop; the gating in
                                    # should_attempt retries next interval.
                                    pass

                        if tid in cache_snap:
                            pid, name = cache_snap[tid]
                            label = name if name else f"P{pid}"
                            labels.append(f"{label} {conf:.2f}")
                        else:
                            labels.append(f"#{tid} {conf:.2f}")

                if self._frame_num % self.PRUNE_EVERY == 0:
                    self._prune_caches()

                frame = self._tracker.annotate(frame, tracked, labels=labels or None)

                # Draw interest zones overlay on annotated frame
                with self._lock:
                    zones_snap = list(self._zones)
                if zones_snap:
                    fh, fw = frame.shape[:2]
                    for z in zones_snap:
                        if not z.get("enabled", True):
                            continue
                        try:
                            pts = np.array(
                                [[int(p[0] * fw), int(p[1] * fh)]
                                 for p in json.loads(z["polygon_json"])],
                                dtype=np.int32,
                            )
                            cv2.polylines(frame, [pts], isClosed=True, color=(0, 200, 255), thickness=2)
                            cv2.putText(
                                frame, z["name"], tuple(pts[0]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1,
                            )
                        except Exception:
                            pass

                detections = []
                live = len(tracked.xyxy) if tracked.xyxy is not None else 0

            elif self._detector is not None:
                # Phase-3 fallback: plain YOLO boxes, no tracking
                detections = self._detector.detect(frame)
                frame = self._detector.annotate(frame, detections)
                live = len(detections)
            else:
                detections = []
                live = 0

            now = time.monotonic()
            self._fps_times.append(now)
            while self._fps_times and now - self._fps_times[0] > 5.0:
                self._fps_times.popleft()
            with self._lock:
                self._frame = frame
                self._detections = detections
                self._live_count = live
                self._fps = len(self._fps_times) / 5.0

    def _recognition_worker(self) -> None:
        """Consume person crops and run face recognition off the capture thread.

        MEJORAS.md punto 10 (y 13: los commits SQLite del recognizer ahora
        ocurren aquí, no en el hilo caliente de captura).
        """
        while self._running:
            try:
                crop, tid = self._recog_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                pid, name, _ = self._recognizer.process_crop(crop, tid)
            except Exception:
                logger.exception("Recognition worker error (tracker %d)", tid)
                continue
            if pid is None:
                continue
            with self._lock:
                first_time = tid not in self._person_cache
                self._person_cache[tid] = (pid, name)
            if first_time:
                self._try_save_capture(crop, pid)

    def _prune_caches(self) -> None:
        """Drop state for tracks not seen in PRUNE_AGE frames (MEJORAS.md punto 12)."""
        stale = {
            tid for tid, fn in self._tid_last_seen.items()
            if self._frame_num - fn > self.PRUNE_AGE
        }
        if not stale:
            return
        for tid in stale:
            del self._tid_last_seen[tid]
        with self._lock:
            for tid in stale:
                self._person_cache.pop(tid, None)
        if self._recognizer is not None:
            self._recognizer.prune(set(self._tid_last_seen))

    def _create_capture(self) -> cv2.VideoCapture:
        """Create a fresh ``VideoCapture`` tuned for low-latency RTSP."""
        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _reconnect(self) -> None:
        """Release the current capture and reconnect with exponential backoff."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        delay = 1.0
        max_delay = 30.0

        while self._running:
            logger.warning("Reconnecting RTSP in %.1fs...", delay)
            time.sleep(delay)
            cap = self._create_capture()
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    self._cap = cap
                    logger.info("RTSP reconnection successful")
                    return
            cap.release()
            delay = min(delay * 2, max_delay)
