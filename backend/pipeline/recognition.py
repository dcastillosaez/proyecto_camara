"""RecognitionWorker — reconocimiento facial con ritmo propio.

Porta RTSPStream._recognition_worker (Fase 17) con dos cambios: consume
del broker en vez de una cola de crops alimentada por el hilo de captura,
y su ritmo lo gobierna un AdaptiveRate con recognition_target_fps
(default 2 FPS) en vez del gating interno del recognizer.

Fase 24: es el dueno del ciclo de vida de la identidad temporal. Elige a
que tracks atender preguntando a IdentityStateMachine.needs_recognition()
(FACE-11) en vez de reintentar indefinidamente sobre `person_id is None`;
es el unico escritor de person_id/person_name/identity_state en el
TrackRegistry; y publica los eventos de identidad (PERSON_RECOGNIZED/
UNKNOWN_PERSON/IDENTITY_LOST) via EventEngine.emit_identity, desde este
mismo hilo, sin await. Sin identity_fsm (parametro None, default) conserva
el comportamiento ciego de la Fase 23 — util como baseline para medir el
criterio 6 (ver TEST_inference_budget_drops_on_unconfirmed_track).
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

import numpy as np

from backend.observability.metrics import metrics as _metrics
from backend.perception.face.identity import IdentityState, IdentityStateMachine
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.events.engine import EventEngine
    from backend.pipeline.broker import Subscription
    from backend.recognizer import PersonRecognizer

logger = logging.getLogger(__name__)


class RecognitionWorker:
    """Identifica personas en los tracks que lo necesitan, a su propio ritmo."""

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
        identity_fsm: IdentityStateMachine | None = None,
        event_engine: EventEngine | None = None,
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
        self._fsm = identity_fsm
        self._event_engine = event_engine

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_prune = 0.0
        self._identified = 0
        self._exceptions = 0
        self._face_inferences = 0

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
            "face_inferences": self._face_inferences,
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
            self._sync_identity(now)
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
                result = self._recognizer.process_crop_scored(crop, target.track_id)
            except Exception:
                self._exceptions += 1
                logger.exception(
                    "RecognitionWorker: fallo de reconocimiento (track %d)", target.track_id
                )
                continue
            self._face_inferences += 1
            face_latency = time.monotonic() - t0
            self._rate.observe(face_latency)
            _metrics.inference_latency_seconds.labels(stage="face").observe(face_latency)

            if self._fsm is None:
                # Comportamiento Fase 23 — baseline del criterio 6.
                if result.person_id is None:
                    continue
                self._registry.set_identity(target.track_id, result.person_id, result.name)
                self._identified += 1
                self._notify_identified(crop, result.person_id)
                continue

            now2 = time.monotonic()
            transition = self._fsm.on_face_result(
                target.track_id, result.person_id, result.score, now2
            )
            self._registry.set_identity_state(target.track_id, self._fsm.state_of(target.track_id))
            pid, _conf = self._fsm.identity_of(target.track_id)
            if pid is not None:
                # El nombre solo es fiable si corresponde al pid que la FSM ha
                # fijado: el ganador de la votacion puede no ser el match de
                # ESTE frame.
                name = result.name if result.person_id == pid else None
                self._registry.set_identity(target.track_id, pid, name)
            if transition is not None:
                self._emit_identity(
                    transition,
                    person_name=result.name if result.person_id == transition.person_id else None,
                    bbox=target.bbox,
                    captured_at=frame.captured_at,
                    processed_at=now2,
                )
            if transition is not None and transition.to_state is IdentityState.CONFIRMED:
                self._identified += 1
                self._notify_identified(crop, pid)

    def _next_candidate(self, now: float):
        """Track mas antiguo que merece una inferencia facial ahora, o None.

        Con FSM (Fase 24, FACE-11) el criterio es needs_recognition(): track nuevo,
        votacion en curso, identidad temporalmente perdida, confianza de identidad
        baja o revalidacion vencida. Sin FSM se conserva el criterio de la Fase 23
        (`person_id is None`), que reintentaba indefinidamente sobre los tracks que
        nunca llegan a identificarse.
        """
        tracks = [
            ts for ts in self._registry.snapshot().values()
            if (now - ts.first_seen) >= self._min_track_age
        ]
        if self._fsm is None:
            tracks = [ts for ts in tracks if ts.person_id is None]
        else:
            tracks = [ts for ts in tracks if self._fsm.needs_recognition(ts.track_id, now)]
        if not tracks:
            return None
        return min(tracks, key=lambda ts: ts.first_seen)

    def _crop_for(self, image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
        x1, y1, x2, y2 = bbox
        p = self.CROP_PAD
        fh, fw = image.shape[:2]
        crop = image[max(0, y1 - p):min(fh, y2 + p), max(0, x1 - p):min(fw, x2 + p)]
        return crop.copy() if crop.size else None

    def _notify_identified(self, crop: np.ndarray, person_id: int) -> None:
        if self._on_identified is None:
            return
        try:
            self._on_identified(crop, person_id)
        except Exception:
            logger.exception("RecognitionWorker: on_identified fallo")

    def _sync_identity(self, now: float) -> None:
        """Tracks caidos + expiraciones de lost_ttl. Un solo hilo, sin lock.

        frame_ids(), no active_ids(): active_ids() tarda hasta 30s (ttl de prune)
        en dejar de ver un track desaparecido, y para entonces ByteTrack ya le
        habria asignado un track_id nuevo al reaparecer -- la FSM emitiria un
        segundo PERSON_RECOGNIZED para la misma visita (D-05).
        """
        if self._fsm is None:
            return
        try:
            transitions = self._fsm.on_active_tracks(self._registry.frame_ids(), now)
            transitions += self._fsm.on_tick(now)
        except Exception:
            self._exceptions += 1
            logger.exception("RecognitionWorker: mantenimiento de la FSM de identidad fallo")
            return
        for t in transitions:
            self._emit_identity(t)

    def _emit_identity(
        self, transition, person_name=None, bbox=None, captured_at=None, processed_at=None
    ) -> None:
        if self._event_engine is None or transition is None:
            return
        try:
            self._event_engine.emit_identity(
                transition, datetime.datetime.now(), person_name=person_name,
                bbox=bbox, captured_at=captured_at, processed_at=processed_at,
            )
        except Exception:
            logger.exception("RecognitionWorker: emision de evento de identidad fallo")

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
