"""Repositories: every SQL query in the project lives here (verified by grep in Phase 37).

Reconstructs backend.events.types.Event objects from storage.models.Event rows and
back — the Pydantic Event is the single contract; these are just its persisted shape.
"""

from __future__ import annotations

import base64
import datetime
import json
from typing import Any

from sqlalchemy import and_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.events.types import Event as EventDTO
from backend.events.types import EventType, Severity
from backend.storage import models


def _encode_cursor(ts: datetime.datetime, id_: str) -> str:
    raw = f"{ts.isoformat()}|{id_}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime.datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_ = raw.split("|", 1)
    return datetime.datetime.fromisoformat(ts_str), id_


class EventRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    @staticmethod
    def _to_row(event: EventDTO) -> models.Event:
        return models.Event(
            id=event.id,
            camera_id=event.camera_id,
            type=event.type.value,
            ts=event.ts,
            severity=event.severity.value,
            track_id=event.track_id,
            person_id=event.person_id,
            zone_id=event.zone_id,
            confidence=event.confidence,
            bbox=json.dumps(list(event.bbox)) if event.bbox else None,
            snapshot_path=event.snapshot_path,
            recording_id=event.recording_id,
            payload=event.payload,
        )

    @staticmethod
    def _to_dto(row: models.Event) -> EventDTO:
        return EventDTO(
            id=row.id,
            type=EventType(row.type),
            camera_id=row.camera_id,
            ts=row.ts,
            severity=Severity(row.severity),
            track_id=row.track_id,
            person_id=row.person_id,
            zone_id=row.zone_id,
            confidence=row.confidence,
            bbox=tuple(json.loads(row.bbox)) if row.bbox else None,
            snapshot_path=row.snapshot_path,
            recording_id=row.recording_id,
            payload=row.payload or {},
        )

    async def insert(self, event: EventDTO) -> None:
        async with self._sf() as session:
            async with session.begin():
                session.add(self._to_row(event))

    async def get(self, event_id: str) -> EventDTO | None:
        async with self._sf() as session:
            row = await session.get(models.Event, event_id)
            return self._to_dto(row) if row is not None else None

    async def query(
        self,
        *,
        type: EventType | None = None,
        severity: Severity | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
        camera_id: str | None = None,
        ts_from: datetime.datetime | None = None,
        ts_to: datetime.datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[EventDTO], str | None]:
        """Filter + cursor-paginate, newest first. Cursor is (ts, id) base64-encoded."""
        conditions = []
        if type is not None:
            conditions.append(models.Event.type == type.value)
        if severity is not None:
            conditions.append(models.Event.severity == severity.value)
        if person_id is not None:
            conditions.append(models.Event.person_id == person_id)
        if zone_id is not None:
            conditions.append(models.Event.zone_id == zone_id)
        if camera_id is not None:
            conditions.append(models.Event.camera_id == camera_id)
        if ts_from is not None:
            conditions.append(models.Event.ts >= ts_from)
        if ts_to is not None:
            conditions.append(models.Event.ts <= ts_to)
        if cursor is not None:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            conditions.append(
                tuple_(models.Event.ts, models.Event.id) < tuple_(cursor_ts, cursor_id)
            )

        q = (
            select(models.Event)
            .order_by(models.Event.ts.desc(), models.Event.id.desc())
            .limit(limit)
        )
        if conditions:
            q = q.where(and_(*conditions))

        async with self._sf() as session:
            result = await session.execute(q)
            rows = list(result.scalars().all())

        items = [self._to_dto(r) for r in rows]
        next_cursor = _encode_cursor(rows[-1].ts, rows[-1].id) if len(rows) == limit else None
        return items, next_cursor


class DetectionStatRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def upsert_minute(
        self,
        camera_id: str,
        minute: datetime.datetime,
        detections: int,
        unique_tracks: int,
        avg_confidence: float | None,
        max_concurrent: int,
    ) -> None:
        """Accumulate into the row for this (camera_id, minute) — never a row per detection."""
        minute = minute.replace(second=0, microsecond=0)
        async with self._sf() as session:
            async with session.begin():
                result = await session.execute(
                    select(models.DetectionStat).where(
                        models.DetectionStat.camera_id == camera_id,
                        models.DetectionStat.minute == minute,
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    session.add(
                        models.DetectionStat(
                            camera_id=camera_id,
                            minute=minute,
                            detections=detections,
                            unique_tracks=unique_tracks,
                            avg_confidence=avg_confidence,
                            max_concurrent=max_concurrent,
                        )
                    )
                else:
                    row.detections += detections
                    row.unique_tracks = max(row.unique_tracks, unique_tracks)
                    row.max_concurrent = max(row.max_concurrent, max_concurrent)
                    if avg_confidence is not None:
                        row.avg_confidence = (
                            avg_confidence
                            if row.avg_confidence is None
                            else (row.avg_confidence + avg_confidence) / 2
                        )

    async def recent(self, camera_id: str, limit: int = 60) -> list[dict[str, Any]]:
        async with self._sf() as session:
            result = await session.execute(
                select(models.DetectionStat)
                .where(models.DetectionStat.camera_id == camera_id)
                .order_by(models.DetectionStat.minute.desc())
                .limit(limit)
            )
            return [
                {
                    "minute": r.minute.isoformat(),
                    "detections": r.detections,
                    "unique_tracks": r.unique_tracks,
                    "avg_confidence": r.avg_confidence,
                    "max_concurrent": r.max_concurrent,
                }
                for r in result.scalars().all()
            ]


class RecordingRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def insert(self, **fields: Any) -> int:
        async with self._sf() as session:
            async with session.begin():
                rec = models.Recording(**fields)
                session.add(rec)
                await session.flush()
                return int(rec.id)

    async def get(self, recording_id: int) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(models.Recording, recording_id)
            return self._to_dict(row) if row is not None else None

    async def update_upload_state(
        self, recording_id: int, upload_state: str, drive_file_id: str | None = None
    ) -> None:
        async with self._sf() as session:
            async with session.begin():
                row = await session.get(models.Recording, recording_id)
                if row is not None:
                    row.upload_state = upload_state
                    row.upload_attempts += 1
                    if drive_file_id is not None:
                        row.drive_file_id = drive_file_id

    async def recent(self, camera_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        q = select(models.Recording).order_by(models.Recording.started_at.desc()).limit(limit)
        if camera_id is not None:
            q = q.where(models.Recording.camera_id == camera_id)
        async with self._sf() as session:
            result = await session.execute(q)
            return [self._to_dict(r) for r in result.scalars().all()]

    @staticmethod
    def _to_dict(row: models.Recording) -> dict[str, Any]:
        return {
            "id": row.id,
            "camera_id": row.camera_id,
            "filename": row.filename,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "duration_s": row.duration_s,
            "upload_state": row.upload_state,
            "upload_attempts": row.upload_attempts,
            "drive_file_id": row.drive_file_id,
        }


class ZoneRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def list(self, camera_id: str | None = None) -> list[dict[str, Any]]:
        q = select(models.Zone)
        if camera_id is not None:
            q = q.where(models.Zone.camera_id == camera_id)
        async with self._sf() as session:
            result = await session.execute(q)
            return [self._to_dict(z) for z in result.scalars().all()]

    async def upsert(
        self, zone_id: str, camera_id: str, name: str, polygon: list, kind: str | None = None,
        schedule: dict | None = None, enabled: bool = True,
    ) -> None:
        async with self._sf() as session:
            async with session.begin():
                existing = await session.get(models.Zone, zone_id)
                if existing:
                    existing.camera_id = camera_id
                    existing.name = name
                    existing.polygon = polygon
                    existing.kind = kind
                    existing.schedule = schedule
                    existing.enabled = enabled
                else:
                    session.add(models.Zone(
                        id=zone_id, camera_id=camera_id, name=name, polygon=polygon,
                        kind=kind, schedule=schedule, enabled=enabled,
                    ))

    async def delete(self, zone_id: str) -> bool:
        async with self._sf() as session:
            async with session.begin():
                z = await session.get(models.Zone, zone_id)
                if z:
                    await session.delete(z)
                    return True
        return False

    @staticmethod
    def _to_dict(z: models.Zone) -> dict[str, Any]:
        return {
            "id": z.id, "camera_id": z.camera_id, "name": z.name,
            "polygon": z.polygon, "kind": z.kind, "schedule": z.schedule,
            "enabled": bool(z.enabled),
        }


class RuleRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def list(self) -> list[dict[str, Any]]:
        async with self._sf() as session:
            result = await session.execute(select(models.Rule))
            return [self._to_dict(r) for r in result.scalars().all()]

    async def upsert(self, rule_id: str, name: str, enabled: bool, definition: dict) -> None:
        async with self._sf() as session:
            async with session.begin():
                existing = await session.get(models.Rule, rule_id)
                now = datetime.datetime.now()
                if existing:
                    existing.name = name
                    existing.enabled = enabled
                    existing.definition = definition
                    existing.updated_at = now
                else:
                    session.add(models.Rule(
                        id=rule_id, name=name, enabled=enabled,
                        definition=definition, updated_at=now,
                    ))

    async def delete(self, rule_id: str) -> bool:
        async with self._sf() as session:
            async with session.begin():
                r = await session.get(models.Rule, rule_id)
                if r:
                    await session.delete(r)
                    return True
        return False

    @staticmethod
    def _to_dict(r: models.Rule) -> dict[str, Any]:
        return {
            "id": r.id, "name": r.name, "enabled": bool(r.enabled),
            "definition": r.definition, "updated_at": r.updated_at.isoformat(),
        }


class ConfigRepo:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._sf() as session:
            row = await session.get(models.AppConfig, key)
            return row.value if row is not None else default

    async def set(self, key: str, value: Any) -> None:
        async with self._sf() as session:
            async with session.begin():
                row = await session.get(models.AppConfig, key)
                now = datetime.datetime.now()
                if row is None:
                    session.add(models.AppConfig(key=key, value=value, updated_at=now))
                else:
                    row.value = value
                    row.updated_at = now

    async def get_all(self) -> dict[str, Any]:
        async with self._sf() as session:
            result = await session.execute(select(models.AppConfig))
            return {r.key: r.value for r in result.scalars().all()}
