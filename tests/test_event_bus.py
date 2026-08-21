"""Tests for backend.events.bus — EventBus async pub/sub."""

import asyncio
import datetime
import threading

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.events.actions import ActionRegistry
from backend.events.bus import EventBus
from backend.events.rules import Rule, RuleEngine, When
from backend.events.types import Event, EventType
from backend.storage import models
from backend.storage.repositories import EventRepo


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


# --- Fase 30 (D-14): el suscriptor unico ordenado make_event_pipeline() ---------------
#
# Con los cuatro suscriptores concurrentes de la Fase 19 el orden lo decidia el
# scheduler y `payload.rules` se perdia SIEMPRE (_apply_rules mutaba el evento
# despues de que _persist_event ya lo hubiera escrito). Estos cuatro tests fijan el
# contrato nuevo: reglas -> payload -> INSERT -> broadcast -> acciones.

RULE_NAME = "Intrusión nocturna"


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pipeline_test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield EventRepo(sf)
    await engine.dispose()


def make_intrusion() -> Event:
    return Event(type=EventType.INTRUSION, camera_id="cam1", ts=datetime.datetime.now(), track_id=12)


def make_engine(actions=None, registry=None) -> RuleEngine:
    rule = Rule(name=RULE_NAME, when=When(event=EventType.INTRUSION),
                actions=actions or [], enabled=True, debounce_secs=0)
    return RuleEngine([rule], registry=registry or ActionRegistry())


async def _noop(event):
    return None


async def TEST_rules_are_persisted_in_payload_before_insert(repo):
    from backend.main import make_event_pipeline

    scheduled: list = []

    def _collect(coro):
        scheduled.append(coro)
        return coro

    event = make_intrusion()
    pipeline = make_event_pipeline(repo, make_engine(), broadcast_event=_noop,
                                   broadcast_v2=_noop, broadcast_v1=_noop, schedule=_collect)
    await pipeline(event)
    for coro in scheduled:
        await coro

    stored = await repo.get(event.id)
    assert stored is not None
    assert stored.payload["rules"] == [RULE_NAME]


async def TEST_ws_event_broadcast_happens_after_insert_and_carries_rules(repo):
    from backend.main import make_event_pipeline

    scheduled: list = []
    seen: dict = {}

    def _collect(coro):
        scheduled.append(coro)
        return coro

    async def fake_broadcast(event):
        # read-your-writes: en el momento del broadcast la fila ya debe existir
        seen["row"] = await repo.get(event.id)
        seen["event"] = event

    event = make_intrusion()
    pipeline = make_event_pipeline(repo, make_engine(), broadcast_event=fake_broadcast,
                                   broadcast_v2=_noop, broadcast_v1=_noop, schedule=_collect)
    await pipeline(event)
    for coro in scheduled:
        await coro

    assert seen["row"] is not None, "el broadcast salio antes del INSERT"
    assert seen["row"].payload["rules"] == [RULE_NAME]
    assert seen["event"].payload["rules"] == [RULE_NAME]


async def TEST_slow_rule_actions_do_not_block_persistence(repo):
    from backend.main import make_event_pipeline

    scheduled: list = []
    ran: list[str] = []

    def _collect(coro):
        scheduled.append(coro)
        return coro

    async def slow_handler(event, action, rule_name):
        await asyncio.sleep(0.05)
        ran.append(rule_name)

    registry = ActionRegistry()
    registry.register("log", slow_handler)
    engine = make_engine(actions=[{"type": "log"}], registry=registry)

    event = make_intrusion()
    pipeline = make_event_pipeline(repo, engine, broadcast_event=_noop,
                                   broadcast_v2=_noop, broadcast_v1=_noop, schedule=_collect)
    await pipeline(event)

    # El await del pipeline ya termino: la fila esta, las acciones lentas todavia no.
    assert await repo.get(event.id) is not None
    assert ran == []

    for coro in scheduled:
        await coro
    assert ran == [RULE_NAME]


async def TEST_match_failure_does_not_prevent_persistence(repo):
    from backend.main import make_event_pipeline

    scheduled: list = []

    def _collect(coro):
        scheduled.append(coro)
        return coro

    engine = make_engine()

    def boom(event):
        raise RuntimeError("match roto")

    engine.match = boom

    event = make_intrusion()
    pipeline = make_event_pipeline(repo, engine, broadcast_event=_noop,
                                   broadcast_v2=_noop, broadcast_v1=_noop, schedule=_collect)
    await pipeline(event)
    for coro in scheduled:
        await coro

    stored = await repo.get(event.id)
    assert stored is not None
    assert "rules" not in stored.payload
