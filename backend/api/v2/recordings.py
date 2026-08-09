"""API v2 — recordings: listing, detail, thumbnail, retry-upload (Fase 20).

Auth and rate limiting: the app applies auth globally (FastAPI(dependencies=[Depends(verify)])),
so routers included via app.include_router() inherit it automatically — no per-route
Depends(verify) needed here, matching the v1 endpoints' convention. Rate limiting
(SEC-16, Fase 22) uses the shared limiter/rate value from backend/api/v2/deps.py.
"""

from __future__ import annotations

import datetime
import json
import os

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from backend.api.v2.deps import V2_RATE_LIMIT, limiter, pagination_limit
from backend.database import get_session_factory
from backend.storage.repositories import EventRepo, RecordingRepo, UploadState

router = APIRouter(prefix="/api/v2/recordings", tags=["recordings"])


def _recording_repo() -> RecordingRepo:
    return RecordingRepo(get_session_factory())


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_recordings(
    request: Request,
    camera_id: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    person_id: int | None = Query(default=None),
    upload_state: str | None = Query(default=None),
    from_dt: datetime.datetime | None = Query(default=None, alias="from"),
    to_dt: datetime.datetime | None = Query(default=None, alias="to"),
    limit: int = pagination_limit(),
):
    """Recordings with filters by camera, range, reason, person, and upload state."""
    if upload_state is not None:
        try:
            UploadState(upload_state)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid upload_state: {upload_state}")

    recordings = await _recording_repo().list(
        camera_id=camera_id, reason=reason, person_id=person_id,
        upload_state=upload_state, ts_from=from_dt, ts_to=to_dt, limit=limit,
    )
    return {"recordings": recordings}


@router.get("/{recording_id}")
@limiter.limit(V2_RATE_LIMIT)
async def get_recording(request: Request, recording_id: int):
    """Full metadata for one recording, plus its triggering event if any."""
    rec = await _recording_repo().get(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recording not found")

    trigger_event = None
    if rec["trigger_event_id"]:
        event = await EventRepo(get_session_factory()).get(rec["trigger_event_id"])
        if event is not None:
            trigger_event = json.loads(event.model_dump_json())

    return {**rec, "trigger_event": trigger_event}


@router.get("/{recording_id}/thumbnail")
@limiter.limit(V2_RATE_LIMIT)
async def get_recording_thumbnail(request: Request, recording_id: int):
    """Serve the clip thumbnail. Immutable once generated — cached for a day."""
    rec = await _recording_repo().get(recording_id)
    if rec is None or not rec.get("thumbnail_path"):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    path = rec["thumbnail_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Thumbnail file missing on disk")
    return FileResponse(
        path, media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/{recording_id}/retry-upload")
@limiter.limit(V2_RATE_LIMIT)
async def retry_upload(request: Request, recording_id: int):
    """Requeue a permanently failed upload as pending for the next poll cycle."""
    repo = _recording_repo()
    rec = await repo.get(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec["upload_state"] != UploadState.FAILED.value:
        raise HTTPException(
            status_code=409, detail=f"Recording is {rec['upload_state']!r}, not failed"
        )
    await repo.mark_upload(recording_id, UploadState.PENDING, next_attempt_at=None)
    return await repo.get(recording_id)
