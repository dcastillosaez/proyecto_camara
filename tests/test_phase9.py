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


@pytest.fixture
def tracker():
    return PersonTracker(lines=[{"id": "l1", "name": "Linea 1", "start": sv.Point(0, 360), "end": sv.Point(1280, 360)}])


# ---------------------------------------------------------------------------
# Tracker — tracker_id in crossing events
# ---------------------------------------------------------------------------

# ─── El evento de cruce IN incluye el tracker_id de la persona ───────────────
# _drain_events en main.py usa tracker_id para buscar el nombre de la persona
# en _person_cache. Si el evento no lleva tracker_id, la persona cruzaría
# como anónima aunque haya sido reconocida, perdiéndose el vínculo nombre-cruce.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_054_crossing_in_includes_tracker_id(tracker):
    """IN crossing event must carry the tracker_id of the crossing person."""
    det = _fake_detections([7])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([True]), np.array([False]))),
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
def TEST_055_crossing_out_includes_tracker_id(tracker):
    """OUT crossing event must carry the tracker_id of the crossing person."""
    det = _fake_detections([42])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([False]), np.array([True]))),
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
def TEST_056_no_crossing_produces_no_events(tracker):
    """When nobody crosses, crossing list is empty."""
    det = _fake_detections([1, 2])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._lines[0]["zone"], "trigger", return_value=(np.array([False, False]), np.array([False, False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert crossings == []


# ─── El mismo cruce no puede generar dos eventos ─────────────────────────────
# La deduplicación es responsabilidad de LineZone (guarda el estado de cada
# tracker_id y solo dispara en cambios de estado), no del tracker. Se usa el
# LineZone REAL: una persona cruza la línea y luego permanece quieta al otro
# lado durante varios frames — solo el frame del cruce produce un evento.
# (MEJORAS.md punto 1: _crossed_ids ya no bloquea los contadores direccionales,
# para que una ida y vuelta cuente 'in' Y 'out'.)
# ─────────────────────────────────────────────────────────────────────────────
def TEST_057_same_crossing_not_counted_twice(tracker):
    """A person crossing once and staying in scene yields exactly one event."""
    def det_at(y: int) -> sv.Detections:
        det = sv.Detections(
            xyxy=np.array([[600, y - 100, 700, y + 100]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([0]),
        )
        det.tracker_id = np.array([5])
        return det

    events = []
    # Cruza la línea (y=360) y se queda quieta al otro lado 5 frames
    for y in [200, 300, 500, 500, 500, 500, 500]:
        with patch.object(tracker._byte_tracker, "update_with_detections", return_value=det_at(y)):
            _, crossings = tracker.update(sv.Detections.empty())
        events += crossings

    assert len(events) == 1
    counts = tracker.get_counts()["l1"]
    assert counts["in"] + counts["out"] == 1
    assert counts["total"] == 1


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
async def TEST_058_insert_event_stores_person_name(isolated_db):
    """insert_event persists person_name when provided."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0), "Alice")
    events = await db_module.get_recent_events(10)
    assert events[0]["person_name"] == "Alice"


# ─── insert_event acepta person_name=None para cruces anónimos ───────────────
# La mayoría de cruces serán de personas no reconocidas (face_recognition no
# disponible o cara no enrolada). La columna person_name es nullable y debe
# almacenarse como NULL en SQLite, no como la cadena "None".
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_059_insert_event_person_name_nullable(isolated_db):
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
async def TEST_060_get_recent_events_includes_person_name_key(isolated_db):
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
async def TEST_061_migration_adds_column_to_existing_db(tmp_path):
    """init_db is idempotent — calling it twice does not raise."""
    db_file = tmp_path / "migrate.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    try:
        await db_module.init_db()
        await db_module.init_db()
    finally:
        db_module._engine, db_module._session_factory = orig_engine, orig_sf
        await engine.dispose()


# ─── _blob_to_encoding rechaza blobs de formato legacy (SEC-15) ──────────────
# La Fase 22 elimina el fallback a pickle.loads: cualquier blob que no mida
# exactamente el tamaño esperado (512*4=2048 bytes desde la Fase 23, antes
# 128*8=1024 con dlib) debe lanzar en lugar de deserializarse con pickle.
# scripts/reenroll.py es la única vía soportada para convertir blobs legacy.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_109_blob_to_encoding_rejects_legacy_format(tmp_path):
    """A non-numpy-sized blob raises instead of falling back to pickle.loads."""
    import pickle as _pickle_for_test_fixture_only
    legacy_blob = _pickle_for_test_fixture_only.dumps(np.random.rand(128).astype(np.float64))
    with pytest.raises(ValueError):
        PersonRecognizer._blob_to_encoding(legacy_blob)


# ---------------------------------------------------------------------------
# PersonRecognizer — enroll_named_face
#
# Fase 23: PersonRecognizer.enroll_named_face is exercised against mocked
# FaceEngine/FaceQualityAssessor in tests/test_recognizer_orchestration.py
# (TEST_enroll_named_face_no_face_returns_none/_registers_new_person/
# _updates_existing_person) — the dlib-era versions that used to live here,
# mocking backend.recognizer.fr, are superseded now that fr no longer exists.
# ---------------------------------------------------------------------------


# ─── visit_count solo sube si la última visita es antigua ────────────────────
# Regresión del punto 3 de MEJORAS.md: _touch incrementa visit_count solo si
# last_seen es anterior a VISIT_GAP_MINUTES. Re-matches dentro de la misma
# estancia (ByteTrack pierde y recupera el track) no inflan el contador;
# un avistamiento tras un hueco largo sí cuenta como visita nueva.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_093_visit_count_respects_gap(tmp_path):
    """_touch increments visit_count only after VISIT_GAP_MINUTES of absence."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    if not r.available:
        pytest.skip("face_recognition not installed")

    enc = np.zeros(512, dtype=np.float32)
    with r._lock:
        pid = r._register(enc)

    # Visto hace 2 min (misma estancia) → no incrementa
    r._conn.execute(
        "UPDATE persons SET last_seen=datetime('now','-2 minutes') WHERE id=?", (pid,)
    )
    r._touch(pid)
    count = r._conn.execute("SELECT visit_count FROM persons WHERE id=?", (pid,)).fetchone()[0]
    assert count == 1

    # Visto hace 30 min (visita nueva) → incrementa
    r._conn.execute(
        "UPDATE persons SET last_seen=datetime('now','-30 minutes') WHERE id=?", (pid,)
    )
    r._touch(pid)
    count = r._conn.execute("SELECT visit_count FROM persons WHERE id=?", (pid,)).fetchone()[0]
    assert count == 2


# ---------------------------------------------------------------------------
# PersonRecognizer — quality gates, consensus, ratio test, face selection,
# re-verification (MEJORAS.md puntos 4-8)
#
# Fase 23: this whole block (TEST_094-105) mocked backend.recognizer.fr
# (face_recognition/dlib), which no longer exists in the module — recognizer.py
# now delegates to backend.perception.face.{engine,quality}. Equivalent
# coverage (quality-gate rejection, consensus buffering, ratio-test ambiguity,
# same-person-multiple-samples grouping, upper-half face selection,
# majority-vote re-verification) lives in tests/test_recognizer_orchestration.py,
# mocking FaceEngine/FaceQualityAssessor instead.
# ---------------------------------------------------------------------------


def _recog(tmp_path) -> PersonRecognizer:
    """A PersonRecognizer with a mocked (always-available) FaceEngine —
    used by tests below that exercise internals unrelated to face detection
    itself (should_attempt, prune, purge_unnamed)."""
    engine = MagicMock()
    engine.available = True
    with patch("backend.recognizer.FaceEngine", return_value=engine):
        return PersonRecognizer(db_path=str(tmp_path / "p.db"))


# ---------------------------------------------------------------------------
# PersonRecognizer — gating para el worker, poda y retención (MEJORAS.md 10, 12, 15)
# ---------------------------------------------------------------------------

# ─── Punto 10: should_attempt aplica el intervalo y marca el intento ──────────
# El hilo de captura usa should_attempt como gate barato antes de encolar el
# crop para el worker. Un True consume el intento: la siguiente llamada dentro
# del intervalo devuelve False. Tracks identificados esperan REVERIFY_INTERVAL
# en lugar de RECOG_INTERVAL.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_106_should_attempt_gates_and_marks(tmp_path):
    """should_attempt is True once per interval; identified tracks wait longer."""
    r = _recog(tmp_path)
    assert r.should_attempt(1, 100) is True
    assert r.should_attempt(1, 101) is False
    assert r.should_attempt(1, 100 + r.RECOG_INTERVAL) is True

    r._cache[2] = (1, None)  # track ya identificado
    assert r.should_attempt(2, 0) is True
    assert r.should_attempt(2, r.RECOG_INTERVAL + 1) is False
    assert r.should_attempt(2, r.REVERIFY_INTERVAL) is True


# ─── Punto 12: prune elimina estado de tracks inactivos ──────────────────────
# Los tracker_id de ByteTrack crecen de forma monótona: sin poda, los dicts
# por track (_cache, _last_attempt, _pending) crecen sin límite en un
# proceso 24/7. prune debe borrar los ids ausentes y conservar los activos.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_107_prune_drops_inactive_track_state(tmp_path):
    """prune removes per-track dicts for ids not in the active set."""
    r = _recog(tmp_path)
    r._cache[1] = (1, None)
    r._cache[2] = (2, None)
    r._last_attempt[1] = 10
    r._last_attempt[2] = 20
    r._pending[2] = [np.zeros(512, dtype=np.float32)]

    r.prune({1})

    assert r._cache == {1: (1, None)}
    assert r._last_attempt == {1: 10}
    assert r._pending == {}


# ─── Punto 15: purge_unnamed borra anónimos de paso, respeta el resto ─────────
# Personas sin nombre con visit_count == 1 y last_seen antiguo son transeúntes
# que degradan el matching si se acumulan. La purga debe borrarlas (fila +
# embeddings + listas en memoria + cache), y no tocar nunca personas con
# nombre ni anónimos recientes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_108_purge_unnamed_removes_stale_single_visit(tmp_path):
    """Stale unnamed one-visit persons are purged; named/recent ones survive."""
    r = _recog(tmp_path)
    rng = np.random.default_rng(0)
    with r._lock:
        pid_old = r._register(rng.standard_normal(512).astype(np.float32))
        pid_named = r._register(rng.standard_normal(512).astype(np.float32))
        pid_recent = r._register(rng.standard_normal(512).astype(np.float32))
    r._conn.execute(
        "UPDATE persons SET last_seen=datetime('now','-40 days') WHERE id IN (?,?)",
        (pid_old, pid_named),
    )
    r._conn.execute("UPDATE persons SET name='Eve' WHERE id=?", (pid_named,))
    r._conn.commit()
    r._cache[5] = (pid_old, None)

    assert r.purge_unnamed(30) == 1

    ids = {p["id"] for p in r.list_persons()}
    assert ids == {pid_named, pid_recent}
    assert pid_old not in r._person_ids
    assert 5 not in r._cache
    # días <= 0 desactiva la purga
    assert r.purge_unnamed(0) == 0


# ---------------------------------------------------------------------------
# API — POST /api/enroll_face
#
# "Sin face_recognition, enroll_named_face devuelve None inmediatamente" is
# now tests/test_recognizer_orchestration.py::TEST_enroll_named_face_unavailable_returns_none.
# ---------------------------------------------------------------------------

import httpx
from httpx import ASGITransport
import backend.main as main_module


# ─── 503 cuando face_recognition no está disponible ──────────────────────────
# Si recognizer.available es False (librería no instalada), el endpoint debe
# devolver 503 Service Unavailable con un mensaje claro, en lugar de 500 con
# NameError o intentar ejecutar código que no existe.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_066_enroll_face_503_when_recognizer_unavailable():
    """Returns 503 when the recognizer reports the library is not installed."""
    mock_stream = MagicMock()
    mock_stream.recognizer = MagicMock()
    mock_stream.recognizer.available = False

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
async def TEST_067_enroll_face_422_when_no_face_detected():
    """Returns 422 when enroll_named_face finds no face in the image."""
    mock_stream = MagicMock()
    mock_stream.recognizer = MagicMock()
    mock_stream.recognizer.available = True
    mock_stream.get_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_stream.recognizer.enroll_named_face = MagicMock(return_value=None)

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
async def TEST_068_enroll_face_success_returns_person_id():
    """Returns 200 with person_id and name on successful enrolment."""
    mock_stream = MagicMock()
    mock_stream.recognizer = MagicMock()
    mock_stream.recognizer.available = True
    mock_stream.get_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_stream.recognizer.enroll_named_face = MagicMock(return_value=3)

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Frank", "use_current_frame": "true"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["person_id"] == 3
    assert body["name"] == "Frank"
