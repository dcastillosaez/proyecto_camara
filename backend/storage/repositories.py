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

from sqlalchemy import String, and_, bindparam, case, func, select, text, tuple_, update
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


# Ventana y contiguidad para la asignacion retroactiva por track (Fase 30, OPS-08).
# Los tracker_id de ByteTrack se reinician al recrear el tracker (backend/tracker.py:181)
# y la tabla `tracks` nunca se escribe: sin estas dos cotas, un UPDATE por track_id
# asignaria la identidad a otra persona de otro dia (30-RESEARCH.md Pitfall 3).
# 60s es holgado: ByteTrack pierde el track a los 60 frames (~4s @15fps).
TRACK_GAP_SECS = 60.0
TRACK_WINDOW_HOURS = 6


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

    @staticmethod
    def _filter_conditions(
        *,
        type: EventType | list[EventType] | None = None,
        severity: Severity | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
        camera_id: str | None = None,
        rule: str | None = None,
        ts_from: datetime.datetime | None = None,
        ts_to: datetime.datetime | None = None,
    ) -> tuple[list, dict]:
        """Condiciones WHERE compartidas por query() y count(). Devuelve (conditions, params).

        El prefijo '+' unario del IN multi-valor desactiva idx_events_type_ts SOLO en ese
        termino: sin el, SQLite elige ese indice y ordena con TEMP B-TREE (medido: 54ms
        vs 0,52ms @100k, 30-RESEARCH.md Hallazgo 7).
        """
        conditions: list = []
        params: dict = {}
        types = [type] if isinstance(type, EventType) else (list(type) if type else [])
        if len(types) == 1:
            conditions.append(models.Event.type == types[0].value)
        elif len(types) > 1:
            conditions.append(
                text("+events.type IN :types").bindparams(
                    bindparam("types", expanding=True, type_=String))
            )
            params["types"] = [t.value for t in types]
        if severity is not None:
            conditions.append(models.Event.severity == severity.value)
        if person_id is not None:
            conditions.append(models.Event.person_id == person_id)
        if zone_id is not None:
            conditions.append(models.Event.zone_id == zone_id)
        if camera_id is not None:
            conditions.append(models.Event.camera_id == camera_id)
        if rule is not None:
            # T-30-05: el nombre de regla llega del navegador -> bindparam, nunca f-string.
            conditions.append(text(
                "EXISTS (SELECT 1 FROM json_each(events.payload, '$.rules') je "
                "WHERE je.value = :rule)"
            ))
            params["rule"] = rule
        if ts_from is not None:
            conditions.append(models.Event.ts >= ts_from)
        if ts_to is not None:
            conditions.append(models.Event.ts <= ts_to)
        return conditions, params

    async def query(
        self,
        *,
        type: EventType | list[EventType] | None = None,
        severity: Severity | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
        camera_id: str | None = None,
        rule: str | None = None,
        ts_from: datetime.datetime | None = None,
        ts_to: datetime.datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[EventDTO], str | None]:
        """Filter + cursor-paginate, newest first. Cursor is (ts, id) base64-encoded."""
        conditions, params = self._filter_conditions(
            type=type, severity=severity, person_id=person_id, zone_id=zone_id,
            camera_id=camera_id, rule=rule, ts_from=ts_from, ts_to=ts_to)
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
        if params:
            q = q.params(**params)

        async with self._sf() as session:
            result = await session.execute(q)
            rows = list(result.scalars().all())

        items = [self._to_dto(r) for r in rows]
        next_cursor = _encode_cursor(rows[-1].ts, rows[-1].id) if len(rows) == limit else None
        return items, next_cursor

    async def count(
        self,
        *,
        type: EventType | list[EventType] | None = None,
        severity: Severity | None = None,
        person_id: int | None = None,
        zone_id: str | None = None,
        camera_id: str | None = None,
        rule: str | None = None,
        ts_from: datetime.datetime | None = None,
        ts_to: datetime.datetime | None = None,
    ) -> int:
        """COUNT(*) con los mismos filtros que query(), sin cursor ni limit.

        Se llama SOLO en la primera pagina y solo si hay filtros activos: medido
        21ms @100k / 0,9ms @10k, pedirlo en cada scroll seria malgastarlo (T-30-06).
        """
        conditions, params = self._filter_conditions(
            type=type, severity=severity, person_id=person_id, zone_id=zone_id,
            camera_id=camera_id, rule=rule, ts_from=ts_from, ts_to=ts_to)
        q = select(func.count()).select_from(models.Event)
        if conditions:
            q = q.where(and_(*conditions))
        if params:
            q = q.params(**params)
        async with self._sf() as session:
            result = await session.execute(q)
            return int(result.scalar_one())

    async def track_scope(self, event_id: str) -> dict | None:
        """Bloque CONTIGUO de eventos del mismo track alrededor de *event_id*.

        Nunca 'WHERE track_id = ?' a secas: se acota por camera_id + ventana de
        +-TRACK_WINDOW_HOURS y se corta en el primer hueco > TRACK_GAP_SECS.
        """
        anchor = await self.get(event_id)
        if anchor is None or anchor.track_id is None:
            return None
        window = datetime.timedelta(hours=TRACK_WINDOW_HOURS)
        q = (
            select(models.Event.id, models.Event.ts)
            .where(and_(
                models.Event.camera_id == anchor.camera_id,
                models.Event.track_id == anchor.track_id,
                models.Event.ts >= anchor.ts - window,
                models.Event.ts <= anchor.ts + window,
            ))
            .order_by(models.Event.ts.asc(), models.Event.id.asc())
        )
        async with self._sf() as session:
            rows = list((await session.execute(q)).all())
        if not rows:
            return None
        idx = next((i for i, r in enumerate(rows) if r.id == anchor.id), None)
        if idx is None:
            return None
        start = idx
        while start > 0 and (rows[start].ts - rows[start - 1].ts).total_seconds() <= TRACK_GAP_SECS:
            start -= 1
        end = idx
        while end + 1 < len(rows) and (rows[end + 1].ts - rows[end].ts).total_seconds() <= TRACK_GAP_SECS:
            end += 1
        block = rows[start:end + 1]
        return {
            "event_ids": [r.id for r in block],
            "count": len(block),
            "from": block[0].ts,
            "to": block[-1].ts,
        }

    async def assign_person(self, event_id: str, person_id: int) -> dict:
        """Propaga una identidad al bloque contiguo del track (Fase 30, OPS-08, criterio 5).

        El UPDATE va por lista EXPLICITA de ids calculada por track_scope(), nunca
        'WHERE track_id = ?': eso alcanzaria tracks homonimos de otros dias (Pitfall 3).
        Un UNKNOWN_PERSON deja de ser advertencia al ganar identidad; el resto de
        tipos conserva su severidad.
        """
        scope = await self.track_scope(event_id)
        if scope is None or not scope["event_ids"]:
            return {"person_id": person_id, "updated": 0, "event_ids": []}
        ids = scope["event_ids"]
        async with self._sf() as session:
            async with session.begin():
                await session.execute(
                    update(models.Event)
                    .where(models.Event.id.in_(ids))
                    .values(
                        person_id=person_id,
                        severity=case(
                            (models.Event.type == EventType.UNKNOWN_PERSON.value,
                             Severity.INFO.value),
                            else_=models.Event.severity,
                        ),
                    )
                )
        return {"person_id": person_id, "updated": len(ids), "event_ids": ids}

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

    async def by_trigger_event_ids(self, ids: list[str]) -> dict[str, dict]:
        """Mapa event_id -> datos de su grabacion, para una pagina completa (<=200 ids).

        events.recording_id NUNCA se escribe: el vinculo real lo pone _on_clip_ready
        en recordings.trigger_event_id (backend/main.py:353-357). La tabla recordings
        es pequena y no tiene indice por esa columna; el escaneo es despreciable
        frente a anadir un quinto indice (30-RESEARCH.md Hallazgo 4).
        """
        if not ids:
            return {}
        q = (
            select(models.Recording)
            .where(models.Recording.trigger_event_id.in_(ids))
            .order_by(models.Recording.id.asc())
        )
        async with self._sf() as session:
            rows = list((await session.execute(q)).scalars().all())
        out: dict[str, dict] = {}
        for row in rows:            # orden ascendente: la ultima gana
            out[row.trigger_event_id] = {
                "recording_id": row.id,
                "local_path": row.local_path,
                "thumbnail_path": row.thumbnail_path,
            }
        return out

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


BUCKET_HOUR_MAX_DAYS = 7


def bucket_for(cur_from: datetime.datetime, cur_to: datetime.datetime) -> str:
    """Cubo horario hasta 7 dias, diario por encima.

    ES UNA DECISION DE LEGIBILIDAD, NO DE TAMANO. Medido (31-RESEARCH.md,
    criterio 3): 30 dias en cubo horario pesan 11,3 KB con arrays paralelos y
    hasta el rango maximo de 90 dias horarios cabe en 57,0 KB — el limite del
    criterio son 100 KB, o sea 8,8x de margen. El umbral existe porque 720
    barras no se leen, y porque la regla de tipo de grafica del UI-SPEC cambia
    a linea por encima de 48 cubos. Que nadie lo "optimice" creyendo que esta
    aqui por peso.
    """
    return "hour" if (cur_to - cur_from) <= datetime.timedelta(days=BUCKET_HOUR_MAX_DAYS) else "day"


def _bucket_expr(bucket: str) -> str:
    """substr sobre el TEXT ISO de ancho fijo — 2,3x mas rapido que strftime
    (51,8 ms frente a 120,8 ms @100k). El formato de almacenamiento esta
    protegido por TEST_datetime_storage_format_is_fixed_width_iso (31-01):
    si ese test cae, hay que volver a strftime de forma explicita."""
    return "substr(ts,1,13)" if bucket == "hour" else "substr(ts,1,10)"


class AnalyticsRepo:
    """Las cuatro agregaciones de la Vista de analitica (OPS-12..OPS-14), todas
    resueltas en SQL sobre `events` — nunca `detection_stats` (ver docstring del
    plan 31-04 para las tres razones) y nunca Python (`sorted()`/`sum()` sobre
    filas ya traidas), que es justo lo que OPS-14 exige.
    """

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def hourly(
        self,
        camera_id: str,
        cur_from: datetime.datetime,
        cur_to: datetime.datetime,
        bucket: str,
    ) -> list[tuple[str, int, int]]:
        """[(bucket, actual, anterior), ...] ordenado por bucket. Cubos VACIOS NO
        aparecen: el relleno a cero lo hace el router, que es quien conoce el eje
        completo.

        Serie actual + periodo anterior en UNA consulta (50,6 ms medidos @100k
        sobre 60 dias de rango). Nota de correccion: en cubo diario, los `b` del
        periodo anterior y del actual son fechas DISTINTAS, asi que ninguna fila
        lleva `cur` y `prev` a la vez — es correcto y esperado, el router empareja
        por POSICION en el eje (cubo i del actual con cubo i del anterior), no
        por etiqueta.
        """
        prev_from = cur_from - (cur_to - cur_from)
        sql = text(f"""
            SELECT {_bucket_expr(bucket)} AS b,
                   SUM(CASE WHEN ts >= :cur_from THEN 1 ELSE 0 END) AS cur,
                   SUM(CASE WHEN ts <  :cur_from THEN 1 ELSE 0 END) AS prev
              FROM events
             WHERE camera_id = :cam AND ts >= :prev_from AND ts < :cur_to
               AND type = :etype
             GROUP BY b ORDER BY b
        """)
        params = {
            "cam": camera_id, "cur_from": cur_from, "cur_to": cur_to,
            "prev_from": prev_from, "etype": EventType.LINE_CROSSED.value,
        }
        async with self._sf() as session:
            rows = (await session.execute(sql, params)).all()
        return [(row.b, int(row.cur or 0), int(row.prev or 0)) for row in rows]

    async def summary(
        self,
        camera_id: str,
        cur_from: datetime.datetime,
        cur_to: datetime.datetime,
        bucket: str,
    ) -> dict:
        """{'total', 'previous_total', 'peak_bucket', 'peak_value', 'min_bucket',
        'min_value', 'known', 'unknown'}.

        `known`/`unknown` cuentan PERSONAS DISTINTAS del periodo actual, no
        eventos (decision cerrada del research, pregunta A6 de 31-RESEARCH.md):
        "342 conocidas" leido como eventos es una cifra enorme y poco intuitiva;
        leido como personas es 12, que es lo que la etiqueta sugiere en
        castellano. Y SIN filtro de tipo: `person_id` se escribe en eventos de
        identidad, no en los `LINE_CROSSED`, asi que filtrar por tipo devolveria
        siempre cero.

        Si `total` sale `None` (rango sin eventos) se devuelve `0`; si no hay
        cubos, `peak_bucket`/`min_bucket` van a `None` y sus valores a `0`.
        """
        prev_from = cur_from - (cur_to - cur_from)
        etype = EventType.LINE_CROSSED.value
        bucket_expr = _bucket_expr(bucket)

        totals_sql = text(f"""
            WITH b AS (
              SELECT {bucket_expr} AS bucket, COUNT(*) AS n
                FROM events
               WHERE camera_id = :cam AND ts >= :cur_from AND ts < :cur_to AND type = :etype
               GROUP BY bucket
            )
            SELECT (SELECT SUM(n) FROM b) AS total,
                   (SELECT bucket FROM b ORDER BY n DESC, bucket ASC LIMIT 1) AS peak_bucket,
                   (SELECT MAX(n)  FROM b) AS peak_value,
                   (SELECT bucket FROM b ORDER BY n ASC,  bucket ASC LIMIT 1) AS min_bucket,
                   (SELECT MIN(n)  FROM b) AS min_value
        """)
        window_sql = text("""
            SELECT SUM(CASE WHEN ts >= :cur_from THEN 1 ELSE 0 END) AS cur,
                   SUM(CASE WHEN ts <  :cur_from THEN 1 ELSE 0 END) AS prev
              FROM events
             WHERE camera_id = :cam AND ts >= :prev_from AND ts < :cur_to AND type = :etype
        """)
        identity_sql = text("""
            SELECT COUNT(DISTINCT person_id) AS known,
                   COUNT(DISTINCT CASE WHEN person_id IS NULL THEN track_id END) AS unknown
              FROM events
             WHERE camera_id = :cam AND ts >= :cur_from AND ts < :cur_to
        """)
        params = {
            "cam": camera_id, "cur_from": cur_from, "cur_to": cur_to,
            "prev_from": prev_from, "etype": etype,
        }

        async with self._sf() as session:
            totals = (await session.execute(totals_sql, params)).one()
            window = (await session.execute(window_sql, params)).one()
            identity = (await session.execute(identity_sql, params)).one()

        return {
            "total": int(totals.total or 0),
            "previous_total": int(window.prev or 0),
            "peak_bucket": totals.peak_bucket,
            "peak_value": int(totals.peak_value or 0),
            "min_bucket": totals.min_bucket,
            "min_value": int(totals.min_value or 0),
            "known": int(identity.known or 0),
            "unknown": int(identity.unknown or 0),
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
