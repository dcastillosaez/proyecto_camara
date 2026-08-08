"""Legacy crossing-event API — delegates to backend.storage.repositories (schema v2).

Kept for backward compatibility with existing endpoints: return shapes (dicts
with id/timestamp/direction/person_name/is_intrusion) are unchanged, but
storage now goes through EventRepo against the typed `events` table instead of
the old dedicated crossing-events table (see backend/storage/migrations.py —
the v1 table is renamed to `crossing_events` and kept as a hot backup).

Zones/captures/recordings are untouched by the v2 migration beyond an added
`camera_id` column, so their functions still use direct ORM queries here.
"""

from __future__ import annotations

import datetime
import os
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, and_, create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import get_settings
from backend.events.types import Event, EventType
from backend.storage.migrations import run_migrations
from backend.storage.repositories import EventRepo

# ---------------------------------------------------------------------------
# Schema — zones/captures/recordings only.
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Zone(Base):
    __tablename__ = "zones"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    polygon_json = Column(String, nullable=False)  # JSON: [[x_frac, y_frac], ...]
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)


class Capture(Base):
    __tablename__ = "captures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    image_path = Column(String(255), nullable=True)


class Recording(Base):
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    gdrive_id = Column(String(100), nullable=True)
    upload_status = Column(String(20), nullable=False, default="pending")  # pending|uploaded|failed
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    duration_secs = Column(Float, nullable=True)


# ---------------------------------------------------------------------------
# Engine / session factory (lazy singletons)
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        db_path = get_settings().db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            _get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


def _event_repo() -> EventRepo:
    return EventRepo(_get_session_factory())


def get_session_factory():
    """Expose the async session factory for other repositories (main.py wiring)."""
    return _get_session_factory()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Migrate to schema v2 (idempotent) and enable WAL mode. Call once at startup."""
    engine = _get_engine()
    db_path = engine.url.database
    if db_path and db_path != ":memory:":
        sync_engine = create_engine(f"sqlite:///{db_path}")
        try:
            run_migrations(sync_engine)
        finally:
            sync_engine.dispose()

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        # No-op for zones/recordings (already created/extended by run_migrations);
        # creates `captures`, which has no v2 equivalent model.
        await conn.run_sync(Base.metadata.create_all)


def _event_to_legacy_dict(event: Event) -> dict[str, Any]:
    payload = event.payload or {}
    return {
        "id": event.id,
        "timestamp": event.ts.isoformat(),
        "direction": payload.get("direction", "?"),
        "person_name": payload.get("person_name"),
        "is_intrusion": bool(payload.get("is_intrusion", False)),
    }


async def insert_event(
    direction: str,
    timestamp: datetime.datetime | None = None,
    person_name: str | None = None,
    is_intrusion: bool = False,
) -> None:
    """Persist one crossing event (non-blocking) as a typed LINE_CROSSED event."""
    ts = timestamp or datetime.datetime.now()
    event = Event(
        type=EventType.LINE_CROSSED,
        camera_id="cam1",
        ts=ts,
        payload={
            "direction": direction,
            "person_name": person_name,
            "is_intrusion": bool(is_intrusion),
        },
    )
    await _event_repo().insert(event)


async def get_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return the *limit* most recent crossing events, newest first."""
    items, _ = await _event_repo().query(type=EventType.LINE_CROSSED, limit=limit)
    return [_event_to_legacy_dict(e) for e in items]


async def get_events_filtered(
    limit: int = 200,
    direction: str | None = None,
    person_name: str | None = None,
    is_intrusion: bool | None = None,
    from_dt: datetime.datetime | None = None,
    to_dt: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """Return crossing events matching the supplied filters, newest first.

    direction/person_name/is_intrusion live in Event.payload, which EventRepo
    doesn't filter on at the SQL level, so they're applied here in Python
    after a type+range query. Fine at this project's event volume (decenas/dia).
    """
    repo = _event_repo()
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    scanned = 0
    while len(results) < limit and scanned < 5000:
        items, cursor = await repo.query(
            type=EventType.LINE_CROSSED,
            ts_from=from_dt,
            ts_to=to_dt,
            cursor=cursor,
            limit=min(200, max(limit * 2, 50)),
        )
        if not items:
            break
        scanned += len(items)
        for e in items:
            d = _event_to_legacy_dict(e)
            if direction in ("in", "out") and d["direction"] != direction:
                continue
            if person_name is not None and person_name.lower() not in (d["person_name"] or "").lower():
                continue
            if is_intrusion is not None and d["is_intrusion"] != is_intrusion:
                continue
            results.append(d)
            if len(results) >= limit:
                break
        if cursor is None:
            break
    return results


async def get_stats_today() -> dict[str, Any]:
    """Total crossings today + hourly breakdown for the last 24 h."""
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = datetime.datetime.now() - datetime.timedelta(hours=24)

    repo = _event_repo()
    total = await repo.count_since(today_start, type=EventType.LINE_CROSSED)
    hourly = await repo.hourly_counts(since_24h, type=EventType.LINE_CROSSED)
    return {"total_today": total, "hourly": hourly}


async def purge_old_events(retention_days: int) -> int:
    """Delete crossing events older than *retention_days*. Returns deleted count."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)
    return await _event_repo().delete_before(cutoff, type=EventType.LINE_CROSSED)


async def delete_events_range(from_dt: datetime.datetime, to_dt: datetime.datetime) -> int:
    """Delete crossing events in [from_dt, to_dt]. Returns number of deleted rows."""
    return await _event_repo().delete_range(from_dt, to_dt, type=EventType.LINE_CROSSED)


async def insert_recording(filename: str, created_at: datetime.datetime | None = None) -> int:
    """Persist a new recording row with status='pending'. Returns the row id."""
    ts = created_at or datetime.datetime.now()
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            rec = Recording(filename=filename, created_at=ts, upload_status="pending")
            session.add(rec)
            await session.flush()
            return int(rec.id)


async def update_recording(
    rec_id: int,
    upload_status: str,
    gdrive_id: str | None = None,
) -> None:
    """Update upload_status (and optionally gdrive_id) for a recording row."""
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            rec = await session.get(Recording, rec_id)
            if rec:
                rec.upload_status = upload_status
                if gdrive_id is not None:
                    rec.gdrive_id = gdrive_id


async def get_recent_recordings(limit: int = 20) -> list[dict[str, Any]]:
    """Return the *limit* most recent recordings, newest first."""
    sf = _get_session_factory()
    async with sf() as session:
        result = await session.execute(
            select(Recording).order_by(Recording.created_at.desc()).limit(limit)
        )
        return [
            {
                "id": r.id,
                "filename": r.filename,
                "gdrive_id": r.gdrive_id,
                "upload_status": r.upload_status,
                "created_at": r.created_at.isoformat(),
            }
            for r in result.scalars().all()
        ]


async def delete_recordings_range(from_dt: datetime.datetime, to_dt: datetime.datetime) -> int:
    """Delete recordings created in [from_dt, to_dt]. Returns number of deleted rows."""
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            result = await session.execute(
                select(Recording).where(
                    Recording.created_at >= from_dt,
                    Recording.created_at <= to_dt,
                )
            )
            rows = result.scalars().all()
            count = len(rows)
            for row in rows:
                await session.delete(row)
    return count


async def get_zones() -> list[dict[str, Any]]:
    """Return all zones ordered by creation date."""
    sf = _get_session_factory()
    async with sf() as session:
        result = await session.execute(select(Zone).order_by(Zone.created_at))
        return [
            {
                "id": z.id,
                "name": z.name,
                "polygon_json": z.polygon_json,
                "enabled": bool(z.enabled),
                "created_at": z.created_at.isoformat(),
            }
            for z in result.scalars().all()
        ]


async def upsert_zone(
    zone_id: str,
    name: str,
    polygon_json: str,
    enabled: bool = True,
) -> None:
    """Insert or update a zone by id."""
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            existing = await session.get(Zone, zone_id)
            if existing:
                existing.name = name
                existing.polygon_json = polygon_json
                existing.enabled = enabled
            else:
                session.add(Zone(
                    id=zone_id, name=name, polygon_json=polygon_json,
                    enabled=enabled, created_at=datetime.datetime.now(),
                ))


async def delete_zone(zone_id: str) -> bool:
    """Delete a zone by id. Returns True if it existed."""
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            z = await session.get(Zone, zone_id)
            if z:
                await session.delete(z)
                return True
    return False


async def insert_capture(
    person_id: int,
    timestamp: datetime.datetime,
    image_path: str,
) -> int:
    """Persist a gallery capture. Returns the row id."""
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            cap = Capture(person_id=person_id, timestamp=timestamp, image_path=image_path)
            session.add(cap)
            await session.flush()
            return int(cap.id)


async def get_captures_for_person(person_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Return the *limit* most recent captures for a person, newest first."""
    sf = _get_session_factory()
    async with sf() as session:
        result = await session.execute(
            select(Capture)
            .where(Capture.person_id == person_id)
            .order_by(Capture.timestamp.desc())
            .limit(limit)
        )
        return [
            {
                "id": c.id,
                "person_id": c.person_id,
                "timestamp": c.timestamp.isoformat(),
                "image_path": c.image_path,
            }
            for c in result.scalars().all()
        ]


async def purge_old_recordings(retention_days: int) -> int:
    """Delete recording rows older than *retention_days*. Returns deleted count."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            result = await session.execute(
                select(Recording).where(Recording.created_at < cutoff)
            )
            rows = result.scalars().all()
            count = len(rows)
            for row in rows:
                await session.delete(row)
    return count
