"""Tests for GET/POST/DELETE /api/v2/rules y POST /{id}/test (Fase 33, 33-06).

Router probado con una app FastAPI local (no `backend.main.app`): el wiring real al
`RuleEngine` en vivo llega en el Plan 33-08. `RuleRepo`/`EventRepo` se sustituyen
parcheando `rules_module._rule_repo`/`rules_module._event_repo` con dobles de prueba,
mismo patron que `tests/test_config_api.py`. `app.state.limiter`/el exception handler de
slowapi se replican aqui porque `@limiter.limit()` necesita un `request.app.state.limiter`
real para aplicar la politica (mismo Limiter compartido de `backend/api/v2/deps.py`).
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.v2 import rules as rules_module
from backend.api.v2.deps import limiter
from backend.events.rules import RuleEngine
from backend.events.types import Event, EventType


def _local_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(rules_module.router)
    return app


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=_local_app()), base_url="http://test")


def _rule_row(
    rule_id: str = "r1",
    name: str = "Regla 1",
    enabled: bool = True,
    when: dict | None = None,
    actions: list | None = None,
) -> dict:
    return {
        "id": rule_id,
        "name": name,
        "enabled": enabled,
        "definition": {
            "when": when or {"event": "LINE_CROSSED"},
            "debounce_secs": 0.0,
            "actions": actions if actions is not None else [{"type": "log"}],
        },
        "updated_at": datetime.datetime(2026, 1, 1).isoformat(),
    }


def _fake_rule_repo(rows: list[dict] | None = None, get_return: dict | None = None) -> MagicMock:
    repo = MagicMock()
    repo.list = AsyncMock(return_value=rows if rows is not None else [])
    repo.get = AsyncMock(return_value=get_return)
    repo.upsert = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=True)
    return repo


def _fake_event_repo(events: list[Event] | None = None) -> MagicMock:
    repo = MagicMock()
    repo.query = AsyncMock(return_value=(events or [], None))
    return repo


def _event(event_type: EventType = EventType.LINE_CROSSED, camera_id: str = "cam1") -> Event:
    return Event(type=event_type, camera_id=camera_id, ts=datetime.datetime(2026, 1, 1, 12, 0, 0))


@pytest.fixture(autouse=True)
def _reset_rules_wiring():
    yield
    rules_module.configure(None)


# ─── GET /api/v2/rules ───────────────────────────────────────────────────────
async def TEST_get_rules_returns_list_from_repo():
    rows = [_rule_row()]
    with patch.object(rules_module, "_rule_repo", return_value=_fake_rule_repo(rows=rows)):
        async with await _client() as client:
            resp = await client.get("/api/v2/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rules"] == rows


# ─── POST /api/v2/rules — valid ──────────────────────────────────────────────
async def TEST_post_valid_rule_persists_and_reloads_engine():
    fake_repo = _fake_rule_repo(rows=[_rule_row()])
    engine = MagicMock(spec=RuleEngine)
    rules_module.configure(engine)
    payload = {
        "id": "r1",
        "name": "Regla 1",
        "enabled": True,
        "when": {"event": "LINE_CROSSED"},
        "actions": [{"type": "log"}],
    }
    with patch.object(rules_module, "_rule_repo", return_value=fake_repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/rules", json=payload)
    assert resp.status_code == 200
    fake_repo.upsert.assert_awaited_once()
    engine.reload.assert_called_once()
    assert resp.json()["rules"] == [_rule_row()]


# ─── POST /api/v2/rules — invalid event ──────────────────────────────────────
async def TEST_post_invalid_event_type_returns_custom_422_shape():
    payload = {
        "id": "r1",
        "name": "Regla 1",
        "when": {"event": "NOT_A_REAL_EVENT"},
        "actions": [{"type": "log"}],
    }
    with patch.object(rules_module, "_rule_repo", return_value=_fake_rule_repo()):
        async with await _client() as client:
            resp = await client.post("/api/v2/rules", json=payload)
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors[0]["field"] == "when.event"
    assert "message" in errors[0]


# ─── POST /api/v2/rules — empty actions ──────────────────────────────────────
async def TEST_post_empty_actions_returns_422():
    payload = {
        "id": "r1",
        "name": "Regla 1",
        "when": {"event": "LINE_CROSSED"},
        "actions": [],
    }
    with patch.object(rules_module, "_rule_repo", return_value=_fake_rule_repo()):
        async with await _client() as client:
            resp = await client.post("/api/v2/rules", json=payload)
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert any(e["field"] == "actions" for e in errors)


# ─── POST /api/v2/rules — invalid action type ────────────────────────────────
async def TEST_post_invalid_action_type_returns_422():
    payload = {
        "id": "r1",
        "name": "Regla 1",
        "when": {"event": "LINE_CROSSED"},
        "actions": [{"type": "invalido"}],
    }
    with patch.object(rules_module, "_rule_repo", return_value=_fake_rule_repo()):
        async with await _client() as client:
            resp = await client.post("/api/v2/rules", json=payload)
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert any("actions" in e["field"] for e in errors)


# ─── DELETE /api/v2/rules/{id} ───────────────────────────────────────────────
async def TEST_delete_nonexistent_rule_returns_404():
    fake_repo = _fake_rule_repo()
    fake_repo.delete = AsyncMock(return_value=False)
    with patch.object(rules_module, "_rule_repo", return_value=fake_repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/rules/nope")
    assert resp.status_code == 404


async def TEST_delete_existing_rule_reloads_engine_and_returns_remaining():
    fake_repo = _fake_rule_repo(rows=[])
    fake_repo.delete = AsyncMock(return_value=True)
    engine = MagicMock(spec=RuleEngine)
    rules_module.configure(engine)
    with patch.object(rules_module, "_rule_repo", return_value=fake_repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/rules/r1")
    assert resp.status_code == 200
    assert resp.json()["rules"] == []
    engine.reload.assert_called_once()


# ─── POST /api/v2/rules/{id}/test ────────────────────────────────────────────
async def TEST_test_rule_nonexistent_id_returns_404():
    with patch.object(rules_module, "_rule_repo", return_value=_fake_rule_repo(get_return=None)):
        async with await _client() as client:
            resp = await client.post("/api/v2/rules/nope/test")
    assert resp.status_code == 404


async def TEST_test_rule_counts_matches_without_mutating_debounce():
    row = _rule_row(when={"event": "LINE_CROSSED", "camera": "cam1"})
    events = [
        _event(EventType.LINE_CROSSED, "cam1"),
        _event(EventType.LINE_CROSSED, "cam1"),
        _event(EventType.ZONE_ENTERED, "cam1"),
    ]
    fake_rule_repo = _fake_rule_repo(get_return=row)
    fake_event_repo = _fake_event_repo(events=events)
    real_engine = RuleEngine(rules=[], registry=MagicMock())
    with patch.object(rules_module, "_rule_repo", return_value=fake_rule_repo), \
         patch.object(rules_module, "_event_repo", return_value=fake_event_repo):
        rules_module.configure(real_engine)
        async with await _client() as client:
            resp1 = await client.post("/api/v2/rules/r1/test")
            resp2 = await client.post("/api/v2/rules/r1/test")
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1 == {"would_fire": 2, "total_checked": 3}
    # Repetir /test no altera el resultado (would_match no muta el estado de debounce).
    assert resp2.json() == body1


# --- Wiring en main.py -----------------------------------------------------
def TEST_main_imports_with_rules_router_registered():
    import backend.main as main_module
    paths = {getattr(r, "path", None) for r in main_module.app.routes}
    assert "/api/v2/rules" in paths
    assert "/api/v2/rules/{rule_id}" in paths
