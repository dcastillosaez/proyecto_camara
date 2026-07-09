"""Entry point: starts uvicorn with optional SSL from config."""
import logging
import uvicorn

from backend.config import get_settings
from backend.ssl_utils import ensure_self_signed_cert


def _patch_asyncio_win10054() -> None:
    """Suppress the benign WinError 10054 from ProactorEventLoop on Windows.

    These come from loop.call_exception_handler(), not logging, so a
    logging.Filter cannot intercept them. We install a custom exception
    handler that drops the specific error and forwards everything else.
    """
    import asyncio, sys
    if sys.platform != "win32":
        return
    loop = asyncio.get_event_loop()
    default_handler = loop.get_exception_handler()

    def _handler(loop, context):
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError) and getattr(exc, "winerror", None) == 10054:
            return
        if default_handler:
            default_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


def main() -> None:
    _patch_asyncio_win10054()
    s = get_settings()
    ssl_kwargs: dict = {}
    if s.ssl_certfile and s.ssl_keyfile:
        ensure_self_signed_cert(s.ssl_certfile, s.ssl_keyfile)
        ssl_kwargs = {"ssl_certfile": s.ssl_certfile, "ssl_keyfile": s.ssl_keyfile}
    uvicorn.run("backend.main:app", host=s.host, port=s.port, **ssl_kwargs)


if __name__ == "__main__":
    main()
