"""IdentityState / IdentityTransition / TemporalVoter — identidad temporal (Fase 24).

SPEC_v2.md §5.5 fija el contrato de TemporalVoter (window/min_votes/min_ratio) y
los 4 estados de identidad. Este modulo es dominio puro: no importa `time`, no
arranca hilos, no hace I/O y no construye eventos. Todos los metodos que dependen
del reloj lo reciben como parametro `now: float` (monotonico), igual que
AdaptiveRate.should_process(now) en backend/pipeline/rate.py.

Fuera de alcance aqui: publicar eventos (lo hace EventEngine traduciendo
IdentityTransition) y persistir el estado. La re-identificacion por apariencia
(Fase 25) entra por on_reid_result(), que reutiliza _claim_lost() y NO vota en
el TemporalVoter: la votacion sigue siendo exclusivamente facial.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum


class IdentityState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    TEMPORARILY_LOST = "TEMPORARILY_LOST"


@dataclass
class IdentityTransition:
    """Cambio de estado de identidad de un track.

    La FSM devuelve esto, NO un Event: perception/ no conoce camera_id ni el reloj
    de pared. EventEngine lo traduce a Event (o lo descarta si `emits` es False o si
    la transicion no tiene tipo de evento en el catalogo de SPEC_v2.md §6.1).
    """

    track_id: int
    from_state: IdentityState
    to_state: IdentityState
    person_id: int | None = None
    confidence: float = 0.0
    votes: int = 0
    window: int = 0
    emits: bool = True   # False = cambio de estado silencioso (misma visita)


class TemporalVoter:
    """Ventana deslizante de votos por track (SPEC_v2.md §5.5, FACE-07)."""

    def __init__(self, window: int = 8, min_votes: int = 3, min_ratio: float = 0.6) -> None:
        self._window = window
        self._min_votes = min_votes
        self._min_ratio = min_ratio
        # track_id -> ultimos `window` resultados (person_id, score). `None` es un
        # voto valido: significa "frame sin match" y penaliza el ratio, que es
        # justo lo que exige "evidencia coherente".
        self._votes: dict[int, deque[tuple[int | None, float]]] = {}

    @property
    def window(self) -> int:
        return self._window

    @property
    def min_votes(self) -> int:
        return self._min_votes

    def vote(self, track_id: int, person_id: int | None, score: float) -> None:
        votes = self._votes.setdefault(track_id, deque(maxlen=self._window))
        votes.append((person_id, score))

    def verdict(self, track_id: int) -> tuple[int | None, float]:
        """(person_id ganador, confianza agregada) o (None, 0.0)."""
        votes = self._votes.get(track_id)
        if not votes:
            return None, 0.0
        matched = [pid for pid, _ in votes if pid is not None]
        if len(matched) < self._min_votes:
            return None, 0.0
        winner, count = Counter(matched).most_common(1)[0]
        if count < self._min_votes:
            return None, 0.0
        if count / len(votes) < self._min_ratio:
            return None, 0.0
        scores = [s for pid, s in votes if pid == winner]
        return winner, sum(scores) / len(scores)

    def votes_for(self, track_id: int) -> int:
        """Numero de votos acumulados en la ventana (con o sin match)."""
        votes = self._votes.get(track_id)
        return len(votes) if votes else 0

    def matched_votes(self, track_id: int) -> int:
        """Numero de votos CON match en la ventana. Distingue 'identidades en
        conflicto' (sigue habiendo caras) de 'se acabaron los matches'."""
        votes = self._votes.get(track_id)
        if not votes:
            return 0
        return sum(1 for pid, _ in votes if pid is not None)

    def reset(self, track_id: int) -> None:
        self._votes.pop(track_id, None)

    def prune(self, active_track_ids: set[int]) -> None:
        """ByteTrack nunca reutiliza track_ids: sin prune, _votes crece sin cota en
        un proceso 24/7 (invariante de la Fase 22). Sin lock: un solo hilo."""
        for tid in list(self._votes):
            if tid not in active_track_ids:
                del self._votes[tid]


@dataclass
class _TrackIdentity:
    """Estado de identidad de un track (patron `TrackState` de tracking.py)."""

    state: IdentityState = IdentityState.UNKNOWN
    person_id: int | None = None
    confidence: float = 0.0
    last_face_at: float = 0.0            # ultima inferencia facial de este track
    last_revalidation_at: float = 0.0    # ultima revalidacion CON EXITO (D-06)
    lost_at: float | None = None         # instante de entrada en TEMPORARILY_LOST
    failed_revalidations: int = 0
    recognized_emitted: bool = False     # PERSON_RECOGNIZED ya emitido (una vez)
    unknown_emitted: bool = False        # UNKNOWN_PERSON ya emitido (una vez, D-02)


class IdentityStateMachine:
    """4 estados de identidad por track y sus transiciones (SPEC_v2.md §5.5, FACE-08).

    Reloj inyectado: ningun metodo llama a time.monotonic(). Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock.

    No construye Event: devuelve IdentityTransition y EventEngine traduce.
    """

    MAX_FAILED_REVALIDATIONS = 3   # criterio 5: tres ciclos de revalidacion (D-04)

    def __init__(
        self,
        voter: TemporalVoter | None = None,
        lost_ttl: float = 30.0,
        revalidate_after: float = 120.0,
        low_confidence: float = 0.55,
    ) -> None:
        self._voter = voter if voter is not None else TemporalVoter()
        self._lost_ttl = lost_ttl
        self._revalidate_after = revalidate_after
        self._low_confidence = low_confidence
        self._states: dict[int, _TrackIdentity] = {}

    def state_of(self, track_id: int) -> IdentityState:
        st = self._states.get(track_id)
        return st.state if st is not None else IdentityState.UNKNOWN

    def identity_of(self, track_id: int) -> tuple[int | None, float]:
        """(person_id, confianza) solo si el track esta CONFIRMED."""
        st = self._states.get(track_id)
        if st is None or st.state is not IdentityState.CONFIRMED:
            return None, 0.0
        return st.person_id, st.confidence

    def _claim_lost(self, person_id: int, now: float) -> bool:
        """Un track nuevo reclama la identidad de un track perdido hace poco.

        ByteTrack nunca reutiliza track_ids: al recuperar a una persona le asigna
        un id nuevo. Sin esta busqueda POR person_id, cada reaparicion arrancaria
        en UNKNOWN y emitiria un segundo PERSON_RECOGNIZED (rompe FACE-09 y
        FACE-10 a la vez) — Pitfall 3 del RESEARCH.
        """
        for tid, st in list(self._states.items()):
            if (
                st.state is IdentityState.TEMPORARILY_LOST
                and st.person_id == person_id
                and st.lost_at is not None
                and now - st.lost_at <= self._lost_ttl
            ):
                del self._states[tid]
                self._voter.reset(tid)
                return True
        return False

    def on_face_result(
        self, track_id: int, person_id: int | None, score: float, now: float
    ) -> IdentityTransition | None:
        st = self._states.setdefault(track_id, _TrackIdentity())
        st.last_face_at = now
        self._voter.vote(track_id, person_id, score)
        winner, conf = self._voter.verdict(track_id)
        prev = st.state

        if prev is IdentityState.UNKNOWN:
            if person_id is None:
                return None
            # Pitfall 3: un solo match coherente basta para heredar una
            # identidad perdida hace poco, sin re-votar (FACE-09/FACE-10).
            if self._claim_lost(person_id, now):
                st.state = IdentityState.CONFIRMED
                st.person_id = person_id
                st.confidence = score
                st.failed_revalidations = 0
                st.last_revalidation_at = now
                st.recognized_emitted = True
                return IdentityTransition(
                    track_id,
                    IdentityState.UNKNOWN,
                    IdentityState.CONFIRMED,
                    person_id=person_id,
                    confidence=score,
                    votes=self._voter.votes_for(track_id),
                    window=self._voter.window,
                    emits=False,
                )
            st.state = IdentityState.CANDIDATE
            return IdentityTransition(
                track_id,
                IdentityState.UNKNOWN,
                IdentityState.CANDIDATE,
                votes=self._voter.votes_for(track_id),
                window=self._voter.window,
                emits=False,
            )

        if prev is IdentityState.CANDIDATE:
            if winner is not None:
                inherited = self._claim_lost(winner, now)
                emits = False if inherited else not st.recognized_emitted
                st.state = IdentityState.CONFIRMED
                st.person_id = winner
                st.confidence = conf
                st.failed_revalidations = 0
                st.last_revalidation_at = now
                st.recognized_emitted = True
                return IdentityTransition(
                    track_id,
                    IdentityState.CANDIDATE,
                    IdentityState.CONFIRMED,
                    person_id=winner,
                    confidence=conf,
                    votes=self._voter.votes_for(track_id),
                    window=self._voter.window,
                    emits=emits,
                )
            if (
                self._voter.votes_for(track_id) >= self._voter.window
                and self._voter.matched_votes(track_id) < self._voter.min_votes
            ):
                votes_n = self._voter.votes_for(track_id)
                window_n = self._voter.window
                emits = not st.unknown_emitted
                st.state = IdentityState.UNKNOWN
                st.unknown_emitted = True
                st.person_id = None
                self._voter.reset(track_id)
                return IdentityTransition(
                    track_id,
                    IdentityState.CANDIDATE,
                    IdentityState.UNKNOWN,
                    votes=votes_n,
                    window=window_n,
                    emits=emits,
                )
            return None

        if prev is IdentityState.CONFIRMED:
            # OJO: el reset de exito mira el match de ESTE frame
            # (person_id == st.person_id), no el veredicto agregado del
            # voter. needs_recognition() solo dispara inferencias
            # espaciadas por revalidate_after (una cada ~120s), asi que la
            # ventana del voter conserva votos historicos durante varios
            # ciclos: si el reset tambien aceptase "winner == st.person_id",
            # una sola ventana con mayoria antigua enmascararia varios
            # ciclos reales sin match y el criterio 5 (tres fallos) nunca
            # se cumpliria con revalidaciones tan espaciadas.
            if person_id == st.person_id:
                st.failed_revalidations = 0
                st.last_revalidation_at = now
                st.confidence = conf or st.confidence
                return None
            if winner is not None and winner != st.person_id:
                # El voter tiene mayoria para otra persona: corregir la
                # identidad (preserva la re-verificacion que hoy da
                # PersonRecognizer._votes, que 24-03 retira).
                st.person_id = winner
                st.confidence = conf
                st.failed_revalidations = 0
                st.last_revalidation_at = now
                return IdentityTransition(
                    track_id,
                    IdentityState.CONFIRMED,
                    IdentityState.CONFIRMED,
                    person_id=winner,
                    confidence=conf,
                    votes=self._voter.votes_for(track_id),
                    window=self._voter.window,
                    emits=True,
                )
            if person_id is not None:
                # Frame de otra persona aislado, sin mayoria en el voter:
                # no secuestra el track ni cuenta como fallo de revalidacion.
                return None
            revalidation_due = (now - st.last_revalidation_at) >= self._revalidate_after
            if not revalidation_due:
                return None
            st.failed_revalidations += 1
            st.last_revalidation_at = now
            if st.failed_revalidations >= self.MAX_FAILED_REVALIDATIONS:
                st.state = IdentityState.UNKNOWN
                st.person_id = None
                st.recognized_emitted = False
                self._voter.reset(track_id)
                return IdentityTransition(
                    track_id,
                    IdentityState.CONFIRMED,
                    IdentityState.UNKNOWN,
                    emits=True,
                    votes=self._voter.votes_for(track_id),
                    window=self._voter.window,
                )
            return None

        # TEMPORARILY_LOST: el MISMO track_id reaparece (ByteTrack no
        # siempre pierde el id en una oclusion breve). Un solo match
        # coherente basta: la identidad ya se establecio con N votos.
        if person_id == st.person_id:
            st.state = IdentityState.CONFIRMED
            st.lost_at = None
            st.failed_revalidations = 0
            st.last_revalidation_at = now
            return IdentityTransition(
                track_id,
                IdentityState.TEMPORARILY_LOST,
                IdentityState.CONFIRMED,
                person_id=st.person_id,
                confidence=st.confidence,
                votes=self._voter.votes_for(track_id),
                window=self._voter.window,
                emits=False,
            )
        return None

    def on_reid_result(
        self, track_id: int, person_id: int | None, similarity: float, now: float
    ) -> IdentityTransition | None:
        """Segunda via de recuperacion de identidad: apariencia, sin cara visible (Fase 25).

        NO vota en el TemporalVoter: la votacion es facial y la Fase 25 no la toca.
        Solo actua sobre tracks sin evidencia facial propia; un track CANDIDATE con
        votacion en curso o CONFIRMED nunca es secuestrado por apariencia.
        """
        if person_id is None:
            return None
        st = self._states.get(track_id)
        if st is not None and st.state is not IdentityState.UNKNOWN:
            return None                       # la cara manda; ReID no interfiere
        if st is not None and self._voter.matched_votes(track_id) > 0:
            return None                       # ya hay evidencia facial de este track
        if not self._claim_lost(person_id, now):
            return None                       # nadie perdido con esa identidad
        st = self._states.setdefault(track_id, _TrackIdentity())
        st.state = IdentityState.CONFIRMED
        st.person_id = person_id
        st.confidence = similarity
        st.failed_revalidations = 0
        st.last_revalidation_at = now
        # Pitfall 5: sin refrescar last_face_at, on_tick borraria este estado por
        # rancio (now - last_face_at > stale_ttl). Consecuencia deliberada: el track
        # heredado por apariencia no revalida con cara hasta revalidate_after (120 s).
        st.last_face_at = now
        st.recognized_emitted = True
        return IdentityTransition(
            track_id,
            IdentityState.UNKNOWN,
            IdentityState.CONFIRMED,
            person_id=person_id,
            confidence=similarity,
            votes=0,
            window=self._voter.window,
            emits=False,                      # misma visita: no hay 2o PERSON_RECOGNIZED
        )

    def on_track_lost(self, track_id: int, now: float) -> IdentityTransition | None:
        st = self._states.get(track_id)
        if st is None:
            return None

        if st.state is IdentityState.CONFIRMED:
            st.state = IdentityState.TEMPORARILY_LOST
            st.lost_at = now
            self._voter.reset(track_id)
            return IdentityTransition(
                track_id,
                IdentityState.CONFIRMED,
                IdentityState.TEMPORARILY_LOST,
                person_id=st.person_id,
                confidence=st.confidence,
                votes=0,
                window=self._voter.window,
                emits=False,
            )

        if st.state is IdentityState.CANDIDATE:
            votes_n = self._voter.votes_for(track_id)
            window_n = self._voter.window
            emits = not st.unknown_emitted
            del self._states[track_id]
            self._voter.reset(track_id)
            return IdentityTransition(
                track_id,
                IdentityState.CANDIDATE,
                IdentityState.UNKNOWN,
                votes=votes_n,
                window=window_n,
                emits=emits,
            )

        if st.state is IdentityState.UNKNOWN:
            del self._states[track_id]
            return None

        return None  # ya estaba TEMPORARILY_LOST

    def needs_recognition(self, track_id: int, now: float) -> bool:
        """A quien merece la pena hacerle inferencia facial ahora mismo (FACE-11).

        Sustituye al filtro `person_id is None` de RecognitionWorker._next_candidate,
        que reintentaba indefinidamente sobre los tracks que nunca llegan a
        identificarse (~120 inferencias/min a 2 FPS, para siempre).
        """
        st = self._states.get(track_id)
        if st is None:
            return True                                    # track nuevo
        if st.state is IdentityState.CANDIDATE:
            return True                                    # votacion en curso
        if st.state is IdentityState.TEMPORARILY_LOST:
            return True                                    # intentar recuperar la identidad
        if st.state is IdentityState.UNKNOWN:
            # Ventana aun sin llenar: seguimos reuniendo evidencia.
            if self._voter.votes_for(track_id) < self._voter.window:
                return True
            # Ventana agotada sin ningun match: backoff (criterio 6).
            return (now - st.last_face_at) >= self._revalidate_after
        # CONFIRMED
        if st.confidence < self._low_confidence:            # D-03: confianza del voter
            return True
        return (now - st.last_face_at) >= self._revalidate_after

    def on_active_tracks(self, active_ids: set[int], now: float) -> list[IdentityTransition]:
        """Detecta tracks caidos comparando con los ids activos del TrackRegistry.

        Los TEMPORARILY_LOST se saltan: existen precisamente para sobrevivir a
        que el track desaparezca (Pitfall 2 del RESEARCH). El voter SI se poda
        por active_ids; los estados de la FSM no.
        """
        out: list[IdentityTransition] = []
        for tid in list(self._states):
            if tid in active_ids:
                continue
            if self._states[tid].state is IdentityState.TEMPORARILY_LOST:
                continue
            t = self.on_track_lost(tid, now)
            if t is not None:
                out.append(t)
        self._voter.prune(active_ids)
        return out

    def on_tick(self, now: float) -> list[IdentityTransition]:
        stale_ttl = self._lost_ttl + self._revalidate_after * self.MAX_FAILED_REVALIDATIONS
        out: list[IdentityTransition] = []
        for tid in list(self._states):
            st = self._states.get(tid)
            if st is None:
                continue
            if (
                st.state is IdentityState.TEMPORARILY_LOST
                and st.lost_at is not None
                and now - st.lost_at > self._lost_ttl
            ):
                person_id = st.person_id
                del self._states[tid]
                self._voter.reset(tid)
                out.append(
                    IdentityTransition(
                        tid,
                        IdentityState.TEMPORARILY_LOST,
                        IdentityState.UNKNOWN,
                        person_id=person_id,
                        emits=True,
                    )
                )
                continue
            # Seguro de vida (invariante de la Fase 22): una entrada rancia
            # desaparece aunque nadie llame on_active_tracks a tiempo. Un
            # CONFIRMED que revalida cada revalidate_after refresca
            # last_face_at y sobrevive.
            if now - st.last_face_at > stale_ttl:
                del self._states[tid]
                self._voter.reset(tid)
        return out
