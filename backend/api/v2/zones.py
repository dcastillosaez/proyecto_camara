"""API v2 — CRUD de zonas de interes: GET/POST(upsert)/DELETE /api/v2/zones (Fase 33, D-02, OPS-21, OPS-23).

Sustituye a `/api/zones` (v1, backend/main.py) que se retira en el Plan 33-08 una vez el
frontend y `config_schema.py` apunten aqui. Sobre el mismo `ZoneRepo` (esquema v2) que ya
existia, este router anade lo que v1 nunca valido: rango [0,1] por punto del poligono
(33-RESEARCH.md Anti-patterns), `kind` cerrado a un vocabulario conocido y `schedule`
verificado con un dry-run de `is_schedule_active` antes de persistir. `kind="exclude_objects"`
se conserva como cuarto valor heredado de la Fase 27 (33-RESEARCH.md Pitfall 2), no se
remapea.

Auth and rate limiting: la app aplica auth globalmente
(FastAPI(dependencies=[Depends(verify)])), asi que este router la hereda automaticamente al
incluirse con app.include_router() — no hace falta Depends(verify) por ruta. El rate limit
(SEC-16) usa el limiter/valor compartidos de backend/api/v2/deps.py, mismo molde que
events.py/config.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.database import get_session_factory
from backend.events.rules import is_schedule_active
from backend.storage.repositories import ZoneRepo

router = APIRouter(prefix="/api/v2/zones", tags=["zones"])

# "exclude_objects" es heredado de la Fase 27 (backend/database.py:48-50, zonas donde los
# objetos nunca disparan OBJECT_LEFT) y se conserva sin remapear (33-RESEARCH.md Pitfall 2).
_KIND_VALUES = {"counting", "restricted", "exclusion", "exclude_objects"}

_camera_manager: Any = None


def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan (Plan 33-08)."""
    global _camera_manager
    _camera_manager = camera_manager


def _zone_repo() -> ZoneRepo:
    return ZoneRepo(get_session_factory())


class ZoneIn(BaseModel):
    id: str
    camera_id: str = "cam1"
    name: str
    polygon: list[list[float]]
    kind: str | None = None
    schedule: dict[str, Any] | None = None
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

    @field_validator("polygon")
    @classmethod
    def _polygon_valid(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError("polygon must have >=3 points")
        for p in v:
            if len(p) != 2 or not all(0.0 <= float(c) <= 1.0 for c in p):
                raise ValueError(f"point out of [0,1] range: {p}")
        return v

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in _KIND_VALUES:
            raise ValueError(f"kind must be one of: {', '.join(sorted(_KIND_VALUES))}")
        return v

    @field_validator("schedule")
    @classmethod
    def _schedule_valid(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None:
            try:
                is_schedule_active(v)
            except Exception as exc:
                raise ValueError("schedule invalido") from exc
        return v


async def _push_hot_reload(zone_repo: ZoneRepo) -> None:
    """Empuja las zonas vigentes a cada pipeline vivo, filtradas por camera_id (criterio 6:
    <1s, sin reiniciar). Sin _camera_manager configurado (tests/arranque previo a Plan 33-08),
    no hace nada."""
    if _camera_manager is None:
        return
    for pipeline in _camera_manager.all():
        zones = await zone_repo.list(camera_id=pipeline.camera_id)
        pipeline.set_zones(zones)


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_zones(request: Request, camera_id: str | None = None) -> dict[str, Any]:
    return {"zones": await _zone_repo().list(camera_id=camera_id)}


@router.post("")
@limiter.limit(V2_RATE_LIMIT)
async def upsert_zone(request: Request, body: ZoneIn) -> dict[str, Any]:
    zone_repo = _zone_repo()
    await zone_repo.upsert(
        body.id, body.camera_id, body.name, body.polygon,
        kind=body.kind, schedule=body.schedule, enabled=body.enabled,
    )
    await _push_hot_reload(zone_repo)
    return {"zones": await zone_repo.list()}


@router.delete("/{zone_id}")
@limiter.limit(V2_RATE_LIMIT)
async def delete_zone(request: Request, zone_id: str) -> dict[str, Any]:
    zone_repo = _zone_repo()
    if not await zone_repo.delete(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    await _push_hot_reload(zone_repo)
    return {"zones": await zone_repo.list()}
