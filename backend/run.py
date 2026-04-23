"""Entry point: starts uvicorn with optional SSL from config."""
import uvicorn

from backend.config import get_settings
from backend.ssl_utils import ensure_self_signed_cert


def main() -> None:
    s = get_settings()
    ssl_kwargs: dict = {}
    if s.ssl_certfile and s.ssl_keyfile:
        ensure_self_signed_cert(s.ssl_certfile, s.ssl_keyfile)
        ssl_kwargs = {"ssl_certfile": s.ssl_certfile, "ssl_keyfile": s.ssl_keyfile}
    uvicorn.run("backend.main:app", host=s.host, port=s.port, **ssl_kwargs)


if __name__ == "__main__":
    main()
