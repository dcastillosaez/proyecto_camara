"""TrackGallery — continuidad de identidad por apariencia (SPEC_v2.md §5.6, REID-02/03/04).

Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
eventos. Todos los metodos que dependen del reloj lo reciben como parametro
`now: float` (monotonico), igual que IdentityStateMachine y AdaptiveRate.
La firma de SPEC §5.6 omitia `now` y `active_identities`; sin el primero no se
puede aplicar la ventana de 15 s y sin el segundo no se puede detectar el
conflicto que exige REID-02 (misma correccion que la Fase 24 hizo con
on_face_result).

Fuera de alcance aqui: decidir si la herencia se aplica (esa politica de
producto vive en RecognitionWorker) y transicionar el estado de identidad
(eso es IdentityStateMachine.on_reid_result).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class _GalleryEntry:
    """Ultimo embedding conocido de un track (patron `_TrackIdentity` de identity.py)."""

    emb: np.ndarray                # float32 512D L2-normalizado (2 KB; float64 costaria 4 KB)
    person_id: int | None          # identidad CONFIRMED del track cuando se embebio
    last_seen: float                # ultima vez que el track se refresco: base del TTL
    last_embedded_at: float         # ultima inferencia ReID de este track: base del criterio 5


class TrackGallery:
    """Memoria de apariencia de los tracks recientes (SPEC_v2.md §5.6, REID-02/04).

    Reloj inyectado: ningun metodo llama a time.monotonic(). Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock — igual que IdentityStateMachine.

    No aplica politica de producto: resolve() calcula SIEMPRE el candidato real y
    devuelve (person_id, similitud). Que la herencia se aplique o solo se registre
    lo decide un flag de politica que vive en el worker; si resolve() devolviera
    None en modo observacion se perderia justo el dato que se quiere auditar.
    """

    def __init__(
        self,
        inherit_window: float = 15.0,
        similarity_threshold: float = 0.7,
        interval: float = 2.0,
        max_entries: int = 256,
    ) -> None:
        self._inherit_window = inherit_window
        self._threshold = similarity_threshold
        self._interval = interval
        self._max_entries = max_entries
        self._entries: dict[int, _GalleryEntry] = {}

    def needs_embedding(self, track_id: int, now: float) -> bool:
        """A que track toca re-embeber ahora mismo (criterio 5: max 1 cada reid_interval_secs).

        Espejo exacto de IdentityStateMachine.needs_recognition (FACE-11), pero con
        su propio reloj: reutilizar `last_face_at` mezclaria la cadencia facial
        (revalidate_after = 120 s) con la de apariencia (2 s) en el mismo campo.
        """
        e = self._entries.get(track_id)
        return e is None or (now - e.last_embedded_at) >= self._interval

    def update(self, track_id: int, emb: np.ndarray, identity: int | None, now: float) -> None:
        """Crea o refresca la entrada de apariencia de un track.

        Fuerza float32 (2 KB/entrada; numpy usaria float64 = 4 KB por defecto).
        """
        e = self._entries.get(track_id)
        stored = emb.astype(np.float32, copy=False)
        if e is None:
            self._entries[track_id] = _GalleryEntry(
                emb=stored, person_id=identity, last_seen=now, last_embedded_at=now,
            )
        else:
            e.emb = stored
            e.person_id = identity
            e.last_seen = now
            e.last_embedded_at = now
        # Cota dura tambien desde update(): no depende de que el mantenimiento
        # periodico (prune()) se ejecute a tiempo (Fase 22, "seguro de vida").
        self._enforce_cap()

    def resolve(
        self, track_id: int, emb: np.ndarray, now: float, active_identities: set[int],
    ) -> tuple[int | None, float]:
        """Candidato real a heredar identidad por apariencia, con su similitud (REID-02).

        4 reglas en este orden exacto:
        1. Candidatos = entradas con person_id conocido y de OTRO track.
        2. Frescura: dentro de la ventana de herencia.
        3. Similitud: coseno directo (ADR-03: np.dot, sin base vectorial), maximo.
        4. Umbral ESTRICTO (sim > threshold, coherente con "similitud > 0.7" del
           criterio 2) + comprobacion de conflicto contra active_identities.

        Devuelve SIEMPRE la similitud real del mejor candidato, incluso cuando no
        se hereda (umbral no superado o conflicto): es el dato de auditoria que
        exige el criterio 4. La decision de aplicar la herencia no vive aqui.
        """
        best_person_id: int | None = None
        best_sim = 0.0
        found = False
        for tid, e in self._entries.items():
            if tid == track_id or e.person_id is None:
                continue
            if now - e.last_seen > self._inherit_window:
                continue
            sim = float(emb @ e.emb)
            if not found or sim > best_sim:
                best_sim = sim
                best_person_id = e.person_id
                found = True

        if not found:
            return None, 0.0
        if best_sim <= self._threshold:
            return None, best_sim
        if best_person_id in active_identities:
            # Conflicto: la identidad candidata sigue visible en otro track del
            # frame actual — esto es lo que impide fusionar dos personas cuando
            # la "perdida" en realidad no se ha ido de la camara.
            return None, best_sim
        return best_person_id, best_sim

    def prune(self, now: float, frame_ids: set[int]) -> None:
        """Doble guarda de expiracion, calcada de IdentityStateMachine.on_tick.

        Guarda 1 (TTL): borra entradas mas viejas que la ventana de herencia. Un
        track visible refresca `last_seen` en cada update() (<= 2 s), asi que
        nunca caduca estando en pantalla.
        Guarda 2 (cota dura): ver _enforce_cap — "seguro de vida" de la Fase 22.
        """
        for tid in list(self._entries):
            if tid in frame_ids:
                self._entries[tid].last_seen = now
        for tid in list(self._entries):
            if now - self._entries[tid].last_seen > self._inherit_window:
                del self._entries[tid]
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        """Cota dura por max_entries, LRU por last_seen (Fase 22, "seguro de vida").

        Actua aunque nadie llame a prune() a tiempo — igual que la cota de
        _states en IdentityStateMachine.on_tick (identity.py:450-453). Se llama
        tanto desde update() como desde prune() para que la cota se cumpla sin
        depender del mantenimiento periodico.
        """
        if len(self._entries) <= self._max_entries:
            return
        overflow = len(self._entries) - self._max_entries
        oldest = sorted(self._entries.items(), key=lambda kv: kv[1].last_seen)[:overflow]
        for tid, _ in oldest:
            del self._entries[tid]
