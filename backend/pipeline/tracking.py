"""TrackRegistry — estado compartido de tracks, punto de encuentro entre workers.

DetectionWorker escribe el estado de tracks; StreamingWorker lo lee para
dibujar el overlay; RecognitionWorker lo lee para saber que tracks
necesitan cara (SPEC_v2.md §5.3, 18-CONTEXT.md).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from backend.perception.face.identity import IdentityState


@dataclass
class TrackState:
    """Estado de un track. Los lectores no deben mutarlo (snapshot es copia superficial)."""

    track_id: int
    first_seen: float
    last_seen: float
    bbox: tuple[int, int, int, int]
    confidence: float
    centroid_history: deque = field(default_factory=lambda: deque(maxlen=150))
    zones: set[str] = field(default_factory=set)
    zone_entry_times: dict[str, float] = field(default_factory=dict)
    person_id: int | None = None
    person_name: str | None = None
    # Estado de identidad de la FSM (Fase 24, FACE-08). Escritor unico:
    # RecognitionWorker, igual que person_id/person_name.
    identity_state: IdentityState = IdentityState.UNKNOWN


class TrackRegistry:
    """
    Estado compartido de tracks, protegido por un unico RLock.

    Se prohibe que dos workers escriban el mismo campo: DetectionWorker es
    el unico escritor de bbox/confidence/centroid_history/_frame_ids (via
    set_frame_ids); RecognitionWorker es el unico escritor de
    person_id/person_name/identity_state via set_identity/set_identity_state.
    """

    def __init__(self, history_len: int = 150) -> None:
        self._history_len = history_len
        self._lock = threading.RLock()
        self._tracks: dict[int, TrackState] = {}
        # Ids vistos en el ultimo frame procesado por DetectionWorker (Fase 24,
        # D-05). Distinto de active_ids(): ese es el TTL de 30s de prune().
        self._frame_ids: frozenset[int] = frozenset()

    def update_from_detections(self, tracked: Any, now: float) -> list[int]:
        """Actualiza el estado desde una pasada de tracking. Devuelve los track_ids nuevos."""
        ids = tracked.tracker_id
        if ids is None:
            return []
        new_ids: list[int] = []
        with self._lock:
            for i, tid in enumerate(ids):
                tid = int(tid)
                x1, y1, x2, y2 = map(int, tracked.xyxy[i])
                conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                ts = self._tracks.get(tid)
                if ts is None:
                    ts = TrackState(
                        track_id=tid,
                        first_seen=now,
                        last_seen=now,
                        bbox=(x1, y1, x2, y2),
                        confidence=conf,
                        centroid_history=deque(maxlen=self._history_len),
                    )
                    self._tracks[tid] = ts
                    new_ids.append(tid)
                else:
                    ts.last_seen = now
                    ts.bbox = (x1, y1, x2, y2)
                    ts.confidence = conf
                ts.centroid_history.append((now, cx, cy))
        return new_ids

    def get(self, track_id: int) -> TrackState | None:
        with self._lock:
            return self._tracks.get(track_id)

    def snapshot(self) -> dict[int, TrackState]:
        """Copia superficial bajo lock. Los TrackState se comparten por referencia."""
        with self._lock:
            return dict(self._tracks)

    def active_ids(self) -> set[int]:
        with self._lock:
            return set(self._tracks.keys())

    def set_frame_ids(self, ids: set[int]) -> None:
        """Ids de tracks vistos en el frame actual (D-05, Fase 24, FACE-10).

        A diferencia de active_ids() (todas las claves vivas, incluidas las que
        llevan hasta `ttl` segundos sin verse), esto es exacto e inmediato. Lo
        escribe DetectionWorker en cada frame; IdentityStateMachine.on_active_tracks
        lo necesita para detectar la perdida de un track sin esperar al TTL de
        prune() -- de lo contrario un track_id nuevo (ByteTrack nunca reutiliza
        ids) confirmaria como visita nueva mientras el viejo sigue "activo".
        """
        with self._lock:
            self._frame_ids = frozenset(ids)

    def frame_ids(self) -> set[int]:
        with self._lock:
            return set(self._frame_ids)

    def set_identity(self, track_id: int, person_id: int, name: str | None) -> None:
        with self._lock:
            ts = self._tracks.get(track_id)
            if ts is not None:
                ts.person_id = person_id
                ts.person_name = name

    def set_identity_state(self, track_id: int, state: IdentityState) -> None:
        with self._lock:
            ts = self._tracks.get(track_id)
            if ts is not None:
                ts.identity_state = state

    def prune(self, now: float, ttl: float = 30.0) -> list[int]:
        """Elimina tracks sin actualizar desde hace mas de ttl. Devuelve los ids expirados."""
        with self._lock:
            expired = [
                tid for tid, ts in self._tracks.items() if now - ts.last_seen > ttl
            ]
            for tid in expired:
                del self._tracks[tid]
            return expired
