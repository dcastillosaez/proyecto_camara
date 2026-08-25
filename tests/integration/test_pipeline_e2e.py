"""Test de integracion del pipeline completo (Fase 34, TEST-01).

FakeRTSP (cv2.VideoCapture parcheado, fixture `mock_video_capture` de
tests/conftest.py) -> CaptureWorker real -> DetectionWorker real con un
detector FALSO (sin YOLO/GPU) -> PersonTracker real (ByteTrack) ->
TrackRegistry -> EventEngine -> EventBus -> make_event_pipeline() real
(RuleEngine -> INSERT en SQLite -> broadcast WebSocket), exactamente el
mismo cableado que backend/main.py:lifespan pero sin camara real ni
servidor HTTP. Ejecutable en CI (ver .github/workflows/tests.yml).
"""

from __future__ import annotations

import asyncio
import datetime

import numpy as np
import pytest_asyncio
import supervision as sv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.events.actions import ActionRegistry
from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.rules import Rule, RuleEngine, When
from backend.events.types import EventType
from backend.main import make_event_pipeline
from backend.pipeline.manager import CameraPipeline
from backend.storage import models
from backend.storage.repositories import EventRepo
from backend.tracker import PersonTracker


class _FakeDetector:
    """Sustituye a PersonDetector (YOLO): misma interfaz (detect_sv), sin modelo real."""

    def __init__(self) -> None:
        self.calls = 0

    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        self.calls += 1
        return sv.Detections(
            xyxy=np.array([[100.0, 100.0, 200.0, 300.0]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([0]),
        )


class _EmptyDetector:
    """Nunca detecta nada -- control negativo (ningun evento debe emitirse)."""

    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        return sv.Detections.empty()


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> None:
    """Sondea predicate() hasta que sea verdadero o lance AssertionError por timeout."""
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condicion no cumplida en {timeout}s")


@pytest_asyncio.fixture
async def event_repo(tmp_path):
    """Misma base temporal que tests/test_event_bus.py -- SQLite real, no mock."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pipeline_e2e.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield EventRepo(sf)
    await engine.dispose()


def _make_pipeline(detector) -> CameraPipeline:
    loop = asyncio.get_running_loop()
    bus = EventBus(loop=loop)
    event_engine = EventEngine(bus, camera_id="cam1")
    pipeline = CameraPipeline(
        "cam1", "rtsp://fake-source", detector=detector, tracker=PersonTracker(frame_rate=15),
        event_engine=event_engine, detection_fps=(30.0, 30.0, 30.0),
    )
    return pipeline, bus, event_engine


async def TEST_full_chain_persists_and_broadcasts_person_entered(mock_video_capture, event_repo):
    """FakeRTSP -> detector mock -> tracker real -> EventEngine -> bus -> RuleEngine
    -> INSERT -> WebSocket, sin camara real ni YOLO (TEST-01, criterio 1 de la Fase 34)."""
    pipeline, bus, _ = _make_pipeline(_FakeDetector())

    rule = Rule(name="Persona detectada", when=When(event=EventType.PERSON_ENTERED),
                actions=[], enabled=True, debounce_secs=0)
    rule_engine = RuleEngine([rule], registry=ActionRegistry())

    broadcasted: list = []

    async def _capture_broadcast(event):
        broadcasted.append(event)

    bus.subscribe("event_pipeline", make_event_pipeline(
        event_repo, rule_engine,
        broadcast_event=_capture_broadcast, broadcast_v2=_capture_broadcast,
        broadcast_v1=_capture_broadcast,
    ))

    pipeline.start()
    try:
        await _wait_until(lambda: len(broadcasted) > 0)
    finally:
        pipeline.stop()

    event = broadcasted[0]
    assert event.type == EventType.PERSON_ENTERED
    assert event.camera_id == "cam1"
    assert event.payload["rules"] == ["Persona detectada"]

    stored = await event_repo.get(event.id)
    assert stored is not None
    assert stored.type == EventType.PERSON_ENTERED


async def TEST_full_chain_without_detections_emits_no_events(mock_video_capture, event_repo):
    """Control negativo: sin detecciones, ningun PERSON_ENTERED cruza la cadena
    (evita que el arnes de test de un falso positivo permanente)."""
    pipeline, bus, _ = _make_pipeline(_EmptyDetector())
    rule_engine = RuleEngine([], registry=ActionRegistry())

    broadcasted: list = []

    async def _capture_broadcast(event):
        broadcasted.append(event)

    bus.subscribe("event_pipeline", make_event_pipeline(
        event_repo, rule_engine,
        broadcast_event=_capture_broadcast, broadcast_v2=_capture_broadcast,
        broadcast_v1=_capture_broadcast,
    ))

    pipeline.start()
    try:
        await asyncio.sleep(0.5)  # varios ciclos de deteccion a 30 fps objetivo
    finally:
        pipeline.stop()

    assert broadcasted == []
