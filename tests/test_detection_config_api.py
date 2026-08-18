"""Tests for /api/v2/detection/classes (Fase 27, BEH-06).

Cubren el criterio 1 del ROADMAP por el lado del backend: los cuatro rechazos con 400,
el camino feliz completo (persistencia + propagacion + CONFIG_CHANGED) y la precedencia
de app_config sobre la env var YOLO_CLASSES al arrancar. La parte visual (checkbox de
"person" marcado y deshabilitado en el panel) la cierra el checkpoint manual de 27-11.

Cableado: en vez de parchear el global de main.py (patron de la Fase 22), se llama
directamente a detection_module.configure(mock_manager, mock_engine) en cada test —
ventaja de haber copiado el molde de metrics.py en vez del global de main.py. `ConfigRepo`
se sustituye parcheando `detection_module._config_repo` con un doble de prueba, para no
tocar la base de datos real del proyecto.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport

import backend.main as main_module
from backend.api.v2 import detection as detection_module


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test")


def _fake_repo(get_return=None) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=get_return)
    repo.set = AsyncMock(return_value=None)
    return repo


@pytest.fixture(autouse=True)
def _reset_detection_wiring():
    yield
    detection_module.configure(None, None)


# ─── GET ───────────────────────────────────────────────────────────────────
async def TEST_get_classes_returns_active_and_catalog():
    repo = _fake_repo(get_return=[0, 24])
    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/detection/classes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == [0, 24]
    assert len(body["available"]) == 6
    assert body["locked"] == [0]
    catalog = {c["id"]: c for c in body["available"]}
    assert catalog[0]["name"] == "person"
    assert catalog[0]["locked"] is True
    assert catalog[24]["locked"] is False


# ─── PUT — rechazos con 400 ─────────────────────────────────────────────────
async def TEST_rejects_empty_class_list():
    repo = _fake_repo()
    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/detection/classes", json={"classes": []})
    assert resp.status_code == 400
    assert "ciego" in resp.json()["detail"]
    repo.set.assert_not_awaited()


async def TEST_rejects_missing_person_class():
    repo = _fake_repo()
    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/detection/classes", json={"classes": [24]})
    assert resp.status_code == 400
    assert "person" in resp.json()["detail"]
    repo.set.assert_not_awaited()


async def TEST_rejects_out_of_range_class():
    repo = _fake_repo()
    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/detection/classes", json={"classes": [0, 999]})
    assert resp.status_code == 400
    assert resp.json()["detail"]
    repo.set.assert_not_awaited()


async def TEST_rejects_duplicate_classes():
    repo = _fake_repo()
    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/detection/classes", json={"classes": [0, 24, 24]})
    assert resp.status_code == 400
    assert resp.json()["detail"]
    repo.set.assert_not_awaited()


# ─── PUT — camino feliz ─────────────────────────────────────────────────────
async def TEST_put_persists_propagates_and_emits():
    repo = _fake_repo()
    pipeline = MagicMock()
    mock_manager = MagicMock()
    mock_manager.all.return_value = [pipeline]
    mock_engine = MagicMock()
    detection_module.configure(mock_manager, mock_engine)

    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/detection/classes", json={"classes": [0, 24]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == [0, 24]

    repo.set.assert_awaited_once_with("yolo_classes", [0, 24])
    pipeline.set_detection_classes.assert_called_once_with([0, 24])
    mock_engine.config_changed.assert_called_once()
    _, kwargs = mock_engine.config_changed.call_args
    assert kwargs.get("classes") == [0, 24]


async def TEST_put_persists_before_propagating():
    """El orden importa: si el proceso muriera en medio, el arranque siguiente aplicaria
    lo que el operador pidio (persistir primero) en vez de perderlo (propagar primero)."""
    repo = _fake_repo()
    pipeline = MagicMock()
    mock_manager = MagicMock()
    mock_manager.all.return_value = [pipeline]

    parent = MagicMock()
    parent.attach_mock(repo.set, "config_set")
    parent.attach_mock(pipeline.set_detection_classes, "pipeline_set")

    detection_module.configure(mock_manager, None)
    with patch.object(detection_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put("/api/v2/detection/classes", json={"classes": [0, 24]})

    assert resp.status_code == 200
    call_names = [c[0] for c in parent.mock_calls]
    assert call_names.index("config_set") < call_names.index("pipeline_set")


# ─── Precedencia en el arranque (main.py) ───────────────────────────────────
def TEST_empty_persisted_row_is_treated_as_absent():
    """Una fila [] guardada por error en app_config no debe dejar el detector ciego."""
    assert main_module._resolve_active_classes([], [0]) == [0]
    assert main_module._resolve_active_classes(None, [0]) == [0]
    assert main_module._resolve_active_classes([0, 24], [0]) == [0, 24]
