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
from backend.perception.objects import ObjectAnalyzer, ObjectFinding, ObjectKind
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


def _tracked_cls(boxes, tids, class_ids, names=None) -> sv.Detections:
    """Variante de _tracked_at con class_id REAL y data["class_name"].

    Los helpers existentes ponen class_id a ceros, asi que no sirven para probar la
    particion por clase: todo pareceria persona.
    """
    det = sv.Detections(
        xyxy=np.array(boxes, dtype=float),
        confidence=np.ones(len(tids)),
        class_id=np.array(class_ids, dtype=int),
        data={"class_name": np.array(names or [str(c) for c in class_ids])},
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


# ─── Regresion: ByteTrack no es class-aware (Fase 27, 27-RESEARCH.md Q4) ─────
# El tensor que entra al matcher se construye solo con xyxy y confidence
# (supervision/tracker/byte_tracker/core.py:104-110) y el reensamblado del
# tracker_id es una asignacion humgara por IoU con umbral 0,5. El research
# reprodujo que un track de mochila le TRANSFIERE su id a una persona colocada
# casi en la misma caja. Sin la particion por clase, activar "car" haria que los
# vehiculos sumaran al conteo de linea de la Fase 4 — que esta en produccion —,
# RecognitionWorker buscaria caras en mochilas y accumulate_detections
# contaminaria detection_stats, que es la fuente del baseline de BEH-09.
# Estos tests son la barrera que impide que eso vuelva a ser posible.
# ───────────────────────────────────────────────────────────────────────────
def TEST_object_class_does_not_reach_line_zone():
    from backend.tracker import PersonTracker

    worker = _worker_for_zones()
    line_start, line_end = sv.Point(0, 300), sv.Point(640, 300)
    # Pasos de 10px: ByteTrack matchea por IoU (umbral 0,8) entre frames, asi que
    # saltos grandes de posicion perderian el tracker_id y falsearia el test.
    person_ys = list(range(230, 340, 10))  # cruza y=300 hacia abajo

    # Escenario A: persona cruzando la linea, con un coche solapado cada frame
    tracker_a = PersonTracker(line_start, line_end, frame_rate=15)
    for y in person_ys:
        mixed = _tracked_cls(
            boxes=[[300, y, 340, y + 60], [10, 10, 60, 60]],
            tids=[1, 2], class_ids=[0, 2], names=["person", "car"],
        )
        person_dets, _ = worker._split_by_class(mixed)
        tracker_a.update(person_dets)

    # Escenario B: la misma persona, sin ningun coche en la entrada
    tracker_b = PersonTracker(line_start, line_end, frame_rate=15)
    for y in person_ys:
        person_only = _tracked_cls([[300, y, 340, y + 60]], [1], [0], names=["person"])
        tracker_b.update(person_only)

    assert tracker_a.get_counts() == tracker_b.get_counts()
    assert tracker_a.get_counts()["total"] >= 1  # confirma que la linea SI se cruzo


def TEST_objects_not_in_registry():
    from backend.tracker import ObjectTracker, PersonTracker

    broker = FrameBroker()
    person_tracker = PersonTracker(sv.Point(0, 300), sv.Point(640, 300), frame_rate=15)
    object_tracker = ObjectTracker(frame_rate=15)
    registry = TrackRegistry()
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), person_tracker, registry, AdaptiveRate(),
        object_tracker=object_tracker, object_class_ids={2},
    )

    mixed = _tracked_cls(
        boxes=[[300, 200, 340, 260], [500, 200, 540, 260], [10, 10, 60, 60]],
        tids=[1, 2, 3], class_ids=[0, 0, 2], names=["person", "person", "car"],
    )
    person_dets, object_dets = worker._split_by_class(mixed)
    tracked, _ = person_tracker.update(person_dets)
    obj_tracked = object_tracker.update(object_dets)

    now = time.monotonic()
    registry.update_from_detections(tracked, now)
    worker._emit_track_lifecycle(tracked, captured_at=0.0, processed_at=now)
    worker._update_object_boxes(obj_tracked)

    assert len(tracked) == 2  # solo las 2 personas llegaron al tracker de personas
    assert registry.frame_ids() == {int(tid) for tid in tracked.tracker_id}
    assert len(registry.snapshot()) == 2  # el coche NUNCA entra en el registry
    assert len(worker.get_object_boxes()) == 1
    assert worker.get_object_boxes()[0]["class_name"] == "car"


def TEST_bytetrack_ids_do_not_migrate_between_classes():
    """El test que reproduce el hallazgo (27-RESEARCH.md Q4): sv.ByteTrack construye
    el tensor del matcher solo con xyxy y confidence
    (supervision/tracker/byte_tracker/core.py:104-110), asi que sin particion por
    clase el id de un track de mochila "perdido" puede reasignarse a una persona que
    aparece casi en la misma caja (reasignacion humgara con umbral IoU 0,5).

    El punto NO es que los ids sean numeros concretos (ambos ByteTrack empiezan en
    1 de forma independiente) sino que el tracker de personas nunca procesa la caja
    de la mochila: su primer id nace en el frame en el que aparece la persona, no se
    hereda de otro track.
    """
    from backend.tracker import ObjectTracker, PersonTracker

    backpack_box = [300, 300, 400, 500]
    person_box = [300, 305, 405, 505]  # solapa fuertemente con la mochila

    # --- Reproduccion del bug: un unico ByteTrack para las dos clases ---------
    shared = sv.ByteTrack(lost_track_buffer=60, frame_rate=15)
    out = None
    for _ in range(5):
        out = shared.update_with_detections(
            _tracked_cls([backpack_box], [1], [24], names=["backpack"])
        )
    backpack_id = int(out.tracker_id[0])
    # la mochila desaparece; en su lugar llega una persona casi en la misma caja
    reassigned = shared.update_with_detections(
        _tracked_cls([person_box], [1], [0], names=["person"])
    )
    assert int(reassigned.tracker_id[0]) == backpack_id  # bug reproducido

    # --- Con la particion de la Fase 27: dos ByteTrack independientes ---------
    object_tracker = ObjectTracker(frame_rate=15)
    for _ in range(5):
        object_tracker.update(_tracked_cls([backpack_box], [1], [24], names=["backpack"]))

    person_tracker = PersonTracker(sv.Point(0, 5000), sv.Point(1, 5001), frame_rate=15)
    assert len(person_tracker._byte_tracker.tracked_tracks) == 0  # nunca vio nada aun
    tracked, _ = person_tracker.update(
        _tracked_cls([person_box], [1], [0], names=["person"])
    )

    assert tracked.tracker_id is not None
    assert int(tracked.tracker_id[0]) == 1  # nace en este frame: sin historia que heredar
    assert object_tracker._byte_tracker is not person_tracker._byte_tracker


def TEST_split_by_class_preserves_class_name():
    worker = _worker_for_zones()
    worker.set_object_classes({24})
    mixed = _tracked_cls(
        boxes=[[10, 10, 50, 50], [100, 100, 140, 140]],
        tids=[1, 2], class_ids=[0, 24], names=["person", "backpack"],
    )

    person_dets, object_dets = worker._split_by_class(mixed)

    assert list(person_dets.data["class_name"]) == ["person"]
    assert list(object_dets.data["class_name"]) == ["backpack"]


def TEST_sync_frame_rate_reaches_both_trackers():
    broker = FrameBroker()
    tracker = MagicMock()
    object_tracker = MagicMock()
    rate = MagicMock()
    rate.effective_fps = 6.0
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), tracker, TrackRegistry(), rate,
        object_tracker=object_tracker,
    )

    worker._sync_tracker_frame_rate()

    tracker.set_frame_rate.assert_called_once_with(6.0)
    object_tracker.set_frame_rate.assert_called_once_with(6.0)


def TEST_no_object_classes_behaves_like_today():
    worker = _worker_for_zones()  # object_tracker=None, object_class_ids vacio por defecto
    sv_dets = _tracked_cls(
        boxes=[[10, 10, 50, 50], [60, 60, 100, 100]],
        tids=[1, 2], class_ids=[0, 0], names=["person", "person"],
    )

    person_dets, object_dets = worker._split_by_class(sv_dets)

    assert len(person_dets) == len(sv_dets)
    assert len(object_dets) == 0
    assert worker._object_tracker is None


def TEST_object_boxes_snapshot_is_a_copy():
    worker = _worker_for_zones()
    obj_tracked = _tracked_cls([[10, 10, 50, 50]], [1], [24], names=["backpack"])
    worker._update_object_boxes(obj_tracked)

    snap = worker.get_object_boxes()
    snap[0]["class_name"] = "mutated"

    assert worker.get_object_boxes()[0]["class_name"] == "backpack"


# ─── Cableado del ObjectAnalyzer en el hilo de deteccion (Fase 27, BEH-07) ───

def TEST_object_left_emitted_from_worker():
    broker = FrameBroker()
    event_engine = MagicMock()
    analyzer = ObjectAnalyzer(left_secs=1.0, warmup_secs=0.0, gone_secs=0.5)
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
        objects=analyzer,
    )
    no_persons = sv.Detections.empty()
    obj_tracked = _tracked_cls([[10, 10, 50, 50]], [1], [24], names=["backpack"])

    worker._analyze_objects(obj_tracked, no_persons, captured_at=0.0, processed_at=0.0)
    worker._analyze_objects(obj_tracked, no_persons, captured_at=1.5, processed_at=1.5)

    event_engine.emit_object.assert_called()
    finding = event_engine.emit_object.call_args[0][0]
    assert finding.kind == ObjectKind.LEFT


def TEST_object_analysis_failure_does_not_kill_thread():
    broker = FrameBroker()
    event_engine = MagicMock()
    objects = MagicMock()
    objects.analyze.side_effect = RuntimeError("boom")
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
        objects=objects,
    )
    obj_tracked = _tracked_cls([[10, 10, 50, 50]], [1], [24], names=["backpack"])

    worker._analyze_objects(obj_tracked, sv.Detections.empty(), captured_at=0.0, processed_at=0.0)

    assert worker._exceptions == 1
    event_engine.emit_object.assert_not_called()


def TEST_object_prune_findings_are_emitted():
    """Protege contra ignorar el retorno de prune(): OBJECT_REMOVED se decide ahi."""
    broker = FrameBroker()
    event_engine = MagicMock()
    objects = MagicMock()
    objects.analyze.return_value = []
    removed = ObjectFinding(kind=ObjectKind.REMOVED, track_id=1, class_name="backpack")
    objects.prune.return_value = [removed]
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
        objects=objects,
    )
    obj_tracked = _tracked_cls([[10, 10, 50, 50]], [1], [24], names=["backpack"])

    worker._analyze_objects(obj_tracked, sv.Detections.empty(), captured_at=0.0, processed_at=0.0)

    event_engine.emit_object.assert_called_once()
    finding = event_engine.emit_object.call_args[0][0]
    assert finding is removed
    assert finding.kind == ObjectKind.REMOVED


def TEST_excluded_zone_suppresses_object_candidate():
    import json

    worker = _worker_for_zones()
    event_engine = MagicMock()
    worker._event_engine = event_engine
    objects = MagicMock()
    objects.analyze.return_value = []
    objects.prune.return_value = []
    worker._objects = objects
    worker.set_zones([{
        "id": "zex", "name": "Exclusion", "kind": "exclude_objects", "enabled": True,
        "polygon_json": json.dumps([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
    }])
    worker._update_zones_and_heat(sv.Detections.empty(), (360, 640, 3))
    obj_tracked = _tracked_cls([[10, 10, 50, 50]], [1], [24], names=["backpack"])

    worker._analyze_objects(obj_tracked, sv.Detections.empty(), captured_at=0.0, processed_at=0.0)

    observations = objects.analyze.call_args[0][0]
    assert observations[0].excluded is True


# ─── ObjectAnalyzer y ObjectTracker sobreviven a un reinicio del worker ──────
# Se construyen FUERA de _make_detection (manager.py): el supervisor re-ejecuta
# la factoria en cada reinicio y construirlos dentro borraria anclas, latches, la
# marca de arranque y el contador de ids de objeto. Consecuencia concreta: la
# ventana de warmup se reabriria, todo el mobiliario fijo volveria a "aparecer" y
# a los 60 s habria una rafaga de OBJECT_LEFT — que es WARNING y por tanto sube
# un clip a Google Drive por cada mueble. Mismo motivo que la FSM de identidad
# (Fase 24), la galeria ReID (Fase 25) y el BehaviorAnalyzer (Fase 26).
# ─────────────────────────────────────────────────────────────────────────────

def TEST_object_analyzer_survives_worker_restart():
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline("cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock())

    factory = pipeline.supervisor._entries["detector"].factory
    worker1 = factory()
    analyzer = pipeline.objects
    assert analyzer is not None
    assert worker1._objects is analyzer

    worker2 = factory()
    assert worker2 is not worker1
    assert pipeline.objects is analyzer      # misma instancia, no una nueva
    assert worker2._objects is analyzer


def TEST_object_tracker_survives_worker_restart():
    """Si el ObjectTracker se reconstruyera, los track_id de objeto volverian a 1 y
    todo el mobiliario "aparecería" otra vez."""
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline("cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock())

    factory = pipeline.supervisor._entries["detector"].factory
    worker1 = factory()
    tracker = pipeline.object_tracker
    assert tracker is not None
    assert worker1._object_tracker is tracker

    worker2 = factory()
    assert worker2 is not worker1
    assert pipeline.object_tracker is tracker  # misma instancia, no una nueva
    assert worker2._object_tracker is tracker


def TEST_objects_disabled_leaves_pipeline_without_analyzer():
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline(
        "cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock(), objects_enabled=False
    )

    assert pipeline.objects is None
    assert pipeline.object_tracker is None

    factory = pipeline.supervisor._entries["detector"].factory
    worker = factory()
    assert worker is not None
    assert worker._objects is None
    assert worker._object_tracker is None


def TEST_set_object_detection_classes_does_not_restart_worker():
    from backend.pipeline.manager import CameraPipeline

    detector = MagicMock()
    pipeline = CameraPipeline("cam1", "rtsp://fake", detector=detector, tracker=MagicMock())
    pipeline.detection = MagicMock()

    pipeline.set_detection_classes([0, 24])

    detector.set_classes.assert_called_once_with([0, 24])
    pipeline.detection.set_object_classes.assert_called_once_with({24})
    pipeline.detection.stop.assert_not_called()
