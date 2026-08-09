"""RecognitionWorker — reconocimiento facial con ritmo propio.

Porta RTSPStream._recognition_worker (Fase 17) con dos cambios: consume
del broker en vez de una cola de crops alimentada por el hilo de captura,
y su ritmo lo gobierna un AdaptiveRate con recognition_target_fps
(default 2 FPS) en vez del gating interno del recognizer.

Elige a que tracks atender consultando el TrackRegistry: prioriza los mas
antiguos sin identidad. Los tracks ya identificados se saltan — la
revalidacion temporal llega en la Fase 24.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

import numpy as np

from backend.observability.metrics import metrics as _metrics
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.pipeline.broker import Subscription
    from backend.recognizer import PersonRecognizer

logger = logging.getLogger(__name__)


class RecognitionWorker:
    """Identifica personas en los tracks sin identidad, a su propio ritmo."""

    CROP_PAD = 20

    def __init__(
        self,
        sub: Subscription,
        registry: TrackRegistry,
        recognizer: PersonRecognizer,
        rate: AdaptiveRate,
        min_track_age: float = 0.5,
        prune_interval: float = 10.0,
        on_identified: Callable[[np.ndarray, int], None] | None = None,
    ) -> None:
        self._sub = sub
        self._registry = registry
        self._recognizer = recognizer
        self._rate = rate
        # Evita gastar inferencia en tracks que van a desaparecer enseguida
        self._min_track_age = min_track_age
        self._prune_interval = prune_interval
        # Callback opcional para la galeria de capturas (main.py lo cablea)
        self._on_identified = on_identified

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_prune = 0.0
        self._identified = 0
        self._exceptions = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="recognition-worker"
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
                logger.warning("RecognitionWorker: thread did not stop within %.1fs", timeout)
        self._sub.close()

    @property
    def stats(self) -> dict:
        return {
            "identified": self._identified,
            "exceptions": self._exceptions,
            **self._rate.stats,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        available = getattr(self._recognizer, "available", False)
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            if not available:
                continue

            now = time.monotonic()
            self._maybe_prune(now)
            if not self._rate.should_process(now):
                continue

            target = self._next_candidate(now)
            if target is None:
                continue

            crop = self._crop_for(frame.image, target.bbox)
            if crop is None:
                continue

            t0 = time.monotonic()
            try:
                pid, name, _ = self._recognizer.process_crop(crop, target.track_id)
            except Exception:
                self._exceptions += 1
                logger.exception(
                    "RecognitionWorker: fallo de reconocimiento (track %d)", target.track_id
                )
                continue
            face_latency = time.monotonic() - t0
            self._rate.observe(face_latency)
            _metrics.inference_latency_seconds.labels(stage="face").observe(face_latency)

            if pid is None:
                continue
            self._registry.set_identity(target.track_id, pid, name)
            self._identified += 1
            if self._on_identified is not None:
                try:
                    self._on_identified(crop, pid)
                except Exception:
                    logger.exception("RecognitionWorker: on_identified fallo")

    def _next_candidate(self, now: float):
        """Track mas antiguo sin identidad y con edad suficiente, o None."""
        candidates = [
            ts for ts in self._registry.snapshot().values()
            if ts.person_id is None and (now - ts.first_seen) >= self._min_track_age
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda ts: ts.first_seen)

    def _crop_for(self, image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
        x1, y1, x2, y2 = bbox
        p = self.CROP_PAD
        fh, fw = image.shape[:2]
        crop = image[max(0, y1 - p):min(fh, y2 + p), max(0, x1 - p):min(fw, x2 + p)]
        return crop.copy() if crop.size else None

    def _maybe_prune(self, now: float) -> None:
        """
        Limpia las caches por track del recognizer.

        Se hace contra ``registry.active_ids()`` en vez de contra los ids
        que devuelve ``registry.prune()``: el DetectionWorker tambien poda
        el registry, asi que depender de quien llama primero a prune()
        seria una carrera. Con el set de activos, el resultado es el mismo
        sin importar el orden.
        """
        if now - self._last_prune < self._prune_interval:
            return
        self._last_prune = now
        try:
            self._recognizer.prune(self._registry.active_ids())
        except Exception:
            logger.exception("RecognitionWorker: prune de caches fallo")
