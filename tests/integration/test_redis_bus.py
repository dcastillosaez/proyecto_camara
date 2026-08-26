"""Fase 37 (SCALE-10): RedisBus contra un Redis real -- no un mock.

Se salta automaticamente si TEST_REDIS_URL no esta definida: no forma parte de
la suite por defecto (no hay Redis en CI todavia -- ver STACK.md "Cuando migrar
a Postgres/Redis"). Para ejecutarlo localmente:

    docker run -d --rm -p 56379:6379 redis:7-alpine

    TEST_REDIS_URL=redis://localhost:56379/0 \\
        .venv/Scripts/python.exe -m pytest tests/integration/test_redis_bus.py -v
"""

from __future__ import annotations

import asyncio
import datetime
import os

import pytest

from backend.events.bus import EventBusBase, InProcessBus, RedisBus, create_event_bus
from backend.events.types import Event, EventType

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not TEST_REDIS_URL,
    reason="TEST_REDIS_URL no definida -- requiere un Redis real, ver docstring del modulo",
)


def _event(i: int = 0) -> Event:
    return Event(
        type=EventType.LINE_CROSSED, camera_id="cam1",
        ts=datetime.datetime.now(), payload={"i": i},
    )


async def TEST_redisbus_is_event_bus_base():
    assert isinstance(RedisBus(TEST_REDIS_URL), EventBusBase)


async def TEST_publish_delivers_to_local_subscriber():
    bus = RedisBus(TEST_REDIS_URL, channel="test:events:local")
    await bus.start()
    received = []
    done = asyncio.Event()

    async def handler(event: Event) -> None:
        received.append(event)
        done.set()

    bus.subscribe("h1", handler)
    try:
        await bus.publish(_event())
        await asyncio.wait_for(done.wait(), timeout=5.0)
    finally:
        await bus.close()

    assert len(received) == 1
    assert received[0].payload == {"i": 0}
    assert bus.stats["published"] == 1


async def TEST_publish_fans_out_across_two_bus_instances():
    """El caso real que RedisBus existe para resolver: dos procesos backend
    distintos (aqui, dos instancias RedisBus separadas) comparten el mismo bus
    via el canal Redis -- publicar en una llega a los subscribers de la otra."""
    channel = "test:events:cross-process"
    bus_a = RedisBus(TEST_REDIS_URL, channel=channel)
    bus_b = RedisBus(TEST_REDIS_URL, channel=channel)
    await bus_a.start()
    await bus_b.start()

    received_on_b = []
    done = asyncio.Event()

    async def handler_b(event: Event) -> None:
        received_on_b.append(event)
        done.set()

    bus_b.subscribe("h_b", handler_b)
    try:
        await bus_a.publish(_event(42))
        await asyncio.wait_for(done.wait(), timeout=5.0)
    finally:
        await bus_a.close()
        await bus_b.close()

    assert len(received_on_b) == 1
    assert received_on_b[0].payload == {"i": 42}


async def TEST_publish_threadsafe_bridges_from_worker_thread():
    """Mismo contrato que InProcessBus.publish_threadsafe (Fase 18): un hilo de
    worker (sin loop propio) puede publicar sin awaitear nada."""
    import threading

    loop = asyncio.get_running_loop()
    bus = RedisBus(TEST_REDIS_URL, channel="test:events:threadsafe", loop=loop)
    await bus.start()
    received = []
    done = asyncio.Event()

    async def handler(event: Event) -> None:
        received.append(event)
        done.set()

    bus.subscribe("h1", handler)
    try:
        t = threading.Thread(target=bus.publish_threadsafe, args=(_event(7),))
        t.start()
        t.join(timeout=5.0)
        await asyncio.wait_for(done.wait(), timeout=5.0)
    finally:
        await bus.close()

    assert len(received) == 1
    assert received[0].payload == {"i": 7}


async def TEST_create_event_bus_picks_redis_when_configured():
    class _FakeSettings:
        redis_url = TEST_REDIS_URL

    bus = create_event_bus(_FakeSettings())
    assert isinstance(bus, RedisBus)


async def TEST_create_event_bus_defaults_to_in_process():
    class _FakeSettings:
        redis_url = ""

    bus = create_event_bus(_FakeSettings())
    assert isinstance(bus, InProcessBus)
