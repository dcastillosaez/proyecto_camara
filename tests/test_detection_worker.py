"""Tests for backend.pipeline.detection.DetectionWorker — deteccion desacoplada."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest
import supervision as sv

from backend.perception.behavior import BehaviorAnalyzer, BehaviorKind
from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.detection import DetectionWorker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.tracking import TrackRegistry


def _make_frame(seq: int) -> Frame:
    return Frame(
        camera_id="cam1", seq=seq, captured_at=time.monotonic(),
        wall_clock=datetime.now(), image=np.zeros((360, 640, 3), dtype=np.uint8),
    )


def _tracked(ids: list[int]) -> sv.Detections:
    n = len(ids)
    det = sv.Detections(
        xyxy=np.array([[10, 10, 50, 50]] * n, dtype=float),
        confidence=np.full(n, 0.9),
        class_id=np.zeros(n, dtype=int),
    )
    det.tracker_id = np.array(ids)
    return det


class _Publisher:
    """Publica frames a ritmo continuo en un hilo de fondo, para simular
    una camara a ~25-30 FPS mientras el worker procesa a su propio ritmo."""

    def __init__(self, broker: FrameBroker):
        self._broker = broker
        self._running = False
        self._seq = 0

    def start(self, interval: float = 0.03) -> None:
        self._running = True

        def _loop():
            while self._running:
                self._broker.publish(_make_frame(self._seq))
                self._seq += 1
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)


@pytest.fixture
def broker():
    return FrameBroker()


# ─── Corre al FPS objetivo, no al ritmo de publicacion ───────────────────────
def test_runs_at_target_fps(broker):
    detector = MagicMock()
    detector.detect_sv.return_value = sv.Detections.empty()
    tracker = MagicMock()
    tracker.update.return_value = (sv.Detections.empty(), [])

    sub = broker.subscribe("detector")
    rate = AdaptiveRate(target_fps=8.0, min_fps=8.0, max_fps=8.0)  # fijo, sin escalones
    worker = DetectionWorker(sub, detector, tracker, TrackRegistry(), rate)
    worker.start()

    pub = _Publisher(broker)
    pub.start(interval=0.04)  # ~25 FPS de publicacion
    time.sleep(1.0)
    pub.stop()
    worker.stop()

    # a 8 FPS objetivo durante ~1s, se esperan ~8 llamadas, no ~25
    assert 4 <= detector.detect_sv.call_count <= 14


# ─── Un detector lento no bloquea al broker ──────────────────────────────────
def test_slow_detector_does_not_block_broker(broker):
    detector = MagicMock()

    def _slow_detect(image):
        time.sleep(0.2)
        return sv.Detections.empty()

    detector.detect_sv.side_effect = _slow_detect
    tracker = MagicMock()
    tracker.update.return_value = (sv.Detections.empty(), [])

    sub = broker.subscribe("detector")
    rate = AdaptiveRate(target_fps=12.0, min_fps=3.0, max_fps=12.0)
    worker = DetectionWorker(sub, detector, tracker, TrackRegistry(), rate)
    worker.start()

    pub = _Publisher(broker)
    pub.start(interval=0.01)  # ~100 FPS de publicacion, mucho mas rapido que el detector
    time.sleep(1.0)
    pub.stop()
    dropped = broker.stats()["detector"]["dropped"]  # antes de stop(): cierra la suscripcion
    worker.stop()

    assert dropped > 0


# ─── El frame_rate del tracker sigue al FPS efectivo ─────────────────────────
def test_tracker_frame_rate_follows_effective_fps(broker):
    detector = MagicMock()

    def _slow_detect(image):
        time.sleep(0.3)  # fuerza que la latencia supere el presupuesto
        return sv.Detections.empty()

    detector.detect_sv.side_effect = _slow_detect
    tracker = MagicMock()
    tracker.update.return_value = (sv.Detections.empty(), [])

    sub = broker.subscribe("detector")
    rate = AdaptiveRate(target_fps=8.0, min_fps=3.0, max_fps=12.0)
    worker = DetectionWorker(sub, detector, tracker, TrackRegistry(), rate)
    worker.start()

    pub = _Publisher(broker)
    pub.start(interval=0.01)
    time.sleep(2.0)  # tiempo suficiente para 3+ observaciones lentas -> baja de escalon
    pub.stop()
    worker.stop()

    tracker.set_frame_rate.assert_called()
    called_with = [c.args[0] for c in tracker.set_frame_rate.call_args_list]
    assert any(fps < 8.0 for fps in called_with)


# ─── El registro de tracks se actualiza ──────────────────────────────────────
def test_registry_updated_with_tracks(broker):
    detector = MagicMock()
    detector.detect_sv.return_value = sv.Detections.empty()
    tracker = MagicMock()
    tracker.update.return_value = (_tracked([1, 2]), [])

    sub = broker.subscribe("detector")
    registry = TrackRegistry()
    rate = AdaptiveRate(target_fps=12.0, min_fps=3.0, max_fps=12.0)
    worker = DetectionWorker(sub, detector, tracker, registry, rate)
    worker.start()

    broker.publish(_make_frame(0))
    deadline = time.time() + 2.0
    while time.time() < deadline and not registry.snapshot():
        time.sleep(0.02)
    worker.stop()

    snap = registry.snapshot()
    assert set(snap.keys()) == {1, 2}


# ─── rate.observe recibe la latencia real de la inferencia ──────────────────
def test_latency_is_observed(broker):
    detector = MagicMock()
    detector.detect_sv.return_value = sv.Detections.empty()
    tracker = MagicMock()
    tracker.update.return_value = (sv.Detections.empty(), [])

    sub = broker.subscribe("detector")
    rate = MagicMock()
    rate.should_process.return_value = True
    rate.effective_fps = 8.0
    worker = DetectionWorker(sub, detector, tracker, TrackRegistry(), rate)
    worker.start()

    broker.publish(_make_frame(0))
    deadline = time.time() + 2.0
    while time.time() < deadline and not rate.observe.called:
        time.sleep(0.02)
    worker.stop()

    assert rate.observe.called
    latency = rate.observe.call_args.args[0]
    assert isinstance(latency, float)
    assert latency >= 0.0


# ─── stop() termina el hilo y cierra la suscripcion ──────────────────────────
def test_stop_is_clean(broker):
    detector = MagicMock()
    detector.detect_sv.return_value = sv.Detections.empty()
    tracker = MagicMock()
    tracker.update.return_value = (sv.Detections.empty(), [])

    sub = broker.subscribe("detector")
    worker = DetectionWorker(sub, detector, tracker, TrackRegistry(), AdaptiveRate())
    worker.start()
    time.sleep(0.1)
    worker.stop()

    assert not worker._thread.is_alive()
    assert "detector" not in broker.stats()  # la suscripcion se cerro


# ─── Una excepcion del detector no mata al worker ────────────────────────────
def test_detector_exception_does_not_kill_worker(broker):
    detector = MagicMock()
    calls = {"n": 0}

    def _flaky(image):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return sv.Detections.empty()

    detector.detect_sv.side_effect = _flaky
    tracker = MagicMock()
    tracker.update.return_value = (sv.Detections.empty(), [])

    sub = broker.subscribe("detector")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = DetectionWorker(sub, detector, tracker, TrackRegistry(), rate)
    worker.start()

    for i in range(5):
        broker.publish(_make_frame(i))
        time.sleep(0.15)
    worker.stop()

    assert calls["n"] >= 2  # sobrevivio a la excepcion y siguio procesando


# ---------------------------------------------------------------------------
# Zonas de interes y heatmap — portados de RTSPStream en la Fase 18
# ---------------------------------------------------------------------------

def _worker_for_zones() -> DetectionWorker:
    broker = FrameBroker()
    return DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
    )


def _tracked_at(boxes, tids) -> sv.Detections:
    det = sv.Detections(
        xyxy=np.array(boxes, dtype=float),
        confidence=np.ones(len(tids)),
        class_id=np.zeros(len(tids), dtype=int),
    )
    det.tracker_id = np.array(tids)
    return det


# ─── PolygonZone cuenta presencia y entradas acumuladas por zona ────────────
def test_polygon_zone_counts_presence_and_entries():
    import json

    worker = _worker_for_zones()
    worker.set_zones([{
        "id": "z1", "name": "Puerta", "enabled": True,
        "polygon_json": json.dumps([[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]),
    }])

    shape = (720, 1280, 3)
    # frame 1: track 1 dentro (pies en x=320), track 2 fuera (x=960)
    worker._update_zones_and_heat(
        _tracked_at([[300, 100, 340, 400], [940, 100, 980, 400]], [1, 2]), shape
    )
    assert worker.get_zone_stats() == [
        {"id": "z1", "name": "Puerta", "current": 1, "entries": 1}
    ]

    # frame 2: el track 2 entra en la zona
    worker._update_zones_and_heat(
        _tracked_at([[300, 100, 340, 400], [400, 100, 440, 400]], [1, 2]), shape
    )
    assert worker.get_zone_stats() == [
        {"id": "z1", "name": "Puerta", "current": 2, "entries": 2}
    ]


# ─── El heatmap acumula actividad y se compone bajo demanda ─────────────────
def test_heatmap_accumulates_and_renders():
    worker = _worker_for_zones()
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    assert worker.compose_heatmap(frame) is None   # sin actividad todavia

    worker._update_zones_and_heat(_tracked_at([[600, 100, 680, 400]], [1]), frame.shape)

    heat = worker.compose_heatmap(frame)
    assert heat is not None
    assert heat.shape == frame.shape
    assert heat[380:420, 620:660].any()   # hay calor alrededor de los pies


# ─── D-05: frame_ids() se publica exista o no event_engine ──────────────────
# Sin esto, la construccion por defecto de DetectionWorker (event_engine=None,
# la que usa la mayoria de tests de este fichero y CameraPipeline si no se
# configuran alertas) dejaria frame_ids() vacio para siempre, y
# RecognitionWorker._sync_identity reportaria todo track como perdido en
# cada ciclo -- el mismo bug que D-05 corrige, pero de vuelta y sin aviso.
# ───────────────────────────────────────────────────────────────────────────
def TEST_frame_ids_published_without_event_engine(broker):
    registry = TrackRegistry()
    detector = MagicMock()
    tracker = MagicMock()
    rate = AdaptiveRate(target_fps=5.0, min_fps=5.0, max_fps=5.0)
    worker = DetectionWorker(broker.subscribe("detector"), detector, tracker, registry, rate)

    worker._emit_track_lifecycle(_tracked([1, 2]), captured_at=0.0, processed_at=0.0)

    assert registry.frame_ids() == {1, 2}


# ---------------------------------------------------------------------------
# Fase 26: enganche del BehaviorAnalyzer en _analyze_behavior
# ---------------------------------------------------------------------------

def TEST_behavior_analyzer_emits_crowd_from_worker():
    broker = FrameBroker()
    event_engine = MagicMock()
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
        behavior=BehaviorAnalyzer(crowd_threshold=5),
    )
    boxes = [[i * 100, 10, i * 100 + 30, 50] for i in range(5)]
    tids = [1, 2, 3, 4, 5]

    worker._analyze_behavior(_tracked_at(boxes, tids), captured_at=0.0, processed_at=0.0)

    event_engine.emit_behavior.assert_called_once()
    finding = event_engine.emit_behavior.call_args[0][0]
    assert finding.kind == BehaviorKind.CROWD
    assert finding.magnitudes()["track_count"] == 5


def TEST_behavior_absent_is_noop():
    broker = FrameBroker()
    event_engine = MagicMock()
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
    )

    worker._analyze_behavior(_tracked_at([[10, 10, 50, 50]], [1]), captured_at=0.0, processed_at=0.0)

    event_engine.emit_behavior.assert_not_called()


def TEST_behavior_failure_does_not_kill_thread():
    broker = FrameBroker()
    event_engine = MagicMock()
    behavior = MagicMock()
    behavior.analyze.side_effect = RuntimeError("boom")
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
        behavior=behavior,
    )

    worker._analyze_behavior(_tracked_at([[10, 10, 50, 50]], [1]), captured_at=0.0, processed_at=0.0)

    assert worker._exceptions == 1
    event_engine.emit_behavior.assert_not_called()


def TEST_behavior_zone_membership_snapshot_reuses_zone_states():
    import json

    worker = _worker_for_zones()
    worker.set_zones([
        {"id": "z1", "name": "Z1", "enabled": True,
         "polygon_json": json.dumps([[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]])},
        {"id": "z2", "name": "Z2", "enabled": True,
         "polygon_json": json.dumps([[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]])},
    ])
    shape = (720, 1280, 3)

    worker._update_zones_and_heat(
        _tracked_at([[300, 100, 340, 400], [940, 100, 980, 400]], [1, 2]), shape
    )

    assert worker._zone_membership_snapshot() == {"z1": {1}, "z2": {2}}


# ─── El BehaviorAnalyzer sobrevive a un reinicio del worker por el supervisor ─
def TEST_behavior_analyzer_survives_worker_restart():
    """El analizador se construye FUERA de _make_detection (manager.py): un
    reinicio del worker (el supervisor la re-ejecuta) no debe borrar las
    anclas y latches ya acumulados -- eso produciria una rafaga de eventos
    duplicados en el frame siguiente. Mismo motivo que la FSM de identidad
    (Fase 24) y la galeria de apariencia (Fase 25)."""
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline("cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock())

    factory = pipeline.supervisor._entries["detector"].factory
    worker1 = factory()
    analyzer = pipeline.behavior
    assert analyzer is not None
    assert worker1._behavior is analyzer

    worker2 = factory()
    assert worker2 is not worker1
    assert pipeline.behavior is analyzer     # misma instancia, no una nueva
    assert worker2._behavior is analyzer


# ─── behavior_enabled=False deja el pipeline sin analizador ─────────────────
def TEST_behavior_disabled_leaves_pipeline_without_analyzer():
    """Con behavior_enabled=False no se construye BehaviorAnalyzer y el
    worker sigue siendo funcional (via de comportamiento no-op)."""
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline(
        "cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock(), behavior_enabled=False
    )

    assert pipeline.behavior is None

    factory = pipeline.supervisor._entries["detector"].factory
    worker = factory()
    assert worker is not None
    assert worker._behavior is None


# ─── Los umbrales configurados llegan al analizador de punta a punta ────────
def TEST_behavior_thresholds_reach_the_analyzer():
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline(
        "cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock(),
        crowd_threshold=3, loiter_secs=7.0, immobile_radius_px=11.0,
    )

    assert pipeline.behavior is not None
    assert pipeline.behavior._crowd_threshold == 3
    assert pipeline.behavior._loiter_secs == 7.0
    assert pipeline.behavior._immobile_radius_px == 11.0
