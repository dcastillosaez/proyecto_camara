"""WorkerSupervisor — vigila los workers del pipeline, reinicia y marca FAILED.

Supervisor simple, no framework (18-CONTEXT.md): un hilo que cada
`interval` segundos comprueba `worker.is_alive()` y recrea con la factory
los que hayan muerto. Tres caidas dentro de una ventana de 60 s marcan el
worker como FAILED y se deja de reintentar — reintentar en bucle un
worker que falla siempre solo consume CPU y llena el log.

En esta fase el modo degradado se loguea y se expone por el endpoint de
salud; emitirlo como evento tipado DEGRADED_MODE llega en la Fase 19.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WorkerStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"
    STOPPED = "stopped"


class _Entry:
    """Estado de supervision de un worker registrado."""

    def __init__(self, name: str, factory: Callable[[], Any]) -> None:
        self.name = name
        self.factory = factory
        self.worker: Any | None = None
        self.status = WorkerStatus.STOPPED
        # Timestamps de las caidas dentro de la ventana deslizante
        self.crashes: deque[float] = deque()
        self.total_restarts = 0


class WorkerSupervisor:
    """Arranca, vigila y reinicia los workers de una cámara."""

    def __init__(
        self,
        interval: float = 5.0,
        max_restarts: int = 3,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        *max_restarts* es el numero de caidas dentro de *window* segundos
        que se toleran: con el default de 3, el worker se reinicia tras la
        primera y la segunda caida, y la tercera lo marca FAILED.
        """
        self._interval = interval
        self._max_crashes = max_restarts
        self._window = window
        self._clock = clock

        self._lock = threading.RLock()
        self._entries: dict[str, _Entry] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        with self._lock:
            if name in self._entries:
                raise ValueError(f"Worker already registered: {name}")
            self._entries[name] = _Entry(name, factory)

    def start_all(self) -> None:
        with self._lock:
            for entry in self._entries.values():
                self._spawn(entry)
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="worker-supervisor"
        )
        self._thread.start()

    def stop_all(self, timeout: float = 5.0) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
        with self._lock:
            for entry in self._entries.values():
                self._stop_entry(entry, timeout)

    def get(self, name: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(name)
            return entry.worker if entry else None

    def status(self) -> dict[str, WorkerStatus]:
        with self._lock:
            return {name: e.status for name, e in self._entries.items()}

    @property
    def degraded(self) -> bool:
        with self._lock:
            return any(e.status == WorkerStatus.FAILED for e in self._entries.values())

    def stats(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: {"status": e.status.value, "restarts": e.total_restarts}
                for name, e in self._entries.items()
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _spawn(self, entry: _Entry) -> None:
        entry.status = WorkerStatus.STARTING
        try:
            entry.worker = entry.factory()
            entry.worker.start()
            entry.status = WorkerStatus.RUNNING
        except Exception:
            entry.status = WorkerStatus.FAILED
            logger.exception("WorkerSupervisor: no se pudo arrancar %s", entry.name)

    def _stop_entry(self, entry: _Entry, timeout: float) -> None:
        if entry.worker is not None:
            try:
                entry.worker.stop(timeout)
            except TypeError:
                entry.worker.stop()
            except Exception:
                logger.exception("WorkerSupervisor: fallo al parar %s", entry.name)
        entry.status = WorkerStatus.STOPPED

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            with self._lock:
                for entry in self._entries.values():
                    self._check(entry)

    def _check(self, entry: _Entry) -> None:
        if entry.status not in (WorkerStatus.RUNNING, WorkerStatus.RESTARTING):
            return
        worker = entry.worker
        if worker is not None and worker.is_alive():
            return

        now = self._clock()
        # Ventana deslizante: los crashes viejos dejan de contar
        while entry.crashes and now - entry.crashes[0] > self._window:
            entry.crashes.popleft()
        entry.crashes.append(now)

        if len(entry.crashes) >= self._max_crashes:
            entry.status = WorkerStatus.FAILED
            logger.error(
                "WorkerSupervisor: %s marcado FAILED tras %d caidas en %.0fs — "
                "modo degradado, sin mas reintentos",
                entry.name, len(entry.crashes), self._window,
            )
            return

        entry.total_restarts += 1
        entry.status = WorkerStatus.RESTARTING
        logger.warning(
            "WorkerSupervisor: %s caido, reiniciando (caida %d/%d en la ventana)",
            entry.name, len(entry.crashes), self._max_crashes,
        )
        self._spawn(entry)
