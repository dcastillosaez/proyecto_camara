"""HTTP Basic Auth + WebSocket token management."""
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from backend.config import get_settings

_security = HTTPBasic(auto_error=False)
_ws_tokens: set[str] = set()


def _auth_enabled() -> bool:
    return bool(get_settings().dashboard_user)


def verify(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
) -> None:
    """FastAPI dependency — enforces Basic Auth when DASHBOARD_USER is set."""
    if not _auth_enabled():
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm='Tapo Dashboard'"},
            detail="Authentication required",
        )
    s = get_settings()
    user_ok = secrets.compare_digest(credentials.username.encode(), s.dashboard_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), s.dashboard_pass.encode())
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
