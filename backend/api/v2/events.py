"""API v2 — eventos tipados: linea temporal, detalle, alcance de track y asignacion (Fase 30).

Auth and rate limiting: the app applies auth globally (FastAPI(dependencies=[Depends(verify)])),
so routers included via app.include_router() inherit it automatically — no per-route
Depends(verify) needed here. Rate limiting (SEC-16, Fase 22) uses the shared limiter/rate
value from backend/api/v2/deps.py.

Sustituye al endpoint suelto que vivia en main.py desde la Fase 19 (mismo envelope
{"events": [...], "cursor": ...} — frontend/js/views/dashboard.js:274 ya lo consume,
no renombrar claves; solo se anaden `total` y `media`).
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from backend.api.v2.deps import V2_RATE_LIMIT, limiter, pagination_limit, snapshot_url
from backend.database import get_session_factory
from backend.events.types import EventType, Severity
from backend.storage.repositories import EventRepo, RecordingRepo

router = APIRouter(prefix="/api/v2/events", tags=["events"])

_EMPTY_MEDIA: dict[str, Any] = {
    "recording_id": None, "clip_url": None, "thumbnail_url": None, "snapshot_url": None,
}


def _event_repo() -> EventRepo:
    return EventRepo(get_session_factory())


def _recording_repo() -> RecordingRepo:
    return RecordingRepo(get_session_factory())


async def _media_map(events: list) -> dict[str, dict]:
    """event_id -> {recording_id, clip_url, thumbnail_url, snapshot_url}, solo con lo que exista.

    events.recording_id nunca se escribe: el vinculo real es recordings.trigger_event_id
    (30-RESEARCH.md Hallazgo 4). Una consulta por pagina (<=200 ids), nunca una por fila.
    """
    if not events:
        return {}
    by_event = await _recording_repo().by_trigger_event_ids([e.id for e in events])
    out: dict[str, dict] = {}
    for ev in events:
        snap = snapshot_url(ev.snapshot_path)
        rec = by_event.get(ev.id)
        if snap is None and rec is None:
            continue
        entry: dict[str, Any] = {**_EMPTY_MEDIA, "snapshot_url": snap}
        if rec is not None:
            entry["recording_id"] = rec["recording_id"]
            if rec.get("local_path"):
                entry["clip_url"] = "/clips/" + os.path.basename(rec["local_path"])
            if rec.get("thumbnail_path"):
                entry["thumbnail_url"] = f"/api/v2/recordings/{rec['recording_id']}/thumbnail"
        out[ev.id] = entry
    return out


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_events(
    request: Request,
    type: list[str] | None = Query(default=None),
    severity: str | None = Query(default=None),
    person_id: int | None = Query(default=None),
    zone_id: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    rule: str | None = Query(default=None, max_length=100),
    from_dt: datetime.datetime | None = Query(default=None, alias="from"),
    to_dt: datetime.datetime | None = Query(default=None, alias="to"),
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = pagination_limit(),
) -> dict[str, Any]:
    """Eventos tipados con filtros combinables y paginacion por cursor (OPS-09)."""
    try:
        types = [EventType(t) for t in (type or [])] or None
        event_severity = Severity(severity) if severity else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    filters: dict[str, Any] = dict(
        type=types, severity=event_severity, person_id=person_id, zone_id=zone_id,
        camera_id=camera_id, rule=rule, ts_from=from_dt, ts_to=to_dt,
    )
    repo = _event_repo()
    try:
        items, next_cursor = await repo.query(**filters, cursor=cursor, limit=limit)
    except (ValueError, TypeError):          # cursor corrupto o no decodificable
        raise HTTPException(status_code=400, detail="cursor invalido")

    has_filters = any(v is not None for v in filters.values())
    # COUNT(*) solo en la primera pagina y solo con filtros: en cada scroll seria
    # 21 ms @100k malgastados (Pitfall 9 / T-30-15).
    total = await repo.count(**filters) if (cursor is None and has_filters) else None

    return {
        "events": [json.loads(e.model_dump_json()) for e in items],
        "cursor": next_cursor,
        "total": total,
        "media": await _media_map(items),
    }


@router.get("/{event_id}")
@limiter.limit(V2_RATE_LIMIT)
async def get_event(request: Request, event_id: str) -> dict[str, Any]:
    """Un evento con su bloque de medios; 404 si no existe."""
    event = await _event_repo().get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    media = await _media_map([event])
    return {
        "event": json.loads(event.model_dump_json()),
        "media": media.get(event.id, dict(_EMPTY_MEDIA)),
    }


@router.get("/{event_id}/track-scope")
@limiter.limit(V2_RATE_LIMIT)
async def get_track_scope(request: Request, event_id: str) -> dict[str, Any]:
    """Cuantos eventos anteriores/posteriores del mismo track recibirian la identidad.

    Es la previsualizacion que exige D-06/UI-SPEC ("Se aplicara tambien a los eventos
    anteriores de este track (N)"): mismo calculo que assign-person, sin escribir nada.
    """
    repo = _event_repo()
    if await repo.get(event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    scope = await repo.track_scope(event_id)
    if scope is None:
        return {"count": 0, "from": None, "to": None, "event_ids": []}
    return {
        "count": scope["count"],
        "from": scope["from"].isoformat(),
        "to": scope["to"].isoformat(),
        "event_ids": scope["event_ids"],
    }


@router.post("/{event_id}/assign-person")
@limiter.limit(V2_RATE_LIMIT)
async def assign_person(
    request: Request,
    event_id: str,
    person_id: int = Body(..., embed=True, ge=1),
) -> dict[str, Any]:
    """Aplica una identidad ya enrolada al bloque contiguo del track (OPS-08, criterio 5).

    El enrolado en si NO se hace aqui: el cliente llama antes a POST /api/enroll_face,
    que ya valida content_type, tamano y longitud del nombre con tests de regresion de
    seguridad asociados. Duplicar esa validacion aqui seria una regresion.
    """
    repo = _event_repo()
    if await repo.get(event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return await repo.assign_person(event_id, person_id)
