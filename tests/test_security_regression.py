"""Regression tests for propuesta_mejora/vulnerabilidades.md (Fase 22, SEC-15/SEC-16).

One test per documented vulnerability (numbered 1-14 in the source doc), plus
the yolo_model_path validation and /api/v2 hardening this phase adds. This
file is the guarantee that none of the 14 findings reappears — most were
already fixed before this phase (see 22-CONTEXT.md); this locks them in.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport
from pydantic import ValidationError

import backend.main as main_module
from backend.api.v2.deps import V2_RATE_LIMIT, limiter as v2_limiter
from backend.config import Settings, build_rtsp_url, mask_rtsp_url

BACKEND_DIR = Path("backend")


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test")


def _mock_recognizer_stream() -> MagicMock:
    """rtsp_stream stub that clears the two early-exit 503 guards in enroll_face."""
    mock_stream = MagicMock()
    mock_stream.recognizer = MagicMock()
    mock_stream.recognizer.available = True
    return mock_stream


# ─── Vuln 1 — pickle en base de datos de personas ────────────────────────────
def TEST_vuln_01_no_pickle_in_backend():
    offenders = []
    for path in sorted(BACKEND_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "pickle" in line:
                offenders.append(f"{path}:{lineno}")
    assert not offenders, offenders


# ─── Vuln 2 — sin validación de tipo/tamaño en upload de imagen ──────────────
async def TEST_vuln_02_enroll_face_rejects_bad_content_type():
    with patch.object(main_module, "rtsp_stream", _mock_recognizer_stream()):
        async with await _client() as client:
            resp = await client.post(
                "/api/enroll_face",
                data={"name": "Eve"},
                files={"image": ("evil.txt", b"not an image", "text/plain")},
            )
    assert resp.status_code == 415


async def TEST_vuln_02_enroll_face_rejects_oversized_image():
    oversized = b"\xff" * (10 * 1024 * 1024 + 1)
    with patch.object(main_module, "rtsp_stream", _mock_recognizer_stream()):
        async with await _client() as client:
            resp = await client.post(
                "/api/enroll_face",
                data={"name": "Eve"},
                files={"image": ("big.jpg", oversized, "image/jpeg")},
            )
    assert resp.status_code == 413


# ─── Vuln 3 — sin CORS configurado ────────────────────────────────────────────
def TEST_vuln_03_cors_wired_conditionally_on_settings():
    """CORSMiddleware is added at import time, gated on _settings.cors_origins —
    a structural guard against the wiring being deleted (behavioral testing would
    require re-importing backend.main with a different Settings singleton)."""
    src = Path("backend/main.py").read_text(encoding="utf-8")
    assert "CORSMiddleware" in src
    assert "if _settings.cors_origins:" in src


# ─── Vuln 4 — credenciales de cámara en texto plano en CAMERA_URL ────────────
def TEST_vuln_04_rtsp_credentials_built_dynamically_not_embedded():
    s = Settings(camera_url="rtsp://192.168.1.132:554/stream1", rtsp_user="admin", rtsp_pass="secret")
    url = build_rtsp_url(s)
    assert "admin:secret@" in url
    assert "@" not in s.camera_url  # camera_url itself never carries credentials


# ─── Vuln 5 — WS tokens sin TTL ───────────────────────────────────────────────
def TEST_vuln_05_ws_token_expires_after_ttl():
    from backend import auth
    with patch.object(auth, "get_settings", return_value=Settings(dashboard_user="u", dashboard_pass="p")):
        token = auth.issue_ws_token()
        auth._ws_tokens[token] = time.monotonic() - (auth._WS_TOKEN_TTL + 1)
        assert auth.verify_ws_token(token) is False


# ─── Vuln 6 — YOLO_MODEL_PATH sin validación ──────────────────────────────────
def TEST_vuln_06_yolo_model_path_validated():
    with pytest.raises(ValidationError):
        Settings(yolo_model_path="../../../../tmp/evil.pt")


def TEST_model_path_rejects_traversal():
    with pytest.raises(ValidationError):
        Settings(yolo_model_path="../../../../tmp/evil.pt")


def TEST_model_path_rejects_bad_extension():
    with pytest.raises(ValidationError):
        Settings(yolo_model_path="model.exe")


def TEST_model_path_accepts_valid():
    assert Settings(yolo_model_path="yolo26n.pt").yolo_model_path == "yolo26n.pt"
    assert Settings(yolo_model_path="models/arcface.onnx").yolo_model_path == "models/arcface.onnx"


# ─── Vuln 7 — sin rate limiting en ningún endpoint ────────────────────────────
def TEST_vuln_07_sensitive_endpoints_rate_limited():
    from backend.main import _limiter
    for name in ("backend.main.ws_token", "backend.main.enroll_face"):
        assert name in _limiter._route_limits, f"{name} has no rate limit"


def TEST_all_v2_endpoints_rate_limited():
    offenders = []
    for route in main_module.app.routes:
        path = getattr(route, "path", None)
        if path is None or not (path.startswith("/api/v2") or path == "/metrics"):
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            continue  # websocket route — not HTTP, slowapi doesn't apply
        endpoint = route.endpoint
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        if name not in v2_limiter._route_limits:
            offenders.append(f"{path} ({name})")
    assert not offenders, "v2 endpoints missing rate limiting:\n" + "\n".join(offenders)


def TEST_v2_rate_limit_value_is_shared_constant():
    assert V2_RATE_LIMIT and "/" in V2_RATE_LIMIT


# ─── Vuln 8 — certificado autofirmado sin SAN para la IP local ──────────────
def TEST_vuln_08_ssl_cert_san_includes_lan_ip_when_detectable():
    from backend.ssl_utils import _build_san_entries, _detect_lan_ip
    entries = _build_san_entries()
    lan_ip = _detect_lan_ip()
    entry_reprs = [str(e) for e in entries]
    assert any("127.0.0.1" in r or "localhost" in r for r in entry_reprs)
    if lan_ip and lan_ip != "127.0.0.1":
        assert any(lan_ip in r for r in entry_reprs)


# ─── Vuln 9 — sin headers de seguridad HTTP ───────────────────────────────────
async def TEST_vuln_09_security_headers_present():
    async with await _client() as client:
        resp = await client.get("/")  # no DB/pipeline dependency
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers
    assert "Strict-Transport-Security" in resp.headers


# ─── Vuln 10 — limit en /api/events sin cota máxima ──────────────────────────
async def TEST_vuln_10_events_limit_has_upper_bound():
    async with await _client() as client:
        resp = await client.get("/api/events", params={"limit": 9_999_999})
    assert resp.status_code == 422


async def TEST_all_v2_list_endpoints_have_limit_cap():
    async with await _client() as client:
        resp = await client.get("/api/v2/events", params={"limit": 9_999_999})
        assert resp.status_code == 422
        resp = await client.get("/api/v2/recordings", params={"limit": 9_999_999})
        assert resp.status_code == 422


# ─── Vuln 11 — sin validación de longitud en name de enrolamiento ───────────
async def TEST_vuln_11_enroll_name_has_max_length():
    async with await _client() as client:
        resp = await client.post(
            "/api/enroll_face", data={"name": "a" * 10_000, "use_current_frame": "true"}
        )
    assert resp.status_code == 422


# ─── Vuln 12 — logs con URL RTSP incluyendo credenciales ─────────────────────
def TEST_vuln_12_rtsp_url_masked_before_logging():
    masked = mask_rtsp_url("rtsp://admin:secret@192.168.1.132:554/stream1")
    assert "secret" not in masked
    assert "admin" not in masked
    assert "***:***@" in masked


# ─── Vuln 13 — clave privada SSL sin restricción de permisos ────────────────
def TEST_vuln_13_ssl_key_permission_restriction_is_attempted(tmp_path):
    from backend import ssl_utils
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(b"fake-key")
    # Must not raise regardless of platform — best-effort hardening, never fatal.
    ssl_utils._restrict_key_permissions(key_path)


# ─── Vuln 14 — sin Subresource Integrity en CDN de Chart.js ──────────────────
def TEST_vuln_14_chartjs_cdn_has_subresource_integrity():
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    for line in html.splitlines():
        if "chart.js" in line.lower() and "cdn" in line.lower():
            assert "integrity=" in line, "Chart.js CDN <script> missing Subresource Integrity"
            return
    pytest.fail("No Chart.js CDN <script> tag found in frontend/index.html")
