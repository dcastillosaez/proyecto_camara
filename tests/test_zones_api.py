"""Tests para GET/POST(upsert)/DELETE /api/v2/zones (Fase 33, 33-03).

Router probado con una app FastAPI local (no `backend.main.app`): el wiring real a
`camera_manager` llega en el Plan 33-08, que anade su propia comprobacion de integracion.
`ZoneRepo`/`CameraManager` se sustituyen por dobles de prueba via
`patch.object(zones_module, "_zone_repo", ...)` y `zones_module.configure(...)`, mismo
patron que `tests/test_config_api.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.v2 import zones as zones_module
from backend.api.v2.deps import limiter

VALID_POLYGON = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]


def _local_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(zones_module.router)
    return app


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=_local_app()), base_url="http://test")


def _fake_repo(list_return: list | None = None, delete_return: bool = True) -> MagicMock:
    repo = MagicMock()
    repo.list = AsyncMock(return_value=list_return if list_return is not None else [])
    repo.upsert = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=delete_return)
    return repo


@pytest.fixture(autouse=True)
def _reset_zones_wiring():
    yield
    zones_module.configure(None)


# ─── GET /api/v2/zones ────────────────────────────────────────────────────
async def TEST_get_zones_returns_all_without_filter():
    repo = _fake_repo(list_return=[{"id": "z1", "camera_id": "cam1"}])
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/zones")
    assert resp.status_code == 200
    assert resp.json() == {"zones": [{"id": "z1", "camera_id": "cam1"}]}
    repo.list.assert_awaited_once_with(camera_id=None)


async def TEST_get_zones_filters_by_camera_id():
    repo = _fake_repo(list_return=[])
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/zones", params={"camera_id": "cam1"})
    assert resp.status_code == 200
    repo.list.assert_awaited_once_with(camera_id="cam1")


# ─── POST /api/v2/zones — casos validos ──────────────────────────────────
async def TEST_post_zone_valid_defaults_camera_id_and_pushes_hot_reload():
    repo = _fake_repo(list_return=[{"id": "z1", "camera_id": "cam1"}])
    pipeline = MagicMock()
    pipeline.camera_id = "cam1"
    manager = MagicMock()
    manager.all = MagicMock(return_value=[pipeline])
    zones_module.configure(manager)

    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={"id": "z1", "name": "Zona 1", "polygon": VALID_POLYGON},
            )
    assert resp.status_code == 200
    assert resp.json() == {"zones": [{"id": "z1", "camera_id": "cam1"}]}
    repo.upsert.assert_awaited_once_with(
        "z1", "cam1", "Zona 1", VALID_POLYGON, kind=None, schedule=None, enabled=True,
    )
    pipeline.set_zones.assert_called_once_with([{"id": "z1", "camera_id": "cam1"}])


async def TEST_post_zone_kind_exclude_objects_persists_without_rejection():
    repo = _fake_repo(list_return=[])
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={
                    "id": "z1", "name": "Zona 1", "polygon": VALID_POLYGON,
                    "kind": "exclude_objects",
                },
            )
    assert resp.status_code == 200
    repo.upsert.assert_awaited_once()
    assert repo.upsert.call_args.kwargs["kind"] == "exclude_objects"


async def TEST_post_zone_without_camera_manager_does_not_raise():
    repo = _fake_repo(list_return=[])
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={"id": "z1", "name": "Zona 1", "polygon": VALID_POLYGON},
            )
    assert resp.status_code == 200


# ─── POST /api/v2/zones — casos invalidos (422) ──────────────────────────
async def TEST_post_zone_polygon_too_few_points_422():
    repo = _fake_repo()
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={"id": "z1", "name": "Zona 1", "polygon": [[0.1, 0.1], [0.2, 0.2]]},
            )
    assert resp.status_code == 422
    assert ">=3 points" in resp.text


async def TEST_post_zone_point_out_of_range_422():
    repo = _fake_repo()
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={
                    "id": "z1", "name": "Zona 1",
                    "polygon": [[1.5, 0.2], [0.2, 0.2], [0.3, 0.3]],
                },
            )
    assert resp.status_code == 422
    assert "1.5" in resp.text


async def TEST_post_zone_kind_invalid_422():
    repo = _fake_repo()
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={
                    "id": "z1", "name": "Zona 1", "polygon": VALID_POLYGON,
                    "kind": "invalido",
                },
            )
    assert resp.status_code == 422


async def TEST_post_zone_schedule_invalid_time_range_422():
    repo = _fake_repo()
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/zones",
                json={
                    "id": "z1", "name": "Zona 1", "polygon": VALID_POLYGON,
                    "schedule": {"time_range": "25:00-08:00"},
                },
            )
    assert resp.status_code == 422


# ─── DELETE /api/v2/zones/{id} ───────────────────────────────────────────
async def TEST_delete_zone_not_found_404():
    repo = _fake_repo(delete_return=False)
    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/zones/does-not-exist")
    assert resp.status_code == 404


async def TEST_delete_zone_existing_pushes_hot_reload_and_returns_remaining():
    repo = _fake_repo(list_return=[{"id": "z2", "camera_id": "cam1"}], delete_return=True)
    pipeline = MagicMock()
    pipeline.camera_id = "cam1"
    manager = MagicMock()
    manager.all = MagicMock(return_value=[pipeline])
    zones_module.configure(manager)

    with patch.object(zones_module, "_zone_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/zones/z1")
    assert resp.status_code == 200
    assert resp.json() == {"zones": [{"id": "z2", "camera_id": "cam1"}]}
    pipeline.set_zones.assert_called_once_with([{"id": "z2", "camera_id": "cam1"}])


# --- Wiring en main.py -----------------------------------------------------
def TEST_main_imports_with_zones_router_registered():
    import backend.main as main_module
    from tests.route_utils import iter_app_routes
    paths = {getattr(r, "path", None) for r in iter_app_routes(main_module.app)}
    assert "/api/v2/zones" in paths
    assert "/api/v2/zones/{zone_id}" in paths
