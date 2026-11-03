"""Middlewares ASGI de entrada: Origin en métodos que cambian estado (SEC-05) y
tamaño máximo del cuerpo antes de procesarlo (SEC-08).

Son ASGI puros y no BaseHTTPMiddleware: el límite de cuerpo tiene que ver los
trozos según llegan para cortar antes de que FastAPI lo lea entero en memoria.
"""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import urlsplit

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


async def _reply(send: Callable, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start", "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class OriginCheckMiddleware:
    """SEC-05: rechaza con 403 un POST/PUT/PATCH/DELETE cuyo Origin no es el propio
    servidor ni uno de CORS_ORIGINS. Con Basic Auth el navegador reenvía las
    credenciales solo, así que una página de otro origen en la LAN podía disparar
    acciones (borrar eventos, mover el PTZ) contra el dashboard. Sin cabecera Origin
    (curl, scripts) la petición pasa: no hay navegador que la haya forjado."""

    def __init__(self, app, allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in (allowed_origins or [])}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in _STATE_CHANGING:
            origin = _header(scope, b"origin")
            if origin is not None and not self._same_host(origin, scope):
                return await _reply(send, 403, "Origin no permitido")
        await self.app(scope, receive, send)

    def _same_host(self, origin: str, scope: dict[str, Any]) -> bool:
        if origin.rstrip("/").lower() in self.allowed:
            return True
        host = _header(scope, b"host")
        return bool(host) and urlsplit(origin).netloc.lower() == host.lower()


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """SEC-08: corta con 413 un cuerpo mayor que el límite, por Content-Length o
    contando los trozos si no lo trae. Antes /api/enroll_face leía la imagen entera
    y después comprobaba los 10 MB, y uvicorn no pone límite propio."""

    def __init__(self, app, max_bytes: int, overrides: dict[str, int] | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.overrides = overrides or {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.overrides.get(scope["path"], self.max_bytes)
        length = _header(scope, b"content-length")
        if length is not None and length.isdigit() and int(length) > limit:
            return await _reply(send, 413, f"Cuerpo demasiado grande (máximo {limit} bytes)")

        received = 0
        started = False
        rejected = False

        async def limited_receive():
            nonlocal received, rejected, started
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Se responde aqui mismo: FastAPI convierte cualquier excepcion al leer
                    # el cuerpo en un 400 generico, que tracking_send descartara.
                    if not started:
                        started = rejected = True
                        await _reply(send, 413, f"Cuerpo demasiado grande (máximo {limit} bytes)")
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            pass
