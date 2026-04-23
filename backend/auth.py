"""HTTP Basic Auth + WebSocket token management."""
import base64
import secrets

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from backend.config import get_settings

_ws_tokens: set[str] = set()


def _auth_enabled() -> bool:
    return bool(get_settings().dashboard_user)


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
    """Generate and store a single-use WebSocket auth token."""
    token = secrets.token_hex(32)
    _ws_tokens.add(token)
    return token


def verify_ws_token(token: str | None) -> bool:
    """Validate and consume a WS token. Always passes when auth is disabled."""
    if not _auth_enabled():
        return True
    if not token or token not in _ws_tokens:
        return False
    _ws_tokens.discard(token)
    return True
