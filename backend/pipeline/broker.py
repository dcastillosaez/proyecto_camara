"""Fan-out latest-frame: un slot por suscriptor, el productor nunca bloquea.

El invariante de diseno (SPEC_v2.md ADR-01): la captura RTSP nunca debe
esperar a un consumidor. Cada suscriptor tiene su propio slot de un frame;
si no lo consume antes del siguiente publish(), ese frame se pierde para
el, no para los demas. Perder frames es preferible a acumular latencia.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Frame:
    """Un frame capturado, con los timestamps fijados en el momento de la captura.

    El consumidor NO debe mutar `image`: el broker publica la referencia sin
    copiar (ver 17-CONTEXT.md — decision "Sin copia defensiva en publish").
    """

    camera_id: str
    seq: int
    captured_at: float  # time.monotonic() justo tras cap.read()
    wall_clock: datetime  # datetime.now() del mismo instante
    image: np.ndarray

    @property
    def age(self) -> float:
        """Segundos transcurridos desde la captura."""
        return time.monotonic() - self.captured_at


class Subscription:
    """Slot de un frame con espera bloqueante para un unico consumidor."""

    def __init__(self, name: str, broker: "FrameBroker") -> None:
        self.name = name
        self._broker = broker
        self._cond = threading.Condition()
        self._slot: Frame | None = None
        self._closed = False
        self.delivered = 0
        self.dropped = 0
        self.last_seq = -1

    def _offer(self, frame: Frame) -> None:
        """Llamado por el broker. Nunca bloquea mas alla de adquirir el Condition."""
        with self._cond:
            if self._closed:
                return
            if self._slot is not None:
                self.dropped += 1
            self._slot = frame
            self.last_seq = frame.seq
            self._cond.notify()

    def get(self, timeout: float | None = None) -> Frame | None:
        """Devuelve el ultimo frame publicado, esperando hasta *timeout* segundos."""
        with self._cond:
            if self._slot is None and not self._closed:
                self._cond.wait(timeout)
            frame = self._slot
            self._slot = None
            if frame is not None:
                self.delivered += 1
            return frame

    def _mark_closed(self) -> None:
        """Cierra el slot sin tocar el registro del broker (lo usa replace=True)."""
        with self._cond:
            self._closed = True
            self._slot = None
            self._cond.notify_all()

    def close(self) -> None:
        """Cierra la suscripcion y desbloquea a quien este esperando en get()."""
        self._mark_closed()
        self._broker._unsubscribe(self.name, self)


class FrameBroker:
    """Distribuye el ultimo frame a N suscriptores independientes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, Subscription] = {}
        self._latest: Frame | None = None

    def subscribe(self, name: str, replace: bool = False) -> Subscription:
        """
        Registra un suscriptor con *name*.

        Con ``replace=True`` sustituye una suscripcion existente con ese
        nombre en vez de fallar. Lo necesita el WorkerSupervisor: un worker
        que muere por una excepcion nunca llega a cerrar su suscripcion, y
        la factory que lo recrea tiene que poder reclamar el mismo nombre.
        """
        with self._lock:
            existing = self._subs.get(name)
            if existing is not None:
                if not replace:
                    raise ValueError(f"Subscriber already registered: {name}")
                existing._mark_closed()
                logger.debug("FrameBroker: replacing subscriber: %s", name)
            sub = Subscription(name, self)
            self._subs[name] = sub
            logger.debug("FrameBroker: subscriber registered: %s", name)
            return sub

    def _unsubscribe(self, name: str, sub: Subscription | None = None) -> None:
        with self._lock:
            current = self._subs.get(name)
            # Solo retirar si sigue siendo la misma suscripcion: una
            # reemplazada por replace=True no debe llevarse por delante a
            # su sustituta al cerrarse tarde.
            if current is not None and (sub is None or current is sub):
                del self._subs[name]

    def latest(self) -> Frame | None:
        """Ultimo frame publicado, sin consumirlo ni requerir suscripcion.

        Para necesidades puntuales (una captura para enrolar, un chequeo de
        vida) que no justifican montar un worker propio.
        """
        with self._lock:
            return self._latest

    def publish(self, frame: Frame) -> None:
        """Entrega el frame a todos los suscriptores. NUNCA bloquea al productor.

        Copia la lista de suscriptores bajo el lock global y los notifica
        fuera de el, para que un suscriptor no pueda bloquear a los demas.
        """
        with self._lock:
            self._latest = frame
            subs = list(self._subs.values())
        for sub in subs:
            sub._offer(frame)

    def stats(self) -> dict[str, dict[str, int]]:
        """Copia de {name: {delivered, dropped, last_seq}} por suscriptor."""
        with self._lock:
            return {
                name: {
                    "delivered": s.delivered,
                    "dropped": s.dropped,
                    "last_seq": s.last_seq,
                }
                for name, s in self._subs.items()
            }

    def close(self) -> None:
        """Cierra todas las suscripciones activas."""
        with self._lock:
            subs = list(self._subs.values())
        for sub in subs:
            sub.close()
