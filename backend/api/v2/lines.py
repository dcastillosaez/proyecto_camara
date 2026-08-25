"""API v2 — CRUD de lineas de conteo: GET/POST(upsert)/DELETE /api/v2/lines (Fase 33, OPS-22).

Sobre `LineRepo` (Plan 33-01), este router valida rango `[0,1]` por coordenada y longitud
minima de linea (rechaza lineas degeneradas, punto-a-punto) antes de persistir, y empuja el
cambio a todos los pipelines de camara vivos via `CameraPipeline.set_lines` (Plan 33-05) —
mismo molde exacto que `backend/api/v2/zones.py` (Plan 33-03), sustituyendo poligono por
segmento de dos puntos.

Auth and rate limiting: la app aplica auth globalmente
(FastAPI(dependencies=[Depends(verify)])), asi que este router la hereda automaticamente al
incluirse con app.include_router() — no hace falta Depends(verify) por ruta. El rate limit
(SEC-16) usa el limiter/valor compartidos de backend/api/v2/deps.py, mismo molde que
zones.py/events.py/config.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator, model_validator

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.database import get_session_factory
from backend.storage.repositories import LineRepo

router = APIRouter(prefix="/api/v2/lines", tags=["lines"])

_MIN_LENGTH = 0.001

_camera_manager: Any = None


def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan (Plan 33-08)."""
    global _camera_manager
    _camera_manager = camera_manager


def _line_repo() -> LineRepo:
    return LineRepo(get_session_factory())


class LineIn(BaseModel):
    id: str
    camera_id: str = "cam1"
    name: str
    start_x_frac: float
    start_y_frac: float
    end_x_frac: float
    end_y_frac: float
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _id_len(cls, v: str) -> str:
        if len(v) > 50:
            raise ValueError("id too long (max 50)")
        return v

    @field_validator("name")
    @classmethod
    def _name_len(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("name too long (max 100)")
        return v

    @field_validator("start_x_frac", "start_y_frac", "end_x_frac", "end_y_frac")
    @classmethod
    def _frac_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"coordinate out of [0,1] range: {v}")
        return v

    @model_validator(mode="after")
    def _not_degenerate(self) -> "LineIn":
        length = (
            (self.end_x_frac - self.start_x_frac) ** 2
            + (self.end_y_frac - self.start_y_frac) ** 2
        ) ** 0.5
        if length < _MIN_LENGTH:
            raise ValueError("linea degenerada: inicio y fin son el mismo punto")
        return self


async def _push_hot_reload(line_repo: LineRepo) -> None:
    """Empuja las lineas vigentes a cada pipeline vivo, filtradas por camera_id (criterio 6:
    <1s, sin reiniciar). Sin _camera_manager configurado (tests/arranque previo a Plan 33-08),
    no hace nada."""
    if _camera_manager is None:
        return
    for pipeline in _camera_manager.all():
        lines = await line_repo.list(camera_id=pipeline.camera_id)
        pipeline.set_lines(lines)


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_lines(request: Request, camera_id: str | None = None) -> dict[str, Any]:
    return {"lines": await _line_repo().list(camera_id=camera_id)}


@router.post("")
@limiter.limit(V2_RATE_LIMIT)
async def upsert_line(request: Request, body: LineIn) -> dict[str, Any]:
    line_repo = _line_repo()
    await line_repo.upsert(
        body.id, body.camera_id, body.name,
        body.start_x_frac, body.start_y_frac, body.end_x_frac, body.end_y_frac,
        enabled=body.enabled,
    )
    await _push_hot_reload(line_repo)
    return {"lines": await line_repo.list()}


@router.delete("/{line_id}")
@limiter.limit(V2_RATE_LIMIT)
async def delete_line(request: Request, line_id: str) -> dict[str, Any]:
    line_repo = _line_repo()
    if not await line_repo.delete(line_id):
        raise HTTPException(status_code=404, detail="Line not found")
    await _push_hot_reload(line_repo)
    return {"lines": await line_repo.list()}
