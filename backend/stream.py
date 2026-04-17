"""RTSP stream capture with drain thread and auto-reconnection."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from backend.detector import Detection, PersonDetector
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
    ) -> None:
        self._url = url
        self._detector = detector
        self._tracker = tracker
        self._frame: np.ndarray | None = None
        self._detections: list[Detection] = []
        self._lock = threading.Lock()
        self._running = False
        self._cap: cv2.VideoCapture | None = None

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

    def get_counts(self) -> dict[str, int]:
        """Return cumulative line-crossing counts from the tracker, or zeros."""
        if self._tracker is None:
            return {"in": 0, "out": 0, "total": 0}
        return self._tracker.get_counts()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Read frames in a tight loop, keeping only the newest."""
        self._cap = self._create_capture()
        while self._running:
            cap = self._cap
            if cap is None or not cap.isOpened():
                self._reconnect()
                continue
            ret, frame = cap.read()
            if not ret:
                self._reconnect()
                continue

            if self._detector is not None and self._tracker is not None:
                # Full pipeline: supervision detections → ByteTrack → LineZone
                sv_dets = self._detector.detect_sv(frame)
                tracked = self._tracker.update(sv_dets)
                frame = self._tracker.annotate(frame, tracked)
                detections = []  # raw Detection list not used in tracker mode
            elif self._detector is not None:
                # Phase-3 fallback: plain YOLO boxes, no tracking
                detections = self._detector.detect(frame)
                frame = self._detector.annotate(frame, detections)
            else:
                detections = []

            with self._lock:
                self._frame = frame
                self._detections = detections

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
