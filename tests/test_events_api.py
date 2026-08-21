"""Tests del contrato HTTP de /api/v2/events (Fase 30, OPS-07/08/09).

Cubren el envelope de la lista ({events, cursor, total, media}), el filtro por tipo
repetido, los rechazos con 400 de enum invalido, el `total` condicional (solo primera
pagina con filtros, Pitfall 9) y el mapa `media` como clave hermana del evento.

Cableado: el router construye sus repos con `get_session_factory()` importado en su
propio modulo, asi que basta parchear `events_module.get_session_factory` para apuntar
a una base temporal — mismo criterio que test_detection_config_api.py, que parchea el
simbolo del modulo del router y no el global de main.py.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.main as main_module
from backend.api.v2 import events as events_module
from backend.events.types import Event, EventType
from backend.storage import models
from backend.storage.repositories import EventRepo, RecordingRepo


@pytest_asyncio.fixture
async def sf(tmp_path):
    """Base temporal con una camara, ya parcheada dentro del modulo del router."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events_api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    with patch.object(events_module, "get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as c:
        yield c


def make_event(**overrides) -> Event:
    kwargs = {
        "type": EventType.LINE_CROSSED,
        "camera_id": "cam1",
        "ts": datetime.datetime(2026, 8, 20, 18, 30, 0),
    }
    kwargs.update(overrides)
    return Event(**kwargs)


async def _insert(factory, *events: Event) -> None:
    repo = EventRepo(factory)
    for ev in events:
        await repo.insert(ev)


# ─── Lista: envelope y filtros ──────────────────────────────────────────────
async def TEST_list_events_returns_envelope_with_events_and_cursor(sf, client):
    await _insert(sf, make_event(), make_event(), make_event())

    resp = await client.get("/api/v2/events", params={"limit": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"events", "cursor", "total", "media"}
    assert len(body["events"]) == 2
    assert body["cursor"]


async def TEST_list_events_accepts_repeated_type_param(sf, client):
    await _insert(
        sf,
        make_event(type=EventType.INTRUSION),
        make_event(type=EventType.UNKNOWN_PERSON),
        make_event(type=EventType.LINE_CROSSED),
    )

    resp = await client.get("/api/v2/events?type=INTRUSION&type=UNKNOWN_PERSON")

    assert resp.status_code == 200
    types = {e["type"] for e in resp.json()["events"]}
    assert types == {"INTRUSION", "UNKNOWN_PERSON"}


async def TEST_list_events_rejects_unknown_type(sf, client):
    resp = await client.get("/api/v2/events", params={"type": "NO_EXISTE"})
    assert resp.status_code == 400
    assert resp.json()["detail"]


async def TEST_list_events_rejects_unknown_severity(sf, client):
    resp = await client.get("/api/v2/events", params={"severity": "urgentisimo"})
    assert resp.status_code == 400
    assert resp.json()["detail"]


# ─── total condicional (Pitfall 9) ──────────────────────────────────────────
async def TEST_total_is_null_without_filters(sf, client):
    await _insert(sf, make_event(), make_event())

    body = (await client.get("/api/v2/events")).json()

    assert body["total"] is None


async def TEST_total_is_present_on_first_filtered_page(sf, client):
    await _insert(
        sf,
        make_event(type=EventType.INTRUSION, ts=datetime.datetime(2026, 8, 20, 18, 0)),
        make_event(type=EventType.INTRUSION, ts=datetime.datetime(2026, 8, 20, 18, 1)),
        make_event(type=EventType.INTRUSION, ts=datetime.datetime(2026, 8, 20, 18, 2)),
        make_event(type=EventType.LINE_CROSSED),
    )

    first = (await client.get("/api/v2/events?severity=critical&limit=2")).json()
    assert first["total"] == 3
    assert first["cursor"]

    second = (
        await client.get(
            "/api/v2/events", params={"severity": "critical", "limit": 2,
                                      "cursor": first["cursor"]}
        )
    ).json()
    assert second["total"] is None


# ─── media ──────────────────────────────────────────────────────────────────
async def TEST_media_map_only_contains_events_with_media(sf, client):
    with_media = make_event(
        type=EventType.INTRUSION,
        ts=datetime.datetime(2026, 8, 20, 18, 5),
        snapshot_path="data/snapshots/20260820/con-media.jpg",
    )
    without = make_event(ts=datetime.datetime(2026, 8, 20, 18, 4))
    await _insert(sf, with_media, without)

    rec_id = await RecordingRepo(sf).create(
        camera_id="cam1", filename="clip_20260820_180500.mp4",
        started_at=datetime.datetime(2026, 8, 20, 18, 5),
        reason="intrusion", trigger_event_id=with_media.id,
    )

    body = (await client.get("/api/v2/events")).json()

    assert list(body["media"]) == [with_media.id]
    entry = body["media"][with_media.id]
    assert entry["recording_id"] == rec_id
    assert entry["clip_url"] == "/clips/clip_20260820_180500.mp4"
    assert entry["snapshot_url"].endswith("/20260820/con-media.jpg")
    assert entry["thumbnail_url"] is None


async def TEST_limit_is_capped_at_200(sf, client):
    resp = await client.get("/api/v2/events", params={"limit": 500})
    assert resp.status_code == 422


# ─── Detalle ────────────────────────────────────────────────────────────────
async def TEST_get_event_returns_event_and_media(sf, client):
    ev = make_event(type=EventType.INTRUSION)
    await _insert(sf, ev)

    resp = await client.get(f"/api/v2/events/{ev.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["event"]["id"] == ev.id
    assert set(body["media"]) == {
        "recording_id", "clip_url", "thumbnail_url", "snapshot_url"
    }


async def TEST_get_event_404_for_unknown_event(sf, client):
    resp = await client.get("/api/v2/events/no-existe")
    assert resp.status_code == 404
