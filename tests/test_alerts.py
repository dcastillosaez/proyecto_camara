"""Tests del centro de alertas /api/v2/alerts (Fase 30, OPS-11).

Cubren la agrupacion por regla (o por tipo cuando ninguna regla disparo), el orden por
severidad y recencia, la ventana temporal acotada y los contadores del badge de la campana.

Cableado: el router construye sus repos con `get_session_factory()` importado en su propio
modulo, asi que basta parchear `alerts_module.get_session_factory` para apuntar a una base
temporal — mismo criterio que test_events_api.py.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.main as main_module
from backend.api.v2 import alerts as alerts_module
from backend.events.types import Event, EventType
from backend.storage import models
from backend.storage.repositories import ConfigRepo, EventRepo

NOW = datetime.datetime.now()


@pytest_asyncio.fixture
async def sf(tmp_path):
    """Base temporal con una camara, ya parcheada dentro del modulo del router."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'alerts.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    with patch.object(alerts_module, "get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as c:
        yield c


def make_event(minutes_ago: int = 5, **overrides) -> Event:
    kwargs = {
        "type": EventType.INTRUSION,
        "camera_id": "cam1",
        "ts": NOW - datetime.timedelta(minutes=minutes_ago),
    }
    kwargs.update(overrides)
    return Event(**kwargs)


async def _insert(factory, *events: Event) -> None:
    repo = EventRepo(factory)
    for ev in events:
        await repo.insert(ev)


def _by_key(body: dict) -> dict[str, dict]:
    return {g["key"]: g for g in body["groups"]}


# ─── Agrupacion ─────────────────────────────────────────────────────────────
async def TEST_alerts_group_by_rule_name(sf, client):
    await _insert(
        sf,
        *[make_event(minutes_ago=i, payload={"rules": ["Intrusion nocturna"]}) for i in range(5)],
        *[make_event(minutes_ago=i, payload={"rules": ["Merodeo"]}) for i in range(2)],
    )

    body = (await client.get("/api/v2/alerts")).json()

    groups = _by_key(body)
    assert set(groups) == {"rule:Intrusion nocturna", "rule:Merodeo"}
    assert groups["rule:Intrusion nocturna"]["count"] == 5
    assert groups["rule:Merodeo"]["count"] == 2
    assert all(g["mutable"] is True for g in groups.values())
    assert groups["rule:Intrusion nocturna"]["rule_name"] == "Intrusion nocturna"


async def TEST_alerts_group_by_type_when_no_rule(sf, client):
    await _insert(sf, make_event(), make_event(minutes_ago=6))

    body = (await client.get("/api/v2/alerts")).json()

    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["key"] == "type:INTRUSION"
    assert group["rule_name"] is None
    assert group["mutable"] is False
    assert group["count"] == 2
    assert group["severity"] == "critical"


async def TEST_alerts_exclude_info_severity(sf, client):
    await _insert(
        sf,
        make_event(type=EventType.LINE_CROSSED),
        make_event(type=EventType.INTRUSION),
    )

    body = (await client.get("/api/v2/alerts")).json()

    assert set(_by_key(body)) == {"type:INTRUSION"}


async def TEST_alerts_include_info_events_that_fired_a_rule(sf, client):
    await _insert(
        sf,
        make_event(type=EventType.LINE_CROSSED, payload={"rules": ["Paso de linea"]}),
    )

    body = (await client.get("/api/v2/alerts")).json()

    groups = _by_key(body)
    assert "rule:Paso de linea" in groups
    assert groups["rule:Paso de linea"]["severity"] == "info"


async def TEST_alerts_sorted_by_severity_then_recency(sf, client):
    await _insert(
        sf,
        make_event(minutes_ago=120, type=EventType.INTRUSION),           # critical, antiguo
        make_event(minutes_ago=1, type=EventType.UNKNOWN_PERSON),        # warning, reciente
    )

    body = (await client.get("/api/v2/alerts")).json()

    assert [g["key"] for g in body["groups"]] == ["type:INTRUSION", "type:UNKNOWN_PERSON"]


async def TEST_alerts_respect_window_hours(sf, client):
    await _insert(
        sf,
        make_event(minutes_ago=48 * 60, type=EventType.INTRUSION),
        make_event(minutes_ago=10, type=EventType.UNKNOWN_PERSON),
    )

    body = (await client.get("/api/v2/alerts", params={"hours": 24})).json()

    assert set(_by_key(body)) == {"type:UNKNOWN_PERSON"}
    assert body["window_hours"] == 24


@pytest.mark.parametrize("hours", [0, 1000])
async def TEST_alerts_hours_param_is_bounded(sf, client, hours):
    resp = await client.get("/api/v2/alerts", params={"hours": hours})

    assert resp.status_code == 422


async def TEST_alerts_counts_match_groups(sf, client):
    await _insert(
        sf,
        make_event(type=EventType.INTRUSION),
        make_event(type=EventType.UNKNOWN_PERSON),
        make_event(type=EventType.OBJECT_LEFT),
    )

    body = (await client.get("/api/v2/alerts")).json()

    assert body["active_count"] == len(body["groups"]) == 3
    assert body["critical_count"] == 1
    assert body["muted_count"] == 0
    assert body["truncated"] is False
    assert body["checked_at"]


# ─── Silenciado ─────────────────────────────────────────────────────────────
async def _muted_rows(factory) -> dict:
    return await ConfigRepo(factory).get(alerts_module.MUTED_KEY, {}) or {}


async def TEST_mute_persists_until_in_app_config(sf, client):
    resp = await client.post(
        "/api/v2/alerts/mute", json={"rule_name": "R", "duration_secs": 900})

    assert resp.status_code == 200
    until = datetime.datetime.fromisoformat(resp.json()["until"])
    assert 890 <= (until - datetime.datetime.now()).total_seconds() <= 900
    rows = await _muted_rows(sf)
    assert rows["R"]["until"] == resp.json()["until"]


async def TEST_mute_rejects_arbitrary_duration(sf, client):
    resp = await client.post(
        "/api/v2/alerts/mute", json={"rule_name": "R", "duration_secs": 12345})

    assert resp.status_code == 400
    assert "900" in resp.json()["detail"]
    assert await _muted_rows(sf) == {}


async def TEST_mute_rejects_empty_rule_name(sf, client):
    resp = await client.post(
        "/api/v2/alerts/mute", json={"rule_name": "", "duration_secs": 900})

    assert resp.status_code in (400, 422)
    assert await _muted_rows(sf) == {}


async def TEST_muted_rule_is_excluded_from_active_count(sf, client):
    await _insert(
        sf,
        make_event(payload={"rules": ["Intrusion nocturna"]}),
        make_event(type=EventType.UNKNOWN_PERSON),
    )
    before = (await client.get("/api/v2/alerts")).json()["active_count"]

    await client.post(
        "/api/v2/alerts/mute",
        json={"rule_name": "Intrusion nocturna", "duration_secs": 3600})
    body = (await client.get("/api/v2/alerts")).json()

    assert body["active_count"] == before - 1
    assert body["muted_count"] == 1
    group = _by_key(body)["rule:Intrusion nocturna"]
    assert group["muted_until"] is not None      # sigue visible, solo atenuado


async def TEST_expired_mute_is_ignored_and_purged_on_write(sf, client):
    past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat()
    await ConfigRepo(sf).set(alerts_module.MUTED_KEY, {"Vieja": {"until": past, "camera_id": None}})
    await _insert(sf, make_event(payload={"rules": ["Vieja"]}))

    body = (await client.get("/api/v2/alerts")).json()
    assert body["muted_count"] == 0
    assert _by_key(body)["rule:Vieja"]["muted_until"] is None

    await client.post("/api/v2/alerts/mute", json={"rule_name": "Otra", "duration_secs": 900})
    assert "Vieja" not in await _muted_rows(sf)


async def TEST_unmute_removes_entry(sf, client):
    await client.post("/api/v2/alerts/mute", json={"rule_name": "R", "duration_secs": 900})

    resp = await client.post("/api/v2/alerts/unmute", json={"rule_name": "R"})

    assert resp.status_code == 200
    assert resp.json() == {"rule_name": "R", "muted": False}
    assert await _muted_rows(sf) == {}


async def TEST_mute_emits_config_changed(sf, client):
    engine = MagicMock()
    with patch.object(alerts_module, "_event_engine", engine):
        await client.post("/api/v2/alerts/mute", json={"rule_name": "R", "duration_secs": 3600})

    engine.config_changed.assert_called_once()
    kwargs = engine.config_changed.call_args.kwargs
    assert kwargs["muted_rule"] == "R"
    assert kwargs["duration_secs"] == 3600
