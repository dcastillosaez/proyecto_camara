"""Tests for backend.events.actions — ActionRegistry and notifier decoupling."""

from __future__ import annotations

import datetime

import pytest

from backend.events import actions
from backend.events.actions import ACTIONS, configure
from backend.events.rules import Action, Rule, RuleEngine
from backend.events.types import Event, EventType
from backend.notifier import Notifier


def make_event(**overrides) -> Event:
    kwargs = {"type": EventType.INTRUSION, "camera_id": "cam1", "ts": "2026-04-16T18:30:00"}
    kwargs.update(overrides)
    return Event(**kwargs)


@pytest.fixture(autouse=True)
def _reset_actions_state():
    """configure() mutates module-level state — reset it around every test."""
    yield
    actions._notifier = None
    actions._emit = None
    actions._recorder_hook = None
    actions._snapshot_hook = None
    actions._upload_hook = None
    actions._flag_hook = None


def TEST_all_actions_registered():
    expected = {"record", "snapshot", "notify", "telegram", "webhook", "log", "upload_drive", "set_flag"}
    assert set(ACTIONS.registered) == expected
    for name in expected:
        assert ACTIONS.get(name) is not None


async def TEST_action_failure_does_not_block_siblings():
    class BrokenNotifier(Notifier):
        async def send_telegram(self, text, image=None):
            raise RuntimeError("telegram down")

    recorded = []

    async def recorder_hook(event, action):
        recorded.append(event)

    configure(notifier=BrokenNotifier(telegram_token="t", telegram_chat_id="c"), recorder_hook=recorder_hook)

    rule = Rule(
        name="r1",
        when={"event": "INTRUSION"},
        actions=[Action(type="telegram"), Action(type="record")],
    )
    engine = RuleEngine([rule], registry=ACTIONS)

    fired = await engine.evaluate(make_event())

    assert fired == ["r1"]
    assert len(recorded) == 1


async def TEST_action_failure_emits_event():
    emitted = []

    async def failing_upload(event, action):
        raise RuntimeError("drive unreachable")

    async def emit(event):
        emitted.append(event)

    configure(upload_hook=failing_upload, emit=emit)

    source_event = make_event()
    handler = ACTIONS.get("upload_drive")
    await handler(source_event, Action(type="upload_drive"))

    assert len(emitted) == 1
    assert emitted[0].type == EventType.UPLOAD_FAILED
    assert emitted[0].payload["source_event_id"] == source_event.id


async def TEST_template_interpolation():
    sent = []

    class CapturingNotifier(Notifier):
        async def send_telegram(self, text, image=None):
            sent.append(text)
            return True

    configure(notifier=CapturingNotifier(telegram_token="t", telegram_chat_id="c"))

    event = make_event(zone_id="jardin", ts=datetime.datetime(2026, 4, 16, 23, 5, 30))
    handler = ACTIONS.get("telegram")
    await handler(event, Action(type="telegram", template="Intrusion en {zone_id} a las {ts:%H:%M:%S}"))

    assert sent == ["Intrusion en jardin a las 23:05:30"]


def TEST_notifier_has_no_decision_logic():
    import pathlib
    source = pathlib.Path("backend/notifier.py").read_text(encoding="utf-8")
    assert "alert_on_" not in source
    assert "cooldown" not in source
