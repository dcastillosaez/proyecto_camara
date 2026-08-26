"""Tests for /api/v2/cameras y /api/v2/cameras/{camera_id}/health (Fase 17,
extraidos a su propio router en la Fase 35).

Cableado: se llama directamente a cameras_module.configure(mock_manager) en cada
test en vez de parchear el global de main.py — mismo criterio que
test_detection_config_api.py.
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock

import httpx
import pytest
from httpx import ASGITransport

import backend.main as main_module
from backend.api.v2 import cameras as cameras_module
from backend.pipeline.capture import CaptureHealth


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test")


@pytest.fixture(autouse=True)
def _reset_cameras_wiring():
    yield
    cameras_module.configure(None)


def _fake_pipeline(camera_id="cam1", connected=True, degraded=False) -> MagicMock:
    pipeline = MagicMock()
    pipeline.health = CaptureHealth(
        camera_id=camera_id, connected=connected, fps=12.5, reconnects=0,
        last_frame_age_s=0.2, native_resolution=(1280, 720), frames_captured=100,
    )
    pipeline.worker_status.return_value = {"capture": "running", "detector": "running"}
    pipeline.degraded = degraded
    pipeline.get_fps.return_value = 12.5
    pipeline.get_detection_fps.return_value = 8.0
    pipeline.broker.stats.return_value = {"subscribers": 2}
    pipeline.stats.return_value = {"detection": {"effective_fps": 8.0}}
    return pipeline


def _mock_manager(*pipelines) -> MagicMock:
    manager = MagicMock()
    manager.all.return_value = list(pipelines)
    by_id = {p.health.camera_id: p for p in pipelines}
    manager.get.side_effect = lambda cid: by_id.get(cid)
    return manager


async def TEST_list_returns_503_when_pipeline_v2_not_active():
    cameras_module.configure(None)
    async with await _client() as client:
        resp = await client.get("/api/v2/cameras")
    assert resp.status_code == 503


async def TEST_list_returns_health_for_every_camera():
    cam1, cam2 = _fake_pipeline("cam1"), _fake_pipeline("cam2", connected=False)
    cameras_module.configure(_mock_manager(cam1, cam2))

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras")

    assert resp.status_code == 200
    body = resp.json()
    assert {c["camera_id"] for c in body["cameras"]} == {"cam1", "cam2"}
    assert all("workers" in c and "degraded" in c for c in body["cameras"])


async def TEST_list_is_empty_with_zero_cameras_but_pipeline_active():
    cameras_module.configure(_mock_manager())

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras")

    assert resp.status_code == 200
    assert resp.json() == {"cameras": []}


async def TEST_health_returns_503_when_pipeline_v2_not_active():
    cameras_module.configure(None)
    async with await _client() as client:
        resp = await client.get("/api/v2/cameras/cam1/health")
    assert resp.status_code == 503


async def TEST_health_returns_404_for_unknown_camera():
    cameras_module.configure(_mock_manager(_fake_pipeline("cam1")))
    async with await _client() as client:
        resp = await client.get("/api/v2/cameras/does-not-exist/health")
    assert resp.status_code == 404


async def TEST_health_includes_capture_and_detection_fps_distinct():
    """capture_fps y detection_fps deliberadamente distintos: esa diferencia ES
    la prueba de que el pipeline esta desacoplado (ver el docstring del endpoint)."""
    pipeline = _fake_pipeline("cam1")
    pipeline.get_fps.return_value = 25.0
    pipeline.get_detection_fps.return_value = 8.0
    cameras_module.configure(_mock_manager(pipeline))

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras/cam1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["capture_fps"] == 25.0
    assert body["detection_fps"] == 8.0
    assert body["camera_id"] == "cam1"


async def TEST_health_body_matches_capture_health_fields():
    pipeline = _fake_pipeline("cam1")
    cameras_module.configure(_mock_manager(pipeline))

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras/cam1/health")

    body = resp.json()
    for key, value in asdict(pipeline.health).items():
        # JSON no distingue tupla de lista: native_resolution vuelve como [w, h].
        assert body[key] == (list(value) if isinstance(value, tuple) else value)
