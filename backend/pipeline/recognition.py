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
    from backend.perception.reid.engine import ReIDEngine
    from backend.perception.reid.gallery import TrackGallery
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
        reid_engine: "ReIDEngine | None" = None,
        reid_gallery: "TrackGallery | None" = None,
        reid_inherit: bool = False,
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
        self._reid_engine = reid_engine
        self._gallery = reid_gallery
        # El flag de politica vive AQUI, no en TrackGallery. resolve() calcula
        # siempre el candidato real; si lo hiciera la galeria devolviendo None
        # en modo observacion se perderia justo el dato que se quiere auditar
        # (que identidad se habria heredado) — RESEARCH §Q7, criterio 4.
        self._reid_inherit = reid_inherit

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_prune = 0.0
        self._identified = 0
        self._exceptions = 0
        self._face_inferences = 0
        self._reid_inferences = 0
        self._reid_matches = 0
        self._reid_inherited = 0
        self._reid_conflicts = 0

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
            "reid_inferences": self._reid_inferences,
            "reid_matches": self._reid_matches,
            "reid_inherited": self._reid_inherited,
            "reid_conflicts": self._reid_conflicts,
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

            self._face_pass(frame, now)
            self._reid_pass(frame, time.monotonic())

    def _face_pass(self, frame, now: float) -> None:
        """Via facial (Fase 23/24), extraida de `_loop` (Fase 25): la ausencia de
        candidato facial no debe impedir la pasada ReID (persona de espaldas, el
        caso que `_next_candidate`/`needs_recognition()` no cubre)."""
        target = self._next_candidate(now)
        if target is None:
            return

        crop = self._crop_for(frame.image, target.bbox)
        if crop is None:
            return

        t0 = time.monotonic()
        try:
            result = self._recognizer.process_crop_scored(crop, target.track_id)
        except Exception:
            self._exceptions += 1
            logger.exception(
                "RecognitionWorker: fallo de reconocimiento (track %d)", target.track_id
            )
            return
        self._face_inferences += 1
        face_latency = time.monotonic() - t0
        self._rate.observe(face_latency)
        _metrics.inference_latency_seconds.labels(stage="face").observe(face_latency)

        if self._fsm is None:
            # Comportamiento Fase 23 — baseline del criterio 6.
            if result.person_id is None:
                return
            self._registry.set_identity(target.track_id, result.person_id, result.name)
            self._identified += 1
            self._notify_identified(crop, result.person_id)
            return

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

    def _reid_pass(self, frame, now: float) -> None:
        """Via de apariencia (Fase 25). Corre en el mismo tick que la facial y en
        el mismo hilo: la FSM es single-thread sin lock (identity.py:130)."""
        if self._reid_engine is None or self._gallery is None or self._fsm is None:
            return
        if not getattr(self._reid_engine, "available", False):
            return
        try:
            target = self._next_reid_candidate(now)
            if target is None:
                return
            crop = self._crop_for(frame.image, target.bbox)
            if crop is None:
                return
            t0 = time.monotonic()
            emb = self._reid_engine.embed(crop)
            reid_latency = time.monotonic() - t0
            if emb is None:
                return
            self._reid_inferences += 1
            # Pitfall 6: NUNCA self._rate.observe(reid_latency). Ese AdaptiveRate
            # esta fijado a 2 FPS (min=max) y no cambiaria el ritmo, pero si
            # contaminaria avg_latency en /api/v2/cameras/{id}/health, que
            # significa "latencia facial".
            _metrics.inference_latency_seconds.labels(stage="reid").observe(reid_latency)

            pid_now, _conf = self._fsm.identity_of(target.track_id)
            self._gallery.update(target.track_id, emb, pid_now, now)

            pid, sim = self._gallery.resolve(
                target.track_id, emb, now, self._active_identities()
            )
            if pid is None:
                return
            self._reid_matches += 1
            logger.info(
                "ReID: track %d -> person %d (sim %.3f, inherit=%s)",
                target.track_id, pid, sim, self._reid_inherit,
            )
            if not self._reid_inherit:
                return                      # modo solo-observacion (criterio 4)
            now2 = time.monotonic()
            transition = self._fsm.on_reid_result(target.track_id, pid, sim, now2)
            if transition is None:
                self._reid_conflicts += 1   # la FSM rechazo la herencia
                return
            self._reid_inherited += 1
            self._registry.set_identity_state(
                target.track_id, self._fsm.state_of(target.track_id)
            )
            self._registry.set_identity(target.track_id, pid, None)
            self._emit_identity(
                transition,
                bbox=target.bbox,
                captured_at=frame.captured_at,
                processed_at=now2,
            )
        except Exception:
            self._exceptions += 1
            logger.exception("RecognitionWorker: via ReID fallo")

    def _next_reid_candidate(self, now: float):
        """Track mas antiguo que toca re-embeber ahora, o None.

        Deliberadamente NO usa fsm.needs_recognition(): el caso que ReID cubre
        (persona de espaldas, TEMPORARILY_LOST, UNKNOWN en backoff de 120 s) es
        justo donde ese gate dice que no. El unico limite es reid_interval_secs
        (criterio 5, dentro de TrackGallery.needs_embedding) y min_track_age.

        Cota agregada (RESEARCH §Q4): como mucho un track por tick; a 2 FPS y
        reid_interval_secs=2.0 eso sostiene hasta 4 tracks concurrentes a ritmo
        pleno, y con mas tracks el intervalo efectivo por track se degrada por
        encima de 2 s — degradacion segura (menos coste, nunca mas) que sigue
        cumpliendo el criterio 5.

        Solo candidatos en frame_ids() (bug encontrado en 25-04, Task 3): un
        track fuera del frame actual no tiene bbox fiable -- recortar sobre su
        posicion vieja en el frame ACTUAL captura fondo/oclusion, no a la
        persona. Ademas, si se re-embebiera de todos modos, gallery.update()
        escribiria identity_of(tid)==None (identity.py:155-159 solo devuelve
        person_id si el track esta CONFIRMED) y borraria la identidad que el
        propio ReID necesita conservar en ese track para que otro lo reclame
        despues -- justo lo contrario del criterio 3.
        """
        visible = self._registry.frame_ids()
        tracks = [
            ts for ts in self._registry.snapshot().values()
            if ts.track_id in visible
            and (now - ts.first_seen) >= self._min_track_age
            and self._gallery.needs_embedding(ts.track_id, now)
        ]
        if not tracks:
            return None
        return min(tracks, key=lambda ts: ts.first_seen)

    def _active_identities(self) -> set[int]:
        """Identidades CONFIRMED sobre tracks visibles en el frame actual (REID-02).

        frame_ids(), no active_ids(): active_ids() tarda hasta 30 s (ttl de prune)
        en dejar de ver un track desaparecido — el bug D-05 de la Fase 24.
        identity_of() ya devuelve identidad solo si el track esta CONFIRMED.
        """
        out: set[int] = set()
        for tid in self._registry.frame_ids():
            pid, _ = self._fsm.identity_of(tid)
            if pid is not None:
                out.add(pid)
        return out

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
            if self._gallery is not None:
                self._gallery.prune(now, self._registry.frame_ids())
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
