"""RecordingWorker — alimenta al ClipRecorder desde el broker.

No cambia la logica de grabacion (ClipRecorder se porta tal cual): solo
cambia de donde vienen los frames. El worker expone la misma interfaz
minima que ClipRecorder consumia de RTSPStream (get_frame /
get_live_count), asi que el recorder no se entera del cambio.

El pre/post-buffer llega en la Fase 20.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

import numpy as np

from backend.pipeline.tracking import TrackRegistry

if TYPE_CHECKING:
    from backend.pipeline.broker import Subscription

logger = logging.getLogger(__name__)


class RecordingWorker:
    """
    Adaptador broker → ClipRecorder.

    Mantiene el ultimo frame publicado y el numero de personas vivas
    (leido del TrackRegistry, no de una deteccion propia), y se lo ofrece
    al ClipRecorder por la misma interfaz que este ya usaba.
    """

    def __init__(
        self,
        sub: Subscription,
        registry: TrackRegistry,
        recorder_factory: Callable[["RecordingWorker"], object],
    ) -> None:
        self._sub = sub
        self._registry = registry
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        # El recorder recibe este worker como "stream": expone get_frame()
        # y get_live_count(), que es todo lo que ClipRecorder necesita.
        self._recorder = recorder_factory(self)

    # ------------------------------------------------------------------
    # Interfaz consumida por ClipRecorder (compatible con RTSPStream)
    # ------------------------------------------------------------------

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def get_live_count(self) -> int:
        return len(self._registry.active_ids())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="recording-worker"
        )
        self._thread.start()
        self._recorder.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._recorder.stop()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("RecordingWorker: thread did not stop within %.1fs", timeout)
        self._sub.close()

    @property
    def recorder(self) -> object:
        return self._recorder

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            with self._lock:
                self._frame = frame.image
