"""Worker de captura RTSP puro: lee, reescala y publica. Nada mas.

Portado de backend.stream.RTSPStream (la parte previa al procesamiento de
IA) para que la captura no dependa de ningun paso de vision por computador
posterior (SPEC_v2.md ADR-01).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from backend.pipeline.broker import Frame, FrameBroker

logger = logging.getLogger(__name__)


@dataclass
class CaptureHealth:
    """Snapshot del estado de salud de un CaptureWorker."""

    camera_id: str
    connected: bool
    fps: float
    reconnects: int
    last_frame_age_s: float
    native_resolution: tuple[int, int] | None
    frames_captured: int


class CaptureWorker:
    """Captura frames RTSP en un hilo daemon, reescala y publica en el broker.

    Usa el mismo patron drain que RTSPStream: un hilo en bucle cerrado lee
    tan rapido como puede, sin acumular buffer. La reconexion usa backoff
    exponencial (1 s a 30 s) identico al de v1.2.
    """

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        broker: FrameBroker,
        process_size: tuple[int, int] | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._url = rtsp_url
        self._broker = broker
        self._process_size = process_size

        self._running = False
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._seq = 0

        self._lock = threading.Lock()
        self._connected = False
        self._reconnects = 0
        self._frames_captured = 0
        self._native_resolution: tuple[int, int] | None = None
        self._last_frame_at: float = 0.0
        self._frame_times: deque[float] = deque(maxlen=30)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background capture thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name=f"capture-{self._camera_id}"
        )
        self._thread.start()

    def is_alive(self) -> bool:
        """True si el hilo del worker sigue vivo (lo consulta WorkerSupervisor)."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the capture thread and release the VideoCapture."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning(
                    "CaptureWorker %s: thread did not stop within %.1fs",
                    self._camera_id, timeout,
                )
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._lock:
            self._connected = False

    @property
    def health(self) -> CaptureHealth:
        with self._lock:
            fps = 0.0
            if len(self._frame_times) >= 2:
                span = self._frame_times[-1] - self._frame_times[0]
                if span > 0:
                    fps = (len(self._frame_times) - 1) / span
            age = time.perf_counter() - self._last_frame_at if self._last_frame_at else float("inf")
            return CaptureHealth(
                camera_id=self._camera_id,
                connected=self._connected,
                fps=fps,
                reconnects=self._reconnects,
                last_frame_age_s=age,
                native_resolution=self._native_resolution,
                frames_captured=self._frames_captured,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        self._cap = self._create_capture()
        while self._running:
            cap = self._cap
            if cap is None or not cap.isOpened():
                self._reconnect()
                continue
            ret, raw = cap.read()
            captured_at = time.monotonic()
            perf_at = time.perf_counter()
            wall_clock = datetime.now()
            if not ret:
                with self._lock:
                    self._connected = False
                self._reconnect()
                continue

            with self._lock:
                self._connected = True
                if self._native_resolution is None:
                    self._native_resolution = (raw.shape[1], raw.shape[0])

            image = raw
            if self._process_size is not None:
                image = cv2.resize(image, self._process_size)

            frame = Frame(
                camera_id=self._camera_id,
                seq=self._seq,
                captured_at=captured_at,
                wall_clock=wall_clock,
                image=image,
            )
            self._seq += 1

            with self._lock:
                self._frames_captured += 1
                self._last_frame_at = perf_at
                self._frame_times.append(perf_at)

            self._broker.publish(frame)

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
            logger.warning(
                "CaptureWorker %s: reconnecting in %.1fs...", self._camera_id, delay
            )
            time.sleep(delay)
            cap = self._create_capture()
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    self._cap = cap
                    with self._lock:
                        self._reconnects += 1
                        self._connected = True
                    logger.info("CaptureWorker %s: reconnection successful", self._camera_id)
                    return
            cap.release()
            delay = min(delay * 2, max_delay)
