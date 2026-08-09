"""Common dependencies for the /api/v2 surface (Fase 22 — SEC-16 hardening).

Auth is already applied app-wide via FastAPI(dependencies=[Depends(verify)])
(backend/main.py) — v2 routers inherit it automatically, same as v1.

Rate limiting: slowapi's Limiter.limit() decorator requires a `request: Request`
parameter on the decorated function to extract the client key, so it cannot be
applied to a whole APIRouter without touching each endpoint's signature. The
limiter instance and the rate value are defined once, here, and imported by
every v2 endpoint — the only thing repeated per endpoint is the decorator
line itself, not the policy it enforces.

Pagination: PAGINATION_LIMIT is the shared Query(...) factory list endpoints
use for their `limit` parameter, capping it at 200 regardless of what the
caller requests.
"""

from __future__ import annotations

from fastapi import Query
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

V2_RATE_LIMIT = "60/minute"


def pagination_limit(default: int = 50, le: int = 200):
    """Query(...) factory for list endpoints — caps `limit` at *le* regardless of request."""
    return Query(default=default, ge=1, le=le)
