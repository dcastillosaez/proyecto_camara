"""EventBus: dos implementaciones intercambiables (Fase 37, SCALE-10).

InProcessBus (default, comportamiento identico al de las Fases 1-36): fan-out a
N subscribers dentro de un unico proceso via una asyncio.Queue en memoria.

RedisBus: mismo contrato publico (EventBusBase), pero publish() emite al canal
pub/sub de Redis en vez de a una cola local -- permite compartir el bus entre
varios procesos backend. `EventBus` (el nombre que main.py y el resto del
codigo importan desde la Fase 1) sigue siendo un alias de InProcessBus: sin
REDIS_URL configurada, el comportamiento es exactamente el de siempre, sin
dependencia dura de Redis.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Awaitable, Callable

from backend.events.types import Event
from backend.observability.metrics import metrics as _metrics

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBusBase(abc.ABC):
    """Contrato comun consumido por main.py -- InProcessBus y RedisBus lo implementan
    de forma intercambiable (Fase 37, criterio 3)."""

    @abc.abstractmethod
    def subscribe(self, name: str, handler: Handler) -> None: ...

    @abc.abstractmethod
    def unsubscribe(self, name: str) -> None: ...

    @abc.abstractmethod
    async def publish(self, event: Event) -> None: ...

    @abc.abstractmethod
    def publish_threadsafe(self, event: Event) -> None: ...

    async def start(self) -> None:
        """No-op por defecto. RedisBus lo sobreescribe para abrir la conexion
        pub/sub antes de que main.py empiece a publicar/suscribir."""
        return None

    async def close(self) -> None:
        """No-op por defecto. RedisBus lo sobreescribe para cerrar la conexion."""
        return None

    @property
    @abc.abstractmethod
    def stats(self) -> dict[str, int]: ...

    @property
    @abc.abstractmethod
    def queue_depth(self) -> int: ...


class InProcessBus(EventBusBase):
    """Delivers the same Event object (by reference) to every subscriber.

    Serialization happens at the edges (persistence, WebSocket) — never on the bus.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None, maxsize: int = 1000) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._subscribers: dict[str, Handler] = {}
        self._stats = {"published": 0, "delivered": 0, "failed": 0, "dropped": 0}
        self._consumer_task: asyncio.Task | None = None

    def subscribe(self, name: str, handler: Handler) -> None:
        self._subscribers[name] = handler

    def unsubscribe(self, name: str) -> None:
        self._subscribers.pop(name, None)

    def _ensure_consumer(self) -> None:
        if self._consumer_task is not None and not self._consumer_task.done():
            return
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # _enqueue() called with no loop running and none injected at
                # construction (e.g. a synchronous caller exercising the queue
                # directly). The event is still queued; delivery resumes once
                # a consumer gets scheduled from a running loop.
                return
        self._consumer_task = loop.create_task(self._consume())

    def _enqueue(self, event: Event) -> None:
        self._ensure_consumer()
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._stats["dropped"] += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(event)
        self._stats["published"] += 1
        _metrics.events_total.labels(
            type=event.type.value, severity=event.severity.value, camera=event.camera_id
        ).inc()

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            for name, handler in list(self._subscribers.items()):
                asyncio.ensure_future(self._run_handler(name, handler, event))

    async def _run_handler(self, name: str, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
            self._stats["delivered"] += 1
        except Exception:
            self._stats["failed"] += 1
            logger.exception("EventBus subscriber %r failed handling event %s", name, event.id)

    async def publish(self, event: Event) -> None:
        """Enqueue an event. Never blocks — drops the oldest queued event on overflow."""
        self._enqueue(event)

    def publish_threadsafe(self, event: Event) -> None:
        """Bridge for worker threads (Phase 18 pipeline workers). Uses call_soon_threadsafe."""
        loop = self._loop or asyncio.get_event_loop()
        loop.call_soon_threadsafe(self._enqueue, event)

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()


# Alias retro-compatible: main.py y el resto del codigo (Fases 1-36) importan
# "EventBus" -- Fase 37 anade RedisBus como alternativa intercambiable sin
# renombrar el nombre publico historico ni tocar sus ~10 call sites.
EventBus = InProcessBus


class RedisBus(EventBusBase):
    """Publica/consume eventos por un canal pub/sub de Redis (Fase 37, SCALE-10).

    Cada proceso que instancia RedisBus con la misma redis_url/channel comparte el
    mismo bus: publish() en un proceso llega a los subscribers locales de TODOS los
    procesos conectados al canal, incluido el que publico (fan-out simetrico,
    comportamiento estandar de Redis pub/sub). queue_depth() siempre es 0: no hay
    cola local que medir, Redis gestiona su propio buffering.
    """

    def __init__(
        self,
        redis_url: str,
        channel: str = "camara:events",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        import redis.asyncio as redis_asyncio

        self._redis = redis_asyncio.from_url(redis_url)
        self._channel = channel
        self._loop = loop
        self._pubsub = None
        self._subscribers: dict[str, Handler] = {}
        self._stats = {"published": 0, "delivered": 0, "failed": 0, "dropped": 0}
        self._listen_task: asyncio.Task | None = None

    def subscribe(self, name: str, handler: Handler) -> None:
        self._subscribers[name] = handler

    def unsubscribe(self, name: str) -> None:
        self._subscribers.pop(name, None)

    async def start(self) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel)
        self._listen_task = asyncio.ensure_future(self._listen())

    async def close(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(self._channel)
            await self._pubsub.aclose()
        await self._redis.aclose()

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                event = Event.model_validate_json(message["data"])
            except Exception:
                logger.exception("RedisBus: mensaje no deserializable en canal %s", self._channel)
                continue
            for name, handler in list(self._subscribers.items()):
                asyncio.ensure_future(self._run_handler(name, handler, event))

    async def _run_handler(self, name: str, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
            self._stats["delivered"] += 1
        except Exception:
            self._stats["failed"] += 1
            logger.exception("RedisBus subscriber %r failed handling event %s", name, event.id)

    async def publish(self, event: Event) -> None:
        await self._redis.publish(self._channel, event.model_dump_json())
        self._stats["published"] += 1
        _metrics.events_total.labels(
            type=event.type.value, severity=event.severity.value, camera=event.camera_id
        ).inc()

    def publish_threadsafe(self, event: Event) -> None:
        """Bridge for worker threads (Phase 18 pipeline workers). Publica de forma
        asincrona en el loop inyectado -- a diferencia de InProcessBus no puede
        limitarse a encolar de forma sincrona: publish() aqui es una llamada de red."""
        loop = self._loop or asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(self.publish(event), loop)
        future.add_done_callback(
            lambda f: f.exception() and logger.error(
                "RedisBus.publish_threadsafe fallo publicando %s: %s", event.id, f.exception()
            )
        )

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def queue_depth(self) -> int:
        return 0


def create_event_bus(
    settings, loop: asyncio.AbstractEventLoop | None = None
) -> EventBusBase:
    """Fabrica del bus segun configuracion (Fase 37, SCALE-10): `redis_url` vacio
    (default) mantiene el comportamiento in-process de siempre; con valor, usa
    RedisBus. Unico punto de decision -- main.py no necesita saber cual es cual."""
    if settings.redis_url:
        return RedisBus(settings.redis_url, loop=loop)
    return InProcessBus(loop=loop)
