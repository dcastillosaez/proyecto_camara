"""StreamingWorker — overlay y encode JPEG para el feed MJPEG.

No ejecuta deteccion: dibuja leyendo el TrackRegistry que alimenta el
DetectionWorker. Asi el video se sirve al ritmo de la camara aunque la
deteccion corra mucho mas lenta (18-CONTEXT.md).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import cv2
import numpy as np
import supervision as sv

from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.pipeline.broker import Subscription
    from backend.tracker import PersonTracker

logger = logging.getLogger(__name__)


class StreamingWorker:
    """
    Consume frames del broker, les dibuja el overlay del ultimo estado
    conocido de tracks y los deja encodeados en JPEG listos para el
    generador MJPEG.

    Con cero clientes conectados no encodea nada: en una camara que nadie
    esta mirando, el encode es puro gasto de CPU.
    """

    JPEG_QUALITY = 80

    def __init__(
        self,
        sub: Subscription,
        registry: TrackRegistry,
        tracker: PersonTracker,
    ) -> None:
        self._sub = sub
        self._registry = registry
        self._tracker = tracker

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._clients = 0
        self._encoded = 0
        # Zonas a dibujar: lista de (poligono_px, texto). La actualiza el
        # DetectionWorker via set_zone_overlay — el streaming no las calcula.
        self._zone_overlay: list[tuple[np.ndarray, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="streaming-worker"
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("StreamingWorker: thread did not stop within %.1fs", timeout)
        self._sub.close()

    def get_jpeg(self) -> bytes | None:
        """Ultimo frame anotado y encodeado, o None si aun no hay ninguno."""
        with self._lock:
            return self._jpeg

    def client_connected(self) -> None:
        with self._lock:
            self._clients += 1

    def client_disconnected(self) -> None:
        with self._lock:
            self._clients = max(0, self._clients - 1)

    def set_zone_overlay(self, overlay: list[tuple[np.ndarray, str]]) -> None:
        """Zonas a dibujar, calculadas por el DetectionWorker."""
        with self._lock:
            self._zone_overlay = list(overlay)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {"clients": self._clients, "encoded": self._encoded}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            with self._lock:
                if self._clients <= 0:
                    continue  # nadie mirando: no gastamos CPU en encodear
            try:
                annotated = self._annotate(frame.image)
                ok, jpeg = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY]
                )
                if not ok:
                    continue
                data = jpeg.tobytes()
            except Exception:
                logger.exception("StreamingWorker: fallo al anotar/encodear, se salta el frame")
                continue
            with self._lock:
                self._jpeg = data
                self._encoded += 1

    def _annotate(self, image: np.ndarray) -> np.ndarray:
        """Dibuja cajas, etiquetas y zonas desde el estado compartido."""
        snapshot = self._registry.snapshot()
        out = image
        if snapshot:
            states = list(snapshot.values())
            detections = sv.Detections(
                xyxy=np.array([s.bbox for s in states], dtype=float),
                confidence=np.array([s.confidence for s in states], dtype=float),
                class_id=np.zeros(len(states), dtype=int),
            )
            detections.tracker_id = np.array([s.track_id for s in states])
            labels = [
                f"{s.person_name or f'P{s.person_id}'} {s.confidence:.2f}"
                if s.person_id is not None
                else f"#{s.track_id} {s.confidence:.2f}"
                for s in states
            ]
            out = self._tracker.annotate(out, detections, labels=labels)
        else:
            out = out.copy()

        with self._lock:
            zones = list(self._zone_overlay)
        for pts, text in zones:
            pts32 = np.asarray(pts, dtype=np.int32)
            cv2.polylines(out, [pts32], isClosed=True, color=(0, 200, 255), thickness=2)
            cv2.putText(
                out, text, tuple(pts32[0]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1,
            )
        return out
