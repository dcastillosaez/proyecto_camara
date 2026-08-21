"""API v2 — centro de alertas: agrupacion por regla y silenciado temporal (Fase 30, OPS-11).

Auth y rate limiting: heredados de la app (FastAPI(dependencies=[Depends(verify)])) y
de backend/api/v2/deps.py, igual que el resto de routers v2.

La agrupacion se hace aqui y no en el navegador a proposito: agrupar en el cliente
exigiria descargarse el historial entero (30-RESEARCH.md, Architectural Responsibility Map).
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.database import get_session_factory
from backend.events.types import Severity
from backend.storage.repositories import ConfigRepo, EventRepo

router = APIRouter(prefix="/api/v2/alerts", tags=["alerts"])

MUTED_KEY = "alerts.muted_rules"
MUTE_DURATIONS = (900, 3600, 28800)      # 15 min / 1 h / 8 h — lista blanca (UI-SPEC)
SEVERITY_RANK = {"critical": 2, "warning": 1, "info": 0}
PAGE_CAP = 200                            # tope por severidad; ver docstring de list_alerts

_mute_lock = asyncio.Lock()               # serializa el read-modify-write de app_config
_event_engine: Any = None


def configure(event_engine: Any = None) -> None:
    """Wire the live EventEngine (para emitir CONFIG_CHANGED). Called once from lifespan."""
    global _event_engine
    _event_engine = event_engine


def _config_repo() -> ConfigRepo:
    return ConfigRepo(get_session_factory())


async def _load_muted(now: datetime.datetime) -> dict[str, dict]:
    """Reglas silenciadas todavia vigentes. La expiracion es perezosa: no hay tarea de fondo,
    las entradas caducadas se descartan al leer y desaparecen del disco en la siguiente
    escritura (30-RESEARCH.md Hallazgo 8)."""
    raw = await _config_repo().get(MUTED_KEY, {}) or {}
    return {
        name: data for name, data in raw.items()
        if data.get("until") and datetime.datetime.fromisoformat(data["until"]) > now
    }


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_alerts(
    request: Request, hours: int = Query(default=24, ge=1, le=168)
) -> dict[str, Any]:
    """Alertas activas de la ventana, agrupadas por la regla que las disparo (OPS-11).

    Se consultan como mucho PAGE_CAP eventos por severidad (critical y warning) mas
    los que dispararon regla: el recuento por grupo se calcula sobre ese conjunto y
    `truncated` avisa si se alcanzo el tope. Es deliberado: el cajon muestra actividad
    reciente, no un censo historico, y un COUNT por grupo obligaria a una consulta por regla.
    """
    now = datetime.datetime.now()
    since = now - datetime.timedelta(hours=hours)
    repo = EventRepo(get_session_factory())
    collected: list = []
    truncated = False
    for sev in (Severity.CRITICAL, Severity.WARNING):
        items, next_cursor = await repo.query(severity=sev, ts_from=since, limit=PAGE_CAP)
        collected.extend(items)
        truncated = truncated or next_cursor is not None
    # eventos info que SI dispararon una regla: si una regla se molesto en disparar, es alerta
    info_items, info_cursor = await repo.query(
        severity=Severity.INFO, ts_from=since, limit=PAGE_CAP)
    collected.extend([e for e in info_items if e.payload.get("rules")])
    truncated = truncated or info_cursor is not None

    muted = await _load_muted(now)
    groups: dict[str, dict] = {}
    for ev in collected:
        rules = ev.payload.get("rules") or []
        keys = [("rule:" + r, r) for r in rules] or [("type:" + ev.type.value, None)]
        for key, rule_name in keys:
            g = groups.setdefault(key, {
                "key": key, "rule_name": rule_name, "event_type": ev.type.value,
                "severity": ev.severity.value, "count": 0,
                "last_ts": ev.ts, "last_event_id": ev.id, "zone_id": ev.zone_id,
                "mutable": rule_name is not None,
            })
            g["count"] += 1
            if SEVERITY_RANK.get(ev.severity.value, 0) > SEVERITY_RANK.get(g["severity"], 0):
                g["severity"] = ev.severity.value
            if ev.ts > g["last_ts"]:
                g.update(last_ts=ev.ts, last_event_id=ev.id,
                         zone_id=ev.zone_id, event_type=ev.type.value)

    out = []
    for g in groups.values():
        entry = dict(g)
        entry["last_ts"] = g["last_ts"].isoformat()
        m = muted.get(g["rule_name"]) if g["rule_name"] else None
        entry["muted_until"] = m["until"] if m else None
        out.append(entry)
    # severidad descendente y, dentro de la misma severidad, lo mas reciente primero (UI-SPEC)
    out.sort(key=lambda g: (SEVERITY_RANK.get(g["severity"], 0), g["last_ts"]), reverse=True)

    active = [g for g in out if g["muted_until"] is None]
    return {
        "groups": out,
        "active_count": len(active),
        "critical_count": sum(1 for g in active if g["severity"] == "critical"),
        "muted_count": len(out) - len(active),
        "window_hours": hours,
        "truncated": truncated,
        "checked_at": now.isoformat(),
    }


@router.post("/mute")
@limiter.limit(V2_RATE_LIMIT)
async def mute_rule(
    request: Request,
    rule_name: str = Body(..., min_length=1, max_length=100),
    duration_secs: int = Body(...),
) -> dict[str, Any]:
    """Silencia una regla durante un tiempo acotado (OPS-11, D-16/D-17).

    Silenciar es SOLO de presentacion: la regla se sigue evaluando, sus acciones se
    siguen ejecutando (sigue grabando el clip y mandando el aviso) y el evento se
    sigue persistiendo. Lo unico que cambia es que su grupo sale atenuado en el cajon
    y no cuenta para el badge. Silenciar desde la UI no debe hacerte perder pruebas
    (30-RESEARCH.md Hallazgo 8).
    """
    if duration_secs not in MUTE_DURATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"duracion no valida: elige una de {MUTE_DURATIONS} segundos")
    now = datetime.datetime.now()
    until = now + datetime.timedelta(seconds=duration_secs)
    async with _mute_lock:                    # read-modify-write sobre una unica fila
        current = await _load_muted(now)      # ya purgado de caducadas
        current[rule_name] = {"until": until.isoformat(), "camera_id": None}
        await _config_repo().set(MUTED_KEY, current)
    if _event_engine is not None:
        _event_engine.config_changed(now, muted_rule=rule_name, duration_secs=duration_secs)
    return {"rule_name": rule_name, "until": until.isoformat()}


@router.post("/unmute")
@limiter.limit(V2_RATE_LIMIT)
async def unmute_rule(
    request: Request,
    rule_name: str = Body(..., embed=True, min_length=1, max_length=100),
) -> dict[str, Any]:
    """Reactiva una regla silenciada antes de que expire su duracion."""
    now = datetime.datetime.now()
    async with _mute_lock:
        current = await _load_muted(now)
        current.pop(rule_name, None)
        await _config_repo().set(MUTED_KEY, current)
    if _event_engine is not None:
        _event_engine.config_changed(now, unmuted_rule=rule_name)
    return {"rule_name": rule_name, "muted": False}
