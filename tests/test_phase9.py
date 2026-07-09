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
    return PersonTracker(start=sv.Point(0, 360), end=sv.Point(1280, 360))


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
def TEST_055_crossing_out_includes_tracker_id(tracker):
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
def TEST_056_no_crossing_produces_no_events(tracker):
    """When nobody crosses, crossing list is empty."""
    det = _fake_detections([1, 2])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([False, False]), np.array([False, False]))),
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
    counts = tracker.get_counts()
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
def TEST_062_enroll_named_face_no_face_returns_none(tmp_path):
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
def TEST_063_enroll_named_face_registers_new_person(tmp_path):
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
def TEST_064_enroll_named_face_updates_existing_person(tmp_path):
    """Renames an existing matched person instead of creating a duplicate."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    enc = np.random.rand(128).astype(np.float64)

    mock_new = MagicMock()
    mock_new.face_locations.return_value = [(0, 50, 50, 0)]
    mock_new.face_encodings.return_value = [enc]
    mock_new.face_distance.return_value = np.array([0.8])
    with patch("backend.recognizer.fr", mock_new):
        pid1 = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Dave")

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

    enc = np.zeros(128, dtype=np.float64)
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
# PersonRecognizer — quality gates de identify_or_register (MEJORAS.md punto 4)
# ---------------------------------------------------------------------------

_SHARP_FRAME = None


def _sharp_frame() -> np.ndarray:
    """Frame de ruido aleatorio — varianza de Laplaciano altísima (pasa el filtro de blur)."""
    global _SHARP_FRAME
    if _SHARP_FRAME is None:
        rng = np.random.default_rng(42)
        _SHARP_FRAME = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    return _SHARP_FRAME


def _recog(tmp_path) -> PersonRecognizer:
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    if not r.available:
        pytest.skip("face_recognition not installed")
    return r


# ─── Gate 1: cara demasiado pequeña se descarta ──────────────────────────────
# Embeddings de caras < MIN_FACE_SIZE px no son fiables y generaban personas
# fantasma. Una cara de 50×50 (bajo el mínimo de 60) debe descartarse sin
# registrar nada, devolviendo (None, None, False) para reintentar más tarde.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_094_identify_rejects_small_face(tmp_path):
    """Faces smaller than MIN_FACE_SIZE are discarded without registering."""
    r = _recog(tmp_path)
    m = MagicMock()
    m.face_locations.return_value = [(0, 50, 50, 0)]  # 50×50 < 60
    with patch("backend.recognizer.fr", m):
        result = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)
    assert result == (None, None, False)
    assert r.list_persons() == []
    m.face_encodings.assert_not_called()


# ─── Gate 2: cara borrosa se descarta ────────────────────────────────────────
# Un frame uniforme (varianza de Laplaciano = 0) simula desenfoque de
# movimiento. La cara pasa el filtro de tamaño pero no el de nitidez;
# no debe llegar a codificarse ni registrarse.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_095_identify_rejects_blurry_face(tmp_path):
    """Blurry faces (low Laplacian variance) are discarded without registering."""
    r = _recog(tmp_path)
    m = MagicMock()
    m.face_locations.return_value = [(0, 80, 80, 0)]  # 80×80 ≥ 60
    blurry = np.full((200, 200, 3), 128, dtype=np.uint8)  # uniforme → var 0
    with patch("backend.recognizer.fr", m):
        result = r.identify_or_register(blurry, (0, 0, 200, 200), 1, 0)
    assert result == (None, None, False)
    assert r.list_persons() == []
    m.face_encodings.assert_not_called()


# ─── Gate 3: consenso de K muestras antes de registrar persona nueva ─────────
# Antes, una sola cara no reconocida creaba una persona en BD (fantasmas por
# frames malos). Ahora hacen falta NEW_PERSON_CONSENSUS=3 muestras consistentes
# de frames distintos del mismo track: los 2 primeros intentos devuelven None
# y el 3.º registra con is_new=True y las 3 muestras guardadas.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_096_identify_needs_consensus_to_register(tmp_path):
    """A new person is registered only after 3 consistent samples."""
    r = _recog(tmp_path)
    enc = np.random.rand(128).astype(np.float64)
    m = MagicMock()
    m.face_locations.return_value = [(0, 80, 80, 0)]
    m.face_encodings.return_value = [enc]
    m.face_distance.return_value = np.array([0.1])  # muestras consistentes entre sí

    with patch("backend.recognizer.fr", m):
        r1 = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)
        r2 = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 30)
        r3 = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 60)

    assert r1 == (None, None, False)
    assert r2 == (None, None, False)
    pid, name, is_new = r3
    assert pid is not None and is_new is True
    persons = r.list_persons()
    assert len(persons) == 1
    assert persons[0]["sample_count"] == 3  # las 3 muestras del consenso


# ─── Gate 3: muestra inconsistente resetea el buffer ─────────────────────────
# Si la 2.ª muestra difiere de la 1.ª más de CONSENSUS_TOLERANCE (cara de otra
# persona, o basura), el buffer se resetea: tras 3 intentos no hay registro
# porque nunca se acumulan 3 muestras consistentes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_097_identify_inconsistent_sample_resets_buffer(tmp_path):
    """An inconsistent sample resets the consensus buffer — no registration."""
    r = _recog(tmp_path)
    enc = np.random.rand(128).astype(np.float64)
    m = MagicMock()
    m.face_locations.return_value = [(0, 80, 80, 0)]
    m.face_encodings.return_value = [enc]
    m.face_distance.return_value = np.array([0.9])  # cada muestra difiere de las previas

    with patch("backend.recognizer.fr", m):
        for fn in (0, 30, 60):
            result = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, fn)
            assert result == (None, None, False)

    assert r.list_persons() == []


# ─── Match contra persona existente sigue siendo de muestra única ────────────
# El consenso solo aplica al REGISTRO de personas nuevas. Reconocer a una
# persona ya en BD debe seguir funcionando al primer intento con una sola
# muestra buena — es un caso de bajo riesgo y la latencia importa.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_098_identify_existing_person_single_sample(tmp_path):
    """Matching an already-known person still works on the first attempt."""
    r = _recog(tmp_path)
    enc = np.random.rand(128).astype(np.float64)
    with r._lock:
        pid = r._register(enc)

    m = MagicMock()
    m.face_locations.return_value = [(0, 80, 80, 0)]
    m.face_encodings.return_value = [enc]
    m.face_distance.return_value = np.array([0.1])  # match seguro

    with patch("backend.recognizer.fr", m):
        rpid, name, is_new = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)

    assert rpid == pid
    assert is_new is False


# ---------------------------------------------------------------------------
# PersonRecognizer — ratio test y agrupación por persona (MEJORAS.md 5 y 6)
# ---------------------------------------------------------------------------

def _enc_at_distance(d: float) -> np.ndarray:
    """Embedding a distancia euclídea exacta *d* del vector cero."""
    return np.full(128, d / np.sqrt(128), dtype=np.float64)


def _real_distance_mock(enc: np.ndarray) -> MagicMock:
    """Mock de fr con face_distance REAL (numpy) — la geometría no se falsea."""
    m = MagicMock()
    m.face_locations.return_value = [(0, 80, 80, 0)]
    m.face_encodings.return_value = [enc]
    m.face_distance.side_effect = lambda known, e: np.linalg.norm(
        np.asarray(known) - e, axis=1
    )
    return m


# ─── Match ambiguo entre dos personas: no decide ni registra ─────────────────
# Dos personas conocidas a distancias 0.45 y 0.50 del embedding entrante:
# ambas dentro de TOLERANCE=0.55 pero separadas menos de MATCH_MARGIN=0.10.
# Decidir sería arriesgar una identidad falsa; bufferizar arriesgaría
# registrar un duplicado. El sample se descarta: sin match, sin persona nueva.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_099_ambiguous_match_neither_decides_nor_registers(tmp_path):
    """Two known persons within MATCH_MARGIN of each other → sample skipped."""
    r = _recog(tmp_path)
    enc = np.zeros(128, dtype=np.float64)
    with r._lock:
        r._register(_enc_at_distance(0.45))
        r._register(_enc_at_distance(0.50))

    m = _real_distance_mock(enc)
    with patch("backend.recognizer.fr", m):
        for fn in (0, 30, 60):
            result = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, fn)
            assert result == (None, None, False)

    assert len(r.list_persons()) == 2  # ninguna persona nueva
    assert r.get_cached(1) is None     # y ningún match cacheado


# ─── Match decisivo con margen suficiente: acepta ────────────────────────────
# Persona A a 0.30 y persona B a 0.50: margen 0.20 ≥ MATCH_MARGIN.
# El ratio test debe aceptar a A al primer intento.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_100_decisive_match_with_margin_accepts(tmp_path):
    """Best person clearly ahead of runner-up → match accepted."""
    r = _recog(tmp_path)
    enc = np.zeros(128, dtype=np.float64)
    with r._lock:
        pid_a = r._register(_enc_at_distance(0.30))
        r._register(_enc_at_distance(0.50))

    m = _real_distance_mock(enc)
    with patch("backend.recognizer.fr", m):
        rpid, _, is_new = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)

    assert rpid == pid_a
    assert is_new is False


# ─── Dos muestras de la MISMA persona no bloquean el ratio test ──────────────
# Persona A con embeddings a 0.30 y 0.32 (entre sí a 0.02) y persona B a 0.55.
# Sin agrupación por persona, el "segundo mejor" sería la otra muestra de A
# (margen 0.02 < 0.10 → rechazo erróneo). Con agrupación (punto 6), el
# runner-up real es B (margen 0.25) y el match con A se acepta.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_101_same_person_samples_do_not_block_ratio_test(tmp_path):
    """Ratio test compares persons, not individual samples of the same person."""
    r = _recog(tmp_path)
    enc = np.zeros(128, dtype=np.float64)
    with r._lock:
        pid_a = r._register(_enc_at_distance(0.30))
        # segunda muestra de A, solo en memoria — suficiente para el matching
        r._person_ids.append(pid_a)
        r._person_names.append(None)
        r._encodings.append(_enc_at_distance(0.32))
        r._register(_enc_at_distance(0.55))

    m = _real_distance_mock(enc)
    with patch("backend.recognizer.fr", m):
        rpid, _, is_new = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)

    assert rpid == pid_a
    assert is_new is False


# ---------------------------------------------------------------------------
# PersonRecognizer — selección de cara y re-verificación (MEJORAS.md 7 y 8)
# ---------------------------------------------------------------------------

# ─── Punto 7: se elige la cara de la mitad superior, no la mayor ─────────────
# El bbox de la persona trackeada tiene su cabeza en la mitad superior del
# crop. Una cara MÁS GRANDE pero en la mitad inferior (otra persona por
# detrás, solapando el bbox) no debe ganar. Se verifica qué localización
# llega a face_encodings.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_102_select_face_prefers_upper_half(tmp_path):
    """A bigger face in the lower half loses to the tracked person's face."""
    r = _recog(tmp_path)
    upper_face = (0, 70, 70, 0)        # 70×70, centro y=35 (mitad superior)
    lower_face = (110, 199, 199, 110)  # 89×89, centro y=154 (mitad inferior)
    enc = np.random.rand(128).astype(np.float64)
    m = MagicMock()
    m.face_locations.return_value = [lower_face, upper_face]
    m.face_encodings.return_value = [enc]
    m.face_distance.return_value = np.array([0.1])

    with patch("backend.recognizer.fr", m):
        r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)

    m.face_encodings.assert_called_once()
    assert m.face_encodings.call_args.kwargs["known_face_locations"] == [upper_face]


# ─── Punto 8: la re-verificación corrige un primer match erróneo ─────────────
# Frame 0: match con persona A → cacheado. Frames 300 y 600 (re-verify):
# la cara matchea con B. Votos [A,B] → empate, gana A (sin flip prematuro);
# votos [A,B,B] → mayoría B, la cache se corrige y se devuelve B.
# Antes del fix, el primer match se quedaba pegado al track para siempre.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_103_reverify_corrects_wrong_identity(tmp_path):
    """Majority vote flips the cached identity after repeated disagreement."""
    r = _recog(tmp_path)
    enc_a = np.zeros(128, dtype=np.float64)
    enc_b = _enc_at_distance(1.0)
    with r._lock:
        pid_a = r._register(enc_a)
        pid_b = r._register(enc_b)

    m = _real_distance_mock(enc_a)
    with patch("backend.recognizer.fr", m):
        rpid, _, _ = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)
        assert rpid == pid_a

        m.face_encodings.return_value = [enc_b]  # a partir de aquí la cara es B
        rv = r.REVERIFY_INTERVAL
        r2, _, _ = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, rv)
        assert r2 == pid_a                      # empate [A,B] → sin flip
        assert r.get_cached(1) == (pid_a, None)

        r3, _, _ = r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 2 * rv)
        assert r3 == pid_b                      # mayoría [A,B,B] → corrige
        assert r.get_cached(1) == (pid_b, None)


# ─── Punto 8: track cacheado no respeta RECOG_INTERVAL sino REVERIFY ─────────
# Tras identificar, los intentos antes de REVERIFY_INTERVAL no deben ni
# llegar a la detección de caras (ahorro de CPU): face_locations no se llama.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_104_cached_track_waits_reverify_interval(tmp_path):
    """No face detection runs on a cached track before REVERIFY_INTERVAL."""
    r = _recog(tmp_path)
    enc = np.zeros(128, dtype=np.float64)
    with r._lock:
        r._register(enc)

    m = _real_distance_mock(enc)
    with patch("backend.recognizer.fr", m):
        r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)
        m.face_locations.reset_mock()
        result = r.identify_or_register(
            _sharp_frame(), (0, 0, 200, 200), 1, r.RECOG_INTERVAL + 1
        )

    assert result == (None, None, False)
    m.face_locations.assert_not_called()


# ─── Punto 8: cara desconocida en re-verify no crea persona nueva ────────────
# Un track ya identificado cuya cara deja de matchear (oclusión, otra persona
# cruzando por delante del bbox) NO debe alimentar el buffer de consenso ni
# registrar una persona nueva: la identidad cacheada se mantiene.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_105_reverify_unknown_face_does_not_register(tmp_path):
    """An unknown face during re-verify never seeds a new person."""
    r = _recog(tmp_path)
    enc_a = np.zeros(128, dtype=np.float64)
    with r._lock:
        pid_a = r._register(enc_a)

    m = _real_distance_mock(enc_a)
    with patch("backend.recognizer.fr", m):
        r.identify_or_register(_sharp_frame(), (0, 0, 200, 200), 1, 0)

        m.face_encodings.return_value = [_enc_at_distance(0.9)]  # desconocida
        rv = r.REVERIFY_INTERVAL
        for k in (1, 2, 3):
            result = r.identify_or_register(
                _sharp_frame(), (0, 0, 200, 200), 1, k * rv
            )
            assert result == (None, None, False)

    assert len(r.list_persons()) == 1          # sin personas nuevas
    assert r.get_cached(1) == (pid_a, None)    # identidad intacta


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
# por track (_cache, _last_attempt, _pending, _votes) crecen sin límite en un
# proceso 24/7. prune debe borrar los ids ausentes y conservar los activos.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_107_prune_drops_inactive_track_state(tmp_path):
    """prune removes per-track dicts for ids not in the active set."""
    from collections import deque as _deque
    r = _recog(tmp_path)
    r._cache[1] = (1, None)
    r._cache[2] = (2, None)
    r._last_attempt[1] = 10
    r._last_attempt[2] = 20
    r._pending[2] = [np.zeros(128)]
    r._votes[2] = _deque([2], maxlen=r.VOTE_WINDOW)

    r.prune({1})

    assert r._cache == {1: (1, None)}
    assert r._last_attempt == {1: 10}
    assert r._pending == {}
    assert r._votes == {}


# ─── Punto 15: purge_unnamed borra anónimos de paso, respeta el resto ─────────
# Personas sin nombre con visit_count == 1 y last_seen antiguo son transeúntes
# que degradan el matching si se acumulan. La purga debe borrarlas (fila +
# embeddings + listas en memoria + cache), y no tocar nunca personas con
# nombre ni anónimos recientes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_108_purge_unnamed_removes_stale_single_visit(tmp_path):
    """Stale unnamed one-visit persons are purged; named/recent ones survive."""
    r = _recog(tmp_path)
    with r._lock:
        pid_old = r._register(_enc_at_distance(0.30))
        pid_named = r._register(_enc_at_distance(0.50))
        pid_recent = r._register(_enc_at_distance(0.70))
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


# ─── Sin librería face_recognition: devuelve None inmediatamente ─────────────
# En sistemas donde dlib/face_recognition no está instalado, PersonRecognizer.
# _available es False. enroll_named_face debe devolver None sin intentar
# llamar a fr.*, lo que causaría NameError o AttributeError.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_065_enroll_named_face_unavailable_returns_none(tmp_path):
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
async def TEST_066_enroll_face_503_when_recognizer_unavailable():
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
async def TEST_067_enroll_face_422_when_no_face_detected():
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
async def TEST_068_enroll_face_success_returns_person_id():
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
