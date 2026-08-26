"""Tests for /api/v2/cameras y /api/v2/cameras/{camera_id}/health (Fase 17,
extraidos a su propio router en la Fase 35).

Cableado: se llama directamente a cameras_module.configure(mock_manager) en cada
test en vez de parchear el global de main.py — mismo criterio que
test_detection_config_api.py.
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

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


def _fake_pipeline(camera_id="cam1", connected=True, degraded=False, estimated_cpu_pct=0.0) -> MagicMock:
    pipeline = MagicMock()
    pipeline.health = CaptureHealth(
        camera_id=camera_id, connected=connected, fps=12.5, reconnects=0,
        last_frame_age_s=0.2, native_resolution=(1280, 720), frames_captured=100,
    )
    pipeline.worker_status.return_value = {"capture": "running", "detector": "running"}
    pipeline.degraded = degraded
    pipeline.estimated_cpu_pct = estimated_cpu_pct
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


async def TEST_list_includes_per_camera_and_total_estimated_cpu():
    """SCALE-08: coste de CPU estimado por camara y total, con umbral de aviso."""
    cam1 = _fake_pipeline("cam1", estimated_cpu_pct=60.0)
    cam2 = _fake_pipeline("cam2", estimated_cpu_pct=90.0)
    cameras_module.configure(_mock_manager(cam1, cam2))  # sin services -> umbral por defecto

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras")

    body = resp.json()
    by_id = {c["camera_id"]: c for c in body["cameras"]}
    assert by_id["cam1"]["estimated_cpu_pct"] == 60.0
    assert by_id["cam2"]["estimated_cpu_pct"] == 90.0
    assert body["total_estimated_cpu_pct"] == 150.0
    assert body["cpu_budget_warn_pct"] == cameras_module._DEFAULT_CPU_BUDGET_WARN_PCT
    assert body["over_budget"] is False  # 150 < 200 por defecto


async def TEST_list_flags_over_budget_when_total_exceeds_configured_threshold():
    cam1 = _fake_pipeline("cam1", estimated_cpu_pct=90.0)
    cam2 = _fake_pipeline("cam2", estimated_cpu_pct=90.0)
    services = MagicMock()
    services.settings.cpu_budget_warn_pct = 150.0
    cameras_module.configure(_mock_manager(cam1, cam2), services=services)

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras")

    body = resp.json()
    assert body["total_estimated_cpu_pct"] == 180.0
    assert body["cpu_budget_warn_pct"] == 150.0
    assert body["over_budget"] is True


async def TEST_list_is_empty_with_zero_cameras_but_pipeline_active():
    cameras_module.configure(_mock_manager())

    async with await _client() as client:
        resp = await client.get("/api/v2/cameras")

    assert resp.status_code == 200
    assert resp.json()["cameras"] == []
    assert resp.json()["total_estimated_cpu_pct"] == 0.0
    assert resp.json()["over_budget"] is False


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


# ─── Fase 36 (SCALE-05): CRUD en caliente ──────────────────────────────────
def _fake_repo(get_return=None, create_return=None, update_return=None, delete_return=True, list_return=None) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=get_return)
    repo.create = AsyncMock(return_value=create_return)
    repo.update = AsyncMock(return_value=update_return)
    repo.delete = AsyncMock(return_value=delete_return)
    repo.list = AsyncMock(return_value=list_return if list_return is not None else [])
    return repo


_CAM2 = {"id": "cam2", "name": "Entrada trasera", "rtsp_url": "rtsp://user:pass@10.0.0.5/stream",
          "enabled": True, "process_w": None, "process_h": None,
          "created_at": None, "last_seen_at": None}


async def TEST_create_camera_persists_and_starts_pipeline_when_enabled():
    repo = _fake_repo(get_return=None, create_return=_CAM2)
    manager = _mock_manager()
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo), \
         patch.object(cameras_module, "start_camera_pipeline", new=AsyncMock()) as start_mock:
        async with await _client() as client:
            resp = await client.post("/api/v2/cameras", json={
                "id": "cam2", "name": "Entrada trasera",
                "rtsp_url": "rtsp://user:pass@10.0.0.5/stream", "enabled": True,
            })

    assert resp.status_code == 200
    repo.create.assert_awaited_once_with(
        "cam2", "Entrada trasera", "rtsp://user:pass@10.0.0.5/stream",
        enabled=True, process_w=None, process_h=None,
    )
    start_mock.assert_awaited_once()
    body = resp.json()["camera"]
    assert body["id"] == "cam2"
    assert body["rtsp_url"] == "rtsp://***:***@10.0.0.5/stream"  # SEC-* enmascarado


async def TEST_create_camera_conflict_when_id_already_exists():
    repo = _fake_repo(get_return=_CAM2)
    cameras_module.configure(_mock_manager(), services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo), \
         patch.object(cameras_module, "start_camera_pipeline", new=AsyncMock()) as start_mock:
        async with await _client() as client:
            resp = await client.post("/api/v2/cameras", json={
                "id": "cam2", "name": "X", "rtsp_url": "rtsp://host/s",
            })

    assert resp.status_code == 409
    repo.create.assert_not_awaited()
    start_mock.assert_not_awaited()


async def TEST_create_camera_disabled_does_not_start_pipeline():
    disabled = {**_CAM2, "enabled": False}
    repo = _fake_repo(get_return=None, create_return=disabled)
    cameras_module.configure(_mock_manager(), services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo), \
         patch.object(cameras_module, "start_camera_pipeline", new=AsyncMock()) as start_mock:
        async with await _client() as client:
            resp = await client.post("/api/v2/cameras", json={
                "id": "cam2", "name": "X", "rtsp_url": "rtsp://host/s", "enabled": False,
            })

    assert resp.status_code == 200
    start_mock.assert_not_awaited()


async def TEST_create_camera_rejects_non_rtsp_url():
    async with await _client() as client:
        resp = await client.post("/api/v2/cameras", json={
            "id": "cam2", "name": "X", "rtsp_url": "http://host/s",
        })
    assert resp.status_code == 422


async def TEST_create_camera_503_when_pipeline_v2_not_active():
    repo = _fake_repo(get_return=None, create_return=_CAM2)
    cameras_module.configure(None, services=None)

    with patch.object(cameras_module, "_camera_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/cameras", json={
                "id": "cam2", "name": "X", "rtsp_url": "rtsp://host/s",
            })
    assert resp.status_code == 503


async def TEST_update_camera_404_when_unknown():
    repo = _fake_repo(get_return=None)
    cameras_module.configure(_mock_manager(), services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/cameras/does-not-exist", json={"name": "X"})
    assert resp.status_code == 404


async def TEST_update_camera_rename_only_does_not_restart_pipeline():
    repo = _fake_repo(get_return=_CAM2, update_return={**_CAM2, "name": "Renombrada"})
    manager = _mock_manager()
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo), \
         patch.object(cameras_module, "start_camera_pipeline", new=AsyncMock()) as start_mock:
        async with await _client() as client:
            resp = await client.put("/api/v2/cameras/cam2", json={"name": "Renombrada"})

    assert resp.status_code == 200
    manager.remove.assert_not_called()
    start_mock.assert_not_awaited()
    assert resp.json()["camera"]["name"] == "Renombrada"


async def TEST_update_camera_rtsp_url_change_restarts_pipeline():
    new_url = "rtsp://user:pass@10.0.0.9/stream"
    repo = _fake_repo(get_return=_CAM2, update_return={**_CAM2, "rtsp_url": new_url})
    manager = _mock_manager()
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo), \
         patch.object(cameras_module, "start_camera_pipeline", new=AsyncMock()) as start_mock:
        async with await _client() as client:
            resp = await client.put("/api/v2/cameras/cam2", json={"rtsp_url": new_url})

    assert resp.status_code == 200
    manager.remove.assert_called_once_with("cam2")
    start_mock.assert_awaited_once()


async def TEST_update_camera_disable_stops_pipeline_without_restarting():
    repo = _fake_repo(get_return=_CAM2, update_return={**_CAM2, "enabled": False})
    manager = _mock_manager()
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo), \
         patch.object(cameras_module, "start_camera_pipeline", new=AsyncMock()) as start_mock:
        async with await _client() as client:
            resp = await client.put("/api/v2/cameras/cam2", json={"enabled": False})

    assert resp.status_code == 200
    manager.remove.assert_called_once_with("cam2")
    start_mock.assert_not_awaited()


async def TEST_delete_camera_stops_pipeline_and_removes_catalog_row():
    repo = _fake_repo(get_return=_CAM2, delete_return=True)
    manager = _mock_manager()
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/cameras/cam2")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": "cam2"}
    manager.remove.assert_called_once_with("cam2")
    repo.delete.assert_awaited_once_with("cam2")


async def TEST_delete_camera_404_when_unknown():
    repo = _fake_repo(get_return=None)
    cameras_module.configure(_mock_manager(), services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.delete("/api/v2/cameras/does-not-exist")
    assert resp.status_code == 404


async def TEST_delete_one_camera_does_not_touch_others():
    """SCALE-05: borrar una camara no debe tocar el CameraManager de las demas."""
    repo = _fake_repo(get_return=_CAM2)
    cam1 = _fake_pipeline("cam1")
    manager = _mock_manager(cam1)
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo):
        async with await _client() as client:
            await client.delete("/api/v2/cameras/cam2")

    manager.remove.assert_called_once_with("cam2")
    assert manager.all() == [cam1]


async def TEST_catalog_masks_rtsp_url_and_reports_running_state():
    running = {**_CAM2, "id": "cam1"}
    stopped = {**_CAM2, "id": "cam2"}
    repo = _fake_repo(list_return=[running, stopped])
    manager = _mock_manager(_fake_pipeline("cam1"))
    cameras_module.configure(manager, services=object())

    with patch.object(cameras_module, "_camera_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/cameras/catalog")

    assert resp.status_code == 200
    by_id = {c["id"]: c for c in resp.json()["cameras"]}
    assert by_id["cam1"]["running"] is True
    assert by_id["cam2"]["running"] is False
    assert by_id["cam1"]["rtsp_url"] == "rtsp://***:***@10.0.0.5/stream"
