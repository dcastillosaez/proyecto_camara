"""API v2 — listado y salud de camaras (Fase 17, extraido de main.py en la Fase 35
para seguir el mismo patron que el resto de backend/api/v2/: router propio +
configure(camera_manager) desde el lifespan, en vez de vivir embebido en main.py).

Auth y rate limiting: la app aplica auth globalmente
(FastAPI(dependencies=[Depends(verify)])), asi que los routers incluidos con
app.include_router() la heredan automaticamente. El rate limit (SEC-16) usa el
limiter/valor compartidos de backend/api/v2/deps.py.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.api.v2.deps import V2_RATE_LIMIT, limiter

router = APIRouter(prefix="/api/v2/cameras", tags=["cameras"])

_camera_manager: Any = None


def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_cameras(request: Request):
    """List cameras managed by pipeline v2, with their capture health."""
    if _camera_manager is None:
        raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
    return {
        "cameras": [
            {**asdict(p.health), "workers": p.worker_status(), "degraded": p.degraded}
            for p in _camera_manager.all()
        ]
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
