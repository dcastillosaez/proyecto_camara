"""RTSP stream capture with drain thread and auto-reconnection."""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
    """

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background capture thread."""
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

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

    def _try_save_capture(
        self,
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
        person_id: int,
    ) -> None:
        """Save a cropped capture for a recognised person (throttled)."""
        import datetime as _dt
        now = time.time()
        if now - self._last_capture.get(person_id, 0) < self._settings.gallery_throttle_secs:
            return
        self._last_capture[person_id] = now

        x1, y1, x2, y2 = bbox
        pad = 20
        h, w = frame.shape[:2]
        crop = frame[max(0, y1 - pad):min(h, y2 + pad), max(0, x1 - pad):min(w, x2 + pad)]
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
                # Full pipeline: YOLO → ByteTrack → LineZone → (face recognition)
                self._frame_num += 1
                sv_dets = self._detector.detect_sv(frame)
                tracked, crossings = self._tracker.update(sv_dets)
                if crossings and self._event_loop and self._event_queue:
                    is_intrusion = not self._is_in_schedule()
                    for c in crossings:
                        tid_c = c.get("tracker_id")
                        person_name = None
                        if tid_c is not None and tid_c in self._person_cache:
                            pid_c, name_c = self._person_cache[tid_c]
                            person_name = name_c if name_c else f"P{pid_c}"
                        self._event_loop.call_soon_threadsafe(
                            self._event_queue.put_nowait,
                            {**c, "person_name": person_name, "is_intrusion": is_intrusion},
                        )

                # Face recognition — try to identify each tracked person
                labels: list[str] = []
                if tracked.tracker_id is not None:
                    for i, tid in enumerate(tracked.tracker_id):
                        tid = int(tid)
                        conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0

                        # Run recognizer if available and person not yet cached
                        if self._recognizer is not None and tid not in self._person_cache:
                            x1, y1, x2, y2 = map(int, tracked.xyxy[i])
                            pid, name, _ = self._recognizer.identify_or_register(
                                frame, (x1, y1, x2, y2), tid, self._frame_num
                            )
                            if pid is not None:
                                self._person_cache[tid] = (pid, name)
                                self._try_save_capture(frame, (x1, y1, x2, y2), pid)

                        if tid in self._person_cache:
                            pid, name = self._person_cache[tid]
                            label = name if name else f"P{pid}"
                            labels.append(f"{label} {conf:.2f}")
                        else:
                            labels.append(f"#{tid} {conf:.2f}")

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
