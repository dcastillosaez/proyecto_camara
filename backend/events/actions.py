"""ActionRegistry: the 8 executable actions a matched rule can trigger.

Real side effects (recording, snapshot capture, Drive upload) are wired in via
configure() at startup — this module works standalone with log-only fallbacks
so it stays testable without a live pipeline.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Awaitable, Callable

from backend.events.rules import Action
from backend.events.types import Event, EventType
from backend.notifier import Notifier

logger = logging.getLogger(__name__)

Handler = Callable[[Event, Action], Awaitable[None]]


class ActionRegistry:
    """Dispatch table: action type name -> async handler(event, action)."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler) -> None:
        self._handlers[name] = handler

    def get(self, name: str) -> Handler | None:
        return self._handlers.get(name)

    @property
    def registered(self) -> list[str]:
        return list(self._handlers)


ACTIONS = ActionRegistry()

# Wired at startup via configure() — kept as module state so handlers stay plain
# functions (matches the ACTIONS dict shape RuleEngine expects).
_notifier: Notifier | None = None
_emit: Callable[[Event], Awaitable[None]] | None = None
_recorder_hook: Handler | None = None
_snapshot_hook: Handler | None = None
_upload_hook: Handler | None = None
_flag_hook: Handler | None = None


def configure(
    *,
    notifier: Notifier | None = None,
    emit: Callable[[Event], Awaitable[None]] | None = None,
    recorder_hook: Handler | None = None,
    snapshot_hook: Handler | None = None,
    upload_hook: Handler | None = None,
    flag_hook: Handler | None = None,
) -> None:
    """Wire real pipeline dependencies. Idempotent — only overwrites what's passed."""
    global _notifier, _emit, _recorder_hook, _snapshot_hook, _upload_hook, _flag_hook
    if notifier is not None:
        _notifier = notifier
    if emit is not None:
        _emit = emit
    if recorder_hook is not None:
        _recorder_hook = recorder_hook
    if snapshot_hook is not None:
        _snapshot_hook = snapshot_hook
    if upload_hook is not None:
        _upload_hook = upload_hook
    if flag_hook is not None:
        _flag_hook = flag_hook


def _interpolate(template: str, event: Event) -> str:
    values: dict[str, Any] = {
        "id": event.id,
        "type": event.type.value,
        "camera_id": event.camera_id,
        "ts": event.ts,
        "severity": event.severity.value,
        "track_id": event.track_id,
        "person_id": event.person_id,
        "person_name": event.person_name,
        "zone_id": event.zone_id,
        "confidence": event.confidence,
        **event.payload,
    }
    try:
        return template.format(**values)
    except (KeyError, IndexError) as exc:
        logger.warning("Placeholder desconocido en template %r: %s", template, exc)
        return template


async def _emit_upload_failed(source_event: Event, reason: str) -> None:
    if _emit is None:
        return
    failure = Event(
        type=EventType.UPLOAD_FAILED,
        camera_id=source_event.camera_id,
        ts=datetime.datetime.now(),
        payload={"reason": reason, "source_event_id": source_event.id},
    )
    await _emit(failure)


async def _action_record(event: Event, action: Action) -> None:
    if _recorder_hook is not None:
        await _recorder_hook(event, action)
    else:
        logger.info("record: sin recorder configurado, se ignora (event=%s)", event.id)


async def _action_snapshot(event: Event, action: Action) -> None:
    if _snapshot_hook is not None:
        await _snapshot_hook(event, action)
    else:
        logger.info("snapshot: sin snapshot_hook configurado, se ignora (event=%s)", event.id)


async def _action_telegram(event: Event, action: Action) -> None:
    if _notifier is None:
        logger.warning("telegram: Notifier no configurado")
        return
    text = _interpolate(action.template, event) if action.template else (
        f"{event.type.value} en {event.camera_id}"
    )
    await _notifier.send_telegram(text)


async def _action_webhook(event: Event, action: Action) -> None:
    if _notifier is None:
        logger.warning("webhook: Notifier no configurado")
        return
    await _notifier.send_webhook(event.model_dump(mode="json"))


async def _action_notify(event: Event, action: Action) -> None:
    """Unifies whatever channels are configured (Web Push + telegram + webhook)."""
    if _notifier is None:
        return
    text = f"{event.type.value} en {event.camera_id} ({event.severity.value})"
    if "telegram" in _notifier.active_channels:
        await _notifier.send_telegram(text)
    if "webhook" in _notifier.active_channels:
        await _notifier.send_webhook(event.model_dump(mode="json"))


async def _action_log(event: Event, action: Action) -> None:
    logger.info(
        "regla disparada: type=%s camera=%s severity=%s",
        event.type.value, event.camera_id, event.severity.value,
    )


async def _action_upload_drive(event: Event, action: Action) -> None:
    if _upload_hook is None:
        logger.info("upload_drive: sin upload_hook configurado, se ignora (event=%s)", event.id)
        return
    try:
        await _upload_hook(event, action)
    except Exception as exc:
        logger.warning("upload_drive fallo: %s", exc)
        await _emit_upload_failed(event, str(exc))


async def _action_set_flag(event: Event, action: Action) -> None:
    if _flag_hook is not None:
        await _flag_hook(event, action)
    else:
        logger.info("set_flag: sin flag_hook configurado, se ignora (event=%s)", event.id)


ACTIONS.register("record", _action_record)
ACTIONS.register("snapshot", _action_snapshot)
ACTIONS.register("notify", _action_notify)
ACTIONS.register("telegram", _action_telegram)
ACTIONS.register("webhook", _action_webhook)
ACTIONS.register("log", _action_log)
ACTIONS.register("upload_drive", _action_upload_drive)
ACTIONS.register("set_flag", _action_set_flag)
