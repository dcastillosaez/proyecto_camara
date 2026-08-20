"""Tests for backend.storage — v2 schema, repositories, indices, and performance."""

from __future__ import annotations

import datetime
import time

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.events.types import Event, EventType, Severity
from backend.storage import models
from backend.storage.repositories import ConfigRepo, DetectionStatRepo, EventRepo
from scripts.seed_events import seed_events


@pytest_asyncio.fixture
async def db(tmp_path):
    db_file = tmp_path / "storage_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield str(db_file), sf
    await engine.dispose()


def make_event(**overrides) -> Event:
    kwargs = {"type": EventType.LINE_CROSSED, "camera_id": "cam1", "ts": "2026-04-16T18:30:00"}
    kwargs.update(overrides)
    return Event(**kwargs)


async def TEST_event_roundtrip_db(db):
    _, sf = db
    repo = EventRepo(sf)
    event = make_event(
        type=EventType.INTRUSION, track_id=5, confidence=0.87,
        bbox=(10, 20, 100, 200), payload={"direction": "in"},
    )
    await repo.insert(event)

    fetched = await repo.get(event.id)
    assert fetched is not None
    assert fetched == event


async def TEST_query_by_type_and_range(db):
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 1, 10)))
    await repo.insert(make_event(type=EventType.INTRUSION, ts=datetime.datetime(2026, 1, 2, 10)))
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 3, 10)))
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 2, 1, 10)))

    items, _ = await repo.query(
        type=EventType.LINE_CROSSED,
        ts_from=datetime.datetime(2026, 1, 1),
        ts_to=datetime.datetime(2026, 1, 31),
        limit=50,
    )
    assert len(items) == 2
    assert all(e.type == EventType.LINE_CROSSED for e in items)
    assert all(datetime.datetime(2026, 1, 1) <= e.ts <= datetime.datetime(2026, 1, 31) for e in items)


# ─── Fase 30 (OPS-09): tipo multi-valor, filtro por regla y count() ──────────


async def TEST_query_accepts_multiple_types(db):
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 1, 10)))
    await repo.insert(make_event(type=EventType.INTRUSION, ts=datetime.datetime(2026, 1, 2, 10)))
    await repo.insert(make_event(type=EventType.UNKNOWN_PERSON, ts=datetime.datetime(2026, 1, 3, 10)))

    items, _ = await repo.query(type=[EventType.INTRUSION, EventType.UNKNOWN_PERSON])

    assert {e.type for e in items} == {EventType.INTRUSION, EventType.UNKNOWN_PERSON}
    assert [e.ts for e in items] == sorted((e.ts for e in items), reverse=True)


async def TEST_query_single_type_still_accepts_enum(db):
    """La forma antigua (un enum suelto) es la que usa backend/database.py:166."""
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(type=EventType.LINE_CROSSED))
    await repo.insert(make_event(type=EventType.INTRUSION))

    items, _ = await repo.query(type=EventType.LINE_CROSSED)

    assert len(items) == 1
    assert items[0].type == EventType.LINE_CROSSED


async def TEST_query_filters_by_rule_name(db):
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(payload={"rules": ["Intrusión nocturna"]}))
    await repo.insert(make_event(payload={"rules": ["Otra"]}))
    await repo.insert(make_event(payload={"direction": "in"}))  # sin clave 'rules'

    items, _ = await repo.query(rule="Intrusión nocturna")

    assert len(items) == 1
    assert items[0].payload["rules"] == ["Intrusión nocturna"]


async def TEST_query_rule_filter_is_not_interpolated(db):
    """T-30-05: el nombre de regla viaja por bindparam, jamas por f-string."""
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(payload={"rules": ["Intrusión nocturna"]}))

    items, _ = await repo.query(rule="' OR 1=1 --")

    assert items == []


async def TEST_count_matches_query_filters(db):
    _, sf = db
    repo = EventRepo(sf)
    base = datetime.datetime(2026, 1, 1)
    for i in range(30):
        await repo.insert(make_event(type=EventType.INTRUSION, ts=base + datetime.timedelta(minutes=i)))
    for i in range(10):
        await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=base + datetime.timedelta(minutes=i)))

    items, _ = await repo.query(type=EventType.INTRUSION, limit=10)

    assert len(items) == 10
    assert await repo.count(type=EventType.INTRUSION) == 30
    assert await repo.count(type=[EventType.INTRUSION, EventType.LINE_CROSSED]) == 40
    assert await repo.count() == 40


async def TEST_multi_type_query_plan_uses_timeline_index(db):
    """Pitfall 2: sin el '+' unario SQLite elige idx_events_type_ts y ordena con
    TEMP B-TREE (medido 54 ms vs 0,52 ms @100k). Se comprueba sobre el SQL real."""
    import sqlite3

    from sqlalchemy import and_, select
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    db_file, sf = db
    seed_events(db_file, n=2_000, days=7, camera_id="cam1")

    conditions, params = EventRepo._filter_conditions(
        type=[EventType.INTRUSION, EventType.UNKNOWN_PERSON, EventType.LINE_CROSSED],
        severity=Severity.WARNING,
    )
    q = (
        select(models.Event)
        .where(and_(*conditions))
        .order_by(models.Event.ts.desc(), models.Event.id.desc())
        .limit(50)
    )
    if params:
        q = q.params(**params)
    sql = str(q.compile(
        dialect=sqlite_dialect.dialect(), compile_kwargs={"literal_binds": True}))

    conn = sqlite3.connect(db_file)
    try:
        plan = " ".join(str(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql))
    finally:
        conn.close()

    assert "TEMP B-TREE FOR ORDER BY" not in plan, plan
    assert "idx_events_ts_id" in plan, plan


async def TEST_cursor_pagination_is_stable(db):
    _, sf = db
    repo = EventRepo(sf)
    base = datetime.datetime(2026, 1, 1)
    for i in range(100):
        await repo.insert(make_event(ts=base + datetime.timedelta(minutes=i)))

    seen_ids = []
    cursor = None
    for _ in range(20):  # generous upper bound on page count
        items, cursor = await repo.query(limit=10, cursor=cursor)
        seen_ids.extend(e.id for e in items)
        if cursor is None:
            break

    assert len(seen_ids) == 100
    assert len(set(seen_ids)) == 100


# ─── Fase 30 (OPS-08): alcance retroactivo por track ─────────────────────────
# Los tracker_id de ByteTrack se reinician al recrear el tracker (backend/tracker.py:181)
# y la tabla `tracks` nunca se escribe: track_id=7 de hoy y track_id=7 de anteayer son
# personas distintas. Estos tests fijan las tres cotas que lo impiden (30-RESEARCH.md
# Pitfall 3): misma camara, ventana de +-6 h y corte en el primer hueco > 60 s.
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_track(repo, *, base, offsets_s, track_id=7, camera_id="cam1", **overrides):
    """Inserta un evento por cada offset (segundos desde *base*) y devuelve sus ids."""
    ids = []
    for offset in offsets_s:
        ev = make_event(
            camera_id=camera_id,
            track_id=track_id,
            ts=base + datetime.timedelta(seconds=offset),
            **overrides,
        )
        await repo.insert(ev)
        ids.append(ev.id)
    return ids


async def TEST_track_scope_returns_contiguous_block(db):
    _, sf = db
    repo = EventRepo(sf)
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)
    ids = await _seed_track(repo, base=base, offsets_s=[0, 10, 20, 30, 40])

    scope = await repo.track_scope(ids[2])

    assert scope is not None
    assert scope["count"] == 5
    assert set(scope["event_ids"]) == set(ids)
    assert scope["from"] == base
    assert scope["to"] == base + datetime.timedelta(seconds=40)


async def TEST_track_scope_cuts_on_gap(db):
    _, sf = db
    repo = EventRepo(sf)
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)
    first = await _seed_track(repo, base=base, offsets_s=[0, 10, 20])
    second = await _seed_track(repo, base=base, offsets_s=[320, 330])  # hueco de 5 min

    scope = await repo.track_scope(first[1])

    assert scope["count"] == 3
    assert set(scope["event_ids"]) == set(first)
    assert not set(scope["event_ids"]) & set(second)


async def TEST_track_scope_ignores_homonym_track_from_another_day(db):
    """Regresion del Pitfall 3: mismo track_id, 48 h de distancia, persona distinta."""
    _, sf = db
    repo = EventRepo(sf)
    recent = datetime.datetime(2026, 1, 3, 12, 0, 0)
    old = recent - datetime.timedelta(hours=48)
    ids_recent = await _seed_track(repo, base=recent, offsets_s=[0])
    await _seed_track(repo, base=old, offsets_s=[0])

    scope = await repo.track_scope(ids_recent[0])

    assert scope["count"] == 1
    assert scope["event_ids"] == ids_recent


async def TEST_track_scope_respects_camera_id(db):
    _, sf = db
    repo = EventRepo(sf)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)
    ids_cam1 = await _seed_track(repo, base=base, offsets_s=[0], camera_id="cam1")
    ids_cam2 = await _seed_track(repo, base=base, offsets_s=[0], camera_id="cam2")

    scope = await repo.track_scope(ids_cam1[0])

    assert scope["event_ids"] == ids_cam1
    assert ids_cam2[0] not in scope["event_ids"]


async def TEST_track_scope_returns_none_without_track_id(db):
    _, sf = db
    repo = EventRepo(sf)
    ev = make_event(track_id=None)
    await repo.insert(ev)

    assert await repo.track_scope(ev.id) is None


async def TEST_detection_stats_upsert(db):
    _, sf = db
    repo = DetectionStatRepo(sf)
    minute = datetime.datetime(2026, 1, 1, 12, 5, 0)

    await repo.upsert_minute("cam1", minute, detections=10, unique_tracks=2, avg_confidence=0.8, max_concurrent=2)
    await repo.upsert_minute("cam1", minute, detections=15, unique_tracks=3, avg_confidence=0.9, max_concurrent=3)

    rows = await repo.recent("cam1", limit=10)
    assert len(rows) == 1
    assert rows[0]["detections"] == 25
    assert rows[0]["unique_tracks"] == 3
    assert rows[0]["max_concurrent"] == 3


# ─── hourly_baseline: media movil por franja horaria (Fase 27, BEH-09) ───────
# El orden de agregacion es lo que se esta probando: primero SUM por (dia, hora)
# y solo despues AVG entre dias. Promediar las filas de minuto daria "media por
# minuto" y ponderaria mas los dias con mas minutos registrados. Se agrega sobre
# unique_tracks y no sobre detections porque detections depende del FPS que
# AdaptiveRate haya elegido (engine.py:281) y no es comparable entre dias.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_hourly_baseline_averages_across_days(db):
    _, sf = db
    repo = DetectionStatRepo(sf)
    # Dia 1: 09:05 + 09:20 + 09:40 -> total 10. Dia 2 -> total 20. Dia 3 -> total 30.
    # Repartido en varios minutos: si el test promediase filas de minuto en vez de
    # sumar por dia primero, "avg_total" saldria distinto de 20.0.
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 9, 5), detections=0, unique_tracks=3, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 9, 20), detections=0, unique_tracks=3, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 9, 40), detections=0, unique_tracks=4, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 2, 9, 5), detections=0, unique_tracks=7, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 2, 9, 20), detections=0, unique_tracks=6, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 2, 9, 40), detections=0, unique_tracks=7, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 3, 9, 5), detections=0, unique_tracks=10, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 3, 9, 20), detections=0, unique_tracks=10, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 3, 9, 40), detections=0, unique_tracks=10, avg_confidence=None, max_concurrent=0)

    baseline = await repo.hourly_baseline("cam1", since=datetime.datetime(2026, 1, 1))

    assert baseline["09"]["avg_total"] == 20.0
    assert baseline["09"]["sample_days"] == 3


async def TEST_hourly_baseline_reports_sample_days(db):
    _, sf = db
    repo = DetectionStatRepo(sf)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 9, 5), detections=0, unique_tracks=5, avg_confidence=None, max_concurrent=0)

    baseline = await repo.hourly_baseline("cam1", since=datetime.datetime(2026, 1, 1))

    assert baseline["09"]["sample_days"] == 1


async def TEST_hourly_baseline_respects_until(db):
    _, sf = db
    repo = DetectionStatRepo(sf)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 9, 5), detections=0, unique_tracks=5, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 14, 5), detections=0, unique_tracks=9, avg_confidence=None, max_concurrent=0)

    baseline = await repo.hourly_baseline(
        "cam1",
        since=datetime.datetime(2026, 1, 1),
        until=datetime.datetime(2026, 1, 1, 14, 0),
    )

    assert "14" not in baseline
    assert "09" in baseline


async def TEST_hourly_baseline_filters_by_camera(db):
    _, sf = db
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))
    repo = DetectionStatRepo(sf)
    await repo.upsert_minute("cam1", datetime.datetime(2026, 1, 1, 9, 5), detections=0, unique_tracks=5, avg_confidence=None, max_concurrent=0)
    await repo.upsert_minute("cam2", datetime.datetime(2026, 1, 1, 9, 5), detections=0, unique_tracks=99, avg_confidence=None, max_concurrent=0)

    baseline = await repo.hourly_baseline("cam1", since=datetime.datetime(2026, 1, 1))

    assert baseline["09"]["avg_total"] == 5.0


async def TEST_hourly_baseline_empty_window(db):
    _, sf = db
    repo = DetectionStatRepo(sf)

    baseline = await repo.hourly_baseline("cam1", since=datetime.datetime(2026, 1, 1))

    assert baseline == {}


async def TEST_config_repo_roundtrip_list(db):
    _, sf = db
    repo = ConfigRepo(sf)

    await repo.set("yolo_classes", [0, 24, 28])
    assert await repo.get("yolo_classes") == [0, 24, 28]

    await repo.set("yolo_classes", [0])
    assert await repo.get("yolo_classes") == [0]

    assert await repo.get("does_not_exist", default=[0]) == [0]


async def TEST_count_since_and_hourly_counts(db):
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 1, 9, 15)))
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 1, 9, 45)))
    await repo.insert(make_event(type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 1, 14, 0)))
    await repo.insert(make_event(type=EventType.INTRUSION, ts=datetime.datetime(2026, 1, 1, 9, 30)))

    count = await repo.count_since(datetime.datetime(2026, 1, 1), type=EventType.LINE_CROSSED)
    hourly = await repo.hourly_counts(datetime.datetime(2026, 1, 1), type=EventType.LINE_CROSSED)

    assert count == 3
    assert hourly == {"09": 2, "14": 1}


async def TEST_delete_before_and_delete_range(db):
    _, sf = db
    repo = EventRepo(sf)
    await repo.insert(make_event(ts=datetime.datetime(2026, 1, 1)))
    await repo.insert(make_event(ts=datetime.datetime(2026, 2, 1)))
    await repo.insert(make_event(ts=datetime.datetime(2026, 3, 1)))

    deleted_before = await repo.delete_before(datetime.datetime(2026, 1, 15))
    remaining, _ = await repo.query(limit=50)
    assert deleted_before == 1
    assert len(remaining) == 2

    deleted_range = await repo.delete_range(datetime.datetime(2026, 2, 1), datetime.datetime(2026, 2, 28))
    remaining, _ = await repo.query(limit=50)
    assert deleted_range == 1
    assert len(remaining) == 1


async def TEST_indexes_exist(db):
    db_file, sf = db
    expected = {
        "idx_events_ts", "idx_events_type_ts", "idx_events_cam_ts", "idx_events_person",
        "idx_tracks_cam", "idx_recordings_cam", "idx_detstats_minute",
    }
    async with sf() as session:
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
        names = {row[0] for row in result.all()}
    assert expected.issubset(names)


async def TEST_query_performance_100k(db, tmp_path):
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    repo = EventRepo(sf)

    now = datetime.datetime.now()
    start = time.perf_counter()
    items, _ = await repo.query(
        camera_id="cam1",
        ts_from=now - datetime.timedelta(days=7),
        ts_to=now,
        limit=50,
    )
    elapsed = time.perf_counter() - start
    await engine.dispose()

    assert elapsed < 0.5, f"query took {elapsed:.3f}s, expected < 0.5s"
    assert isinstance(items, list)
