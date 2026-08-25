"""Tests para GET/POST(upsert)/DELETE /api/v2/lines (Fase 33, 33-07).

Router probado con una app FastAPI local (no `backend.main.app`): el wiring real a
`camera_manager` llega en el Plan 33-08, que anade su propia comprobacion de integracion.
`LineRepo`/`CameraManager` se sustituyen por dobles de prueba via
`patch.object(lines_module, "_line_repo", ...)` y `lines_module.configure(...)`, mismo
patron que `tests/test_zones_api.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.v2 import lines as lines_module
from backend.api.v2.deps import limiter

VALID_LINE = {
    "id": "l1", "name": "Linea 1",
    "start_x_frac": 0.0, "start_y_frac": 0.5,
    "end_x_frac": 1.0, "end_y_frac": 0.5,
}


def _local_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(lines_module.router)
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
def _reset_lines_wiring():
    yield
    lines_module.configure(None)


# ─── GET /api/v2/lines ────────────────────────────────────────────────────
async def TEST_get_lines_returns_all_without_filter():
    repo = _fake_repo(list_return=[{"id": "l1", "camera_id": "cam1"}])
    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/lines")
    assert resp.status_code == 200
    assert resp.json() == {"lines": [{"id": "l1", "camera_id": "cam1"}]}
    repo.list.assert_awaited_once_with(camera_id=None)


async def TEST_get_lines_filters_by_camera_id():
    repo = _fake_repo(list_return=[])
    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/lines", params={"camera_id": "cam1"})
    assert resp.status_code == 200
    repo.list.assert_awaited_once_with(camera_id="cam1")


# ─── POST /api/v2/lines — casos validos ──────────────────────────────────
async def TEST_post_line_valid_defaults_camera_id_and_pushes_hot_reload():
    repo = _fake_repo(list_return=[{"id": "l1", "camera_id": "cam1"}])
    pipeline = MagicMock()
    pipeline.camera_id = "cam1"
    manager = MagicMock()
    manager.all = MagicMock(return_value=[pipeline])
    lines_module.configure(manager)

    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/lines", json=VALID_LINE)
    assert resp.status_code == 200
    assert resp.json() == {"lines": [{"id": "l1", "camera_id": "cam1"}]}
    repo.upsert.assert_awaited_once_with(
        "l1", "cam1", "Linea 1", 0.0, 0.5, 1.0, 0.5, enabled=True,
    )
    pipeline.set_lines.assert_called_once_with([{"id": "l1", "camera_id": "cam1"}])


async def TEST_post_line_without_camera_manager_does_not_raise():
    repo = _fake_repo(list_return=[])
    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/lines", json=VALID_LINE)
    assert resp.status_code == 200


# ─── POST /api/v2/lines — casos invalidos (422) ──────────────────────────
async def TEST_post_line_coordinate_out_of_range_422():
    repo = _fake_repo()
    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/lines",
                json={**VALID_LINE, "end_x_frac": 1.5},
            )
    assert resp.status_code == 422
    assert "1.5" in resp.text


async def TEST_post_line_degenerate_422():
    repo = _fake_repo()
    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post(
                "/api/v2/lines",
                json={
                    "id": "l1", "name": "Linea 1",
                    "start_x_frac": 0.3, "start_y_frac": 0.3,
                    "end_x_frac": 0.3, "end_y_frac": 0.3,
                },
            )
    assert resp.status_code == 422
    assert "degenerad" in resp.text


# ─── DELETE /api/v2/lines/{id} ───────────────────────────────────────────
async def TEST_delete_line_not_found_404():
    repo = _fake_repo(delete_return=False)
    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/lines/does-not-exist")
    assert resp.status_code == 404


async def TEST_delete_line_existing_pushes_hot_reload_and_returns_remaining():
    repo = _fake_repo(list_return=[{"id": "l2", "camera_id": "cam1"}], delete_return=True)
    pipeline = MagicMock()
    pipeline.camera_id = "cam1"
    manager = MagicMock()
    manager.all = MagicMock(return_value=[pipeline])
    lines_module.configure(manager)

    with patch.object(lines_module, "_line_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/lines/l1")
    assert resp.status_code == 200
    assert resp.json() == {"lines": [{"id": "l2", "camera_id": "cam1"}]}
    pipeline.set_lines.assert_called_once_with([{"id": "l2", "camera_id": "cam1"}])


# --- Wiring en main.py -----------------------------------------------------
def TEST_main_imports_with_lines_router_registered():
    import backend.main as main_module
    from tests.route_utils import iter_app_routes
    paths = {getattr(r, "path", None) for r in iter_app_routes(main_module.app)}
    assert "/api/v2/lines" in paths
    assert "/api/v2/lines/{line_id}" in paths
