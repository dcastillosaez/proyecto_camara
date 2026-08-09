"""API v2 — metrics: Prometheus text exposition and JSON snapshot (Fase 21).

/metrics is unversioned (Prometheus scraping convention). Both routes inherit
the app-wide auth dependency (HTTP Basic, stateless) — "no exige sesion de
dashboard" (21-CONTEXT.md) just means a scraper never needs a login flow or
cookie, which Basic Auth already satisfies.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend.observability.metrics import generate_latest_text, snapshot

router = APIRouter(tags=["metrics"])

_latency_tracker: Any = None


def configure(latency_tracker: Any) -> None:
    """Wire the live LatencyTracker instance. Called once from main.py's lifespan."""
    global _latency_tracker
    _latency_tracker = latency_tracker


@router.get("/metrics")
async def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest_text(), media_type="text/plain; version=0.0.4")


@router.get("/api/v2/metrics")
async def metrics_snapshot() -> dict[str, Any]:
    data = snapshot()
    if _latency_tracker is not None:
        data["e2e_percentiles"] = _latency_tracker.e2e_percentiles()
    return data
