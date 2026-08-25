"""Recorrido de app.routes robusto a la version de FastAPI/Starlette instalada.

FastAPI >=0.140 (Starlette >=1.x) deja de aplanar las rutas de un router
incluido via include_router(): en vez de anadir cada APIRoute directamente a
app.routes, envuelve el router entero en un objeto interno
fastapi.routing._IncludedRouter (path=None) y resuelve las rutas reales bajo
demanda via su atributo `original_router.routes`. Con FastAPI <0.140 este
envoltorio no existe y include_router() ya deja las rutas aplanadas -- de ahi
que este helper compruebe el atributo en vez de asumir una version concreta,
para no romperse otra vez con el siguiente `pip install` sin pin exacto
(requirements.txt usa `>=` a proposito, CLAUDE.md).

Descubierto en la Fase 34 al retirar `continue-on-error: true` de CI: el
patron antiguo (`{getattr(r, "path", None) for r in app.routes}`) dejaba de
ver las rutas de los routers incluidos, y test_security_regression.py's
TEST_all_v2_endpoints_rate_limited pasaba con un falso "todo protegido" al
no encontrar NINGUNA ruta de esos routers que revisar.
"""

from __future__ import annotations

from typing import Iterator


def iter_app_routes(app) -> Iterator:
    """Yield cada ruta real (APIRoute/WebSocketRoute/Mount) de *app*, incluidas
    las de routers montados via include_router() bajo cualquier version."""
    yield from _iter_routes(app.routes)


def _iter_routes(routes) -> Iterator:
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from _iter_routes(original_router.routes)
        else:
            yield route
