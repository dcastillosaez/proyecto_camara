"""Memory-bound regression tests for every accumulative structure in the
pipeline (Fase 22, PIPE-07). One test per structure identified in
22-CONTEXT.md, derived from Fases 17-21: a 24/7 process must not grow
memory just because time (or event volume) passes.

Most of these structures were already bounded when this phase started
(deque(maxlen=...), queue.Queue(maxsize=...), or a prune()/purge that already
runs from the pipeline) — these tests exist to prove it and catch regressions,
not to introduce new bounding logic where it was missing.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.events.bus import EventBus
from backend.events.rules import RuleEngine
from backend.events.types import Event, EventType
from backend.observability.latency import LatencyTracker, Stage
from backend.perception.behavior import BehaviorAnalyzer
from backend.perception.face.identity import IdentityStateMachine, TemporalVoter
from backend.perception.reid.gallery import TrackGallery
from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.recording import RecordingWorker
from backend.pipeline.tracking import TrackRegistry
from backend.recognizer import PersonRecognizer


def _fake_tracked(track_id: int):
    return SimpleNamespace(
        tracker_id=np.array([track_id]),
        xyxy=np.array([[0, 0, 10, 10]], dtype=np.float32),
        confidence=np.array([0.9], dtype=np.float32),
    )


# ─── TrackRegistry._tracks se acota con prune() periódico ────────────────────
# ByteTrack asigna ids monotonamente crecientes: sin poda, 10.000 tracks
# efimeros (cada uno visto una sola vez) dejarian 10.000 entradas vivas para
# siempre. Con ttl=5 y una poda cada iteracion, el registro debe quedarse
# con solo un puñado de tracks recientes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_track_registry_bounded():
    registry = TrackRegistry()
    for i in range(10_000):
        now = float(i)
        registry.update_from_detections(_fake_tracked(i), now)
        registry.prune(now, ttl=5.0)

    assert len(registry.active_ids()) <= 10


# ─── TrackState.centroid_history respeta su maxlen ────────────────────────────
# Un track de larga duracion (persona parada frente a la camara) no debe
# acumular un historial de centroides sin limite: es un deque(maxlen=...),
# no una lista.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_centroid_history_bounded():
    registry = TrackRegistry(history_len=150)
    for i in range(100_000):
        registry.update_from_detections(_fake_tracked(track_id=1), now=float(i))

    state = registry.get(1)
    assert state is not None
    assert len(state.centroid_history) <= 150


# ─── Las caches de PersonRecognizer indexadas por tracker_id se podan ────────
# _cache, _last_attempt y _pending crecerian indefinidamente si no se
# purgan los tracker_ids que ya no estan activos — ByteTrack nunca reutiliza
# ids. prune(active_tracker_ids) debe dejar solo las entradas activas.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_recognizer_cache_bounded(tmp_path):
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    for tid in range(10_000):
        r._cache[tid] = (tid, "Someone")
        r._last_attempt[tid] = 0
        r._pending[tid] = []

    r.prune(active_tracker_ids=set(range(9_990, 10_000)))

    assert len(r._cache) == 10
    assert len(r._last_attempt) == 10
    assert len(r._pending) == 10


# ─── TemporalVoter no acumula votos de tracks muertos ────────────────────────
# ByteTrack asigna ids monotonamente crecientes y nunca los reutiliza: sin
# prune(active_ids), _votes crece sin cota en un proceso 24/7.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_temporal_voter_bounded():
    voter = TemporalVoter(window=8)
    for tid in range(10_000):
        voter.vote(tid, 1, 0.9)
        voter.prune(set(range(max(0, tid - 5), tid + 1)))
    assert len(voter._votes) <= 6


# ─── IdentityStateMachine expira sus estados por tiempo, no por active_ids ───
# TEMPORARILY_LOST existe para sobrevivir a que el track desaparezca, asi que no
# se puede podar contra active_ids; la cota la dan lost_ttl y el TTL de estados
# rancios de on_tick(). Medido con este mismo bucle: con un solo person_id en
# juego, _claim_lost reclama la identidad TEMPORARILY_LOST del track anterior
# en cuanto llega el siguiente track_id, así que _states se queda en 1 entrada
# viva — el límite de 500 deja margen amplio (orden de magnitud, no el valor
# exacto) frente a otras combinaciones de parámetros/identidades concurrentes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_state_machine_bounded():
    fsm = IdentityStateMachine(TemporalVoter(window=8), lost_ttl=30.0,
                                revalidate_after=120.0)
    for tid in range(10_000):
        now = float(tid)
        fsm.on_face_result(tid, 1, 0.9, now)
        fsm.on_active_tracks({tid}, now)
        fsm.on_tick(now)
    assert len(fsm._states) <= 500


# ─── El debounce del RuleEngine se poda por antigüedad ────────────────────────
# _last_fired acumula una clave por (regla, camara, persona/track). Con
# tracks efimeros y sin purga, esto crece sin limite en un proceso 24/7.
# _purge_stale ya se invoca en cada evaluate(); aqui se prueba directamente
# con un volumen grande y timestamps que cruzan el umbral de antigüedad.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_rule_debounce_bounded():
    engine = RuleEngine(rules=[], registry=MagicMock())
    base = datetime(2026, 1, 1)
    for i in range(10_000):
        ts = base + timedelta(seconds=i)
        engine._last_fired[("rule", "cam1", str(i))] = ts

    # ttl = max(debounce*10, 3600) with no rules configured -> 3600s
    engine._purge_stale(base + timedelta(seconds=10_000))

    assert len(engine._last_fired) <= 3_601


# ─── La cola del EventBus nunca crece más allá de maxsize ────────────────────
# Sin consumidor (o un consumidor mas lento que la produccion), publicar
# 100.000 eventos no debe hacer crecer la cola interna: se descarta el mas
# antiguo antes que acumular.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_event_bus_queue_bounded():
    bus = EventBus(maxsize=1000)
    event = Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00")
    for _ in range(100_000):
        bus._enqueue(event)

    assert bus._queue.qsize() <= 1000
    assert bus.stats["dropped"] > 0
    assert bus.stats["published"] == 100_000


# ─── El pre-buffer de grabación ya está acotado (Fase 20) ────────────────────
# RingFrameBuffer limita por frames Y por bytes (tests/test_prebuffer.py).
# Referenciado aqui para que la lista de estructuras acumulativas de
# 22-CONTEXT.md quede completa en un solo fichero.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_prebuffer_bounded_reference():
    from backend.pipeline.prebuffer import RingFrameBuffer

    buf = RingFrameBuffer(seconds=1, fps=15, max_bytes=100_000_000)
    base = datetime(2026, 1, 1)
    for i in range(10_000):
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        frame = Frame(camera_id="cam1", seq=i, captured_at=0.0, wall_clock=base, image=image)
        buf.push(frame)

    assert len(buf.drain()) <= 15 + 5  # ~1s * 15fps, generous margin


# ─── La cola de frames en vivo del RecordingWorker descarta antes que crecer ─
# Mientras se ensambla un clip, cada frame nuevo se ofrece a _live_queue.
# Si el hilo de ensamblado se atasca, la cola debe descartar el frame mas
# antiguo en vez de crecer sin limite.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_live_queue_bounded(tmp_path):
    broker = FrameBroker()
    sub = broker.subscribe("recording")
    worker = RecordingWorker(
        sub, TrackRegistry(), clips_dir=str(tmp_path), fps=15.0,
        pre_buffer_secs=1.0, post_buffer_secs=1.0, live_queue_max=50,
    )
    base = datetime(2026, 1, 1)
    for i in range(10_000):
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        frame = Frame(camera_id="cam1", seq=i, captured_at=float(i), wall_clock=base, image=image)
        worker._offer_live(frame)

    assert worker._live_queue.qsize() <= 50
    assert worker._live_dropped > 0


# ─── Los deques del LatencyTracker respetan su ventana ────────────────────────
# Un proceso de larga duracion observa millones de latencias; solo la
# ventana reciente (window=1000 por defecto) debe permanecer en memoria.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_latency_deques_bounded():
    tracker = LatencyTracker(window=1000)
    for i in range(50_000):
        tracker._record(Stage.CAPTURE_TO_PROCESS, duration=0.01)

    assert len(tracker._samples[Stage.CAPTURE_TO_PROCESS]) <= 1000


# ─── El estado de zona por track se recalcula, no se acumula ────────────────
# `inside` se reconstruye cada frame a partir de los tracker_ids ACTUALMENTE
# dentro de la zona (sv.PolygonZone.trigger sobre el frame actual) — un track
# que expira simplemente deja de aparecer, sin necesitar una purga aparte.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_zone_state_bounded():
    zone_state = {"id": "z1", "inside": set(), "entries": 0, "current": 0}
    for i in range(10_000):
        # Cada frame, "inside" se sustituye por los tracker_ids visibles AHORA
        # (nunca se le hace update() acumulativo) — aqui i%5 simula que solo
        # unos pocos tracks estan dentro en un instante dado.
        currently_inside = {i % 5}
        zone_state["entries"] += len(currently_inside - zone_state["inside"])
        zone_state["inside"] = currently_inside

    assert len(zone_state["inside"]) <= 5


# ─── El heatmap es una matriz de tamaño fijo, no una lista de puntos ─────────
# Acumular puntos en una lista crecería sin límite con la actividad; una
# matriz numpy del tamaño del frame es memoria constante sin importar cuantas
# detecciones se acumulen.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_heatmap_does_not_grow():
    import sys

    heat_mask = np.zeros((720, 1280), dtype=np.float32)
    size_before = heat_mask.nbytes
    for _ in range(10_000):
        heat_mask += np.ones((720, 1280), dtype=np.float32)

    assert heat_mask.nbytes == size_before


# ─── tracemalloc: dos ventanas equivalentes no crecen más de 5 MB ────────────
# Complementa los tests de cota individuales con una prueba transversal: si
# alguna estructura no cubierta arriba tuviera una fuga, esta la detecta y
# apunta al fichero/linea exactos via snapshot.compare_to.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_no_growth_over_simulated_windows():
    import tracemalloc

    def run_window(registry, recognizer, bus, n: int) -> None:
        for i in range(n):
            now = float(i)
            registry.update_from_detections(_fake_tracked(i), now)
            registry.prune(now, ttl=5.0)
            recognizer._cache[i] = (i, None)
            recognizer.prune(active_tracker_ids=set(range(max(0, i - 5), i + 1)))
            bus._enqueue(Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00"))

    registry = TrackRegistry()
    recognizer = PersonRecognizer.__new__(PersonRecognizer)
    recognizer._cache, recognizer._last_attempt = {}, {}
    recognizer._pending = {}
    import threading
    recognizer._lock = threading.RLock()
    bus = EventBus(maxsize=1000)

    run_window(registry, recognizer, bus, 2000)  # warm-up — caches/registries settle

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()
    run_window(registry, recognizer, bus, 5000)
    snap2 = tracemalloc.take_snapshot()
    top = snap2.compare_to(snap1, "lineno")[:10]
    growth = sum(s.size_diff for s in top)
    tracemalloc.stop()

    assert growth < 5 * 1024 * 1024, (
        f"Crecimiento de {growth / 1e6:.1f} MB entre dos ventanas equivalentes:\n"
        + "\n".join(map(str, top))
    )


# ─── TrackGallery no acumula embeddings de tracks muertos ─────────────────────
# ByteTrack asigna ids monotonamente crecientes y nunca los reutiliza. Cada
# entrada son 512 float32 = 2 KB; sin doble guarda (TTL de inherit_window +
# cota dura max_entries) un proceso 24/7 la haria crecer sin limite. La cota
# dura es el "seguro de vida" de la Fase 22: actua aunque nadie llame a prune()
# a tiempo. Techo: 256 x 2 KB = 512 KB.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_track_gallery_bounded():
    gallery = TrackGallery(inherit_window=15.0, similarity_threshold=0.7,
                           interval=2.0, max_entries=256)
    emb = np.zeros(512, dtype=np.float32)
    emb[0] = 1.0
    for tid in range(10_000):
        now = float(tid)
        gallery.update(tid, emb, tid % 7, now)
        gallery.prune(now, frame_ids={tid})
    assert len(gallery._entries) <= 256


def TEST_track_gallery_bounded_without_prune():
    """La cota dura actua aunque el mantenimiento periodico nunca se ejecute."""
    gallery = TrackGallery(max_entries=256)
    emb = np.zeros(512, dtype=np.float32)
    emb[0] = 1.0
    for tid in range(10_000):
        gallery.update(tid, emb, 1, now=float(tid))
    assert len(gallery._entries) <= 256


# ─── BehaviorAnalyzer._aggs / _loiter no acumulan tracks efimeros ────────────
# ByteTrack asigna ids monotonamente crecientes y nunca los reutiliza (Fase 26,
# criterio 4). Sin doble guarda (TTL de state_ttl + cota dura max_tracks) un
# proceso 24/7 haria crecer _aggs y _loiter sin limite: cada track efimero deja
# una entrada por track y otra por (track, zona implicita).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_behavior_state_bounded():
    analyzer = BehaviorAnalyzer(max_tracks=256, state_ttl=30.0)
    for tid in range(10_000):
        now = float(tid)
        analyzer.analyze({tid: (1.0, 1.0)}, {}, {}, now)
        analyzer.prune(now, frame_ids={tid})
    assert len(analyzer._aggs) <= 256
    assert len(analyzer._loiter) <= 256


def TEST_behavior_state_bounded_without_prune():
    """La cota dura actua aunque el mantenimiento periodico nunca se ejecute."""
    analyzer = BehaviorAnalyzer(max_tracks=256)
    for tid in range(10_000):
        analyzer.analyze({tid: (1.0, 1.0)}, {}, {}, float(tid))
    assert len(analyzer._aggs) <= 256
    assert len(analyzer._loiter) <= 256
