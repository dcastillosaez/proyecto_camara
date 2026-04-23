"""Entry point: starts uvicorn with optional SSL from config."""
import logging
import uvicorn

from backend.config import get_settings
from backend.ssl_utils import ensure_self_signed_cert


class _SuppressWin10054(logging.Filter):
    """Filter out the benign WinError 10054 noise from asyncio ProactorEventLoop."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "WinError 10054" not in (record.getMessage())


def _patch_asyncio_logger() -> None:
    for name in ("asyncio", "uvicorn.error"):
        logging.getLogger(name).addFilter(_SuppressWin10054())


def main() -> None:
    _patch_asyncio_logger()
    s = get_settings()
    ssl_kwargs: dict = {}
    if s.ssl_certfile and s.ssl_keyfile:
        ensure_self_signed_cert(s.ssl_certfile, s.ssl_keyfile)
        ssl_kwargs = {"ssl_certfile": s.ssl_certfile, "ssl_keyfile": s.ssl_keyfile}
    uvicorn.run("backend.main:app", host=s.host, port=s.port, **ssl_kwargs)


if __name__ == "__main__":
    main()
