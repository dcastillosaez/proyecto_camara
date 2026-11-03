"""HTTP Basic Auth + WebSocket token management."""
import base64
import logging
import secrets
import time

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from backend.config import get_settings

logger = logging.getLogger(__name__)

_WS_TOKEN_TTL = 60  # seconds

# token → issued_at timestamp
_ws_tokens: dict[str, float] = {}


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

    auth = conn.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm='Tapo Dashboard'"},
            detail="Authentication required",
        )
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm='Tapo Dashboard'"},
            detail="Invalid Authorization header",
        )

    s = get_settings()
    user_ok = secrets.compare_digest(username.encode(), s.dashboard_user.encode())
    pass_ok = secrets.compare_digest(password.encode(), s.dashboard_pass.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm='Tapo Dashboard'"},
            detail="Invalid credentials",
        )


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
