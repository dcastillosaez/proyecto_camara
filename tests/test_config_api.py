"""Tests for GET/PUT /api/v2/config y POST /{section}/restore (Fase 32, 32-02).

Router probado con una app FastAPI local (no `backend.main.app`): las Tasks 1-2 no
dependen del cableado en el lifespan de main.py (eso llega en la Task 3, que anade su
propia comprobacion sobre `backend.main`). `app.state.limiter`/el exception handler de
slowapi se replican aqui porque el decorador `@limiter.limit()` necesita un
`request.app.state.limiter` real para aplicar la politica (mismo Limiter compartido de
`backend/api/v2/deps.py` que usa el resto de routers v2).

`ConfigRepo` se sustituye parcheando `config_module._config_repo` con un doble de
prueba, igual que `tests/test_detection_config_api.py` — no se toca la base de datos
real del proyecto.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.v2 import config as config_module
from backend.api.v2.deps import limiter
from backend.config import Settings, get_settings, mask_rtsp_url


def _local_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(config_module.router)
    return app


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=_local_app()), base_url="http://test")


def _fake_repo(get_all_return: dict | None = None) -> MagicMock:
    repo = MagicMock()
    repo.get_all = AsyncMock(return_value=get_all_return or {})
    repo.set = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture(autouse=True)
def _reset_config_wiring():
    yield
    config_module.configure(None, None)


# ─── GET /api/v2/config ──────────────────────────────────────────────────────
async def TEST_get_config_returns_all_sections_with_default_origin():
    repo = _fake_repo(get_all_return={})
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/config")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sections"]) == 8
    keys = {s["key"] for s in body["sections"]}
    assert keys == {
        "camara", "deteccion", "tracking", "reconocimiento",
        "zonas", "reglas", "alertas", "almacenamiento",
    }
    camara = next(s for s in body["sections"] if s["key"] == "camara")
    captura = next(g for g in camara["groups"] if g["key"] == "captura")
    conf_field = next(f for f in captura["fields"] if f["key"] == "camera_driver")
    assert conf_field["origin"] == "default"
    assert conf_field["value"] == "tapo"


async def TEST_get_config_runtime_override_wins():
    repo = _fake_repo(get_all_return={"yolo_confidence": 0.6})
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/config")
    body = resp.json()
    deteccion = next(s for s in body["sections"] if s["key"] == "deteccion")
    personas = next(g for g in deteccion["groups"] if g["key"] == "personas")
    field = next(f for f in personas["fields"] if f["key"] == "yolo_confidence")
    assert field["origin"] == "runtime"
    assert field["value"] == 0.6


async def TEST_get_config_secret_field_never_leaks_value():
    repo = _fake_repo(get_all_return={})
    empty_secret_settings = get_settings().model_copy(update={"rtsp_pass": ""})
    with patch.object(config_module, "_config_repo", return_value=repo), \
         patch.object(config_module, "get_settings", return_value=empty_secret_settings):
        async with await _client() as client:
            resp = await client.get("/api/v2/config")
    body = resp.json()
    camara = next(s for s in body["sections"] if s["key"] == "camara")
    captura = next(g for g in camara["groups"] if g["key"] == "captura")
    rtsp_pass = next(f for f in captura["fields"] if f["key"] == "rtsp_pass")
    assert "value" not in rtsp_pass
    assert rtsp_pass["secret"] is True
    assert rtsp_pass["configured"] is False


async def TEST_get_config_camera_url_always_masked():
    repo = _fake_repo(get_all_return={"camera_url": "rtsp://admin:secret@192.168.1.132:554/x"})
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/config")
    body = resp.json()
    camara = next(s for s in body["sections"] if s["key"] == "camara")
    captura = next(g for g in camara["groups"] if g["key"] == "captura")
    camera_url = next(f for f in captura["fields"] if f["key"] == "camera_url")
    assert "secret" not in camera_url or camera_url["secret"] is False
    assert camera_url["value"] == mask_rtsp_url("rtsp://admin:secret@192.168.1.132:554/x")
    assert "admin" not in camera_url["value"]
    assert "secret" not in camera_url["value"].split("@")[0]


async def TEST_get_config_external_source_groups_have_no_fields():
    repo = _fake_repo(get_all_return={})
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.get("/api/v2/config")
    body = resp.json()
    zonas = next(s for s in body["sections"] if s["key"] == "zonas")
    zonas_definidas = next(g for g in zonas["groups"] if g["key"] == "zonas_definidas")
    assert zonas_definidas["external_source"] == "/api/v2/zones"
    assert zonas_definidas["fields"] == []

    lineas_definidas = next(g for g in zonas["groups"] if g["key"] == "lineas_definidas")
    assert lineas_definidas["external_source"] == "/api/v2/lines"
    assert lineas_definidas["fields"] == []

    reglas = next(s for s in body["sections"] if s["key"] == "reglas")
    reglas_cargadas = next(g for g in reglas["groups"] if g["key"] == "reglas_cargadas")
    assert reglas_cargadas["external_source"] == "/api/v2/rules"
    assert reglas_cargadas["fields"] == []


# ─── PUT /api/v2/config — rechazos 422 ───────────────────────────────────────
async def TEST_put_config_unknown_section_returns_404():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config", json={"section": "no-existe", "changes": {}})
    assert resp.status_code == 404


async def TEST_put_config_unknown_field_returns_422():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "deteccion", "changes": {"campo_inventado": 1}})
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors == [{"field": "campo_inventado", "message": "Campo desconocido."}]
    repo.set.assert_not_awaited()


async def TEST_put_config_secret_field_rejected():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config", json={"section": "camara", "changes": {"rtsp_pass": "x"}})
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors == [{
        "field": "rtsp_pass",
        "message": "Este campo no es editable desde la interfaz.",
    }]
    repo.set.assert_not_awaited()


async def TEST_put_config_readonly_field_rejected():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "camara", "changes": {"camera_url": "rtsp://x"}})
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors == [{
        "field": "camera_url",
        "message": "Este campo no es editable desde la interfaz.",
    }]
    repo.set.assert_not_awaited()


async def TEST_put_config_out_of_range_returns_exact_range_message():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "deteccion", "changes": {"yolo_confidence": 1.5}})
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors == [{
        "field": "yolo_confidence",
        "message": "Debe estar entre 0.05 y 0.95.",
    }]
    repo.set.assert_not_awaited()


async def TEST_put_config_cross_field_validation_uses_literal_settings_message():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={
                    "section": "reconocimiento",
                    "changes": {"identity_min_votes": 10, "identity_vote_window": 2},
                })
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert len(errors) == 1
    assert "identity_vote_window (2) no puede ser menor" in errors[0]["message"]
    assert "identity_min_votes (10)" in errors[0]["message"]
    repo.set.assert_not_awaited()


async def TEST_put_config_batch_returns_all_errors_not_just_first():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={
                    "section": "deteccion",
                    "changes": {
                        "yolo_confidence": 1.5,
                        "identity_min_votes": 10,
                        "identity_vote_window": 2,
                    },
                })
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert len(errors) == 2
    fields = {e["field"] for e in errors}
    assert "yolo_confidence" in fields
    repo.set.assert_not_awaited()


async def TEST_put_config_yolo_classes_missing_person_rejected():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "deteccion", "changes": {"yolo_classes": [24]}})
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors[0]["field"] == "yolo_classes"
    assert "person" in errors[0]["message"]
    repo.set.assert_not_awaited()


# ─── PUT /api/v2/config — camino feliz ───────────────────────────────────────
async def TEST_put_config_yolo_classes_persists_before_propagating_to_all_pipelines():
    repo = _fake_repo()
    pipeline1, pipeline2 = MagicMock(), MagicMock()
    mock_manager = MagicMock()
    mock_manager.all.return_value = [pipeline1, pipeline2]
    mock_engine = MagicMock()
    config_module.configure(mock_manager, mock_engine)

    parent = MagicMock()
    parent.attach_mock(repo.set, "config_set")
    parent.attach_mock(pipeline1.set_detection_classes, "pipeline1_set")

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "deteccion", "changes": {"yolo_classes": [0, 24]}})

    assert resp.status_code == 200
    body = resp.json()
    assert body["section"] == "deteccion"

    repo.set.assert_awaited_once_with("yolo_classes", [0, 24])
    pipeline1.set_detection_classes.assert_called_once_with([0, 24])
    pipeline2.set_detection_classes.assert_called_once_with([0, 24])

    call_names = [c[0] for c in parent.mock_calls]
    assert call_names.index("config_set") < call_names.index("pipeline1_set")

    mock_engine.config_changed.assert_called_once()
    _, kwargs = mock_engine.config_changed.call_args
    assert kwargs["section"] == "deteccion"
    assert kwargs["diff"] == {"yolo_classes": {"before": [0], "after": [0, 24]}}


async def TEST_put_config_process_width_alone_keeps_current_height():
    repo = _fake_repo(get_all_return={"process_height": 900})
    pipeline = MagicMock()
    mock_manager = MagicMock()
    mock_manager.all.return_value = [pipeline]
    config_module.configure(mock_manager, None)

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "camara", "changes": {"process_width": 1600}})

    assert resp.status_code == 200
    pipeline.set_process_size.assert_called_once_with(1600, 900)


async def TEST_put_config_restart_only_field_persists_without_pipeline_call():
    repo = _fake_repo()
    pipeline = MagicMock()
    mock_manager = MagicMock()
    mock_manager.all.return_value = [pipeline]
    config_module.configure(mock_manager, None)

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "deteccion", "changes": {"yolo_confidence": 0.5}})

    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_restart"] == ["yolo_confidence"]
    repo.set.assert_awaited_once_with("yolo_confidence", 0.5)
    pipeline.set_detection_classes.assert_not_called()
    pipeline.set_process_size.assert_not_called()


async def TEST_put_config_emits_exactly_one_config_changed_per_section():
    repo = _fake_repo()
    mock_engine = MagicMock()
    config_module.configure(None, mock_engine)

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={
                    "section": "deteccion",
                    "changes": {"yolo_confidence": 0.5, "yolo_imgsz": 512},
                })

    assert resp.status_code == 200
    mock_engine.config_changed.assert_called_once()
    _, kwargs = mock_engine.config_changed.call_args
    assert set(kwargs["diff"].keys()) == {"yolo_confidence", "yolo_imgsz"}


async def TEST_put_config_secret_never_reaches_diff():
    """Defensa en profundidad (T-32-06): ya es imposible por el 422 de arriba, pero se
    verifica explicitamente que ningun campo secret llega nunca al diff de auditoria."""
    repo = _fake_repo()
    mock_engine = MagicMock()
    config_module.configure(None, mock_engine)

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.put(
                "/api/v2/config",
                json={"section": "deteccion", "changes": {"yolo_confidence": 0.5}})

    assert resp.status_code == 200
    _, kwargs = mock_engine.config_changed.call_args
    assert not any(field_by_key_module_secret(k) for k in kwargs["diff"])


def field_by_key_module_secret(key: str) -> bool:
    from backend.api.v2.config_schema import field_by_key
    f = field_by_key(key)
    return bool(f and f.secret)


# ─── POST /api/v2/config/{section}/restore ───────────────────────────────────
async def TEST_restore_unknown_section_returns_404():
    repo = _fake_repo()
    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/config/no-existe/restore")
    assert resp.status_code == 404
    repo.delete.assert_not_awaited()


async def TEST_restore_deletes_only_runtime_rows_of_that_section():
    repo = _fake_repo(get_all_return={
        "yolo_confidence": 0.6, "yolo_imgsz": 512, "yolo_model_path": "custom.pt",
        "process_width": 1600,  # pertenece a "camara", no a "deteccion"
    })
    mock_engine = MagicMock()
    config_module.configure(None, mock_engine)

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/config/deteccion/restore")

    assert resp.status_code == 200
    body = resp.json()
    assert body["section"] == "deteccion"
    assert body["restored_count"] == 3
    deleted_keys = {c.args[0] for c in repo.delete.await_args_list}
    assert deleted_keys == {"yolo_confidence", "yolo_imgsz", "yolo_model_path"}

    mock_engine.config_changed.assert_called_once()
    _, kwargs = mock_engine.config_changed.call_args
    assert kwargs["section"] == "deteccion"
    assert kwargs["restored"] is True
    assert set(kwargs["diff"].keys()) == {"yolo_confidence", "yolo_imgsz", "yolo_model_path"}


async def TEST_restore_with_no_runtime_fields_is_a_noop():
    repo = _fake_repo(get_all_return={})
    mock_engine = MagicMock()
    config_module.configure(None, mock_engine)

    with patch.object(config_module, "_config_repo", return_value=repo):
        async with await _client() as client:
            resp = await client.post("/api/v2/config/deteccion/restore")

    assert resp.status_code == 200
    body = resp.json()
    assert body["restored_count"] == 0
    repo.delete.assert_not_awaited()
    mock_engine.config_changed.assert_not_called()


# ─── Wiring en main.py ───────────────────────────────────────────────────────
def TEST_main_imports_with_config_router_registered():
    import backend.main as main_module
    paths = {getattr(r, "path", None) for r in main_module.app.routes}
    assert "/api/v2/config" in paths
    assert "/api/v2/config/{section_key}/restore" in paths
