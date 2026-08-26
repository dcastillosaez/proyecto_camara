"""Fase 37 (SCALE-09): los mismos repositorios de storage/repositories.py, motor
PostgreSQL real -- no un mock, un contenedor Postgres de verdad.

Se salta automaticamente si TEST_POSTGRES_URL no esta definida: no forma parte
de la suite por defecto (no hay Postgres en CI todavia -- ver STACK.md "Cuando
migrar a Postgres/Redis" para la decision). Para ejecutarlo localmente:

    docker run -d --rm -p 55432:5432 -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=camara_test postgres:16-alpine

    TEST_POSTGRES_URL=postgresql+asyncpg://postgres:test@localhost:55432/camara_test \\
        .venv/Scripts/python.exe -m pytest tests/integration/test_postgres_repositories.py -v

Verificado manualmente contra ese mismo contenedor antes de escribir este fichero
(37-SUMMARY): encontro y corrigio dos bugs reales de portabilidad, ninguno
hipotetico -- SQLite los deja pasar en silencio, Postgres los rechaza:
  1. AnalyticsRepo.occupancy(): `GROUP BY e.zone_id` sin `z.name` en el SELECT
     -- ilegal en SQL estandar (Postgres: GroupingError), SQLite lo tolera.
  2. AnalyticsRepo.persons_ranking(): `HAVING cur > 0` referenciando el alias de
     SELECT `cur` -- extension no estandar de SQLite; Postgres exige la
     expresion agregada completa (UndefinedColumnError sin el fix).
"""

from __future__ import annotations

import datetime
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.events.types import Event, EventType
from backend.storage import models
from backend.storage.repositories import AnalyticsRepo, EventRepo

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="TEST_POSTGRES_URL no definida -- requiere un Postgres real, ver docstring del modulo",
)


@pytest_asyncio.fixture
async def sf():
    engine = create_async_engine(TEST_POSTGRES_URL)
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)
        await conn.execute(models.Camera.__table__.insert().values(
            id="cam1", name="Camara 1", enabled=True, created_at=datetime.datetime.now(),
        ))
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def TEST_dialect_resolved_to_postgresql(sf):
    assert EventRepo(sf)._dialect == "postgresql"
    assert AnalyticsRepo(sf)._dialect == "postgresql"


async def TEST_event_repo_multi_type_filter_uses_in_not_unary_plus(sf):
    repo = EventRepo(sf)
    now = datetime.datetime.now()
    await repo.insert(Event(type=EventType.INTRUSION, camera_id="cam1", ts=now))
    await repo.insert(Event(type=EventType.UNKNOWN_PERSON, camera_id="cam1", ts=now))
    await repo.insert(Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts=now))
    items, _ = await repo.query(type=[EventType.INTRUSION, EventType.UNKNOWN_PERSON], limit=10)
    assert len(items) == 2


async def TEST_event_repo_rule_filter_uses_jsonb_array_elements(sf):
    repo = EventRepo(sf)
    now = datetime.datetime.now()
    await repo.insert(Event(
        type=EventType.LINE_CROSSED, camera_id="cam1", ts=now, payload={"rules": ["regla-a"]}))
    await repo.insert(Event(
        type=EventType.LINE_CROSSED, camera_id="cam1", ts=now, payload={}))
    items, _ = await repo.query(rule="regla-a", limit=10)
    assert len(items) == 1


async def TEST_event_repo_hourly_counts_uses_to_char(sf):
    repo = EventRepo(sf)
    now = datetime.datetime.now()
    await repo.insert(Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts=now))
    hourly = await repo.hourly_counts(now - datetime.timedelta(hours=1), type=EventType.LINE_CROSSED)
    assert sum(hourly.values()) == 1


async def TEST_analytics_occupancy_group_by_is_ansi_valid(sf):
    async with sf() as session:
        async with session.begin():
            session.add(models.Zone(id="z1", camera_id="cam1", name="Zona 1"))
    now = datetime.datetime.now()
    await EventRepo(sf).insert(Event(
        type=EventType.ZONE_ENTERED, camera_id="cam1", ts=now, zone_id="z1"))
    zones, total = await AnalyticsRepo(sf).occupancy(
        None, now - datetime.timedelta(hours=1), now + datetime.timedelta(minutes=1))
    assert total == 1
    assert zones == [{"zone_id": "z1", "name": "Zona 1", "value": 1}]


async def TEST_analytics_persons_ranking_having_is_ansi_valid(sf):
    async with sf() as session:
        async with session.begin():
            session.add(models.Person(id=1, name="Persona 1"))
    now = datetime.datetime.now()
    await EventRepo(sf).insert(Event(
        type=EventType.LINE_CROSSED, camera_id="cam1", ts=now, person_id=1))
    ranking = await AnalyticsRepo(sf).persons_ranking(
        "cam1", now - datetime.timedelta(hours=1), now + datetime.timedelta(minutes=1))
    assert ranking == [(1, 1, 0)]


async def TEST_init_db_bootstraps_fresh_postgres_schema(monkeypatch):
    """init_db() completo (no solo create_all suelto): crea el esquema v2 +
    `captures` (legacy) + siembra cam1/schema_version, arrancando de una base
    Postgres vacia -- el camino real que sigue la app al arrancar (Fase 37)."""
    import backend.database as database
    from backend.config import get_settings
    from backend.storage.migrations import SCHEMA_VERSION

    engine = create_async_engine(TEST_POSTGRES_URL)
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(database.Base.metadata.drop_all)
    await engine.dispose()

    monkeypatch.setenv("DATABASE_URL", TEST_POSTGRES_URL)
    get_settings.cache_clear()
    database._engine = None
    database._session_factory = None
    try:
        await database.init_db()
        session_factory = database.get_session_factory()
        async with session_factory() as session:
            row = await session.get(models.Camera, "cam1")
            assert row is not None
            version_row = await session.get(models.AppConfig, "schema_version")
            assert int(version_row.value) == SCHEMA_VERSION
    finally:
        database._engine = None
        database._session_factory = None
        get_settings.cache_clear()
