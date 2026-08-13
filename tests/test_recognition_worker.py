"""Tests for backend.pipeline.recognition.RecognitionWorker — reconocimiento con ritmo propio."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.types import EventType
from backend.perception.face.identity import IdentityState, IdentityStateMachine, TemporalVoter
from backend.pipeline.broker import Frame, FrameBroker
from backend.pipeline.rate import AdaptiveRate
from backend.pipeline.recognition import RecognitionWorker
from backend.pipeline.tracking import TrackRegistry
from backend.recognizer import FaceResult


def _make_frame(seq: int) -> Frame:
    return Frame(
        camera_id="cam1", seq=seq, captured_at=time.monotonic(),
        wall_clock=datetime.now(), image=np.zeros((360, 640, 3), dtype=np.uint8),
    )


class _FakeTracked:
    def __init__(self, ids: list[int]):
        self.tracker_id = np.array(ids)
        n = len(ids)
        self.xyxy = np.array([[10, 10, 80, 200]] * n, dtype=float)
        self.confidence = np.full(n, 0.9)


def _publish_for(broker: FrameBroker, seconds: float, interval: float = 0.02) -> None:
    deadline = time.time() + seconds
    seq = 0
    while time.time() < deadline:
        broker.publish(_make_frame(seq))
        seq += 1
        time.sleep(interval)


def _face(person_id=None, name=None, is_new=False, score=0.0, ambiguous=False) -> FaceResult:
    return FaceResult(person_id, name, is_new, score, ambiguous)


def make_engine():
    """Mismo patron que tests/test_event_engine.py: EventBus real sobre el loop
    en marcha + un subscriptor que acumula los eventos recibidos."""
    bus = EventBus(loop=asyncio.get_event_loop())
    received: list = []

    async def capture(event):
        received.append(event)

    bus.subscribe("capture", capture)
    engine = EventEngine(bus, camera_id="cam1")
    return engine, received


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condition not met within {timeout}s")


@pytest.fixture
def broker():
    return FrameBroker()


# ─── Respeta el FPS objetivo de reconocimiento ──────────────────────────────
def test_recognition_respects_target_fps(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop_scored.return_value = _face()  # nunca identifica

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=3.0, min_fps=3.0, max_fps=3.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=1.0)   # ~50 FPS de publicacion
    worker.stop()

    # a 3 FPS objetivo durante ~1 s: ni 1 ni 50
    assert 1 <= recognizer.process_crop_scored.call_count <= 8


# ─── Los tracks ya identificados no se reprocesan ───────────────────────────
def test_recognition_skips_identified_tracks(broker):
    registry = TrackRegistry()
    now = time.monotonic()
    registry.update_from_detections(_FakeTracked([1]), now=now - 10)
    registry.set_identity(1, person_id=42, name="David")

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop_scored.return_value = _face()

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=0.6)
    worker.stop()

    recognizer.process_crop_scored.assert_not_called()


# ─── Al identificar, escribe la identidad en el registry ────────────────────
def test_recognition_sets_identity_on_match(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop_scored.return_value = _face(42, "David")

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    deadline = time.time() + 2.0
    while time.time() < deadline and registry.get(1).person_id is None:
        broker.publish(_make_frame(0))
        time.sleep(0.03)
    worker.stop()

    ts = registry.get(1)
    assert ts.person_id == 42
    assert ts.person_name == "David"


# ─── Una excepcion del reconocedor no mata al worker ────────────────────────
def test_recognition_failure_does_not_kill_worker(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    calls = {"n": 0}

    def _flaky(crop, tid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return _face()

    recognizer.process_crop_scored.side_effect = _flaky

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=1.0, interval=0.05)
    alive = worker._thread.is_alive()
    worker.stop()

    assert calls["n"] >= 2   # sobrevivio a la excepcion
    assert alive


# ─── La cache del reconocedor se limpia cuando expiran tracks ───────────────
def test_recognition_prunes_cache_on_track_expiry(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop_scored.return_value = _face()

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=12.0, min_fps=12.0, max_fps=12.0)
    worker = RecognitionWorker(
        sub, registry, recognizer, rate, min_track_age=0.0, prune_interval=0.05
    )
    worker.start()

    _publish_for(broker, seconds=0.4, interval=0.03)
    # el track 1 desaparece del registry (expirado por el DetectionWorker)
    registry.prune(now=time.monotonic() + 1000, ttl=1.0)
    _publish_for(broker, seconds=0.4, interval=0.03)
    worker.stop()

    recognizer.prune.assert_called()
    last_active = recognizer.prune.call_args.args[0]
    assert 1 not in last_active   # el track expirado ya no esta en el set activo


# ─── Sin reconocedor disponible, el worker no hace nada ─────────────────────
def test_unavailable_recognizer_is_noop(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = False

    sub = broker.subscribe("recognition")
    worker = RecognitionWorker(
        sub, registry, recognizer, AdaptiveRate(), min_track_age=0.0
    )
    worker.start()
    _publish_for(broker, seconds=0.3, interval=0.03)
    worker.stop()

    recognizer.process_crop_scored.assert_not_called()


# ─── D-05: recuperar un track por la ruta real no duplica el reconocimiento ──
# Reproduce el bug que active_ids() (TTL=30s) producia: sin frame_ids(), un
# track_id nuevo reapareciendo antes del TTL global confirmaria como visita
# nueva porque el track viejo seguia "activo" en la FSM. Aqui se pasa por
# TrackRegistry real + _sync_identity real, no por on_track_lost() directo.
# ───────────────────────────────────────────────────────────────────────────
async def TEST_track_recovery_via_real_path_emits_person_recognized_once(broker):
    registry = TrackRegistry()
    recognizer = MagicMock()
    recognizer.available = True
    # El mock solo "reconoce cara" del track activo en cada fase: una persona
    # ocluida no deja un crop reconocible, igual que en produccion.
    match_track = {"id": 1}

    def _scored(crop, track_id):
        if track_id == match_track["id"]:
            return _face(7, "Juan", score=0.8)
        return _face()

    recognizer.process_crop_scored.side_effect = _scored

    fsm = IdentityStateMachine(TemporalVoter(window=3, min_votes=3), lost_ttl=30.0)
    engine, received = make_engine()
    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=20.0, min_fps=20.0, max_fps=20.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0,
                               identity_fsm=fsm, event_engine=engine)
    worker.start()

    # Track 1 aparece y se confirma (3 votos coherentes).
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic())
    registry.set_frame_ids({1})
    _publish_for(broker, seconds=0.3)
    await wait_until(lambda: fsm.state_of(1) is IdentityState.CONFIRMED, timeout=2.0)

    # Track 1 desaparece del frame (oclusion): _sync_identity real lo marca
    # perdido, y el mock deja de "verle" cara (nadie coincide con match_track).
    match_track["id"] = None
    registry.set_frame_ids(set())
    _publish_for(broker, seconds=0.2)
    await wait_until(lambda: fsm.state_of(1) is IdentityState.TEMPORARILY_LOST, timeout=2.0)

    # El TrackRegistry termina soltando el track viejo (lo que haria
    # DetectionWorker.prune() pasado su ttl) -- sin esto seguiria ganando el
    # turno de inferencia sobre el track nuevo por ser el mas antiguo.
    registry.prune(now=time.monotonic(), ttl=0.01)

    # Reaparece con un track_id NUEVO (como haria ByteTrack), misma persona.
    match_track["id"] = 99
    registry.update_from_detections(_FakeTracked([99]), now=time.monotonic())
    registry.set_frame_ids({99})
    _publish_for(broker, seconds=0.3)
    await wait_until(
        lambda: registry.get(99) is not None
        and registry.get(99).identity_state is IdentityState.CONFIRMED,
        timeout=2.0,
    )

    worker.stop()
    # wait_until puede salir sin haber cedido el control al loop ni una sola
    # vez si el predicado ya era cierto en la primera comprobacion (aqui, tras
    # los _publish_for bloqueantes, es lo habitual) -- sin este respiro el
    # EventBus nunca llega a drenar la cola hacia `received`.
    await asyncio.sleep(0.1)
    recognized = [e for e in received if e.type is EventType.PERSON_RECOGNIZED]
    assert len(recognized) == 1, (
        f"se esperaba 1 PERSON_RECOGNIZED, hubo {len(recognized)} -- "
        "el track nuevo confirmo como visita nueva en vez de heredar la identidad"
    )
