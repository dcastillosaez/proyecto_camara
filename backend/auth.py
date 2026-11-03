"""HTTP Basic Auth + WebSocket token management."""
import base64
import logging
import secrets
import time
from collections import deque

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from backend.config import get_settings

logger = logging.getLogger(__name__)

_WS_TOKEN_TTL = 60  # seconds

# token → issued_at timestamp
_ws_tokens: dict[str, float] = {}

# SEC-04: intentos fallidos de Basic Auth por IP. Pasado el maximo dentro de la
# ventana, esa IP recibe 429 sin comprobar credenciales hasta que la ventana se vacie.
# Antes no habia limite: el de slowapi era por URL concreta y por endpoint, y una
# fuerza bruta podia repartirse entre rutas. Acotado: a partir de _FAIL_TRACK_CAP IPs
# se descartan las que no tienen fallos recientes.
_FAIL_WINDOW = 300.0
_FAIL_MAX = 10
_FAIL_TRACK_CAP = 1024
_auth_failures: dict[str, deque[float]] = {}


def _client_ip(conn: HTTPConnection) -> str:
    return conn.client.host if conn.client else "unknown"


def _recent_failures(ip: str, now: float) -> deque[float]:
    window = _auth_failures.get(ip)
    if window is None:
        return deque()
    while window and now - window[0] > _FAIL_WINDOW:
        window.popleft()
    if not window:
        del _auth_failures[ip]
    return window


def _record_failure(ip: str, now: float) -> None:
    if len(_auth_failures) >= _FAIL_TRACK_CAP and ip not in _auth_failures:
        for other in list(_auth_failures):
            _recent_failures(other, now)
        if len(_auth_failures) >= _FAIL_TRACK_CAP:
            _auth_failures.pop(next(iter(_auth_failures)))
    _auth_failures.setdefault(ip, deque()).append(now)


def _unauthorized(detail: str, ip: str) -> HTTPException:
    _record_failure(ip, time.monotonic())
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Basic realm='Tapo Dashboard'"},
        detail=detail,
    )


def _auth_enabled() -> bool:
    return bool(get_settings().dashboard_user)


def check_auth_config(settings=None) -> None:
    """SEC-06: se llama al arrancar. Con DASHBOARD_USER y sin DASHBOARD_PASS bastaria
    conocer el usuario para entrar con la contraseña vacia, asi que se aborta el
    arranque. Sin usuario no hay autenticacion: se permite, pero se avisa."""
    s = settings or get_settings()
    if s.dashboard_user and not s.dashboard_pass:
        raise RuntimeError(
            "DASHBOARD_USER está configurado sin DASHBOARD_PASS: el dashboard aceptaría "
            "la contraseña vacía. Define DASHBOARD_PASS o vacía DASHBOARD_USER."
        )
    if not s.dashboard_user:
        logger.warning(
            "Autenticación desactivada (DASHBOARD_USER vacío): cualquiera en la red puede "
            "ver el vídeo, los clips y los rostros."
        )


def _purge_expired_tokens() -> None:
    now = time.monotonic()
    expired = [t for t, ts in _ws_tokens.items() if now - ts > _WS_TOKEN_TTL]
    for t in expired:
        del _ws_tokens[t]


async def verify(conn: HTTPConnection) -> None:
    """FastAPI dependency — enforces Basic Auth on HTTP routes when DASHBOARD_USER is set.
    WebSocket scope is skipped; WS auth uses single-use tokens instead."""
    if not _auth_enabled():
        return
    if conn.scope.get("type") == "websocket":
        return

    ip = _client_ip(conn)
    if len(_recent_failures(ip, time.monotonic())) >= _FAIL_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos de autenticación fallidos; espera unos minutos",
        )

    auth = conn.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        # Sin cabecera no es un intento fallido: el navegador siempre pide primero sin ella.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm='Tapo Dashboard'"},
            detail="Authentication required",
        )
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise _unauthorized("Invalid Authorization header", ip)

    s = get_settings()
    user_ok = secrets.compare_digest(username.encode(), s.dashboard_user.encode())
    pass_ok = secrets.compare_digest(password.encode(), s.dashboard_pass.encode())
    if not (user_ok and pass_ok):
        raise _unauthorized("Invalid credentials", ip)
    _auth_failures.pop(ip, None)


def issue_ws_token() -> str:
    """Generate and store a single-use WebSocket auth token with TTL."""
    _purge_expired_tokens()
    token = secrets.token_hex(32)
    _ws_tokens[token] = time.monotonic()
    return token


def verify_ws_token(token: str | None) -> bool:
    """Validate and consume a WS token. Always passes when auth is disabled."""
    if not _auth_enabled():
        return True
    _purge_expired_tokens()
    if not token or token not in _ws_tokens:
        return False
    del _ws_tokens[token]
    return True
