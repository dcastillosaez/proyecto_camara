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
    from tests.route_utils import iter_app_routes
    offenders = []
    for route in iter_app_routes(main_module.app):
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
    """GET /api/events se retiro (DEBT-02); su sucesor /api/v2/events mantiene la cota."""
    async with await _client() as client:
        resp = await client.get("/api/v2/events", params={"limit": 9_999_999})
    assert resp.status_code == 422


async def TEST_debt02_retired_v1_routes_are_gone():
    async with await _client() as client:
        for method, path in [("GET", "/api/events"), ("GET", "/api/zones/stats"),
                             ("GET", "/api/heatmap"), ("GET", "/api/alerts/config"),
                             ("POST", "/api/alerts/test"), ("GET", "/api/alerts/status")]:
            resp = await client.request(method, path)
            assert resp.status_code in (404, 405), f"{method} {path} sigue respondiendo"


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


# ─── Vuln 14 — Chart.js sin Subresource Integrity (DEBT-01: ya no hay CDN) ──
# El riesgo era un CDN comprometido. Desde DEBT-01 Chart.js, Tailwind y las fuentes
# se sirven desde frontend/vendor/: index.html no puede cargar nada de otro host.
def TEST_vuln_14_frontend_loads_no_external_resources():
    import re

    html = Path("frontend/index.html").read_text(encoding="utf-8")
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    assert external == [], f"recursos externos en index.html: {external}"
    assert '/static/vendor/chart.umd.min.js' in html
    assert Path("frontend/vendor/chart.umd.min.js").exists()


def TEST_vendored_chartjs_matches_the_previous_sri_hash():
    """El fichero copiado es identico al que el CDN servia con SRI (Chart.js 4.5.1)."""
    import base64
    import hashlib

    digest = hashlib.sha384(Path("frontend/vendor/chart.umd.min.js").read_bytes()).digest()
    assert base64.b64encode(digest).decode() == (
        "jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
    )


def TEST_vendored_fonts_css_points_to_local_files():
    css = Path("frontend/vendor/fonts.css").read_text(encoding="utf-8")
    assert "gstatic" not in css and "googleapis" not in css
    import re

    for url in re.findall(r"url\((/static/vendor/fonts/[^)]+)\)", css):
        assert Path("frontend" + url[len("/static"):]).exists(), url


async def TEST_sec09_csp_has_no_external_hosts():
    async with await _client() as client:
        resp = await client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    assert "http" not in csp, csp


# ═══ Plan de mejoras tras la v2.0 — Fase 2 ════════════════════════════════════
def _auth_settings(**kw) -> Settings:
    return Settings(dashboard_user="u", dashboard_pass="p", **kw)


# ─── SEC-01 — los mounts estáticos y /docs exigen autenticación ──────────────
@pytest.mark.parametrize("path", [
    "/clips/x.mp4", "/gallery/1/x.jpg", "/snapshots/20260101/x.jpg",
    "/docs", "/redoc", "/openapi.json",
])
async def TEST_sec01_static_mounts_and_docs_require_auth(path):
    from backend import auth
    with patch.object(auth, "get_settings", return_value=_auth_settings()):
        async with await _client() as client:
            resp = await client.get(path)
    assert resp.status_code == 401, f"{path} respondio {resp.status_code} sin credenciales"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


async def TEST_sec01_static_mount_accepts_valid_credentials(tmp_path):
    from backend import auth
    with patch.object(auth, "get_settings", return_value=_auth_settings()):
        async with await _client() as client:
            resp = await client.get("/clips/no-existe.mp4", auth=("u", "p"))
    assert resp.status_code == 404   # pasa la auth; el fichero simplemente no existe


async def TEST_sec01_static_mounts_open_without_auth_configured():
    from backend import auth
    with patch.object(auth, "get_settings", return_value=Settings(dashboard_user="")):
        async with await _client() as client:
            resp = await client.get("/clips/no-existe.mp4")
    assert resp.status_code == 404


# ─── SEC-02 — máscara y codificación de credenciales ─────────────────────────
@pytest.mark.parametrize("url", [
    "rtsp://admin:pa/ss@192.168.1.2:554/stream1",
    "rtsp://admin:pa?ss@192.168.1.2/stream1",
    "rtsp://admin:pa#ss@192.168.1.2/stream1",
    "rtsp://admin:p@ss@192.168.1.2/stream1",
])
def TEST_sec02_mask_hides_password_with_url_delimiters(url):
    masked = mask_rtsp_url(url)
    assert "pa" not in masked.split("@")[0] and "ss@" not in masked
    assert "admin" not in masked
    assert masked.startswith("rtsp://***:***@192.168.1.2")


def TEST_sec02_mask_leaves_url_without_credentials():
    assert mask_rtsp_url("rtsp://192.168.1.2:554/stream2") == "rtsp://192.168.1.2:554/stream2"


def TEST_sec02_build_rtsp_url_encodes_delimiters():
    from urllib.parse import unquote, urlparse
    s = Settings(camera_url="rtsp://192.168.1.2:554/stream2", rtsp_user="admin", rtsp_pass="a/b?c#d@e")
    url = build_rtsp_url(s)
    p = urlparse(url)
    assert p.hostname == "192.168.1.2" and p.port == 554 and p.path == "/stream2"
    assert unquote(p.password) == "a/b?c#d@e"
    assert "a/b?c#d@e" not in mask_rtsp_url(url)


def TEST_sec02_simple_credentials_unchanged():
    s = Settings(camera_url="rtsp://192.168.1.2:554/stream2", rtsp_user="admin", rtsp_pass="Secr3t!")
    assert build_rtsp_url(s) == "rtsp://admin:Secr3t!@192.168.1.2:554/stream2"


async def TEST_sec02_telegram_failure_log_does_not_contain_token(caplog):
    import logging

    from backend.notifier import Notifier
    token = "123456:SECRET-TOKEN"
    n = Notifier(telegram_token=token, telegram_chat_id="1")
    err = httpx.ConnectError(f"fallo en https://api.telegram.org/bot{token}/sendMessage")
    with patch("backend.notifier.httpx.AsyncClient.post", side_effect=err), \
         caplog.at_level(logging.DEBUG):
        assert await n.send_telegram("hola") is False
    assert token not in caplog.text
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


# ─── SEC-03 — el nombre de persona no se interpola en innerHTML ─────────────
def TEST_sec03_person_gallery_does_not_interpolate_name_into_html():
    src = Path("frontend/js/components/personGallery.js").read_text(encoding="utf-8")
    start = src.index("row.innerHTML = `")
    end = src.index("`;", start)
    assert "${" not in src[start + len("row.innerHTML = `"):end]
    assert "textContent = p.name" in src


# ─── SEC-06 — usuario sin contraseña aborta el arranque ──────────────────────
def TEST_sec06_user_without_password_aborts_startup():
    from backend.auth import check_auth_config
    with pytest.raises(RuntimeError, match="DASHBOARD_PASS"):
        check_auth_config(Settings(dashboard_user="u", dashboard_pass=""))


def TEST_sec06_no_auth_logs_warning(caplog):
    import logging

    from backend.auth import check_auth_config
    with caplog.at_level(logging.WARNING, logger="backend.auth"):
        check_auth_config(Settings(dashboard_user=""))
    assert "Autenticación desactivada" in caplog.text


def TEST_sec06_user_with_password_is_accepted():
    from backend.auth import check_auth_config
    check_auth_config(_auth_settings())


def TEST_sec06_lifespan_calls_check_auth_config():
    src = Path("backend/main.py").read_text(encoding="utf-8")
    lifespan = src[src.index("async def lifespan"):]
    assert lifespan.index("check_auth_config(settings)") < lifespan.index("await init_db()")


# ─── SEC-11 — la clave existente recupera permisos restrictivos ──────────────
@pytest.mark.skipif(__import__("os").name == "nt", reason="chmod POSIX; en Windows se usa icacls")
def TEST_sec11_existing_key_gets_restricted_permissions(tmp_path):
    import os
    import stat

    from backend.ssl_utils import ensure_self_signed_cert
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert.write_bytes(b"cert")
    key.write_bytes(b"key")
    os.chmod(key, 0o644)
    ensure_self_signed_cert(str(cert), str(key))
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    assert key.read_bytes() == b"key"   # no se regenera


# ─── SEC-04 — fallos de autenticación por IP y límite por plantilla de ruta ──
async def TEST_sec04_repeated_auth_failures_are_throttled_per_ip():
    from backend import auth
    auth._auth_failures.clear()
    try:
        with patch.object(auth, "get_settings", return_value=_auth_settings()):
            async with await _client() as client:
                codes = [(await client.get("/api/stats", auth=("u", "mal"))).status_code
                         for _ in range(auth._FAIL_MAX)]
                assert set(codes) == {401}
                blocked = await client.get("/api/stats", auth=("u", "p"))
                assert blocked.status_code == 429      # ni con la contraseña buena
                assert (await client.get("/api/stats")).status_code == 429
    finally:
        auth._auth_failures.clear()


async def TEST_sec04_success_resets_the_failure_count():
    from backend import auth
    auth._auth_failures.clear()
    try:
        with patch.object(auth, "get_settings", return_value=_auth_settings()), \
             patch.object(main_module, "get_stats_today", return_value={"total_today": 0, "hourly": {}}):
            async with await _client() as client:
                for _ in range(auth._FAIL_MAX - 1):
                    await client.get("/api/stats", auth=("u", "mal"))
                assert (await client.get("/api/stats", auth=("u", "p"))).status_code == 200
                assert auth._auth_failures == {}
    finally:
        auth._auth_failures.clear()


def TEST_sec04_missing_header_is_not_a_failure():
    """El navegador siempre hace la primera petición sin cabecera: no cuenta."""
    import asyncio

    from backend import auth
    auth._auth_failures.clear()
    conn = MagicMock()
    conn.scope = {"type": "http"}
    conn.headers = {}
    conn.client.host = "10.0.0.9"
    with patch.object(auth, "get_settings", return_value=_auth_settings()):
        for _ in range(auth._FAIL_MAX + 2):
            with pytest.raises(Exception) as exc:
                asyncio.run(auth.verify(conn))
            assert exc.value.status_code == 401
    assert auth._auth_failures == {}


def TEST_sec04_rate_limit_counts_per_route_template():
    from backend.main import _limiter
    assert v2_limiter._key_style == "endpoint"
    assert _limiter._key_style == "endpoint"


# ─── SEC-05 — Origin en métodos que cambian estado ───────────────────────────
async def TEST_sec05_cross_origin_post_is_rejected():
    async with await _client() as client:
        resp = await client.delete(
            "/api/events", params={"from_dt": "2026-01-01T00:00:00", "to_dt": "2026-01-02T00:00:00"},
            headers={"Origin": "http://atacante.lan"},
        )
    assert resp.status_code == 403


async def TEST_sec05_same_origin_and_no_origin_pass():
    with patch.object(main_module, "delete_events_range", return_value=0):
        async with await _client() as client:
            params = {"from_dt": "2026-01-01T00:00:00", "to_dt": "2026-01-02T00:00:00"}
            same = await client.delete("/api/events", params=params, headers={"Origin": "http://test"})
            none = await client.delete("/api/events", params=params)
    assert same.status_code == 200
    assert none.status_code == 200


async def TEST_sec05_get_is_not_checked():
    async with await _client() as client:
        resp = await client.get("/", headers={"Origin": "http://atacante.lan"})
    assert resp.status_code == 200


# ─── SEC-08 — tamaño del cuerpo antes de procesarlo ──────────────────────────
async def TEST_sec08_oversized_body_rejected_by_content_length():
    async with await _client() as client:
        resp = await client.post("/api/v2/rules", content=b"x" * (3 * 1024 * 1024),
                                 headers={"Content-Type": "application/json"})
    assert resp.status_code == 413


async def TEST_sec08_streamed_body_without_length_is_cut():
    async def chunks():
        for _ in range(40):
            yield b"x" * (100 * 1024)

    async with await _client() as client:
        resp = await client.post("/api/v2/rules", content=chunks(),
                                 headers={"Content-Type": "application/json"})
    assert resp.status_code == 413


async def TEST_sec08_enroll_keeps_its_larger_limit():
    """La imagen de enrolado sigue admitiendo hasta 10 MB: el 413 lo da el endpoint."""
    oversized = b"\xff" * (10 * 1024 * 1024 + 1)
    with patch.object(main_module, "rtsp_stream", _mock_recognizer_stream()):
        async with await _client() as client:
            resp = await client.post("/api/enroll_face", data={"name": "Eve"},
                                     files={"image": ("big.jpg", oversized, "image/jpeg")})
    assert resp.status_code == 413
    assert "10 MB" in resp.json()["detail"]
