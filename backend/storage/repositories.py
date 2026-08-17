"""Repositories: every SQL query in the project lives here (verified by grep in Phase 37).

Reconstructs backend.events.types.Event objects from storage.models.Event rows and
back — the Pydantic Event is the single contract; these are just its persisted shape.
"""

from __future__ import annotations

import base64
import datetime
import json
from enum import Enum
from typing import Any

from sqlalchemy import and_, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.events.types import Event as EventDTO
from backend.events.types import EventType, Severity
from backend.storage import models


class UploadState(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


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

    async def count_since(self, ts_from: datetime.datetime, type: EventType | None = None) -> int:
        conditions = [models.Event.ts >= ts_from]
        if type is not None:
            conditions.append(models.Event.type == type.value)
        async with self._sf() as session:
            result = await session.execute(
                select(func.count()).select_from(models.Event).where(and_(*conditions))
            )
            return result.scalar() or 0

    async def hourly_counts(
        self, ts_from: datetime.datetime, type: EventType | None = None
    ) -> dict[str, int]:
        conditions = [models.Event.ts >= ts_from]
        if type is not None:
            conditions.append(models.Event.type == type.value)
        async with self._sf() as session:
            result = await session.execute(
                select(
                    func.strftime("%H", models.Event.ts).label("hour"),
                    func.count().label("count"),
                )
                .where(and_(*conditions))
                .group_by(text("hour"))
                .order_by(text("hour"))
            )
            return {row.hour: row.count for row in result.all()}

    async def delete_before(self, cutoff: datetime.datetime, type: EventType | None = None) -> int:
        conditions = [models.Event.ts < cutoff]
        if type is not None:
            conditions.append(models.Event.type == type.value)
        async with self._sf() as session:
            async with session.begin():
                result = await session.execute(select(models.Event).where(and_(*conditions)))
                rows = result.scalars().all()
                for row in rows:
                    await session.delete(row)
        return len(rows)

    async def delete_range(
        self, from_dt: datetime.datetime, to_dt: datetime.datetime, type: EventType | None = None
    ) -> int:
        conditions = [models.Event.ts >= from_dt, models.Event.ts <= to_dt]
        if type is not None:
            conditions.append(models.Event.type == type.value)
        async with self._sf() as session:
            async with session.begin():
                result = await session.execute(select(models.Event).where(and_(*conditions)))
                rows = result.scalars().all()
                for row in rows:
                    await session.delete(row)
        return len(rows)


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

    async def hourly_baseline(
        self,
        camera_id: str,
        since: datetime.datetime,
        until: datetime.datetime | None = None,
    ) -> dict[str, dict[str, float]]:
        """Media movil por franja horaria sobre los ultimos N dias (BEH-09, D-02).

        Dos niveles de agregacion, y el orden importa: primero se SUMA por (dia, hora) y
        solo despues se PROMEDIA entre dias. Promediar directamente sobre las filas de
        minuto daria "media por minuto", no "media por hora", y ademas ponderaria mas los
        dias con mas minutos registrados.

        Se agrupa sobre `unique_tracks`, no sobre `detections`: detections acumula
        len(active_track_ids) UNA VEZ POR FRAME PROCESADO (engine.py:281), asi que depende
        del FPS efectivo que AdaptiveRate haya elegido y no es comparable entre dias con
        distinta carga de CPU. `unique_tracks` mide flujo de personas distintas, que es la
        semantica de "nivel de actividad" acordada con el usuario.

        `until` acota la ventana por arriba para que la hora EN CURSO (parcial) no
        contamine su propio baseline. El endpoint llama a este metodo dos veces: una con
        (now - N dias, inicio de la hora en curso) para el baseline y otra con
        (inicio de la hora en curso, None) para el "ahora".

        strftime() es especifico de SQLite; ya hay precedente en EventRepo.hourly_counts
        (repositories.py:162). El proyecto es SQLite-only. Coste medido en 27-RESEARCH Q7:
        p50 de 11,2 ms sobre 525.600 filas (un año) usando el indice unico
        (camera_id, minute) que ya existe — NO hace falta indice nuevo, el WHERE se
        resuelve con un range scan y los strftime se evaluan solo sobre las filas ya
        filtradas.
        """
        conditions = [
            models.DetectionStat.camera_id == camera_id,
            models.DetectionStat.minute >= since,
        ]
        if until is not None:
            conditions.append(models.DetectionStat.minute < until)
        per_day = (
            select(
                func.strftime("%Y-%m-%d", models.DetectionStat.minute).label("day"),
                func.strftime("%H", models.DetectionStat.minute).label("hour"),
                func.sum(models.DetectionStat.unique_tracks).label("total"),
                func.count().label("mins"),
            )
            .where(and_(*conditions))
            .group_by(text("day"), text("hour"))
            .subquery()
        )
        stmt = (
            select(
                per_day.c.hour,
                func.avg(per_day.c.total).label("avg_total"),
                func.count().label("sample_days"),
                func.sum(per_day.c.mins).label("mins"),
            )
            .group_by(per_day.c.hour)
            .order_by(per_day.c.hour)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {
                row.hour: {
                    "avg_total": float(row.avg_total),
                    "sample_days": int(row.sample_days),
                    "mins": int(row.mins),
                    "avg_per_minute": float(row.avg_total) / max(1.0, row.mins / row.sample_days),
                }
                for row in result.all()
            }


class RecordingRepo:
    """Owns the recordings table: clip metadata, upload-queue state, retention."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def create(
        self,
        camera_id: str,
        filename: str,
        started_at: datetime.datetime,
        reason: str,
        trigger_event_id: str | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
    ) -> int:
        async with self._sf() as session:
            async with session.begin():
                rec = models.Recording(
                    camera_id=camera_id,
                    filename=filename,
                    local_path=filename,
                    started_at=started_at,
                    reason=reason,
                    trigger_event_id=trigger_event_id,
                    person_id=person_id,
                    zone_id=zone_id,
                )
                session.add(rec)
                await session.flush()
                return int(rec.id)

    async def finalize(
        self,
        rec_id: int,
        ended_at: datetime.datetime,
        duration_s: float,
        size_bytes: int,
        sha256: str,
        thumbnail_path: str | None,
        upload_state: UploadState,
    ) -> None:
        state = upload_state.value if isinstance(upload_state, UploadState) else upload_state
        async with self._sf() as session:
            async with session.begin():
                row = await session.get(models.Recording, rec_id)
                if row is None:
                    return
                row.ended_at = ended_at
                row.duration_s = duration_s
                row.size_bytes = size_bytes
                row.sha256 = sha256
                row.thumbnail_path = thumbnail_path
                row.upload_state = state
                if state == UploadState.PENDING.value:
                    row.next_attempt_at = datetime.datetime.now()

    async def next_pending(self, limit: int = 5) -> list[models.Recording]:
        """Pending uploads whose backoff window has elapsed, oldest first."""
        now = datetime.datetime.now()
        async with self._sf() as session:
            result = await session.execute(
                select(models.Recording)
                .where(
                    models.Recording.upload_state == UploadState.PENDING.value,
                    (models.Recording.next_attempt_at.is_(None))
                    | (models.Recording.next_attempt_at <= now),
                )
                .order_by(models.Recording.started_at)
                .limit(limit)
            )
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows

    async def count_by_upload_state(self, state: UploadState) -> int:
        """Cheap COUNT for the metrics sampler (upload_queue_depth)."""
        async with self._sf() as session:
            result = await session.execute(
                select(func.count()).select_from(models.Recording).where(
                    models.Recording.upload_state == state.value
                )
            )
            return result.scalar() or 0

    async def mark_upload(
        self,
        rec_id: int,
        state: UploadState,
        drive_file_id: str | None = None,
        error: str | None = None,
        next_attempt_at: datetime.datetime | None = None,
    ) -> None:
        state_value = state.value if isinstance(state, UploadState) else state
        async with self._sf() as session:
            async with session.begin():
                row = await session.get(models.Recording, rec_id)
                if row is None:
                    return
                row.upload_state = state_value
                row.upload_attempts += 1
                if drive_file_id is not None:
                    row.drive_file_id = drive_file_id
                row.upload_error = error
                row.next_attempt_at = next_attempt_at

    async def expired_local(self, before: datetime.datetime) -> list[models.Recording]:
        """Recordings older than *before* whose local file hasn't been purged yet.

        Excludes pending/uploading rows — never delete a clip before it's been uploaded.
        """
        async with self._sf() as session:
            result = await session.execute(
                select(models.Recording).where(
                    models.Recording.started_at < before,
                    models.Recording.local_path.is_not(None),
                    models.Recording.upload_state.notin_(
                        [UploadState.PENDING.value, UploadState.UPLOADING.value]
                    ),
                )
            )
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows

    async def clear_local_path(self, rec_id: int) -> None:
        """Null local_path after purging the file on disk — the row survives for history."""
        async with self._sf() as session:
            async with session.begin():
                row = await session.get(models.Recording, rec_id)
                if row is not None:
                    row.local_path = None

    async def get(self, recording_id: int) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(models.Recording, recording_id)
            return self._to_dict(row) if row is not None else None

    async def list(
        self,
        camera_id: str | None = None,
        reason: str | None = None,
        person_id: int | None = None,
        upload_state: UploadState | str | None = None,
        ts_from: datetime.datetime | None = None,
        ts_to: datetime.datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions = []
        if camera_id is not None:
            conditions.append(models.Recording.camera_id == camera_id)
        if reason is not None:
            conditions.append(models.Recording.reason == reason)
        if person_id is not None:
            conditions.append(models.Recording.person_id == person_id)
        if upload_state is not None:
            state_value = upload_state.value if isinstance(upload_state, UploadState) else upload_state
            conditions.append(models.Recording.upload_state == state_value)
        if ts_from is not None:
            conditions.append(models.Recording.started_at >= ts_from)
        if ts_to is not None:
            conditions.append(models.Recording.started_at <= ts_to)

        q = select(models.Recording).order_by(models.Recording.started_at.desc()).limit(limit)
        if conditions:
            q = q.where(and_(*conditions))
        async with self._sf() as session:
            result = await session.execute(q)
            return [self._to_dict(r) for r in result.scalars().all()]

    @staticmethod
    def _to_dict(row: models.Recording) -> dict[str, Any]:
        return {
            "id": row.id,
            "camera_id": row.camera_id,
            "filename": row.filename,
            "local_path": row.local_path,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "duration_s": row.duration_s,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "thumbnail_path": row.thumbnail_path,
            "reason": row.reason,
            "trigger_event_id": row.trigger_event_id,
            "person_id": row.person_id,
            "zone_id": row.zone_id,
            "upload_state": row.upload_state,
            "upload_attempts": row.upload_attempts,
            "upload_error": row.upload_error,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
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
