"""Tests for Phase 9: face recognition, enrolment, and person-name tracking."""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import pytest_asyncio
import supervision as sv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module
from backend.recognizer import PersonRecognizer
from backend.tracker import PersonTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_detections(tracker_ids: list[int]) -> sv.Detections:
    n = len(tracker_ids)
    xyxy = np.array([[i * 100, 100, i * 100 + 50, 300] for i in range(n)], dtype=np.float32)
    det = sv.Detections(
        xyxy=xyxy,
        confidence=np.ones(n, dtype=np.float32) * 0.9,
        class_id=np.zeros(n, dtype=int),
    )
    det.tracker_id = np.array(tracker_ids)
    return det


# ---------------------------------------------------------------------------
# Tracker — tracker_id in crossing events
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker():
    return PersonTracker(start=sv.Point(0, 360), end=sv.Point(1280, 360))


# ─── El evento de cruce IN incluye el tracker_id de la persona ───────────────
# _drain_events en main.py usa tracker_id para buscar el nombre de la persona
# en _person_cache. Si el evento no lleva tracker_id, la persona cruzaría
# como anónima aunque haya sido reconocida, perdiéndose el vínculo nombre-cruce.
# ─────────────────────────────────────────────────────────────────────────────
def test_crossing_in_includes_tracker_id(tracker):
    """IN crossing event must carry the tracker_id of the crossing person."""
    det = _fake_detections([7])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert len(crossings) == 1
    assert crossings[0]["tracker_id"] == 7
    assert crossings[0]["direction"] == "in"


# ─── El evento de cruce OUT incluye el tracker_id de la persona ──────────────
# Análogo al test anterior para la dirección OUT. Valida que el campo
# tracker_id se propaga correctamente en ambas direcciones de cruce,
# no solo en la dirección IN.
# ─────────────────────────────────────────────────────────────────────────────
def test_crossing_out_includes_tracker_id(tracker):
    """OUT crossing event must carry the tracker_id of the crossing person."""
    det = _fake_detections([42])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([False]), np.array([True]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert len(crossings) == 1
    assert crossings[0]["tracker_id"] == 42
    assert crossings[0]["direction"] == "out"


# ─── Sin cruce de línea no se generan eventos ─────────────────────────────────
# Si LineZone.trigger devuelve False para todos los IDs (personas en escena
# pero sin cruzar), update() debe devolver lista de cruces vacía. Generar
# eventos falsos inflaría los contadores y la BD de forma incorrecta.
# ─────────────────────────────────────────────────────────────────────────────
def test_no_crossing_produces_no_events(tracker):
    """When nobody crosses, crossing list is empty."""
    det = _fake_detections([1, 2])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([False, False]), np.array([False, False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert crossings == []


# ─── El mismo tracker_id no puede generar dos eventos de cruce ───────────────
# _crossed_ids es un set que deduplica IDs ya contados. Si el mismo ID
# pudiera disparar múltiples eventos, una persona que permanece en escena
# incrementaría el contador indefinidamente en cada frame.
# Se llama update() dos veces con el mismo ID cruzando; solo el primer
# update debe producir un cruce.
# ─────────────────────────────────────────────────────────────────────────────
def test_same_tracker_id_not_counted_twice(tracker):
    """The same tracker_id cannot generate two crossing events."""
    det = _fake_detections([5])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, c1 = tracker.update(sv.Detections.empty())
        _, c2 = tracker.update(sv.Detections.empty())

    assert len(c1) == 1
    assert len(c2) == 0


# ---------------------------------------------------------------------------
# Database — person_name column
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def isolated_db(tmp_path):
    """Swap the global engine/session factory for an isolated temp DB."""
    db_file = tmp_path / "test_events.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    await db_module.init_db()
    yield

    db_module._engine, db_module._session_factory = orig_engine, orig_sf
    await engine.dispose()


# ─── insert_event persiste el nombre de persona en BD ────────────────────────
# Cuando un cruce se asocia a una persona reconocida, su nombre se guarda en
# la columna events.person_name. Este test verifica el round-trip completo:
# insert → query → valor recuperado correctamente.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_insert_event_stores_person_name(isolated_db):
    """insert_event persists person_name when provided."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0), "Alice")
    events = await db_module.get_recent_events(10)
    assert events[0]["person_name"] == "Alice"


# ─── insert_event acepta person_name=None para cruces anónimos ───────────────
# La mayoría de cruces serán de personas no reconocidas (face_recognition no
# disponible o cara no enrolada). La columna person_name es nullable y debe
# almacenarse como NULL en SQLite, no como la cadena "None".
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_insert_event_person_name_nullable(isolated_db):
    """insert_event accepts None person_name (anonymous crossing)."""
    await db_module.insert_event("out", datetime.datetime(2026, 1, 1, 12, 0), None)
    events = await db_module.get_recent_events(10)
    assert events[0]["person_name"] is None


# ─── get_recent_events incluye la clave person_name en cada dict ─────────────
# El WebSocket broadcast y el endpoint /api/events acceden a person_name
# por clave. Si la clave no existe en el dict devuelto por get_recent_events,
# el JSON del WebSocket no incluiría ese campo y el frontend no podría
# mostrar el nombre de la persona detectada.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_recent_events_includes_person_name_key(isolated_db):
    """Every event dict returned by get_recent_events has a 'person_name' key."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0))
    events = await db_module.get_recent_events(10)
    assert "person_name" in events[0]


# ─── init_db es idempotente: llamarlo dos veces no lanza excepción ────────────
# init_db ejecuta ALTER TABLE para añadir columnas nuevas (person_name,
# is_intrusion). En una BD existente esas columnas ya existen y el ALTER
# lanzaría OperationalError. El bloque try/except en init_db lo captura.
# Este test simula una migración sobre una BD ya inicializada.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_migration_adds_column_to_existing_db(tmp_path):
    """init_db is idempotent — calling it twice does not raise."""
    db_file = tmp_path / "migrate.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    try:
        await db_module.init_db()
        await db_module.init_db()  # second call must not raise
    finally:
        db_module._engine, db_module._session_factory = orig_engine, orig_sf
        await engine.dispose()


# ---------------------------------------------------------------------------
# PersonRecognizer — enroll_named_face
# ---------------------------------------------------------------------------


def _make_mock_fr(face_found: bool = True, distance: float = 0.8, encoding=None):
    enc = encoding if encoding is not None else np.random.rand(128).astype(np.float64)
    m = MagicMock()
    m.face_locations.return_value = [(0, 50, 50, 0)] if face_found else []
    m.face_encodings.return_value = [enc] if face_found else []
    m.face_distance.return_value = np.array([distance])
    return m, enc


# ─── Sin cara detectada en la imagen: devuelve None ──────────────────────────
# Si face_locations no encuentra ninguna cara en el frame o la imagen subida,
# enroll_named_face debe devolver None sin registrar ninguna persona ni
# lanzar excepción. El endpoint /api/enroll_face responderá con 422.
# ─────────────────────────────────────────────────────────────────────────────
def test_enroll_named_face_no_face_returns_none(tmp_path):
    """Returns None when no face is detected in the provided image."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    mock_fr, _ = _make_mock_fr(face_found=False)
    with patch("backend.recognizer.fr", mock_fr):
        result = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Bob")
    assert result is None


# ─── Primera enrolación: crea persona nueva con ID positivo ──────────────────
# Cuando no hay embeddings previos (o la distancia supera TOLERANCE=0.55),
# _register() inserta una nueva fila en persons y devuelve su id autoincremental.
# Se verifica que el ID es positivo y que list_persons() incluye el nombre.
# ─────────────────────────────────────────────────────────────────────────────
def test_enroll_named_face_registers_new_person(tmp_path):
    """Registers a new person and returns a positive integer ID."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    mock_fr, _ = _make_mock_fr(face_found=True, distance=0.8)
    with patch("backend.recognizer.fr", mock_fr):
        pid = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Carol")
    assert pid is not None and pid > 0
    assert any(p["name"] == "Carol" for p in r.list_persons())


# ─── Re-enrolación: actualiza nombre sin crear duplicado ─────────────────────
# Si la cara ya existe en BD (distancia <= TOLERANCE), enroll_named_face debe
# actualizar el nombre en lugar de crear una segunda entrada. De lo contrario,
# la misma persona aparecería dos veces en el panel de personas reconocidas.
# Se usa el mismo encoding con distancia 0.1 para simular un match seguro.
# ─────────────────────────────────────────────────────────────────────────────
def test_enroll_named_face_updates_existing_person(tmp_path):
    """Renames an existing matched person instead of creating a duplicate."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    enc = np.random.rand(128).astype(np.float64)

    # Register "Dave" (no existing match)
    mock_new = MagicMock()
    mock_new.face_locations.return_value = [(0, 50, 50, 0)]
    mock_new.face_encodings.return_value = [enc]
    mock_new.face_distance.return_value = np.array([0.8])
    with patch("backend.recognizer.fr", mock_new):
        pid1 = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Dave")

    # Rename to "David" — same encoding, low distance → match
    mock_upd = MagicMock()
    mock_upd.face_locations.return_value = [(0, 50, 50, 0)]
    mock_upd.face_encodings.return_value = [enc]
    mock_upd.face_distance.return_value = np.array([0.1])
    with patch("backend.recognizer.fr", mock_upd):
        pid2 = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "David")

    assert pid1 == pid2
    persons = r.list_persons()
    assert any(p["name"] == "David" for p in persons)
    assert not any(p["name"] == "Dave" for p in persons)


# ─── Sin librería face_recognition: devuelve None inmediatamente ─────────────
# En sistemas donde dlib/face_recognition no está instalado (p.ej. CI sin
# compilación de dlib, Raspberry Pi sin wheels), PersonRecognizer._available
# es False. enroll_named_face debe devolver None sin intentar llamar a fr.*,
# lo que causaría NameError o AttributeError.
# ─────────────────────────────────────────────────────────────────────────────
def test_enroll_named_face_unavailable_returns_none(tmp_path):
    """Returns None immediately when face_recognition library is unavailable."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    r._available = False
    result = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Eve")
    assert result is None


# ---------------------------------------------------------------------------
# API — POST /api/enroll_face
# ---------------------------------------------------------------------------

import httpx
from httpx import ASGITransport

import backend.main as main_module


# ─── 503 cuando face_recognition no está disponible ──────────────────────────
# Si recognizer.available es False (librería no instalada), el endpoint debe
# devolver 503 Service Unavailable con un mensaje claro, en lugar de 500 con
# NameError o intentar ejecutar código que no existe.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_enroll_face_503_when_recognizer_unavailable():
    """Returns 503 when the recognizer reports the library is not installed."""
    mock_stream = MagicMock()
    mock_stream._recognizer = MagicMock()
    mock_stream._recognizer.available = False

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Test", "use_current_frame": "true"})

    assert resp.status_code == 503


# ─── 422 cuando no se detecta cara en la imagen ──────────────────────────────
# enroll_named_face devuelve None si face_locations no encuentra ninguna cara.
# El endpoint debe traducir ese None en un 422 Unprocessable Entity con mensaje
# descriptivo, para que el usuario sepa que debe usar una imagen con cara visible.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_enroll_face_422_when_no_face_detected():
    """Returns 422 when enroll_named_face finds no face in the image."""
    mock_stream = MagicMock()
    mock_stream._recognizer = MagicMock()
    mock_stream._recognizer.available = True
    mock_stream.get_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_stream._recognizer.enroll_named_face = MagicMock(return_value=None)

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Ghost", "use_current_frame": "true"})

    assert resp.status_code == 422


# ─── 200 con person_id y name en enrolación exitosa ──────────────────────────
# Cuando enroll_named_face devuelve un ID válido, el endpoint debe responder
# con 200 y un JSON que incluya person_id y name. El frontend usa estos valores
# para actualizar el panel de personas sin necesidad de recargar la página.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_enroll_face_success_returns_person_id():
    """Returns 200 with person_id and name on successful enrolment."""
    mock_stream = MagicMock()
    mock_stream._recognizer = MagicMock()
    mock_stream._recognizer.available = True
    mock_stream.get_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_stream._recognizer.enroll_named_face = MagicMock(return_value=3)

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Frank", "use_current_frame": "true"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["person_id"] == 3
    assert body["name"] == "Frank"
