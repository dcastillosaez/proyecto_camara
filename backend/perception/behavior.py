"""BehaviorAnalyzer — LOITERING / RUNNING / IMMOBILE / CROWD (SPEC_v2.md §5.7).

Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
eventos. Reloj inyectado: todos los metodos que dependen del reloj lo reciben
como parametro `now: float` (monotonico). Un solo hilo lo llama
(DetectionWorker._loop), por eso no hay lock.

Fuera de alcance aqui: construir Event, conocer camera_id, conocer el reloj de
pared, decidir la severidad y emitir ZONE_ENTERED/ZONE_EXITED (los emite
EventEngine.process_zone desde la Fase 19; reimplementarlos aqui duplicaria
cada evento de zona — 26-CONTEXT.md H-2).

La firma de SPEC_v2.md §5.7 (`analyze(...) -> list[Event]`) queda corregida a
`-> list[BehaviorFinding]` por 26-RESEARCH.md D-3.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

REARM_RATIO = 0.8  # histeresis de re-armado: un umbral numerico oscilaria en el borde


class BehaviorKind(str, Enum):
    LOITERING = "loitering"
    RUNNING = "running"
    IMMOBILE = "immobile"
    CROWD = "crowd"


@dataclass
class BehaviorFinding:
    """El analizador devuelve esto, NO un Event: perception/ no conoce camera_id ni el
    reloj de pared. EventEngine.emit_behavior() lo traduce a Event (26-RESEARCH.md D-3).
    """

    kind: BehaviorKind
    track_id: int | None = None            # None solo para CROWD: evento de escena
    zone_id: str | None = None             # None = escena implicita cuando el track no esta en ninguna zona, D-02
    duration_s: float | None = None        # nombre OBLIGATORIO: rules.py:88-91 lee literalmente payload['duration_s'] para resolver duration_gte
    net_displacement_px: float | None = None
    speed_px_s: float | None = None
    track_count: int | None = None

    def magnitudes(self) -> dict[str, float | int]:
        """Payload que EventEngine.emit_behavior pasara como `payload=` (BEH-05)."""
        out: dict[str, float | int] = {}
        if self.duration_s is not None:
            out["duration_s"] = self.duration_s
        if self.net_displacement_px is not None:
            out["net_displacement_px"] = self.net_displacement_px
        if self.speed_px_s is not None:
            out["speed_px_s"] = self.speed_px_s
        if self.track_count is not None:
            out["track_count"] = self.track_count
        return out


@dataclass
class _TrackAgg:
    """Estado O(1) por track para IMMOBILE y RUNNING (patron `_GalleryEntry`)."""

    imm_anchor_t: float            # ancla temporal del episodio de inmovilidad
    imm_min_x: float                # caja envolvente de las posiciones desde el ancla:
    imm_max_x: float                # su span ES el desplazamiento real, mientras que
    imm_min_y: float                # la distancia al ancla permitiria un diametro de 2R
    imm_max_y: float
    last_seen: float                # base del TTL y del LRU de la cota dura
    imm_latched: bool = False       # un evento IMMOBILE por episodio
    run_latched: bool = False       # un evento RUNNING por episodio


@dataclass
class _ZoneAgg:
    """Ancla de permanencia por (track, zona) (D-04: zonas solapadas -> un LOITERING por zona)."""

    anchor_t: float
    anchor_x: float
    anchor_y: float
    last_seen: float
    latched: bool = False


def _window_speed(
    history: Sequence[tuple[float, float, float]] | None, now: float, window_s: float,
) -> float | None:
    """Velocidad media (desplazamiento NETO / dt) sobre los ultimos window_s segundos.

    None si el track aun no tiene window_s de historia. El corte es SIEMPRE por el
    `t` de la tupla, jamas por len(history) ni por indice (Pitfall 1). El
    desplazamiento es NETO, nunca longitud de camino: la longitud de camino
    integra el jitter del bbox y daria velocidad creciente con el FPS para un
    track parado (Pitfall 6).
    """
    if not history:
        return None
    t_now, x_now, y_now = history[-1]
    old = None
    for t, x, y in reversed(history):
        old = (t, x, y)
        if t_now - t >= window_s:
            break
    if old is None or t_now - old[0] < window_s:
        return None
    dt = t_now - old[0]
    return math.hypot(x_now - old[1], y_now - old[2]) / dt


class BehaviorAnalyzer:
    """Decide LOITERING, RUNNING, IMMOBILE y CROWD a partir de las posiciones del frame.

    Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
    eventos. Reloj inyectado: todos los metodos que dependen del reloj lo reciben
    como parametro `now: float` (monotonico). Un solo hilo lo llama
    (DetectionWorker._loop), por eso no hay lock.

    No aplica politica de producto: LOITERING e IMMOBILE coexisten (D-03); el
    aislamiento que exige el criterio 2 se consigue en las trayectorias de test,
    no con supresion mutua aqui.
    """

    def __init__(
        self,
        loiter_secs: float = 120.0,
        loiter_radius_px: float = 80.0,
        loiter_require_zone: bool = False,
        run_speed_px_s: float = 350.0,
        run_window_secs: float = 1.0,
        immobile_secs: float = 60.0,
        immobile_radius_px: float = 20.0,
        crowd_threshold: int = 5,
        max_tracks: int = 256,
        state_ttl: float = 30.0,
    ) -> None:
        self._loiter_secs = loiter_secs
        self._loiter_radius_px = loiter_radius_px
        self._loiter_require_zone = loiter_require_zone
        self._run_speed_px_s = run_speed_px_s
        self._run_window_secs = run_window_secs
        self._immobile_secs = immobile_secs
        self._immobile_radius_px = immobile_radius_px
        self._crowd_threshold = crowd_threshold
        self._max_tracks = max_tracks
        self._state_ttl = state_ttl

        self._aggs: dict[int, _TrackAgg] = {}
        self._loiter: dict[tuple[int, str | None], _ZoneAgg] = {}
        self._crowd_latched = False  # latch de escena, analogo 1:1 de EventEngine._camera_offline (engine.py:38)

    def analyze(
        self,
        centroids: dict[int, tuple[float, float]],
        zone_membership: dict[str, set[int]],
        histories: dict[int, Sequence[tuple[float, float, float]]],
        now: float,
    ) -> list[BehaviorFinding]:
        findings: list[BehaviorFinding] = []

        for tid in sorted(centroids):
            x, y = centroids[tid]
            agg = self._aggs.get(tid)
            if agg is None:
                agg = _TrackAgg(
                    imm_anchor_t=now,
                    imm_min_x=x, imm_max_x=x,
                    imm_min_y=y, imm_max_y=y,
                    last_seen=now,
                )
                self._aggs[tid] = agg
            agg.last_seen = now

            # ─── IMMOBILE (BEH-02) ─────────────────────────────────────────
            agg.imm_min_x = min(agg.imm_min_x, x); agg.imm_max_x = max(agg.imm_max_x, x)
            agg.imm_min_y = min(agg.imm_min_y, y); agg.imm_max_y = max(agg.imm_max_y, y)
            span = max(agg.imm_max_x - agg.imm_min_x, agg.imm_max_y - agg.imm_min_y)
            if span > self._immobile_radius_px:
                agg.imm_anchor_t = now
                agg.imm_min_x = agg.imm_max_x = x
                agg.imm_min_y = agg.imm_max_y = y
                agg.imm_latched = False              # re-armado: el episodio empieza de cero
            else:
                dur = now - agg.imm_anchor_t
                if not agg.imm_latched and dur > self._immobile_secs:
                    agg.imm_latched = True
                    findings.append(BehaviorFinding(kind=BehaviorKind.IMMOBILE, track_id=tid,
                                                    duration_s=round(dur, 3),
                                                    net_displacement_px=round(span, 3)))

            # ─── RUNNING (BEH-02) ──────────────────────────────────────────
            speed = _window_speed(histories.get(tid), now, self._run_window_secs)
            if speed is not None:
                if not agg.run_latched and speed > self._run_speed_px_s:
                    agg.run_latched = True
                    findings.append(BehaviorFinding(kind=BehaviorKind.RUNNING, track_id=tid,
                                                    speed_px_s=round(speed, 3),
                                                    duration_s=round(self._run_window_secs, 3)))
                elif agg.run_latched and speed < self._run_speed_px_s * REARM_RATIO:
                    agg.run_latched = False

            # ─── LOITERING (BEH-01, D-02, D-04) ────────────────────────────
            zones_of_track = sorted(zid for zid, ids in zone_membership.items() if tid in ids)
            if not zones_of_track:
                target_zones = [] if self._loiter_require_zone else [None]
            else:
                target_zones = zones_of_track
            for zid in target_zones:
                z = self._loiter.get((tid, zid))
                if z is None:
                    z = _ZoneAgg(anchor_t=now, anchor_x=x, anchor_y=y, last_seen=now)
                    self._loiter[(tid, zid)] = z
                z.last_seen = now
                disp = math.hypot(x - z.anchor_x, y - z.anchor_y)
                if disp >= self._loiter_radius_px:
                    z.anchor_t, z.anchor_x, z.anchor_y = now, x, y
                    z.latched = False                    # se alejo: episodio nuevo
                elif not z.latched and now - z.anchor_t > self._loiter_secs:
                    z.latched = True
                    findings.append(BehaviorFinding(kind=BehaviorKind.LOITERING, track_id=tid,
                                                    zone_id=zid, duration_s=round(now - z.anchor_t, 3),
                                                    net_displacement_px=round(disp, 3)))

            # El track salio de una zona en este frame: la re-entrada debe reiniciar el ancla.
            stale_keys = [
                key for key in self._loiter
                if key[0] == tid and key[1] not in target_zones
            ]
            for key in stale_keys:
                del self._loiter[key]

        # ─── CROWD (BEH-03) — latch de escena, analogo 1:1 de camera_offline ──
        count = len(centroids)
        if not self._crowd_latched and count >= self._crowd_threshold:
            self._crowd_latched = True
            findings.append(BehaviorFinding(kind=BehaviorKind.CROWD, track_count=count))
        elif self._crowd_latched and count < self._crowd_threshold * REARM_RATIO:
            self._crowd_latched = False          # re-armado SILENCIOSO: CROWD_CLEARED no existe

        # Cota dura tambien desde este camino de escritura, no solo desde prune(): _enforce_cap()
        self._enforce_cap()
        return findings

    def prune(self, now: float, frame_ids: set[int]) -> None:
        """Doble guarda de expiracion, calcada de TrackGallery.prune.

        Guarda 1 (TTL): borra agregados mas viejos que state_ttl. Un track visible
        refresca `last_seen` en cada analyze() (<= state_ttl), asi que nunca caduca
        estando en pantalla.
        Guarda 2 (cota dura): ver _enforce_cap — "seguro de vida" de la Fase 22.
        """
        for tid in list(self._aggs):
            if tid in frame_ids:
                self._aggs[tid].last_seen = now
        for tid in list(self._aggs):
            if now - self._aggs[tid].last_seen > self._state_ttl:
                del self._aggs[tid]
        for key in list(self._loiter):
            if now - self._loiter[key].last_seen > self._state_ttl:
                del self._loiter[key]
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        """Cota dura por max_tracks, LRU por last_seen (Fase 22, "seguro de vida").

        Actua aunque nadie llame a prune() a tiempo. Se llama tanto desde
        analyze() como desde prune() para que la cota se cumpla sin depender del
        mantenimiento periodico.
        """
        if len(self._aggs) > self._max_tracks:
            overflow = len(self._aggs) - self._max_tracks
            oldest = sorted(self._aggs.items(), key=lambda kv: kv[1].last_seen)[:overflow]
            for tid, _ in oldest:
                del self._aggs[tid]
                for key in [k for k in self._loiter if k[0] == tid]:
                    del self._loiter[key]

        if len(self._loiter) > self._max_tracks:
            overflow = len(self._loiter) - self._max_tracks
            oldest = sorted(self._loiter.items(), key=lambda kv: kv[1].last_seen)[:overflow]
            for key, _ in oldest:
                del self._loiter[key]
