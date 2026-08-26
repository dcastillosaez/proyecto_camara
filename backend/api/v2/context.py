"""API v2 — contexto de escena agregado: hora, zona, personas, nivel de actividad
(Fase 27, BEH-08/BEH-09).

Auth y rate limiting: la app aplica auth globalmente
(FastAPI(dependencies=[Depends(verify)])), asi que los routers incluidos con
app.include_router() la heredan automaticamente. El rate limit (SEC-16) usa el
limiter/valor compartidos de backend/api/v2/deps.py.

Este endpoint es de SOLO RECUENTOS: nunca devuelve el identificador de persona ni su
nombre. Un endpoint de analitica de escena no debe convertirse en un endpoint de
identidad (27-RESEARCH.md § Security Domain).
"""

from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from backend.api.v2.deps import V2_RATE_LIMIT, limiter, resolve_camera_id
from backend.config import Settings, get_settings
from backend.database import get_session_factory
from backend.perception.face.identity import IdentityState
from backend.pipeline.tracking import TrackRegistry
from backend.storage.repositories import DetectionStatRepo

router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])

_camera_manager: Any = None


def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager


def _stat_repo() -> DetectionStatRepo:
    return DetectionStatRepo(get_session_factory())


def _person_counts(registry: TrackRegistry) -> dict[str, int]:
    """Recuento de personas visibles AHORA MISMO, por estado de identidad.

    frame_ids(), no active_ids(): active_ids() arrastra hasta 30s de TTL de prune()
    (tracking.py:130), asi que un track que acaba de perderse seguiria contando como
    "presente" hasta 30s despues de salir del frame. frame_ids() es exacto e inmediato
    (27-RESEARCH.md Q5, mismo criterio que usa RecognitionWorker._sync_identity).

    "Conocida" es identity_state is CONFIRMED, NO que exista un identificador de persona
    asociado al track: set_identity() escribe ese identificador en cuanto hay un match,
    incluso antes de que la votacion temporal confirme (tracking.py:117-122). Usar la
    mera presencia del identificador contaria como "conocida" a alguien todavia en
    CANDIDATE, contradiciendo la semantica de FACE-08.
    """
    visible = registry.frame_ids()
    states = [ts for ts in registry.snapshot().values() if ts.track_id in visible]
    known = sum(1 for ts in states if ts.identity_state is IdentityState.CONFIRMED)
    pending = sum(
        1 for ts in states
        if ts.identity_state in (IdentityState.CANDIDATE, IdentityState.TEMPORARILY_LOST)
    )
    total = len(visible)
    return {"total": total, "known": known, "unknown": total - known - pending, "pending": pending}


def _classify_activity(
    baseline_entry: dict[str, float] | None,
    now_entry: dict[str, float] | None,
    minutes_elapsed: float,
    settings: Settings,
) -> dict[str, Any]:
    """Nivel de actividad de la franja horaria actual contra su media movil (BEH-09).

    Normalizado a TASA POR MINUTO en los dos lados: comparar el total acumulado de una
    hora completa (baseline) contra el de una hora que solo lleva unos minutos (ahora)
    sesgaria "low" cada hora en punto y subiria hasta el minuto 59 (Pitfall 7). "unknown"
    con pocos dias de historial (Pitfall 8) o dentro de los primeros 5 minutos de la
    hora: en ambos casos el sistema debe decir "no se todavia" en vez de inventar un
    veredicto, mismo principio que reid_inherit_identity=False al arrancar (Fase 25).
    """
    sample_days = baseline_entry["sample_days"] if baseline_entry else 0
    if baseline_entry is None or sample_days < settings.context_min_sample_days or minutes_elapsed < 5.0:
        return {"level": "unknown", "current": None, "baseline": None, "ratio": None,
                "sample_days": sample_days}

    baseline_rate = baseline_entry["avg_per_minute"]
    current_total = now_entry["avg_total"] if now_entry else 0.0
    current_rate = current_total / minutes_elapsed

    if baseline_rate <= 0:
        return {"level": "unknown", "current": round(current_rate, 3), "baseline": 0.0,
                "ratio": None, "sample_days": sample_days}

    ratio = current_rate / baseline_rate
    if ratio < settings.context_low_ratio:
        level = "low"
    elif ratio > settings.context_high_ratio:
        level = "high"
    else:
        level = "normal"
    return {
        "level": level, "current": round(current_rate, 3), "baseline": round(baseline_rate, 3),
        "ratio": round(ratio, 3), "sample_days": sample_days,
    }


@router.get("/context")
@limiter.limit(V2_RATE_LIMIT)
async def get_context(
    request: Request,
    camera_id: str | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=90),
) -> dict[str, Any]:
    camera_id = await resolve_camera_id(camera_id, get_session_factory())
    settings = get_settings()
    now = datetime.datetime.now()
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    minutes_elapsed = (now - hour_start).total_seconds() / 60.0
    hour_key = f"{now.hour:02d}"
    window_days = days if days is not None else settings.context_baseline_days

    repo = _stat_repo()
    baseline_map = await repo.hourly_baseline(
        camera_id, since=now - datetime.timedelta(days=window_days), until=hour_start,
    )
    now_map = await repo.hourly_baseline(camera_id, since=hour_start)
    activity = _classify_activity(
        baseline_map.get(hour_key), now_map.get(hour_key), minutes_elapsed, settings,
    )

    pipeline = _camera_manager.get(camera_id) if _camera_manager is not None else None
    if pipeline is not None:
        persons = _person_counts(pipeline.registry)
        zones = pipeline.get_zone_stats()
        objects = pipeline.get_object_stats()
    else:
        persons = {"total": 0, "known": 0, "unknown": 0, "pending": 0}
        zones, objects = [], []

    return {
        "timestamp": now.isoformat(),
        "camera_id": camera_id,
        "hour": now.hour,
        "persons": persons,
        "zones": zones,
        "objects": objects,
        "activity": activity,
    }
