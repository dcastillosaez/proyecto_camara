"""API v2 — agregaciones de la Vista de analitica: /summary, /hourly, /occupancy
y /persons (Fase 31, OPS-12..OPS-14).

Auth y rate limiting: la app aplica auth globalmente
(FastAPI(dependencies=[Depends(verify)])), asi que los routers incluidos con
app.include_router() la heredan automaticamente. El rate limit (SEC-16) usa el
limiter/valor compartidos de backend/api/v2/deps.py.

Este router SI devuelve `person_id` y nombre en /persons, a diferencia de
/context (Fase 27), que es de solo recuentos. Es una diferencia deliberada:
OPS-13 pide explicitamente un ranking de personas con nombre, y se deja
escrita aqui para que nadie la lea como una fuga de identidad (T-31-18).

Todas las agregaciones vienen resueltas de SQL (AnalyticsRepo, 31-04): este
router SOLO formatea, rellena el eje a cero y calcula porcentajes de
variacion sobre totales que ya trajo la base — nunca vuelve a agregar sobre
filas ya traidas (OPS-14).

El heatmap (/heatmap, /heatmap/scale) se compone sobre el ultimo frame fuera
del event loop (asyncio.to_thread), igual que /api/heatmap en main.py, y
distingue 503 (sin camara/frame) de 404 (sin actividad acumulada) — el v1 no
lo hace. El export (/export) no vive aqui: lo anade 31-09.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import cv2
from fastapi import APIRouter, HTTPException, Query, Request, Response

from backend.api.v2.deps import V2_RATE_LIMIT, limiter
from backend.database import get_session_factory
from backend.storage.repositories import AnalyticsRepo, bucket_for

router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])

_camera_manager: Any = None

MAX_RANGE_DAYS = 90
_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager instance. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager


def _repo() -> AnalyticsRepo:
    return AnalyticsRepo(get_session_factory())


def _resolve_range(
    from_: datetime.date, to_: datetime.date
) -> tuple[datetime.datetime, datetime.datetime, int]:
    """Rango inclusivo del cliente -> ventana semiabierta [cur_from, cur_to).

    Las dos cadenas de error son literales de la tabla de copy del UI-SPEC: el
    cliente valida lo mismo antes de pedir nada, pero la autoridad es esta.
    """
    if to_ < from_:
        raise HTTPException(status_code=422, detail="La fecha «Hasta» debe ser posterior a «Desde».")
    span_days = (to_ - from_).days + 1
    if span_days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail="El rango máximo es de 90 días.")
    cur_from = datetime.datetime.combine(from_, datetime.time.min)
    cur_to = datetime.datetime.combine(to_ + datetime.timedelta(days=1), datetime.time.min)
    return cur_from, cur_to, span_days


def _label(dt: datetime.datetime, bucket: str, span_days: int) -> str:
    if bucket == "day":
        return f"{dt.day} {_MESES[dt.month - 1]}"
    if span_days <= 1:
        return f"{dt.hour:02d}:00"
    return f"{dt.day} {_MESES[dt.month - 1]} {dt.hour:02d}:00"


def _axis(start: datetime.datetime, end: datetime.datetime, bucket: str) -> list[datetime.datetime]:
    """Eje completo de cubos [start, end), paso de 1 hora o de 1 dia."""
    step = datetime.timedelta(hours=1) if bucket == "hour" else datetime.timedelta(days=1)
    out, cur = [], start
    while cur < end:
        out.append(cur)
        cur += step
    return out


def _key(dt: datetime.datetime, bucket: str) -> str:
    """Misma forma que devuelve substr(ts,1,13|10) en AnalyticsRepo."""
    return dt.strftime("%Y-%m-%d %H") if bucket == "hour" else dt.strftime("%Y-%m-%d")


def _parse_bucket_key(key: str, bucket: str) -> datetime.datetime:
    """Inverso de _key(): reconstruye el datetime desde la clave de cubo del repo."""
    fmt = "%Y-%m-%d %H" if bucket == "hour" else "%Y-%m-%d"
    return datetime.datetime.strptime(key, fmt)


@router.get("/hourly")
@limiter.limit(V2_RATE_LIMIT)
async def get_hourly(
    request: Request,
    camera_id: str = Query(default="cam1"),
    from_: datetime.date = Query(alias="from"),
    to_: datetime.date = Query(alias="to"),
) -> dict[str, Any]:
    cur_from, cur_to, span_days = _resolve_range(from_, to_)
    bucket = bucket_for(cur_from, cur_to)

    rows = await _repo().hourly(camera_id, cur_from, cur_to, bucket)
    by_key = {b: (cur, prev) for b, cur, prev in rows}

    cur_axis = _axis(cur_from, cur_to, bucket)
    # mismo span, mismo paso -> misma longitud que cur_axis por construccion
    prev_axis = _axis(cur_from - (cur_to - cur_from), cur_from, bucket)

    values = [by_key.get(_key(d, bucket), (0, 0))[0] for d in cur_axis]
    previous = [by_key.get(_key(d, bucket), (0, 0))[1] for d in prev_axis]
    labels = [_label(d, bucket, span_days) for d in cur_axis]

    total = sum(values)
    # en empate gana el indice mas bajo: coincide con ORDER BY n DESC, bucket ASC del repo
    peak_index = max(range(len(values)), key=values.__getitem__) if total else None
    min_index = min(range(len(values)), key=values.__getitem__) if total else None
    has_previous = any(previous)
    chart = "bar" if len(labels) <= 48 else "line"

    return {
        "range": {"from": from_.isoformat(), "to": to_.isoformat(), "bucket": bucket, "days": span_days},
        "labels": labels,
        "values": values,
        "previous": previous,
        "total": total,
        "peak_index": peak_index,
        "min_index": min_index,
        "has_previous": has_previous,
        "chart": chart,
    }


@router.get("/summary")
@limiter.limit(V2_RATE_LIMIT)
async def get_summary(
    request: Request,
    camera_id: str = Query(default="cam1"),
    from_: datetime.date = Query(alias="from"),
    to_: datetime.date = Query(alias="to"),
) -> dict[str, Any]:
    cur_from, cur_to, span_days = _resolve_range(from_, to_)
    bucket = bucket_for(cur_from, cur_to)

    data = await _repo().summary(camera_id, cur_from, cur_to, bucket)

    total = data["total"]
    previous_total = data["previous_total"]
    delta_pct = None if not previous_total else round((total - previous_total) * 100 / previous_total)

    peak = None
    if data["peak_bucket"] is not None:
        peak_dt = _parse_bucket_key(data["peak_bucket"], bucket)
        peak = {"label": _label(peak_dt, bucket, span_days), "value": data["peak_value"]}

    min_ = None
    if data["min_bucket"] is not None:
        min_dt = _parse_bucket_key(data["min_bucket"], bucket)
        min_ = {"label": _label(min_dt, bucket, span_days), "value": data["min_value"]}

    previous_from = from_ - datetime.timedelta(days=span_days)
    previous_to = from_ - datetime.timedelta(days=1)

    return {
        "range": {"from": from_.isoformat(), "to": to_.isoformat(), "bucket": bucket, "days": span_days},
        "previous_range": {"from": previous_from.isoformat(), "to": previous_to.isoformat()},
        "total": total,
        "previous_total": previous_total,
        "delta_pct": delta_pct,
        "peak": peak,
        "min": min_,
        "known": data["known"],
        "unknown": data["unknown"],
    }


@router.get("/occupancy")
@limiter.limit(V2_RATE_LIMIT)
async def get_occupancy(
    request: Request,
    camera_id: str = Query(default="cam1"),
    from_: datetime.date = Query(alias="from"),
    to_: datetime.date = Query(alias="to"),
) -> dict[str, Any]:
    cur_from, cur_to, span_days = _resolve_range(from_, to_)

    rows, total_zones = await _repo().occupancy(camera_id, cur_from, cur_to, limit=10)
    # el orden ya viene descendente de SQL — prohibido sorted() aqui
    labels = [r["name"] for r in rows]
    values = [r["value"] for r in rows]
    truncated = total_zones > len(labels)

    return {
        "range": {"from": from_.isoformat(), "to": to_.isoformat(), "days": span_days},
        "labels": labels,
        "values": values,
        "total_zones": total_zones,
        "truncated": truncated,
    }


@router.get("/persons")
@limiter.limit(V2_RATE_LIMIT)
async def get_persons(
    request: Request,
    camera_id: str = Query(default="cam1"),
    from_: datetime.date = Query(alias="from"),
    to_: datetime.date = Query(alias="to"),
) -> dict[str, Any]:
    cur_from, cur_to, span_days = _resolve_range(from_, to_)

    rows = await _repo().persons_ranking(camera_id, cur_from, cur_to, limit=10)
    avatars = await _repo().person_avatars([pid for pid, _, _ in rows])

    pipeline = _camera_manager.get(camera_id) if _camera_manager is not None else None
    recognizer = getattr(pipeline, "recognizer", None)
    available = bool(recognizer is not None and getattr(recognizer, "available", False))
    if available:
        # sqlite3 sincrono bajo threading.Lock compartido con el hilo de reconocimiento:
        # llamarlo desde la corrutina pararia el event loop y con el el MJPEG y el WS
        # (CLAUDE.md, Pitfall 5). Mismo precedente que main.py con get_heatmap.
        names = {p["id"]: p["name"] for p in await asyncio.to_thread(recognizer.list_persons)}
    else:
        names = {}   # instalacion sin modelos de cara: el ranking degrada, no revienta

    persons = [
        {
            "person_id": pid,
            "name": names.get(pid) or f"Persona {pid}",
            "avatar_url": avatars.get(pid),
            "visits": cur,
            "delta_pct": None if not prev else round((cur - prev) * 100 / prev),
        }
        for pid, cur, prev in rows  # el orden ya viene de SQL — nada de sorted()
    ]

    return {
        "range": {"from": from_.isoformat(), "to": to_.isoformat(), "days": span_days},
        "persons": persons,
        "recognition_available": available,
    }


@router.get("/heatmap")
@limiter.limit(V2_RATE_LIMIT)
async def get_heatmap(request: Request, camera_id: str = Query(default="cam1")) -> Response:
    """Mapa de calor acumulado, compuesto sobre el ultimo frame (JPEG).

    Acumula desde el arranque de la camara y NO sigue el rango de la vista (D-12):
    el panel lo dice con un chip visible en vez de fingir que responde al selector.
    503 y 404 significan cosas distintas y el panel tiene un texto para cada una,
    a diferencia del v1 /api/heatmap, que devuelve 404 para las dos.
    """
    pipeline = _camera_manager.get(camera_id) if _camera_manager is not None else None
    if pipeline is None or pipeline.get_frame() is None:
        raise HTTPException(status_code=503, detail="Cámara sin señal")
    img = await asyncio.to_thread(pipeline.get_heatmap)
    if img is None:
        raise HTTPException(status_code=404, detail="Sin actividad acumulada")
    ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="No se pudo codificar el mapa de calor")
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


@router.get("/heatmap/scale")
@limiter.limit(V2_RATE_LIMIT)
async def get_heatmap_scale(request: Request, camera_id: str = Query(default="cam1")) -> dict[str, Any]:
    """Pico y media de la mascara acumulada, para la leyenda numerica del panel.

    Mismo orden de comprobaciones que /heatmap (503 antes que 404) para que los
    dos endpoints cuenten la misma historia.
    """
    pipeline = _camera_manager.get(camera_id) if _camera_manager is not None else None
    if pipeline is None or pipeline.get_frame() is None:
        raise HTTPException(status_code=503, detail="Cámara sin señal")
    scale = await asyncio.to_thread(pipeline.get_heatmap_scale)
    if scale is None:
        raise HTTPException(status_code=404, detail="Sin actividad acumulada")
    return {
        "peak": scale["peak"],
        "mean": scale["mean"],
        "unit": "frames de detección con presencia",
    }
