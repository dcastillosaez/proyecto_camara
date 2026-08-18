"""ObjectAnalyzer — OBJECT_LEFT / OBJECT_REMOVED (SPEC_v2.md; 27-RESEARCH.md Q1/Q2).

Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
eventos. Reloj inyectado: todos los metodos que dependen del reloj lo reciben
como parametro `now: float` (monotonico). Un solo hilo lo llama
(DetectionWorker._loop), por eso no hay lock.

Fuera de alcance aqui: construir Event, conocer camera_id, conocer el reloj de
pared, decidir que detecciones entran en el tracker (eso es DetectionWorker) y
calcular la pertenencia a zonas (eso ya lo hace sv.PolygonZone.trigger() en
_update_zones_and_heat).

Los umbrales (warmup, radios, gracia de desaparicion) vienen de
27-RESEARCH.md Q1/Q2.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class ObjectKind(str, Enum):
    LEFT = "left"          # -> EventType.OBJECT_LEFT   (Severity.WARNING por catalogo)
    REMOVED = "removed"    # -> EventType.OBJECT_REMOVED (Severity.INFO por catalogo)


@dataclass(frozen=True)
class ObjectObservation:
    """Un objeto trackeado visto en ESTE frame. La construye DetectionWorker."""

    track_id: int
    x: float                                  # ancla BOTTOM_CENTER, no centroide
    y: float
    class_id: int
    class_name: str
    bbox: tuple[float, float, float, float]
    zone_id: str | None = None                # zona en la que cae; None = escena
    excluded: bool = False                    # cae en una zona kind == "exclude_objects"


@dataclass(frozen=True)
class PersonObservation:
    """Una persona visible en ESTE frame. Solo lo que hace falta para el radio."""

    track_id: int
    x: float                                  # ancla BOTTOM_CENTER
    y: float
    height_px: float                          # alto de la bbox: corrige la escala


# Por que ObjectObservation/PersonObservation y no los dicts de behavior.py:
# BehaviorAnalyzer.analyze recibe dict[int, tuple[float, float]] porque solo
# necesita el centroide. Aqui cada objeto arrastra seis atributos (ancla,
# clase, nombre, bbox, zona, exclusion) y seis dicts paralelos serian un
# criadero de bugs de desincronizacion.


@dataclass
class ObjectFinding:
    kind: ObjectKind
    track_id: int
    class_id: int | None = None
    class_name: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    zone_id: str | None = None
    duration_s: float | None = None           # NOMBRE OBLIGATORIO (rules.py:88-91)
    net_displacement_px: float | None = None
    person_distance_px: float | None = None
    person_track_id: int | None = None

    def magnitudes(self) -> dict[str, float | int | str]:
        """Payload del Event. OMITE los None (test_event_engine afirma que ningun
        valor del payload es None)."""
        out: dict[str, float | int | str] = {}
        if self.duration_s is not None:
            out["duration_s"] = self.duration_s
        if self.class_name is not None:
            out["class_name"] = self.class_name
        if self.class_id is not None:
            out["class_id"] = self.class_id
        if self.net_displacement_px is not None:
            out["net_displacement_px"] = self.net_displacement_px
        if self.person_distance_px is not None:
            out["person_distance_px"] = self.person_distance_px
        if self.person_track_id is not None:
            out["person_track_id"] = self.person_track_id
        return out


@dataclass
class _ObjAgg:
    """Estado O(1) por objeto trackeado (patron _TrackAgg de behavior.py:62-73)."""

    first_seen: float                 # nacimiento del track: guarda contra el warmup
    anchor_t: float                   # ancla temporal del episodio de inmovilidad
    min_x: float                      # caja envolvente desde el ancla: su span ES el
    max_x: float                      # desplazamiento real (la distancia al ancla
    min_y: float                      # permitiria un diametro de 2R)
    max_y: float
    last_seen: float                  # base del TTL, de la gracia de desaparicion y del LRU
    last_x: float                     # ultima posicion conocida: la necesita OBJECT_REMOVED
    last_y: float                     # cuando el track ya no esta en el frame
    class_id: int                     # se congela del ultimo frame visto: el payload del
    class_name: str                   # REMOVED se construye cuando el objeto ya no existe
    bbox: tuple[float, float, float, float]
    zone_id: str | None = None
    last_person_near_t: float | None = None   # LA CLAVE de OBJECT_REMOVED (Patron 3)
    last_person_dist: float | None = None
    last_person_track_id: int | None = None
    left_latched: bool = False        # un unico OBJECT_LEFT por episodio (criterio 5)
    stable: bool = False              # llego a considerarse establecido: ya se puede retirar


class ObjectAnalyzer:
    """Decide OBJECT_LEFT y OBJECT_REMOVED a partir de las posiciones del frame.

    Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
    eventos. Reloj inyectado: todos los metodos que dependen del reloj lo reciben
    como parametro `now: float` (monotonico). Un solo hilo lo llama
    (DetectionWorker._loop), por eso no hay lock.
    """

    def __init__(
        self,
        left_secs: float = 60.0,              # <- config object_left_secs
        still_radius_px: float = 20.0,        # <- config object_still_radius_px
        person_radius_px: float = 150.0,      # <- config object_person_radius_px
        person_radius_ratio: float = 0.5,     # <- config object_person_radius_ratio
        warmup_secs: float = 10.0,            # <- config object_warmup_secs
        gone_secs: float = 3.0,               # <- config object_gone_secs
        person_window_secs: float = 10.0,     # <- config object_person_window_secs
        max_tracks: int = 256,                # <- config object_max_tracks
        state_ttl: float = 30.0,
    ) -> None:
        self._left_secs = left_secs
        self._still_radius_px = still_radius_px
        self._person_radius_px = person_radius_px
        self._person_radius_ratio = person_radius_ratio
        self._warmup_secs = warmup_secs
        self._gone_secs = gone_secs
        self._person_window_secs = person_window_secs
        self._max_tracks = max_tracks
        self._state_ttl = state_ttl

        self._started_at: float | None = None
        self._aggs: dict[int, _ObjAgg] = {}
        self._ignored: dict[int, float] = {}  # track_id -> ultimo instante visto (TTL + LRU)

    def analyze(
        self,
        objects: Sequence[ObjectObservation],
        persons: Sequence[PersonObservation],
        now: float,                           # monotonico INYECTADO
    ) -> list[ObjectFinding]:
        if self._started_at is None:
            self._started_at = now          # el analizador no tiene reloj: lo fija el
                                             # primer frame que lo llama
        findings: list[ObjectFinding] = []
        for obs in sorted(objects, key=lambda o: o.track_id):   # orden determinista
            tid = obs.track_id

            # ─── (a) Guarda de ignorados: nunca vuelve a ser candidato ─────────
            if tid in self._ignored:
                self._ignored[tid] = now
                continue

            agg = self._aggs.get(tid)

            # ─── (b) Guarda de warmup y de zona de exclusion (solo al nacer / ──
            # al entrar en zona) ──────────────────────────────────────────────
            if agg is None and now - self._started_at < self._warmup_secs:
                # Guarda (a) de 27-RESEARCH Q2: en el arranque todo lo que esta
                # en escena nace como track nuevo y es indistinguible de algo
                # que acaba de aparecer.
                self._ignored[tid] = now
                continue
            if obs.excluded:
                # Guarda (b): zona kind == "exclude_objects".
                self._aggs.pop(tid, None)
                self._ignored[tid] = now
                continue
            if agg is None:
                agg = _ObjAgg(
                    first_seen=now,
                    anchor_t=now,
                    min_x=obs.x, max_x=obs.x,
                    min_y=obs.y, max_y=obs.y,
                    last_seen=now,
                    last_x=obs.x, last_y=obs.y,
                    class_id=obs.class_id,
                    class_name=obs.class_name,
                    bbox=obs.bbox,
                    zone_id=obs.zone_id,
                )
                self._aggs[tid] = agg

            # ─── (c) Refrescar los campos volatiles ────────────────────────────
            agg.last_seen = now
            agg.last_x, agg.last_y = obs.x, obs.y
            agg.class_id = obs.class_id
            agg.class_name = obs.class_name
            agg.bbox = obs.bbox
            agg.zone_id = obs.zone_id

            # ─── (d) Persona cerca (Patron 3 del research) ─────────────────────
            best_dist: float | None = None
            best_person: PersonObservation | None = None
            for p in persons:
                r = max(self._person_radius_px, self._person_radius_ratio * p.height_px)
                d = math.hypot(obs.x - p.x, obs.y - p.y)
                if d <= r and (best_dist is None or d < best_dist):
                    best_dist = d
                    best_person = p
            if best_person is not None:
                agg.last_person_near_t = now
                agg.last_person_dist = best_dist
                agg.last_person_track_id = best_person.track_id

            # ─── (e) Inmovilidad (copiado de behavior.py:175-190) ──────────────
            agg.min_x = min(agg.min_x, obs.x); agg.max_x = max(agg.max_x, obs.x)
            agg.min_y = min(agg.min_y, obs.y); agg.max_y = max(agg.max_y, obs.y)
            span = max(agg.max_x - agg.min_x, agg.max_y - agg.min_y)
            if span > self._still_radius_px:
                agg.anchor_t = now                      # se movio: episodio nuevo
                agg.min_x = agg.max_x = obs.x
                agg.min_y = agg.max_y = obs.y
                agg.left_latched = False                # re-armado
                agg.stable = False
            else:
                dur = now - agg.anchor_t
                if dur >= self._gone_secs:
                    # `stable` se deriva de object_gone_secs a proposito, SIN
                    # introducir un parametro nuevo: un objeto que se ha
                    # mantenido quieto al menos tanto como la ventana de
                    # gracia con la que se declara su desaparicion es lo
                    # minimo que puede llamarse "establecido". Atarlo en
                    # cambio a object_left_secs haria que una maleta dejada
                    # 20 s y recogida no pudiera producir nunca OBJECT_REMOVED.
                    agg.stable = True
                if (
                    not agg.left_latched
                    and dur > self._left_secs
                    and (agg.last_person_near_t is None
                         or now - agg.last_person_near_t > self._left_secs)
                ):
                    # El radio se usa aqui en sentido NEGATIVO ("left_secs sin
                    # ninguna persona dentro"), asi que pasarse de grande
                    # SUPRIME eventos y es el lado seguro; en OBJECT_REMOVED
                    # se usa en sentido POSITIVO y pasarse es peligroso. Es la
                    # asimetria de 27-RESEARCH Q1: si la calibracion con
                    # camara real obliga a separarlos, hay que SUBIR el de
                    # OBJECT_LEFT y BAJAR el de OBJECT_REMOVED, nunca al reves.
                    agg.left_latched = True
                    findings.append(ObjectFinding(
                        kind=ObjectKind.LEFT, track_id=obs.track_id,
                        class_id=obs.class_id, class_name=obs.class_name,
                        bbox=obs.bbox, zone_id=obs.zone_id,
                        duration_s=round(dur, 3),
                        net_displacement_px=round(span, 3),
                    ))

        self._enforce_cap()                 # cota dura tambien desde este camino de
        return findings                     # escritura (behavior.py:241-243)

    def prune(self, now: float, seen_ids: set[int]) -> list[ObjectFinding]:
        """Doble guarda de expiracion (TTL + cota dura) que ADEMAS decide OBJECT_REMOVED.

        La desaparicion es la señal mas ruidosa de todas: se decide aqui y no en
        analyze() para poder exigir gone_secs de gracia — sin ella una oclusion de
        un frame (alguien pasa por delante) emitiria el evento (27-RESEARCH Pitfall 10).
        """
        findings: list[ObjectFinding] = []
        for tid, agg in list(self._aggs.items()):
            if tid in seen_ids:
                agg.last_seen = now
                continue
            if now - agg.last_seen <= self._gone_secs:
                continue                         # gracia: puede ser una oclusion
            if (
                agg.stable
                and agg.last_person_near_t is not None
                and now - agg.last_person_near_t <= self._person_window_secs
            ):
                findings.append(ObjectFinding(
                    kind=ObjectKind.REMOVED, track_id=tid,
                    class_id=agg.class_id, class_name=agg.class_name,
                    bbox=agg.bbox, zone_id=agg.zone_id,
                    duration_s=round(agg.last_seen - agg.anchor_t, 3),
                    person_distance_px=(round(agg.last_person_dist, 3)
                                         if agg.last_person_dist is not None else None),
                    person_track_id=agg.last_person_track_id,
                ))
            del self._aggs[tid]                  # sin persona cerca: desaparicion silenciosa
        for tid in list(self._ignored):
            if now - self._ignored[tid] > self._state_ttl:
                del self._ignored[tid]
        self._enforce_cap()
        return findings

    def _enforce_cap(self) -> None:
        """Cota dura por max_tracks, LRU por last_seen ("seguro de vida" de la Fase 22).

        Actua aunque nadie llame a prune() a tiempo. Se llama tanto desde
        analyze() como desde prune() para que la cota se cumpla sin depender
        del mantenimiento periodico.
        """
        if len(self._aggs) > self._max_tracks:
            overflow = len(self._aggs) - self._max_tracks
            oldest = sorted(self._aggs.items(), key=lambda kv: kv[1].last_seen)[:overflow]
            for tid, _ in oldest:
                del self._aggs[tid]

        if len(self._ignored) > self._max_tracks:
            overflow = len(self._ignored) - self._max_tracks
            oldest = sorted(self._ignored.items(), key=lambda kv: kv[1])[:overflow]
            for tid, _ in oldest:
                del self._ignored[tid]
