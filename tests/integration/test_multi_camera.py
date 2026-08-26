"""Test de integracion multi-camara (Fase 35, criterios 1, 4 y 5).

Dos CameraPipeline reales, gestionados por UN CameraManager, contra la MISMA
URL RTSP falsa (mock_video_capture no distingue por URL, cv2.VideoCapture
parcheado devuelve siempre el mismo mock) -- exactamente el escenario del
criterio 4. Mismo cableado que tests/integration/test_pipeline_e2e.py (Fase
34) pero con dos camaras en vez de una, para no duplicar la explicacion del
por-que de cada pieza (detector mock, EventBus, make_event_pipeline real).
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest_asyncio
import supervision as sv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.rules import RuleEngine
from backend.events.actions import ActionRegistry
from backend.events.types import EventType
from backend.main import make_event_pipeline
from backend.pipeline.manager import CameraManager
from backend.storage import models
from backend.storage.repositories import EventRepo
from backend.tracker import PersonTracker

SAME_RTSP_URL = "rtsp://fake-source-shared"


class _FakeDetector:
    """Misma interfaz que backend.detector.PersonDetector (detect_sv), sin YOLO real."""

    def __init__(self) -> None:
        self.calls = 0

    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        self.calls += 1
        return sv.Detections(
            xyxy=np.array([[100.0, 100.0, 200.0, 300.0]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([0]),
        )


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> None:
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condicion no cumplida en {timeout}s")


@pytest_asyncio.fixture
async def event_repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'multi_camera.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))
    yield EventRepo(sf)
    await engine.dispose()


def _make_two_camera_manager() -> tuple[CameraManager, EventBus, dict[str, _FakeDetector]]:
    """CameraManager real con dos pipelines, mismo criterio que
    backend/main.py:lifespan (CameraManager() + N x .add()) pero con
    detectores falsos y contra la MISMA URL RTSP (criterio 4)."""
    loop = asyncio.get_running_loop()
    bus = EventBus(loop=loop)
    manager = CameraManager()
    detectors: dict[str, _FakeDetector] = {}
    for camera_id in ("cam1", "cam2"):
        detector = _FakeDetector()
        detectors[camera_id] = detector
        manager.add(
            camera_id, SAME_RTSP_URL, detector=detector, tracker=PersonTracker(frame_rate=15),
            event_engine=EventEngine(bus, camera_id=camera_id),
            detection_fps=(30.0, 30.0, 30.0),
        )
    return manager, bus, detectors


async def TEST_two_pipelines_same_rtsp_url_produce_distinct_camera_ids(mock_video_capture, event_repo):
    """Criterio 1 (CameraManager gestiona N con arranque independiente) y
    criterio 4 (misma URL RTSP -> camera_id distintos en los eventos)."""
    manager, bus, _ = _make_two_camera_manager()
    rule_engine = RuleEngine([], registry=ActionRegistry())

    broadcasted: list = []

    async def _capture_broadcast(event):
        broadcasted.append(event)

    bus.subscribe("event_pipeline", make_event_pipeline(
        event_repo, rule_engine,
        broadcast_event=_capture_broadcast, broadcast_v2=_capture_broadcast,
        broadcast_v1=_capture_broadcast,
    ))

    manager.start_all()
    try:
        await _wait_until(lambda: {e.camera_id for e in broadcasted} == {"cam1", "cam2"})
    finally:
        manager.stop_all()

    person_entered = [e for e in broadcasted if e.type == EventType.PERSON_ENTERED]
    cam_ids = {e.camera_id for e in person_entered}
    assert cam_ids == {"cam1", "cam2"}

    for camera_id in ("cam1", "cam2"):
        items, _ = await event_repo.query(camera_id=camera_id, limit=50)
        stored = [e for e in items if e.type == EventType.PERSON_ENTERED]
        assert stored, f"ningun PERSON_ENTERED persistido para {camera_id}"
        assert all(e.camera_id == camera_id for e in stored)


async def TEST_stopping_and_restarting_one_camera_does_not_affect_the_other(mock_video_capture, event_repo):
    """Criterio 5 / SCALE-04: parar Y reiniciar una camara no afecta a la otra ni al servidor."""
    manager, bus, detectors = _make_two_camera_manager()
    rule_engine = RuleEngine([], registry=ActionRegistry())

    broadcasted: list = []

    async def _capture_broadcast(event):
        broadcasted.append(event)

    bus.subscribe("event_pipeline", make_event_pipeline(
        event_repo, rule_engine,
        broadcast_event=_capture_broadcast, broadcast_v2=_capture_broadcast,
        broadcast_v1=_capture_broadcast,
    ))

    manager.start_all()
    try:
        await _wait_until(lambda: {e.camera_id for e in broadcasted} == {"cam1", "cam2"})

        cam1_pipeline = manager.get("cam1")
        cam2_pipeline = manager.get("cam2")
        assert cam1_pipeline is not None and cam2_pipeline is not None

        # Parar cam1 no debe lanzar ni afectar a cam2 -- "ni al servidor" se
        # traduce en que este mismo proceso de test sigue vivo y respondiendo.
        cam1_pipeline.stop()

        calls_before = detectors["cam2"].calls
        await asyncio.sleep(0.3)  # varios ciclos mas a 30 fps objetivo
        assert detectors["cam2"].calls > calls_before, "cam2 dejo de procesar frames tras parar cam1"

        # cam1 realmente esta parada: su detector no sigue recibiendo llamadas.
        cam1_calls_after_stop = detectors["cam1"].calls
        await asyncio.sleep(0.3)
        assert detectors["cam1"].calls == cam1_calls_after_stop, "cam1 siguio procesando tras stop()"

        # SCALE-04 tambien pide "reiniciar": start() sobre el mismo objeto tras
        # stop() debe reanudar cam1 sin tocar cam2 en ningun momento.
        cam2_calls_before_restart = detectors["cam2"].calls
        cam1_pipeline.start()
        await _wait_until(lambda: detectors["cam1"].calls > cam1_calls_after_stop)
        assert detectors["cam2"].calls >= cam2_calls_before_restart
    finally:
        manager.stop_all()

    # El propio CameraManager sigue operable tras el stop() individual -- no
    # quedo en un estado que rompa start_all()/stop_all() para el resto.
    assert manager.get("cam2") is not None
