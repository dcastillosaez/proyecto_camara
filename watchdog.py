"""Watchdog — lanza backend.run y lo reinicia automáticamente si cae."""
import logging
import signal
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("watchdog")

PYTHON = sys.executable
MIN_UPTIME_SECS = 10   # menos de esto = crash real → backoff
MAX_BACKOFF_SECS = 60

_stop = False


def _handle_signal(sig, frame):
    global _stop
    logger.info("Signal %s recibida — deteniendo watchdog", sig)
    _stop = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def main() -> None:
    backoff = 2
    while not _stop:
        logger.info("Arrancando backend.run…")
        t0 = time.monotonic()
        try:
            proc = subprocess.Popen([PYTHON, "-m", "backend.run"])
            while not _stop:
                try:
                    proc.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
        except Exception as exc:
            logger.error("Error lanzando proceso: %s", exc)
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

        if _stop:
            break

        uptime = time.monotonic() - t0
        if uptime < MIN_UPTIME_SECS:
            logger.warning("Proceso caído tras %.1fs — backoff %ds", uptime, backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECS)
        else:
            backoff = 2

        logger.info("Reiniciando en %ds…", backoff)
        time.sleep(backoff)

    logger.info("Watchdog detenido.")


if __name__ == "__main__":
    main()
