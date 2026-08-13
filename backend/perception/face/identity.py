"""IdentityState / IdentityTransition / TemporalVoter — identidad temporal (Fase 24).

SPEC_v2.md §5.5 fija el contrato de TemporalVoter (window/min_votes/min_ratio) y
los 4 estados de identidad. Este modulo es dominio puro: no importa `time`, no
arranca hilos, no hace I/O y no construye eventos. Todos los metodos que dependen
del reloj lo reciben como parametro `now: float` (monotonico), igual que
AdaptiveRate.should_process(now) en backend/pipeline/rate.py.

Fuera de alcance aqui: publicar eventos (lo hace EventEngine traduciendo
IdentityTransition), persistir el estado y la re-identificacion por apariencia
sin cara visible (Fase 25).
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
