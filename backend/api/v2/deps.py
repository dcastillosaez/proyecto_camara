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

from fastapi import HTTPException, Query
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

V2_RATE_LIMIT = "60/minute"


def pagination_limit(default: int = 50, le: int = 200):
    """Query(...) factory for list endpoints — caps `limit` at *le* regardless of request."""
    return Query(default=default, ge=1, le=le)


async def resolve_camera_id(camera_id: str | None, session_factory) -> str:
    """Resuelve el camera_id efectivo de la peticion (Fase 35, SCALE-03).

    Si el cliente ya lo mando, se respeta tal cual (ni siquiera se comprueba que
    exista: los endpoints que llaman a esto ya toleran una camara desconocida,
    p.ej. devolviendo listas vacias). Si no lo mando, cae al default SOLO cuando
    hay exactamente una camara REGISTRADA en la tabla `cameras` -- nunca a un
    literal "cam1" fijo, que dejaria de tener sentido en cuanto exista una
    segunda camara (Fase 36). Se resuelve contra el catalogo persistido, no
    contra el CameraManager en memoria: estos endpoints consultan historico en
    BD, no estado de pipeline vivo, y el catalogo sigue existiendo aunque el
    pipeline este parado. Con 0 o mas de una camara sin especificar cual, la
    eleccion es ambigua: 400 en vez de adivinar y devolver datos de la camara
    equivocada en silencio.
    """
    if camera_id is not None:
        return camera_id
    from backend.storage.repositories import CameraRepo

    default = await CameraRepo(session_factory).default_camera_id()
    if default is None:
        raise HTTPException(
            status_code=400,
            detail="camera_id requerido: hay varias camaras registradas (o ninguna) y no hay una unica por defecto",
        )
    return default


def snapshot_url(snapshot_path: str | None) -> str | None:
    """Ruta en disco del snapshot -> URL publica servida por el mount /snapshots.

    Vive aqui (y no en main.py) porque lo necesitan main.py — para el bloque `media`
    del mensaje WS — y el router de eventos; importar main desde un router seria
    un ciclo de imports.
    """
    if not snapshot_path:
        return None
    from pathlib import Path

    from backend.config import get_settings

    base = Path(get_settings().snapshot_dir).as_posix().rstrip("/")
    p = Path(snapshot_path).as_posix()
    if p.startswith(base + "/"):
        p = p[len(base) + 1:]
    return "/snapshots/" + p.lstrip("/")
