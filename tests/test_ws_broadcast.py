"""BUG-04: el broadcast WebSocket no puede bloquear ni morir por un cliente."""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import MagicMock, patch

import pytest

import backend.main as main_module
from backend.events.types import Event, EventType


class _Client:
    def __init__(self, delay: float = 0.0, fail: bool = False, on_send=None):
        self.delay, self.fail, self.on_send = delay, fail, on_send
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        if self.on_send:
            self.on_send()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("socket cerrado")
        self.sent.append(payload)


async def TEST_slow_client_is_dropped_without_delaying_the_others():
    fast, slow = _Client(), _Client(delay=60)
    clients = {fast, slow}
    with patch.object(main_module, "_WS_SEND_TIMEOUT", 0.1):
        t0 = asyncio.get_running_loop().time()
        await main_module._send_all(clients, "hola")
        elapsed = asyncio.get_running_loop().time() - t0
    assert fast.sent == ["hola"]
    assert clients == {fast}
    assert elapsed < 1.0


async def TEST_dead_client_is_removed():
    ok, dead = _Client(), _Client(fail=True)
    clients = {ok, dead}
    await main_module._send_all(clients, "x")
    assert clients == {ok}


async def TEST_set_can_change_while_broadcasting():
    clients: set = set()
    late = _Client()
    clients.add(_Client(on_send=lambda: clients.add(late), delay=0.01))
    clients.add(_Client(delay=0.01))
    await main_module._send_all(clients, "x")   # antes: RuntimeError Set changed size
    assert late in clients


async def TEST_rule_actions_do_not_wait_for_the_broadcast():
    scheduled: list = []
    rule_engine = MagicMock()
    rule_engine.match.return_value = ["regla"]

    async def run_actions(event, fired):
        return None

    rule_engine.run_actions = run_actions
    repo = MagicMock()

    async def insert(event):
        return None

    repo.insert = insert
    hang = asyncio.Event()

    async def stuck_broadcast(event):
        await hang.wait()       # un cliente que nunca responde

    async def noop(event):
        return None

    pipeline = main_module.make_event_pipeline(
        repo, rule_engine, broadcast_event=stuck_broadcast, broadcast_v2=noop,
        broadcast_v1=noop, schedule=scheduled.append,
    )
    ev = Event(type=EventType.PERSON_ENTERED, camera_id="cam1", ts=datetime.datetime.now())
    task = asyncio.ensure_future(pipeline(ev))
    await asyncio.sleep(0.05)
    assert len(scheduled) == 1, "las acciones debian programarse antes del broadcast"
    hang.set()
    await task
    for coro in scheduled:
        coro.close()


async def TEST_tracks_loop_survives_a_failing_pipeline():
    bad = MagicMock(camera_id="cam1")
    bad.get_person_boxes.side_effect = RuntimeError("pipeline a medio retirar")
    good = MagicMock(camera_id="cam2")
    good.get_person_boxes.return_value = []
    manager = MagicMock()
    manager.all.return_value = [bad, good]
    sent: list[dict] = []

    async def fake_broadcast(msg):
        sent.append(msg)

    ticks = {"n": 0}
    real_sleep = asyncio.sleep

    async def fake_sleep(_):
        ticks["n"] += 1
        if ticks["n"] > 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    with patch.object(main_module, "camera_manager", manager), \
         patch.object(main_module, "_broadcast", fake_broadcast), \
         patch.object(main_module.asyncio, "sleep", fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await main_module._tracks_broadcast_loop(0)
    assert [m["camera_id"] for m in sent] == ["cam2", "cam2"]   # dos vueltas, sigue vivo
