"""Tests for database functions not covered elsewhere: stats, filters, purge."""
from __future__ import annotations

import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module
from backend.database import Zone


@pytest_asyncio.fixture
async def isolated_db(tmp_path):
    db_file = tmp_path / "test_db_extra.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    await db_module.init_db()
    yield

    db_module._engine, db_module._session_factory = orig_engine, orig_sf
    await engine.dispose()


# ---------------------------------------------------------------------------
# get_stats_today
# ---------------------------------------------------------------------------

# ─── BD vacía: ceros y dict vacío ────────────────────────────────────────────
# Al arrancar el sistema por primera vez o tras un purge total, la BD no tiene
# eventos. get_stats_today() debe devolver total_today=0 y hourly={} sin
# lanzar excepción ni devolver None.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_011_get_stats_today_empty_db(isolated_db):
    """Returns total_today=0 and empty hourly dict when no events exist."""
    stats = await db_module.get_stats_today()
    assert stats["total_today"] == 0
    assert stats["hourly"] == {}


# ─── total_today excluye eventos de días anteriores ──────────────────────────
# El dashboard muestra "personas detectadas hoy". Si total_today incluyera
# eventos de ayer, el contador se reiniciaría a un valor incorrecto cada
# medianoche. Se insertan 2 eventos de hoy y 1 de ayer; solo deben contar 2.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_012_get_stats_today_counts_only_todays_events(isolated_db):
    """total_today must not include events from previous days."""
    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(days=1)
    await db_module.insert_event("in", now)
    await db_module.insert_event("out", now)
    await db_module.insert_event("in", yesterday)
    stats = await db_module.get_stats_today()
    assert stats["total_today"] == 2


# ─── Claves del histograma con formato de hora correcto ──────────────────────
# El frontend Chart.js espera claves de dos caracteres ('08', '14', '23').
# SQLite strftime('%H', ...) siempre produce strings de 2 dígitos con cero
# inicial. Este test verifica que ninguna clave tenga longitud distinta de 2,
# lo que causaría huecos o colisiones en el gráfico horario.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_013_get_stats_today_hourly_keys_are_two_char_strings(isolated_db):
    """hourly dict keys are zero-padded 2-char hour strings like '08', '14'."""
    await db_module.insert_event("in", datetime.datetime.now())
    stats = await db_module.get_stats_today()
    for key in stats["hourly"]:
        assert len(key) == 2, f"Expected 2-char hour key, got {key!r}"


# ─── Estructura mínima del resultado ─────────────────────────────────────────
# El endpoint /api/stats y el WebSocket 'init' consumen este dict directamente.
# Si falta alguna clave, el frontend lanzará un TypeError en JavaScript sin
# mensaje de error claro. Se verifica la presencia de ambas claves esperadas.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_014_get_stats_today_has_required_keys(isolated_db):
    """get_stats_today always returns total_today and hourly keys."""
    stats = await db_module.get_stats_today()
    assert "total_today" in stats
    assert "hourly" in stats


# ---------------------------------------------------------------------------
# get_events_filtered
# ---------------------------------------------------------------------------

# ─── Filtro por dirección IN ──────────────────────────────────────────────────
# El endpoint GET /api/events acepta ?direction=in|out. Cuando se filtra por
# 'in', solo deben aparecer eventos con direction='in'. Se insertan un IN y
# un OUT para confirmar que el OUT queda excluido.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_015_get_events_filtered_by_direction_in(isolated_db):
    """direction='in' returns only IN events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts)
    await db_module.insert_event("out", ts)
    result = await db_module.get_events_filtered(direction="in")
    assert all(e["direction"] == "in" for e in result)
    assert len(result) == 1


# ─── Filtro por dirección OUT ─────────────────────────────────────────────────
# Análogo al anterior pero para 'out'. Valida la simetría del filtro y que
# el campo direction se almacena y recupera exactamente como 'out' (3 chars).
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_016_get_events_filtered_by_direction_out(isolated_db):
    """direction='out' returns only OUT events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts)
    await db_module.insert_event("out", ts)
    result = await db_module.get_events_filtered(direction="out")
    assert all(e["direction"] == "out" for e in result)
    assert len(result) == 1


# ─── Filtro por nombre: coincidencia parcial sin distinguir mayúsculas ────────
# El filtro person_name usa ILIKE('%valor%') para encontrar coincidencias
# parciales. Un usuario que busca 'ali' debe encontrar 'Alice' pero no 'Bob'.
# La búsqueda no debe ser sensible a mayúsculas (SQLite ILIKE).
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_017_get_events_filtered_by_person_name_partial_match(isolated_db):
    """person_name filter performs case-insensitive partial match."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts, "Alice")
    await db_module.insert_event("in", ts, "Bob")
    result = await db_module.get_events_filtered(person_name="ali")
    assert len(result) == 1
    assert result[0]["person_name"] == "Alice"


# ─── Filtro is_intrusion=True: solo intrusiones ───────────────────────────────
# Los eventos de intrusión (fuera del horario configurado) se marcan con
# is_intrusion=True. El filtro debe devolver exclusivamente esos eventos para
# el panel de alertas, excluyendo los eventos normales.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_018_get_events_filtered_by_intrusion_true(isolated_db):
    """is_intrusion=True returns only intrusion events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts, is_intrusion=True)
    await db_module.insert_event("out", ts, is_intrusion=False)
    result = await db_module.get_events_filtered(is_intrusion=True)
    assert len(result) == 1
    assert result[0]["is_intrusion"] is True


# ─── Filtro is_intrusion=False: excluye intrusiones ──────────────────────────
# El filtro False debe devolver solo eventos normales. Valida que el booleano
# se almacena correctamente en SQLite (donde BOOLEAN es INTEGER 0/1) y que
# la comparación funciona en ambas direcciones.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_019_get_events_filtered_by_intrusion_false(isolated_db):
    """is_intrusion=False excludes intrusion events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    await db_module.insert_event("in", ts, is_intrusion=True)
    await db_module.insert_event("out", ts, is_intrusion=False)
    result = await db_module.get_events_filtered(is_intrusion=False)
    assert all(not e["is_intrusion"] for e in result)


# ─── Filtro de rango de fechas: límites inclusivos ───────────────────────────
# from_dt y to_dt son ambos inclusivos (>= y <=). Se insertan 3 eventos en
# días consecutivos y se filtra entre el 1 y el 2: deben aparecer exactamente
# 2 eventos (el del día 3 queda excluido).
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_020_get_events_filtered_date_range_inclusive(isolated_db):
    """from_dt/to_dt boundaries are inclusive."""
    t1 = datetime.datetime(2026, 1, 1, 10, 0)
    t2 = datetime.datetime(2026, 1, 2, 10, 0)
    t3 = datetime.datetime(2026, 1, 3, 10, 0)
    for ts in (t1, t2, t3):
        await db_module.insert_event("in", ts)
    result = await db_module.get_events_filtered(from_dt=t1, to_dt=t2)
    assert len(result) == 2


# ─── Sin filtros activos: devuelve todos hasta el límite ─────────────────────
# Cuando ningún filtro está activo, get_events_filtered actúa como
# get_recent_events. Se insertan 5 eventos y se consulta con limit=10;
# deben aparecer los 5 sin que ninguno se descarte.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_021_get_events_filtered_no_filters_returns_all(isolated_db):
    """With no filters, returns all events up to limit."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    for _ in range(5):
        await db_module.insert_event("in", ts)
    result = await db_module.get_events_filtered(limit=10)
    assert len(result) == 5


# ─── El parámetro limit recorta el resultado ──────────────────────────────────
# La exportación CSV y el endpoint /api/events usan limit para paginar.
# Se insertan 10 eventos y se pide limit=3; deben devolverse exactamente 3.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_022_get_events_filtered_respects_limit(isolated_db):
    """limit parameter caps the number of returned events."""
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    for _ in range(10):
        await db_module.insert_event("in", ts)
    result = await db_module.get_events_filtered(limit=3)
    assert len(result) == 3


# ─── Estructura completa de cada evento devuelto ─────────────────────────────
# El frontend y la exportación CSV acceden por clave. Si falta algún campo
# (id, timestamp, direction, person_name, is_intrusion), aparecería un
# KeyError o columna vacía en el CSV exportado.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_023_get_events_filtered_event_has_all_keys(isolated_db):
    """Every event dict has all expected keys."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0))
    result = await db_module.get_events_filtered()
    assert {"id", "timestamp", "direction", "person_name", "is_intrusion"} <= set(result[0].keys())


# ---------------------------------------------------------------------------
# purge_old_events
# ---------------------------------------------------------------------------

# ─── Purge borra solo los eventos fuera de la ventana de retención ────────────
# purge_old_events(retention_days=30) debe eliminar únicamente eventos con
# timestamp < ahora-30días. Se insertan 2 eventos de hace 40 días y 1 de ahora;
# tras el purge deben quedar exactamente 1 evento y deleted=2.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_024_purge_old_events_deletes_old_keeps_recent(isolated_db):
    """purge_old_events removes events beyond retention_days, keeps recent ones."""
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    new = datetime.datetime.now()
    await db_module.insert_event("in", old)
    await db_module.insert_event("in", old)
    await db_module.insert_event("in", new)
    deleted = await db_module.purge_old_events(retention_days=30)
    assert deleted == 2
    remaining = await db_module.get_recent_events(10)
    assert len(remaining) == 1


# ─── Purge devuelve 0 cuando no hay datos caducados ──────────────────────────
# Si todos los eventos están dentro de la ventana de retención, el purge no
# debe borrar nada. Devolver 0 permite al _purge_loop de main.py omitir el
# log "Purged N events" cuando no hay nada que limpiar.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_025_purge_old_events_returns_zero_when_nothing_old(isolated_db):
    """purge_old_events returns 0 when all events are within the window."""
    await db_module.insert_event("in", datetime.datetime.now())
    deleted = await db_module.purge_old_events(retention_days=30)
    assert deleted == 0


# ─── retention_days=0 elimina todos los eventos ──────────────────────────────
# Con retention_days=0, el cutoff es datetime.now(), así que todos los eventos
# anteriores a este instante quedan fuera de ventana. Útil para limpiezas
# manuales completas desde el panel de administración.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_026_purge_old_events_deletes_all_old(isolated_db):
    """purge_old_events with retention_days=0 deletes everything."""
    old = datetime.datetime.now() - datetime.timedelta(days=1)
    await db_module.insert_event("in", old)
    await db_module.insert_event("out", old)
    deleted = await db_module.purge_old_events(retention_days=0)
    assert deleted == 2


# ---------------------------------------------------------------------------
# purge_old_recordings
# ---------------------------------------------------------------------------

# ─── Purge borra solo grabaciones fuera de ventana, conserva las recientes ───
# La rotación de datos de Phase 16 elimina grabaciones antiguas para liberar
# espacio. Se verifica que solo se borra la grabación de hace 40 días y que
# la reciente permanece intacta con su filename correcto.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_027_purge_old_recordings_deletes_old_keeps_recent(isolated_db):
    """purge_old_recordings removes old rows and keeps recent ones."""
    old = datetime.datetime.now() - datetime.timedelta(days=40)
    new = datetime.datetime.now()
    await db_module.insert_recording("old.mp4", created_at=old)
    await db_module.insert_recording("new.mp4", created_at=new)
    deleted = await db_module.purge_old_recordings(retention_days=30)
    assert deleted == 1
    remaining = await db_module.get_recent_recordings(10)
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "new.mp4"


# ─── Purge de grabaciones devuelve 0 sin datos caducados ─────────────────────
# Analogía directa con el purge de eventos: no debe borrar nada si todo está
# dentro de la ventana y debe devolver 0 para evitar logs innecesarios.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_028_purge_old_recordings_returns_zero_when_nothing_old(isolated_db):
    """purge_old_recordings returns 0 when all recordings are recent."""
    await db_module.insert_recording("clip.mp4")
    deleted = await db_module.purge_old_recordings(retention_days=30)
    assert deleted == 0


# ---------------------------------------------------------------------------
# delete_events_range
# ---------------------------------------------------------------------------

# ─── Borrado manual por rango de fechas: solo afecta al rango indicado ────────
# El endpoint DELETE /api/events borra eventos entre from_dt y to_dt.
# Se insertan 3 eventos en días distintos y se borra el rango [t1, t2];
# el evento del día 3 debe quedar intacto con su timestamp original.
# ─────────────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
# get_zones / kind
# ---------------------------------------------------------------------------

# ─── get_zones() expone kind del ORM legacy (Fase 27, BEH-07) ────────────────
# `zones.kind` ya existia fisicamente (migrations.py:103-108) y el ZoneRepo v2
# ya lo devolvia; el que se habia quedado atras era el Zone legacy de este
# fichero, que es justo el que main.py:468 usa para alimentar al
# DetectionWorker. Sin esto, el pipeline nunca veria kind="exclude_objects".
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_get_zones_returns_kind(isolated_db):
    """get_zones() includes kind, both when set and when left as the default None."""
    sf = db_module.get_session_factory()
    async with sf() as session:
        async with session.begin():
            session.add(Zone(
                id="z1", name="Furniture", polygon_json="[]", enabled=True,
                created_at=datetime.datetime.now(), kind="exclude_objects",
            ))
            session.add(Zone(
                id="z2", name="Entrance", polygon_json="[]", enabled=True,
                created_at=datetime.datetime.now(),
            ))

    zones = await db_module.get_zones()
    by_id = {z["id"]: z for z in zones}
    assert by_id["z1"]["kind"] == "exclude_objects"
    assert by_id["z2"]["kind"] is None


async def TEST_029_delete_events_range_removes_in_range(isolated_db):
    """delete_events_range removes only events within [from_dt, to_dt]."""
    t1 = datetime.datetime(2026, 1, 1, 10, 0)
    t2 = datetime.datetime(2026, 1, 2, 10, 0)
    t3 = datetime.datetime(2026, 1, 3, 10, 0)
    for ts in (t1, t2, t3):
        await db_module.insert_event("in", ts)
    deleted = await db_module.delete_events_range(t1, t2)
    assert deleted == 2
    remaining = await db_module.get_recent_events(10)
    assert len(remaining) == 1
    assert remaining[0]["timestamp"] == t3.isoformat()
