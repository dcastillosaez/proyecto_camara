"""EventBus: async pub/sub with fan-out to N subscribers and a thread bridge."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from backend.events.types import Event
from backend.observability.metrics import metrics as _metrics

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
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
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.ensure_future(self._consume())

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
