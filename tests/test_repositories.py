"""Tests for backend.storage — v2 schema, repositories, indices, and performance."""

from __future__ import annotations

import datetime
import re
import sqlite3
import time

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.events.types import Event, EventType, Severity
from backend.storage import models
from backend.storage.repositories import (
    AnalyticsRepo,
    CameraRepo,
    ConfigRepo,
    DetectionStatRepo,
    EventRepo,
    LineRepo,
    RecordingRepo,
    RuleRepo,
    UploadState,
    bucket_for,
)
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


async def TEST_assign_person_updates_only_contiguous_block(db):
    _, sf = db
    repo = EventRepo(sf)
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)
    block = await _seed_track(repo, base=base, offsets_s=[0, 10, 20, 30, 40])
    outside = await _seed_track(repo, base=base, offsets_s=[400, 410])

    result = await repo.assign_person(block[2], person_id=7)

    assert result["updated"] == 5
    assert set(result["event_ids"]) == set(block)
    for event_id in block:
        assert (await repo.get(event_id)).person_id == 7
    for event_id in outside:
        assert (await repo.get(event_id)).person_id is None


async def TEST_assign_person_downgrades_unknown_person_severity(db):
    """UNKNOWN_PERSON deja de ser advertencia al ganar identidad; el resto no se toca."""
    _, sf = db
    repo = EventRepo(sf)
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)
    unknown = make_event(
        type=EventType.UNKNOWN_PERSON, track_id=7, ts=base, severity=Severity.WARNING)
    crossed = make_event(
        type=EventType.LINE_CROSSED, track_id=7, ts=base + datetime.timedelta(seconds=10),
        severity=Severity.WARNING)
    await repo.insert(unknown)
    await repo.insert(crossed)

    await repo.assign_person(unknown.id, person_id=3)

    assert (await repo.get(unknown.id)).severity == Severity.INFO
    assert (await repo.get(crossed.id)).severity == Severity.WARNING


async def TEST_assign_person_without_track_returns_zero(db):
    _, sf = db
    repo = EventRepo(sf)
    ev = make_event(track_id=None)
    await repo.insert(ev)

    result = await repo.assign_person(ev.id, person_id=7)

    assert result == {"person_id": 7, "updated": 0, "event_ids": []}
    assert (await repo.get(ev.id)).person_id is None


async def TEST_assign_person_does_not_touch_homonym_track(db):
    """T-30-08: el UPDATE va por lista explicita de ids, no por 'WHERE track_id = 7'."""
    _, sf = db
    repo = EventRepo(sf)
    recent = datetime.datetime(2026, 1, 3, 12, 0, 0)
    ids_recent = await _seed_track(repo, base=recent, offsets_s=[0])
    ids_old = await _seed_track(repo, base=recent - datetime.timedelta(hours=48), offsets_s=[0])

    result = await repo.assign_person(ids_recent[0], person_id=7)

    assert result["updated"] == 1
    assert (await repo.get(ids_recent[0])).person_id == 7
    assert (await repo.get(ids_old[0])).person_id is None


# ─── Fase 30: mapa evento -> grabacion de una pagina completa ────────────────
# events.recording_id NUNCA se escribe; el vinculo real lo pone _on_clip_ready en
# recordings.trigger_event_id (backend/main.py:353-357).
# ─────────────────────────────────────────────────────────────────────────────


async def _make_recording(repo, *, trigger_event_id, thumb="thumbs/x.jpg"):
    rec_id = await repo.create(
        camera_id="cam1",
        filename=f"clip_{trigger_event_id}.mp4",
        started_at=datetime.datetime(2026, 1, 1, 12, 0, 0),
        reason="motion",
        trigger_event_id=trigger_event_id,
    )
    await repo.finalize(
        rec_id,
        ended_at=datetime.datetime(2026, 1, 1, 12, 0, 30),
        duration_s=30.0,
        size_bytes=1024,
        sha256="deadbeef",
        thumbnail_path=thumb,
        upload_state=UploadState.DONE,
    )
    return rec_id


async def TEST_by_trigger_event_ids_maps_only_matching(db):
    _, sf = db
    repo = RecordingRepo(sf)
    id_a = await _make_recording(repo, trigger_event_id="ev-a")
    id_b = await _make_recording(repo, trigger_event_id="ev-b")
    await _make_recording(repo, trigger_event_id="ev-c")

    mapping = await repo.by_trigger_event_ids(["ev-a", "ev-b", "ev-zzz"])

    assert set(mapping) == {"ev-a", "ev-b"}
    assert mapping["ev-a"]["recording_id"] == id_a
    assert mapping["ev-b"]["recording_id"] == id_b
    assert mapping["ev-a"]["local_path"] == "clip_ev-a.mp4"
    assert mapping["ev-a"]["thumbnail_path"] == "thumbs/x.jpg"


async def TEST_by_trigger_event_ids_empty_input():
    """Corto-circuito: con la lista vacia no se abre sesion ni se consulta."""

    def exploding_factory():
        raise AssertionError("no deberia abrirse una sesion con la lista vacia")

    assert await RecordingRepo(exploding_factory).by_trigger_event_ids([]) == {}


async def TEST_by_trigger_event_ids_keeps_latest_per_event(db):
    _, sf = db
    repo = RecordingRepo(sf)
    await _make_recording(repo, trigger_event_id="ev-a", thumb="thumbs/old.jpg")
    newer = await _make_recording(repo, trigger_event_id="ev-a", thumb="thumbs/new.jpg")

    mapping = await repo.by_trigger_event_ids(["ev-a"])

    assert len(mapping) == 1
    assert mapping["ev-a"]["recording_id"] == newer
    assert mapping["ev-a"]["thumbnail_path"] == "thumbs/new.jpg"


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


async def TEST_config_repo_delete_removes_existing_key(db):
    _, sf = db
    repo = ConfigRepo(sf)
    await repo.set("yolo_confidence", 0.9)

    removed = await repo.delete("yolo_confidence")

    assert removed is True
    assert await repo.get("yolo_confidence", default=0.45) == 0.45


async def TEST_config_repo_delete_missing_key_returns_false(db):
    _, sf = db
    repo = ConfigRepo(sf)

    removed = await repo.delete("never_written_key")

    assert removed is False


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


# --- Criterio 3 de la Fase 30: 10.000 eventos navegables sin degradacion -----------
#
# Presupuesto de 100 ms por consulta. 30-RESEARCH.md Hallazgo 7 midio 1,66 ms en el
# peor caso @10k sin indice y 0,62 ms en la primera pagina @100k con idx_events_ts_id:
# dos ordenes de magnitud de margen para que el test no sea flaky en una maquina
# cargada, sin dejar de detectar una regresion real (un TEMP B-TREE o un scan completo
# se van a cientos de ms).
_BUDGET_10K_SECS = 0.1


def _perf_repo(db_file) -> tuple:
    """Motor propio sobre la base ya sembrada, para no medir el fixture."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, EventRepo(sf)


async def TEST_timeline_first_page_under_budget_10k(db):
    """Criterio 3: la primera pagina de la linea temporal @10k bajo presupuesto."""
    db_file, _ = db
    seed_events(db_file, n=10_000, days=30, camera_id="cam1")
    engine, repo = _perf_repo(db_file)
    try:
        start = time.perf_counter()
        items, cursor = await repo.query(limit=50)
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert len(items) == 50
    assert cursor is not None
    assert elapsed < _BUDGET_10K_SECS, f"first page took {elapsed * 1000:.1f}ms"


async def TEST_timeline_deep_cursor_page_under_budget_10k(db):
    """Criterio 3: la pagina 100 (~evento 5.000) cuesta lo mismo que la primera.

    Es la comprobacion que importa del cursor (ts, id): con OFFSET, la pagina 100
    tendria que descartar 5.000 filas antes de devolver 50.
    """
    db_file, _ = db
    seed_events(db_file, n=10_000, days=30, camera_id="cam1")
    engine, repo = _perf_repo(db_file)
    try:
        first_page, cursor = await repo.query(limit=50)
        first_ids = {e.id for e in first_page}
        for _ in range(98):  # paginas 2..99
            _, cursor = await repo.query(cursor=cursor, limit=50)
            assert cursor is not None

        start = time.perf_counter()
        deep_page, _ = await repo.query(cursor=cursor, limit=50)
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert len(deep_page) == 50
    assert not ({e.id for e in deep_page} & first_ids), "la pagina 100 repite filas"
    assert elapsed < _BUDGET_10K_SECS, f"deep page took {elapsed * 1000:.1f}ms"


async def TEST_timeline_multi_type_filter_under_budget_10k(db):
    """Criterio 3 + regresion del Pitfall 2: filtro multi-tipo + severidad @10k.

    Sin el '+' unario de _filter_conditions esta consulta ordena con TEMP B-TREE y
    se vuelve ~30x mas lenta (54 ms vs 0,52 ms @100k, 30-RESEARCH.md Hallazgo 7).
    """
    db_file, _ = db
    seed_events(db_file, n=10_000, days=30, camera_id="cam1")
    engine, repo = _perf_repo(db_file)
    try:
        start = time.perf_counter()
        items, _ = await repo.query(
            type=[EventType.INTRUSION, EventType.UNKNOWN_PERSON, EventType.LINE_CROSSED],
            severity=Severity.WARNING,
            limit=50,
        )
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert len(items) == 50
    assert all(e.severity == Severity.WARNING for e in items)
    assert elapsed < _BUDGET_10K_SECS, f"multi-type filter took {elapsed * 1000:.1f}ms"


async def TEST_timeline_index_exists_after_init_10k(db):
    """Criterio 3: el indice que sostiene el presupuesto existe en la base real."""
    db_file, sf = db
    seed_events(db_file, n=10_000, days=30, camera_id="cam1")
    async with sf() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'"))
        names = {row[0] for row in result.all()}

    assert "idx_events_ts_id" in names


# --- Fase 31 (OPS-12/OPS-14): siembra de identidad y zona en seed_events ----------


def TEST_seed_events_populates_persons_and_zones(tmp_path):
    """Con persons/zones pedidos, la siembra reparte identidad y zona en las
    proporciones del banco de pruebas del research (35% / 60%), necesarias para
    que los tests de ranking y ocupacion de 31-04 midan sobre datos reales."""
    db_path = tmp_path / "seed_persons_zones.db"
    engine = create_engine(f"sqlite:///{db_path}")
    models.Base.metadata.create_all(engine)
    engine.dispose()

    seed_events(str(db_path), n=5_000, days=30, camera_id="cam1", persons=60, zones=14)

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        with_person = conn.execute(
            "SELECT COUNT(*) FROM events WHERE person_id IS NOT NULL").fetchone()[0]
        with_zone = conn.execute(
            "SELECT COUNT(*) FROM events WHERE zone_id IS NOT NULL").fetchone()[0]
        distinct_persons = conn.execute(
            "SELECT COUNT(DISTINCT person_id) FROM events").fetchone()[0]
        zone_values = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT zone_id FROM events WHERE zone_id IS NOT NULL")
        ]
    finally:
        conn.close()

    assert total == 5_000
    person_ratio = with_person / total
    zone_ratio = with_zone / total
    assert 0.30 <= person_ratio <= 0.40, person_ratio
    assert 0.55 <= zone_ratio <= 0.65, zone_ratio
    assert distinct_persons <= 60
    assert all(re.fullmatch(r"zona-\d+", z) for z in zone_values)


def TEST_seed_events_defaults_leave_person_and_zone_null(tmp_path):
    """Guarda de compatibilidad con la Fase 30: sin persons/zones, la siembra
    sigue dejando person_id/zone_id a NULL en el 100% de las filas."""
    db_path = tmp_path / "seed_defaults.db"
    engine = create_engine(f"sqlite:///{db_path}")
    models.Base.metadata.create_all(engine)
    engine.dispose()

    seed_events(str(db_path), n=500, days=30, camera_id="cam1")

    conn = sqlite3.connect(db_path)
    try:
        with_person = conn.execute(
            "SELECT COUNT(*) FROM events WHERE person_id IS NOT NULL").fetchone()[0]
        with_zone = conn.execute(
            "SELECT COUNT(*) FROM events WHERE zone_id IS NOT NULL").fetchone()[0]
    finally:
        conn.close()

    assert with_person == 0
    assert with_zone == 0


# --- Fase 31 (OPS-12/OPS-14): guarda del formato de almacenamiento de DateTime ----


async def TEST_datetime_storage_format_is_fixed_width_iso(db):
    """Precondicion de AnalyticsRepo._bucket_expr() (31-04): las agregaciones usan
    substr(ts,1,13)/substr(ts,1,10) en vez de strftime(...) porque es 2,3x mas
    rapido (51,8 ms vs 120,8 ms @100k, 31-RESEARCH.md). Eso convierte una funcion
    semantica en una sintactica: si SQLAlchemy dejara de serializar Event.ts como
    TEXT ISO de ancho fijo, el GROUP BY agruparia mal SIN lanzar ningun error y las
    graficas saldrian con cubos raros sin que nadie supiera por que. Si este test
    cae, hay que volver a strftime (120 ms, sigue dentro de los 500 ms del criterio
    4 del ROADMAP) de forma explicita, no por descuido.
    """
    db_file, sf = db
    async with sf() as session:
        async with session.begin():
            session.add(models.Event(
                id="evt-with-micros", camera_id="cam1", type="LINE_CROSSED",
                ts=datetime.datetime(2026, 8, 22, 9, 5, 3, 123456), severity="info",
                payload={},
            ))
            session.add(models.Event(
                id="evt-zero-micros", camera_id="cam1", type="LINE_CROSSED",
                ts=datetime.datetime(2026, 8, 22, 9, 5, 3, 0), severity="info",
                payload={},
            ))

    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(
            "SELECT typeof(ts), ts, substr(ts,1,13), substr(ts,1,10) "
            "FROM events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
    for typeof_ts, raw_ts, substr13, substr10 in rows:
        assert typeof_ts == "text"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}", raw_ts), raw_ts
        assert substr13 == "2026-08-22 09"
        assert substr10 == "2026-08-22"


# --- Fase 31-04 (OPS-12/OPS-13/OPS-14): AnalyticsRepo -------------------------------


def TEST_analytics_bucket_for_switches_at_seven_days():
    base = datetime.datetime(2026, 1, 1)
    assert bucket_for(base, base + datetime.timedelta(days=1)) == "hour"
    assert bucket_for(base, base + datetime.timedelta(days=7)) == "hour"
    assert bucket_for(base, base + datetime.timedelta(days=8)) == "day"
    assert bucket_for(base, base + datetime.timedelta(days=30)) == "day"


async def TEST_analytics_hourly_splits_current_and_previous(db):
    """Dos ventanas contiguas sembradas a mano: una sola consulta cubre las dos y
    cada fila devuelve (actual, anterior) en su bucket, nunca ambos a la vez —
    los dos periodos caen en horas distintas por construccion."""
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    for _ in range(2):
        await events.insert(make_event(
            type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 15)))
    for _ in range(3):
        await events.insert(make_event(
            type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 1, 10, 15)))

    rows = await repo.hourly("cam1", cur_from, cur_to, "hour")
    by_bucket = {b: (cur, prev) for b, cur, prev in rows}

    assert by_bucket["2026-01-02 10"] == (2, 0)
    assert by_bucket["2026-01-01 10"] == (0, 3)


async def TEST_analytics_hourly_ignores_other_event_types(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 15)))
    await events.insert(make_event(
        type=EventType.INTRUSION, ts=datetime.datetime(2026, 1, 2, 10, 20)))

    rows = await repo.hourly("cam1", cur_from, cur_to, "hour")
    by_bucket = {b: (cur, prev) for b, cur, prev in rows}

    assert by_bucket["2026-01-02 10"] == (1, 0)


async def TEST_analytics_summary_returns_peak_and_min(db):
    """GROUP BY solo devuelve cubos con >=1 evento: un cubo con 0 eventos no puede
    aparecer en 'WITH b AS (SELECT ... GROUP BY bucket)'. El relleno a cero de
    cubos vacios para el eje completo es responsabilidad del router (31-05), no de
    summary() — por eso este test usa dos cubos reales, 5 y 34, que ya suman el
    total esperado."""
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    for _ in range(5):
        await events.insert(make_event(
            type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 4, 0)))
    for _ in range(34):
        await events.insert(make_event(
            type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 18, 0)))

    result = await repo.summary("cam1", cur_from, cur_to, "hour")

    assert result["total"] == 39
    assert result["peak_bucket"] == "2026-01-02 18"
    assert result["peak_value"] == 34
    assert result["min_bucket"] == "2026-01-02 04"
    assert result["min_value"] == 5


async def TEST_analytics_summary_known_unknown_counts_distinct_people(db):
    """known/unknown cuentan personas DISTINTAS, no eventos: 3 eventos de
    person_id=1 y 2 de person_id=2 -> known==2 (dos personas), no 5 (cinco
    eventos); 4 eventos sin identidad con dos track_id distintos -> unknown==2."""
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    for _ in range(3):
        await events.insert(make_event(type=EventType.PERSON_RECOGNIZED, ts=ts, person_id=1))
    for _ in range(2):
        await events.insert(make_event(type=EventType.PERSON_RECOGNIZED, ts=ts, person_id=2))
    for _ in range(2):
        await events.insert(make_event(type=EventType.UNKNOWN_PERSON, ts=ts, track_id=101))
    for _ in range(2):
        await events.insert(make_event(type=EventType.UNKNOWN_PERSON, ts=ts, track_id=102))

    result = await repo.summary("cam1", cur_from, cur_to, "hour")

    assert result["known"] == 2
    assert result["unknown"] == 2


async def TEST_analytics_summary_previous_total_zero_is_not_an_error(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 0)))

    result = await repo.summary("cam1", cur_from, cur_to, "hour")

    assert result["total"] == 1
    assert result["previous_total"] == 0
    assert "percent" not in result
    assert "change_pct" not in result


async def TEST_analytics_occupancy_orders_desc_and_truncates(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    for i in range(1, 13):
        for _ in range(i):
            await events.insert(make_event(
                type=EventType.ZONE_ENTERED, ts=ts, zone_id=f"zona-{i}"))

    zones, total_zones = await repo.occupancy("cam1", cur_from, cur_to)

    assert total_zones == 12
    assert len(zones) == 10
    values = [z["value"] for z in zones]
    assert values == sorted(values, reverse=True)
    assert zones[0] == {"zone_id": "zona-12", "name": "zona-12", "value": 12}


async def TEST_analytics_occupancy_only_counts_zone_entered(db):
    """Una intrusion ya esta contada como entrada: sumarla tambien duplicaria
    la ocupacion de la zona."""
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    await events.insert(make_event(type=EventType.ZONE_ENTERED, ts=ts, zone_id="zona-1"))
    await events.insert(make_event(type=EventType.INTRUSION, ts=ts, zone_id="zona-1"))

    zones, total_zones = await repo.occupancy("cam1", cur_from, cur_to)

    assert total_zones == 1
    assert zones == [{"zone_id": "zona-1", "name": "zona-1", "value": 1}]


async def TEST_analytics_occupancy_falls_back_to_zone_id_when_zone_deleted(db):
    """Sin fila en `zones` (zona borrada, o nunca dada de alta), el COALESCE
    devuelve el zone_id crudo -- nunca None ni la cadena 'null'."""
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    await events.insert(make_event(type=EventType.ZONE_ENTERED, ts=ts, zone_id="zona-borrada"))

    zones, _ = await repo.occupancy("cam1", cur_from, cur_to)

    assert zones == [{"zone_id": "zona-borrada", "name": "zona-borrada", "value": 1}]


async def TEST_analytics_ranking_orders_desc_and_limits(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    for person_id in range(1, 13):
        for _ in range(person_id):
            await events.insert(make_event(
                type=EventType.PERSON_RECOGNIZED, ts=ts, person_id=person_id))

    ranking = await repo.persons_ranking("cam1", cur_from, cur_to)

    assert len(ranking) == 10
    cur_values = [cur for _, cur, _ in ranking]
    assert cur_values == sorted(cur_values, reverse=True)
    assert ranking[0] == (12, 12, 0)


async def TEST_analytics_ranking_excludes_null_person_id(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    await events.insert(make_event(type=EventType.PERSON_RECOGNIZED, ts=ts, person_id=1))
    await events.insert(make_event(type=EventType.UNKNOWN_PERSON, ts=ts, track_id=99))

    ranking = await repo.persons_ranking("cam1", cur_from, cur_to)

    assert ranking == [(1, 1, 0)]


async def TEST_analytics_ranking_returns_previous_window_counts(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    for _ in range(3):
        await events.insert(make_event(
            type=EventType.PERSON_RECOGNIZED, ts=datetime.datetime(2026, 1, 2, 10, 0), person_id=7))
    for _ in range(5):
        await events.insert(make_event(
            type=EventType.PERSON_RECOGNIZED, ts=datetime.datetime(2026, 1, 1, 10, 0), person_id=7))

    ranking = await repo.persons_ranking("cam1", cur_from, cur_to)

    assert ranking == [(7, 3, 5)]


async def TEST_analytics_person_avatars_returns_latest_capture(db):
    """`captures` vive en events.db pero NO en storage.models (Base distinta en
    backend/database.py): se crea a mano aqui, igual que el resto de tests de
    este fichero crean estado con sqlite3 directo cuando hace falta."""
    db_file, sf = db
    repo = AnalyticsRepo(sf)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS captures ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, "
            "timestamp DATETIME NOT NULL, image_path VARCHAR(255))"
        )
        conn.executemany(
            "INSERT INTO captures (person_id, timestamp, image_path) VALUES (?, ?, ?)",
            [
                (1, "2026-01-01 09:00:00.000000", "/data/gallery/1/old.jpg"),
                (1, "2026-01-02 09:00:00.000000", "/data/gallery/1/new.jpg"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    avatars = await repo.person_avatars([1])

    assert avatars == {1: "/gallery/1/new.jpg"}


# --- Fase 36 (SCALE-05): camera_id=None agrega TODAS las camaras ------------------
async def TEST_analytics_hourly_camera_id_none_aggregates_every_camera(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        camera_id="cam1", type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 15)))
    await events.insert(make_event(
        camera_id="cam2", type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 20)))

    rows = await repo.hourly(None, cur_from, cur_to, "hour")

    assert dict((b, cur) for b, cur, _ in rows)["2026-01-02 10"] == 2


async def TEST_analytics_hourly_camera_id_concrete_still_filters(db):
    """camera_id=None es el UNICO valor que agrega -- un id concreto sigue
    filtrando exactamente igual que antes de la Fase 36."""
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        camera_id="cam1", type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 15)))
    await events.insert(make_event(
        camera_id="cam2", type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 10, 15)))

    rows = await repo.hourly("cam1", cur_from, cur_to, "hour")

    assert dict((b, cur) for b, cur, _ in rows)["2026-01-02 10"] == 1


async def TEST_analytics_summary_camera_id_none_aggregates_every_camera(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        camera_id="cam1", type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 4, 0)))
    await events.insert(make_event(
        camera_id="cam2", type=EventType.LINE_CROSSED, ts=datetime.datetime(2026, 1, 2, 5, 0)))

    data = await repo.summary(None, cur_from, cur_to, "hour")

    assert data["total"] == 2


async def TEST_analytics_occupancy_camera_id_none_aggregates_every_camera(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        camera_id="cam1", type=EventType.ZONE_ENTERED, ts=datetime.datetime(2026, 1, 2, 4, 0), zone_id="z1"))
    await events.insert(make_event(
        camera_id="cam2", type=EventType.ZONE_ENTERED, ts=datetime.datetime(2026, 1, 2, 5, 0), zone_id="z1"))

    zones, total = await repo.occupancy(None, cur_from, cur_to)

    assert zones == [{"zone_id": "z1", "name": "z1", "value": 2}]
    assert total == 1


async def TEST_analytics_ranking_camera_id_none_aggregates_every_camera(db):
    _, sf = db
    events = EventRepo(sf)
    repo = AnalyticsRepo(sf)
    cur_from = datetime.datetime(2026, 1, 2, 0, 0, 0)
    cur_to = datetime.datetime(2026, 1, 3, 0, 0, 0)
    await events.insert(make_event(
        camera_id="cam1", type=EventType.PERSON_RECOGNIZED,
        ts=datetime.datetime(2026, 1, 2, 10, 0), person_id=7))
    await events.insert(make_event(
        camera_id="cam2", type=EventType.PERSON_RECOGNIZED,
        ts=datetime.datetime(2026, 1, 2, 11, 0), person_id=7))

    ranking = await repo.persons_ranking(None, cur_from, cur_to)

    assert ranking == [(7, 2, 0)]


# --- Criterio 4 de la Fase 31: las cuatro agregaciones @100k con identidad/zona ----
#
# 0,5s es el presupuesto literal del ROADMAP. Medido en 31-RESEARCH.md: 14-78 ms con
# idx_events_analytics presente (6x-35x de margen), 535-618 ms si el indice desaparece
# -- suficiente margen para no ser flaky y suficiente sensibilidad para detectar la
# regresion real.
_ANALYTICS_BUDGET_SECS = 0.5


def _analytics_repo(db_file) -> tuple:
    """Motor propio sobre la base ya sembrada, para no medir el fixture (mismo
    patron que _perf_repo)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AnalyticsRepo(sf)


async def TEST_analytics_budget_hourly_100k(db):
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1", persons=60, zones=14)
    engine, repo = _analytics_repo(db_file)
    try:
        cur_to = datetime.datetime.now()
        cur_from = cur_to - datetime.timedelta(days=7)
        start = time.perf_counter()
        await repo.hourly("cam1", cur_from, cur_to, "hour")
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert elapsed < _ANALYTICS_BUDGET_SECS, (
        f"hourly tardo {elapsed:.3f}s, presupuesto {_ANALYTICS_BUDGET_SECS}s")


async def TEST_analytics_budget_summary_100k(db):
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1", persons=60, zones=14)
    engine, repo = _analytics_repo(db_file)
    try:
        cur_to = datetime.datetime.now()
        cur_from = cur_to - datetime.timedelta(days=7)
        start = time.perf_counter()
        await repo.summary("cam1", cur_from, cur_to, "hour")
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert elapsed < _ANALYTICS_BUDGET_SECS, (
        f"summary tardo {elapsed:.3f}s, presupuesto {_ANALYTICS_BUDGET_SECS}s")


async def TEST_analytics_budget_occupancy_100k(db):
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1", persons=60, zones=14)
    engine, repo = _analytics_repo(db_file)
    try:
        cur_to = datetime.datetime.now()
        cur_from = cur_to - datetime.timedelta(days=7)
        start = time.perf_counter()
        await repo.occupancy("cam1", cur_from, cur_to)
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert elapsed < _ANALYTICS_BUDGET_SECS, (
        f"occupancy tardo {elapsed:.3f}s, presupuesto {_ANALYTICS_BUDGET_SECS}s")


async def TEST_analytics_budget_persons_ranking_100k(db):
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1", persons=60, zones=14)
    engine, repo = _analytics_repo(db_file)
    try:
        cur_to = datetime.datetime.now()
        cur_from = cur_to - datetime.timedelta(days=7)
        start = time.perf_counter()
        await repo.persons_ranking("cam1", cur_from, cur_to)
        elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    assert elapsed < _ANALYTICS_BUDGET_SECS, (
        f"persons_ranking tardo {elapsed:.3f}s, presupuesto {_ANALYTICS_BUDGET_SECS}s")


async def TEST_analytics_budget_ranking_sees_seeded_persons(db):
    """Sin esto, si seed_events volviera a dejar person_id a NULL, el test de
    presupuesto mediria sobre datos vacios y pasaria por accidente."""
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1", persons=60, zones=14)
    engine, repo = _analytics_repo(db_file)
    try:
        cur_to = datetime.datetime.now()
        cur_from = cur_to - datetime.timedelta(days=7)
        ranking = await repo.persons_ranking("cam1", cur_from, cur_to)
    finally:
        await engine.dispose()

    assert len(ranking) == 10
    assert sum(cur for _, cur, _ in ranking) > 0


async def TEST_analytics_budget_occupancy_sees_seeded_zones(db):
    """Misma guarda que la anterior, para ocupacion: sin zone_id sembrado, el
    presupuesto mediria sobre una lista vacia y pasaria por accidente."""
    db_file, _ = db
    seed_events(db_file, n=100_000, days=30, camera_id="cam1", persons=60, zones=14)
    engine, repo = _analytics_repo(db_file)
    try:
        cur_to = datetime.datetime.now()
        cur_from = cur_to - datetime.timedelta(days=7)
        zones, total_zones = await repo.occupancy("cam1", cur_from, cur_to)
    finally:
        await engine.dispose()

    assert len(zones) == 10
    assert total_zones == 14


async def TEST_analytics_budget_ranking_uses_analytics_index(db):
    """Guarda temprana del hint: si SQLite deja de usar idx_events_analytics en el
    ranking, este test lo detecta antes que un presupuesto @100k que se
    degradaria de forma silenciosa (26,7 ms -> 212,6 ms, sigue bajo los 500 ms
    del criterio 4 -- no habria fallado el test de presupuesto)."""
    db_file, _ = db
    sql = (
        "EXPLAIN QUERY PLAN "
        "SELECT person_id, "
        "SUM(CASE WHEN ts >= '2026-01-08 00:00:00' THEN 1 ELSE 0 END) AS cur, "
        "SUM(CASE WHEN ts <  '2026-01-08 00:00:00' THEN 1 ELSE 0 END) AS prev "
        "FROM events INDEXED BY idx_events_analytics "
        "WHERE camera_id = 'cam1' AND ts >= '2026-01-01 00:00:00' AND ts < '2026-01-15 00:00:00' "
        "AND person_id IS NOT NULL "
        "GROUP BY person_id HAVING cur > 0 ORDER BY cur DESC LIMIT 10"
    )
    conn = sqlite3.connect(db_file)
    try:
        plan = " ".join(str(row) for row in conn.execute(sql))
    finally:
        conn.close()

    assert "idx_events_analytics" in plan, plan


# --- Fase 33 (OPS-22/OPS-23/RULE-05): LineRepo + RuleRepo.get() -------------------


async def TEST_LineRepo_list_empty_db_returns_empty_list(db):
    _, sf = db
    repo = LineRepo(sf)

    assert await repo.list() == []


async def TEST_LineRepo_upsert_creates_then_updates_existing(db):
    _, sf = db
    repo = LineRepo(sf)

    await repo.upsert("l1", "cam1", "Entrada", 0.1, 0.2, 0.9, 0.8, enabled=True)
    lines = await repo.list()
    assert lines == [{
        "id": "l1", "camera_id": "cam1", "name": "Entrada",
        "start_x_frac": 0.1, "start_y_frac": 0.2,
        "end_x_frac": 0.9, "end_y_frac": 0.8, "enabled": True,
    }]

    await repo.upsert("l1", "cam1", "Salida", 0.0, 0.0, 1.0, 1.0, enabled=False)
    lines = await repo.list()
    assert len(lines) == 1
    assert lines[0]["name"] == "Salida"
    assert lines[0]["enabled"] is False


async def TEST_LineRepo_list_filters_by_camera_id(db):
    _, sf = db
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))
    repo = LineRepo(sf)
    await repo.upsert("l1", "cam1", "L1", 0.0, 0.0, 1.0, 1.0)
    await repo.upsert("l2", "cam2", "L2", 0.0, 0.0, 1.0, 1.0)

    lines = await repo.list(camera_id="cam1")

    assert [l["id"] for l in lines] == ["l1"]


async def TEST_LineRepo_delete_returns_true_then_false(db):
    _, sf = db
    repo = LineRepo(sf)
    await repo.upsert("l1", "cam1", "L1", 0.0, 0.0, 1.0, 1.0)

    assert await repo.delete("l1") is True
    assert await repo.delete("l1") is False
    assert await repo.list() == []


async def TEST_rule_get_hit_returns_dict(db):
    _, sf = db
    repo = RuleRepo(sf)
    await repo.upsert("r1", "Regla 1", True, {"when": {"event": "INTRUSION"}, "actions": []})

    rule = await repo.get("r1")

    assert rule["id"] == "r1"
    assert rule["name"] == "Regla 1"
    assert rule["enabled"] is True
    assert rule["definition"] == {"when": {"event": "INTRUSION"}, "actions": []}


async def TEST_rule_get_miss_returns_none(db):
    _, sf = db
    repo = RuleRepo(sf)

    assert await repo.get("does-not-exist") is None


# ─── Fase 35 (SCALE-03): CameraRepo.default_camera_id ────────────────────────
async def TEST_camera_repo_default_id_with_exactly_one_camera(db):
    _, sf = db  # el fixture ya siembra una unica camara 'cam1'
    repo = CameraRepo(sf)

    assert await repo.default_camera_id() == "cam1"


async def TEST_camera_repo_default_id_is_none_with_zero_cameras(db):
    db_file, sf = db
    async with sf() as session:
        async with session.begin():
            await session.execute(models.Camera.__table__.delete())
    repo = CameraRepo(sf)

    assert await repo.default_camera_id() is None


async def TEST_camera_repo_default_id_is_none_with_two_cameras(db):
    _, sf = db
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))
    repo = CameraRepo(sf)

    assert await repo.default_camera_id() is None


# ─── Fase 36 (SCALE-05): CameraRepo CRUD ──────────────────────────────────────
async def TEST_camera_repo_list_returns_all_cameras(db):
    _, sf = db  # el fixture ya siembra 'cam1'
    repo = CameraRepo(sf)

    cameras = await repo.list()

    assert [c["id"] for c in cameras] == ["cam1"]


async def TEST_camera_repo_list_filters_by_enabled(db):
    _, sf = db
    repo = CameraRepo(sf)
    await repo.create("cam2", "Cam 2", "rtsp://cam2/stream", enabled=False)

    assert [c["id"] for c in await repo.list(enabled=True)] == ["cam1"]
    assert [c["id"] for c in await repo.list(enabled=False)] == ["cam2"]


async def TEST_camera_repo_create_persists_all_fields(db):
    _, sf = db
    repo = CameraRepo(sf)

    created = await repo.create(
        "cam2", "Entrada trasera", "rtsp://user:pass@host/stream",
        enabled=True, process_w=640, process_h=480,
    )

    assert created["id"] == "cam2"
    assert created["name"] == "Entrada trasera"
    assert created["rtsp_url"] == "rtsp://user:pass@host/stream"
    assert created["enabled"] is True
    assert created["process_w"] == 640
    assert created["process_h"] == 480

    fetched = await repo.get("cam2")
    assert fetched == created


async def TEST_camera_repo_get_miss_returns_none(db):
    _, sf = db
    repo = CameraRepo(sf)

    assert await repo.get("does-not-exist") is None


async def TEST_camera_repo_update_partial_fields_only(db):
    _, sf = db
    repo = CameraRepo(sf)
    await repo.create("cam2", "Cam 2", "rtsp://cam2/stream")

    updated = await repo.update("cam2", name="Renombrada")

    assert updated["name"] == "Renombrada"
    assert updated["rtsp_url"] == "rtsp://cam2/stream"  # sin tocar


async def TEST_camera_repo_update_unknown_camera_returns_none(db):
    _, sf = db
    repo = CameraRepo(sf)

    assert await repo.update("does-not-exist", name="X") is None


async def TEST_camera_repo_delete_removes_row(db):
    _, sf = db
    repo = CameraRepo(sf)
    await repo.create("cam2", "Cam 2", "rtsp://cam2/stream")

    assert await repo.delete("cam2") is True
    assert await repo.get("cam2") is None


async def TEST_camera_repo_delete_unknown_camera_returns_false(db):
    _, sf = db
    repo = CameraRepo(sf)

    assert await repo.delete("does-not-exist") is False
