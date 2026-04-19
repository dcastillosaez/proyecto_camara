"""SQLite async persistence — events table, WAL mode."""

from __future__ import annotations

import datetime
import os
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import get_settings

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class CrossingEvent(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    direction = Column(String(3), nullable=False)  # "in" | "out"
    person_name = Column(String(100), nullable=True)


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create tables and enable WAL mode. Call once at startup."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
        # Migrate: add person_name column if it doesn't exist yet
        try:
            await conn.execute(text("ALTER TABLE events ADD COLUMN person_name VARCHAR(100)"))
        except Exception:
            pass  # Column already exists


async def insert_event(
    direction: str,
    timestamp: datetime.datetime | None = None,
    person_name: str | None = None,
) -> None:
    """Persist one crossing event (non-blocking)."""
    ts = timestamp or datetime.datetime.now()
    sf = _get_session_factory()
    async with sf() as session:
        async with session.begin():
            session.add(CrossingEvent(timestamp=ts, direction=direction, person_name=person_name))


async def get_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return the *limit* most recent events, newest first."""
    sf = _get_session_factory()
    async with sf() as session:
        result = await session.execute(
            select(CrossingEvent).order_by(CrossingEvent.timestamp.desc()).limit(limit)
        )
        return [
            {"id": r.id, "timestamp": r.timestamp.isoformat(), "direction": r.direction, "person_name": r.person_name}
            for r in result.scalars().all()
        ]


async def get_stats_today() -> dict[str, Any]:
    """Total crossings today + hourly breakdown for the last 24 h."""
    sf = _get_session_factory()
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = datetime.datetime.now() - datetime.timedelta(hours=24)

    async with sf() as session:
        total = (
            await session.execute(
                select(func.count()).where(CrossingEvent.timestamp >= today_start)
            )
        ).scalar() or 0

        rows = (
            await session.execute(
                select(
                    func.strftime("%H", CrossingEvent.timestamp).label("hour"),
                    func.count().label("count"),
                )
                .where(CrossingEvent.timestamp >= since_24h)
                .group_by(text("hour"))
                .order_by(text("hour"))
            )
        ).all()

        hourly = {row.hour: row.count for row in rows}

    return {"total_today": total, "hourly": hourly}
