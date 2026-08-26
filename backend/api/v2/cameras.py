"""API v2 — CRUD, listado y salud de camaras.

GET (listado/salud) es de la Fase 17, extraido de main.py en la Fase 35 para
seguir el mismo patron que el resto de backend/api/v2/. POST/PUT/DELETE son
de la Fase 36 (SCALE-05): arrancan/reconfiguran/paran una CameraPipeline EN
CALIENTE, sin reiniciar el servidor, sobre la factoria compartida con el
arranque (backend/pipeline/factory.py) para que ambos caminos no diverjan.

Auth y rate limiting: la app aplica auth globalmente
(FastAPI(dependencies=[Depends(verify)])), asi que los routers incluidos con
app.include_router() la heredan automaticamente. El rate limit (SEC-16) usa el
limiter/valor compartidos de backend/api/v2/deps.py.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.config import mask_rtsp_url
from backend.database import get_session_factory
from backend.pipeline.factory import SharedPipelineServices, start_camera_pipeline
from backend.storage.repositories import CameraRepo

router = APIRouter(prefix="/api/v2/cameras", tags=["cameras"])

# Mismo valor por defecto que Settings.cpu_budget_warn_pct (backend/config.py) --
# fallback solo cuando _services es None (tests que ejercitan unicamente GET).
_DEFAULT_CPU_BUDGET_WARN_PCT = 200.0

_camera_manager: Any = None
_services: SharedPipelineServices | None = None


def configure(camera_manager: Any, services: SharedPipelineServices | None = None) -> None:
    """Wire the live CameraManager (+ SharedPipelineServices para POST/PUT). Llamado
    una vez desde main.py's lifespan. `services` es opcional para no romper tests que
    solo ejercitan GET (mismo patron que _camera_manager)."""
    global _camera_manager, _services
    _camera_manager = camera_manager
    _services = services


def _camera_repo() -> CameraRepo:
    return CameraRepo(get_session_factory())


def _camera_out(camera: dict[str, Any]) -> dict[str, Any]:
    out = dict(camera)
    if out.get("rtsp_url"):
        out["rtsp_url"] = mask_rtsp_url(out["rtsp_url"])
    out["running"] = bool(_camera_manager is not None and _camera_manager.get(camera["id"]) is not None)
    return out


class CameraIn(BaseModel):
    id: str
    name: str
    rtsp_url: str
    enabled: bool = True
    process_w: int | None = None
    process_h: int | None = None

    @field_validator("id")
    @classmethod
    def _id_len(cls, v: str) -> str:
        if not v or len(v) > 50:
            raise ValueError("id required, max 50 chars")
        return v

    @field_validator("name")
    @classmethod
    def _name_len(cls, v: str) -> str:
        if not v or len(v) > 100:
            raise ValueError("name required, max 100 chars")
        return v

    @field_validator("rtsp_url")
    @classmethod
    def _rtsp_url_valid(cls, v: str) -> str:
        if not v.startswith("rtsp://"):
            raise ValueError("rtsp_url must start with rtsp://")
        return v


class CameraUpdate(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    enabled: bool | None = None
    process_w: int | None = None
    process_h: int | None = None

    @field_validator("name")
    @classmethod
    def _name_len(cls, v: str | None) -> str | None:
        if v is not None and (not v or len(v) > 100):
            raise ValueError("name max 100 chars")
        return v

    @field_validator("rtsp_url")
    @classmethod
    def _rtsp_url_valid(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("rtsp://"):
            raise ValueError("rtsp_url must start with rtsp://")
        return v


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_cameras(request: Request):
    """List cameras managed by pipeline v2, with their capture health y coste de
    CPU estimado (SCALE-08) — ver CameraPipeline.estimated_cpu_pct: es una
    estimacion, no una medicion real del sistema operativo."""
    if _camera_manager is None:
        raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
    pipelines = _camera_manager.all()
    budget = _services.settings.cpu_budget_warn_pct if _services is not None else _DEFAULT_CPU_BUDGET_WARN_PCT
    total_cpu = round(sum(p.estimated_cpu_pct for p in pipelines), 1)
    return {
        "cameras": [
            {
                **asdict(p.health), "workers": p.worker_status(), "degraded": p.degraded,
                "estimated_cpu_pct": p.estimated_cpu_pct,
            }
            for p in pipelines
        ],
        "total_estimated_cpu_pct": total_cpu,
        "cpu_budget_warn_pct": budget,
        "over_budget": total_cpu > budget,
    }


@router.get("/{camera_id}/health")
@limiter.limit(V2_RATE_LIMIT)
async def camera_health(request: Request, camera_id: str):
    """CaptureWorker health for one camera, plus FrameBroker subscriber stats."""
    if _camera_manager is None:
        raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
    pipeline = _camera_manager.get(camera_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {
        **asdict(pipeline.health),
        # capture_fps y detection_fps son deliberadamente distintos: esa
        # diferencia ES la prueba de que el pipeline esta desacoplado.
        "capture_fps": pipeline.get_fps(),
        "detection_fps": pipeline.get_detection_fps(),
        "broker_stats": pipeline.broker.stats(),
        **pipeline.stats(),
    }


@router.get("/catalog")
@limiter.limit(V2_RATE_LIMIT)
async def list_catalog(request: Request):
    """Catalogo persistido (tabla `cameras`), a diferencia de GET '' que solo lista
    pipelines VIVAS — incluye camaras deshabilitadas/paradas, con rtsp_url enmascarada."""
    cameras = await _camera_repo().list()
    return {"cameras": [_camera_out(c) for c in cameras]}


@router.post("")
@limiter.limit(V2_RATE_LIMIT)
async def create_camera(request: Request, body: CameraIn):
    """Da de alta una camara y, si `enabled`, arranca su pipeline sin reiniciar
    el servidor (SCALE-05, criterio 1 de la Fase 36)."""
    repo = _camera_repo()
    if await repo.get(body.id) is not None:
        raise HTTPException(status_code=409, detail="Camera id already exists")
    camera = await repo.create(
        body.id, body.name, body.rtsp_url, enabled=body.enabled,
        process_w=body.process_w, process_h=body.process_h,
    )
    if body.enabled:
        if _camera_manager is None or _services is None:
            raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
        await start_camera_pipeline(_camera_manager, camera, _services)
    return {"camera": _camera_out(camera)}


@router.put("/{camera_id}")
@limiter.limit(V2_RATE_LIMIT)
async def update_camera(request: Request, camera_id: str, body: CameraUpdate):
    """Actualiza el catalogo. Si cambia `rtsp_url`/`process_w`/`process_h`/`enabled`,
    reinicia la pipeline en caliente con los valores nuevos (parar la de otra
    camara no se ve afectada, SCALE-05)."""
    repo = _camera_repo()
    if await repo.get(camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    needs_restart = any(
        v is not None for v in (body.rtsp_url, body.process_w, body.process_h, body.enabled)
    )
    camera = await repo.update(
        camera_id, name=body.name, rtsp_url=body.rtsp_url, enabled=body.enabled,
        process_w=body.process_w, process_h=body.process_h,
    )
    if needs_restart and _camera_manager is not None:
        _camera_manager.remove(camera_id)  # no-op si no estaba corriendo
        if camera["enabled"]:
            if _services is None:
                raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
            await start_camera_pipeline(_camera_manager, camera, _services)
    return {"camera": _camera_out(camera)}


@router.delete("/{camera_id}")
@limiter.limit(V2_RATE_LIMIT)
async def delete_camera(request: Request, camera_id: str):
    """Para la pipeline (si corria) y borra la camara del catalogo. Las demas
    camaras siguen operando sin verse afectadas (SCALE-05)."""
    repo = _camera_repo()
    if await repo.get(camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if _camera_manager is not None:
        _camera_manager.remove(camera_id)
    await repo.delete(camera_id)
    return {"deleted": camera_id}
