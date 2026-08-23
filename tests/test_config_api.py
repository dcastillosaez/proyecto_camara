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
    assert zonas_definidas["external_source"] == "/api/zones"
    assert zonas_definidas["fields"] == []

    reglas = next(s for s in body["sections"] if s["key"] == "reglas")
    reglas_cargadas = next(g for g in reglas["groups"] if g["key"] == "reglas_cargadas")
    assert reglas_cargadas["external_source"] == "/api/v2/rules"
    assert reglas_cargadas["fields"] == []
