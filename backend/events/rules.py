"""RuleEngine: matches typed events against config/rules.yaml and fires actions.

No eval(), no arbitrary code execution — rules.yaml is validated against Pydantic
models. An invalid rule is disabled and logged; it never blocks startup.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Protocol

import yaml
from pydantic import BaseModel, ValidationError

from backend.events.types import Event, EventType

if TYPE_CHECKING:
    from backend.events.actions import ActionRegistry  # noqa: F401

logger = logging.getLogger(__name__)


class When(BaseModel):
    event: EventType
    zone: str | None = None
    camera: str = "*"
    time_range: str | None = None  # "23:00-06:00", puede cruzar medianoche
    days: list[int] | None = None  # 0=lunes .. 6=domingo (datetime.weekday())
    min_confidence: float | None = None
    duration_gte: float | None = None
    person: str | None = None  # nombre o "unknown"


class Action(BaseModel):
    type: Literal[
        "record", "snapshot", "notify", "telegram", "webhook", "log", "upload_drive", "set_flag"
    ]
    pre_secs: float | None = None
    post_secs: float | None = None
    template: str | None = None
    url_ref: str | None = None


class Rule(BaseModel):
    name: str
    enabled: bool = True
    when: When
    debounce_secs: float = 0.0
    actions: list[Action]


class ActionRunner(Protocol):
    """Anything that resolves an action type to a handler — ActionRegistry.get() or a plain dict.get()."""

    def get(self, action_type: str) -> Callable[[Event, Action], Awaitable[None]] | None: ...


def _parse_time_range(spec: str) -> tuple[datetime.time, datetime.time]:
    start_str, end_str = spec.split("-")
    return datetime.time.fromisoformat(start_str), datetime.time.fromisoformat(end_str)


def _time_in_range(t: datetime.time, start: datetime.time, end: datetime.time) -> bool:
    if start <= end:
        return start <= t <= end
    # Cruza medianoche: [start, 23:59:59.999999] U [00:00, end]
    return t >= start or t <= end


def _matches(when: When, event: Event) -> bool:
    if when.event != event.type:
        return False
    if when.zone is not None and when.zone != event.zone_id:
        return False
    if when.camera != "*" and when.camera != event.camera_id:
        return False
    if when.time_range is not None:
        start, end = _parse_time_range(when.time_range)
        if not _time_in_range(event.ts.time(), start, end):
            return False
    if when.days is not None and event.ts.weekday() not in when.days:
        return False
    if when.min_confidence is not None:
        if event.confidence is None or event.confidence < when.min_confidence:
            return False
    if when.duration_gte is not None:
        duration = event.payload.get("duration_s")
        if duration is None or duration < when.duration_gte:
            return False
    if when.person is not None:
        if when.person == "unknown":
            if event.person_name is not None:
                return False
        elif when.person != event.person_name:
            return False
    return True


def load_rules(path: str) -> tuple[list[Rule], list[tuple[str, str]]]:
    """Load and validate rules.yaml. Never raises on a bad rule — collects errors instead."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    valid: list[Rule] = []
    errors: list[tuple[str, str]] = []
    for item in raw.get("rules", []):
        name = item.get("name", "<sin nombre>")
        try:
            valid.append(Rule.model_validate(item))
        except ValidationError as exc:
            reason = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            errors.append((name, reason))
            logger.error("Regla invalida %r: %s", name, reason)
    return valid, errors


class RuleEngine:
    def __init__(
        self, rules: list[Rule], registry: ActionRunner, invalid: list[tuple[str, str]] | None = None
    ) -> None:
        self._registry = registry
        self._rules: list[Rule] = []
        self._invalid: list[tuple[str, str]] = list(invalid) if invalid else []
        self._last_fired: dict[tuple[str, str, str], datetime.datetime] = {}
        self.reload(rules)

    def reload(self, rules: list[Rule], invalid: list[tuple[str, str]] | None = None) -> None:
        self._rules = rules
        if invalid is not None:
            self._invalid = list(invalid)
        self._last_fired.clear()

    @property
    def invalid_rules(self) -> list[tuple[str, str]]:
        return list(self._invalid)

    @staticmethod
    def _debounce_key(rule: Rule, event: Event) -> tuple[str, str, str]:
        who = event.person_id if event.person_id is not None else event.track_id
        return (rule.name, event.camera_id, str(who) if who is not None else "")

    def _is_debounced(self, rule: Rule, event: Event) -> bool:
        if rule.debounce_secs <= 0:
            return False
        last = self._last_fired.get(self._debounce_key(rule, event))
        if last is None:
            return False
        return (event.ts - last).total_seconds() < rule.debounce_secs

    def _purge_stale(self, now: datetime.datetime) -> None:
        if not self._last_fired:
            return
        max_debounce = max((r.debounce_secs for r in self._rules), default=0.0)
        ttl = max(max_debounce * 10, 3600.0)
        stale = [k for k, ts in self._last_fired.items() if (now - ts).total_seconds() > ttl]
        for k in stale:
            del self._last_fired[k]

    async def evaluate(self, event: Event) -> list[str]:
        """Return the names of every rule that matched (and wasn't debounced), in order."""
        self._purge_stale(event.ts)
        fired: list[str] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            if not _matches(rule.when, event):
                continue
            if self._is_debounced(rule, event):
                continue

            self._last_fired[self._debounce_key(rule, event)] = event.ts
            fired.append(rule.name)

            for action in rule.actions:
                handler = self._registry.get(action.type)
                if handler is None:
                    logger.error("Accion desconocida %r en regla %r", action.type, rule.name)
                    continue
                try:
                    await handler(event, action)
                except Exception:
                    logger.exception("Accion %r de regla %r fallo", action.type, rule.name)
        return fired
