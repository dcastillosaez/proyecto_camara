"""Tests for backend.events.bus — EventBus async pub/sub."""

import asyncio
import threading

import pytest

from backend.events.bus import EventBus
from backend.events.types import Event, EventType


def make_event(**overrides) -> Event:
    kwargs = {"type": EventType.LINE_CROSSED, "camera_id": "cam1", "ts": "2026-04-16T18:30:00"}
    kwargs.update(overrides)
    return Event(**kwargs)


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Poll predicate() until truthy or raise on timeout — avoids relying on exact task scheduling."""
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condition not met within {timeout}s")


async def TEST_all_subscribers_receive_event():
    bus = EventBus()
    received: dict[str, Event] = {}

    async def make_handler(name):
        async def handler(event):
            received[name] = event
        return handler

    for name in ("a", "b", "c"):
        bus.subscribe(name, await make_handler(name))

    event = make_event()
    await bus.publish(event)
    await wait_until(lambda: len(received) == 3)

    assert set(received) == {"a", "b", "c"}


async def TEST_same_object_delivered():
    bus = EventBus()
    received = []

    async def h1(event):
        received.append(event)

    async def h2(event):
        received.append(event)

    async def h3(event):
        received.append(event)

    bus.subscribe("h1", h1)
    bus.subscribe("h2", h2)
    bus.subscribe("h3", h3)

    event = make_event()
    await bus.publish(event)
    await wait_until(lambda: len(received) == 3)

    assert received[0] is event
    assert received[1] is event
    assert received[2] is event


async def TEST_subscriber_exception_does_not_block_others():
    bus = EventBus()
    received = []

    async def broken(event):
        raise RuntimeError("boom")

    async def healthy(event):
        received.append(event)

    bus.subscribe("broken", broken)
    bus.subscribe("healthy", healthy)

    event = make_event()
    await bus.publish(event)
    await wait_until(lambda: len(received) == 1)
    await wait_until(lambda: bus.stats["failed"] >= 1)

    assert received[0] is event
    assert bus.stats["failed"] == 1


async def TEST_publish_threadsafe_from_thread():
    loop = asyncio.get_running_loop()
    bus = EventBus(loop=loop)
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe("h", handler)

    event = make_event()

    def worker():
        bus.publish_threadsafe(event)

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    await wait_until(lambda: len(received) == 1)
    assert received[0] is event


async def TEST_unsubscribe_stops_delivery():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe("h", handler)
    await bus.publish(make_event())
    await wait_until(lambda: len(received) == 1)

    bus.unsubscribe("h")
    await bus.publish(make_event())
    await asyncio.sleep(0.05)

    assert len(received) == 1


async def TEST_stats_counts_published_and_failed():
    bus = EventBus()

    async def broken(event):
        raise RuntimeError("boom")

    bus.subscribe("broken", broken)

    await bus.publish(make_event())
    await bus.publish(make_event())
    await wait_until(lambda: bus.stats["failed"] == 2)

    assert bus.stats["published"] == 2
    assert bus.stats["failed"] == 2


async def TEST_queue_is_bounded():
    bus = EventBus(maxsize=5)
    # No subscribers and no yielding between publishes: the background consumer
    # never gets a chance to drain, so the internal queue really fills up.
    for _ in range(10):
        await bus.publish(make_event())

    assert bus.stats["published"] == 10
    assert bus.stats["dropped"] == 5
