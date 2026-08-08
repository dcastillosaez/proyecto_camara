"""Tests for backend.events.rules — RuleEngine validation, matching and debounce."""

from __future__ import annotations

import datetime
import textwrap

import pytest

from backend.events.rules import Rule, RuleEngine, load_rules
from backend.events.types import Event, EventType

SPEC_RULES_YAML = textwrap.dedent("""
    version: 1
    rules:
      - name: intrusion_nocturna
        enabled: true
        when:
          event: PERSON_ENTERED
          zone: jardin
          time_range: "23:00-06:00"
          days: [0,1,2,3,4,5,6]
        debounce_secs: 60
        actions:
          - type: record
            pre_secs: 10
            post_secs: 15
          - type: telegram
            template: "Intrusion en {zone_id} a las {ts:%H:%M:%S}"
          - type: webhook
            url_ref: alert_webhook_url

      - name: persona_desconocida
        when:
          event: UNKNOWN_PERSON
          min_confidence: 0.5
        debounce_secs: 120
        actions: [ {type: snapshot}, {type: record}, {type: notify} ]

      - name: permanencia_excesiva
        when:
          event: LOITERING
          duration_gte: 120
        actions: [ {type: notify} ]
    """)


def make_event(**overrides) -> Event:
    kwargs = {"type": EventType.PERSON_ENTERED, "camera_id": "cam1", "ts": "2026-04-16T18:30:00"}
    kwargs.update(overrides)
    return Event(**kwargs)


def make_rule(**when_overrides) -> dict:
    when = {"event": "PERSON_ENTERED"}
    when.update(when_overrides)
    return {"name": "r1", "when": when, "actions": [{"type": "log"}]}


def TEST_loads_valid_yaml(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(SPEC_RULES_YAML, encoding="utf-8")

    rules, errors = load_rules(str(path))

    assert errors == []
    assert {r.name for r in rules} == {"intrusion_nocturna", "persona_desconocida", "permanencia_excesiva"}


def TEST_invalid_rule_is_disabled_not_fatal(tmp_path):
    yaml_text = textwrap.dedent("""
        version: 1
        rules:
          - name: rota
            when:
              event: NO_EXISTE
            actions: [ {type: log} ]
          - name: sana
            when:
              event: PERSON_ENTERED
            actions: [ {type: log} ]
        """)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    rules, errors = load_rules(str(path))

    assert [r.name for r in rules] == ["sana"]
    assert len(errors) == 1
    assert errors[0][0] == "rota"
    assert errors[0][1]  # motivo legible, no vacio


async def TEST_all_when_conditions_are_and():
    rule = Rule.model_validate(make_rule(zone="jardin", time_range="10:00-11:00"))
    engine = RuleEngine([rule], registry={})

    # Cumple event + zone pero no time_range (18:30 fuera de 10:00-11:00)
    event = make_event(zone_id="jardin", ts=datetime.datetime(2026, 4, 16, 18, 30))
    fired = await engine.evaluate(event)

    assert fired == []


async def TEST_time_range_crossing_midnight():
    rule = Rule.model_validate(make_rule(time_range="23:00-06:00"))
    engine = RuleEngine([rule], registry={})

    at_2330 = await engine.evaluate(make_event(ts=datetime.datetime(2026, 4, 16, 23, 30), track_id=1))
    at_0200 = await engine.evaluate(make_event(ts=datetime.datetime(2026, 4, 17, 2, 0), track_id=2))
    at_1200 = await engine.evaluate(make_event(ts=datetime.datetime(2026, 4, 17, 12, 0), track_id=3))

    assert at_2330 == ["r1"]
    assert at_0200 == ["r1"]
    assert at_1200 == []


async def TEST_days_filter():
    rule = Rule.model_validate(make_rule(days=[5, 6]))  # sabado, domingo
    engine = RuleEngine([rule], registry={})

    tuesday = datetime.datetime(2026, 4, 14, 10, 0)  # martes
    assert tuesday.weekday() == 1
    fired = await engine.evaluate(make_event(ts=tuesday))

    assert fired == []


async def TEST_debounce_suppresses_repeats():
    rule = Rule.model_validate({**make_rule(), "debounce_secs": 60})
    engine = RuleEngine([rule], registry={})

    base = datetime.datetime(2026, 4, 16, 18, 30, 0)
    results = []
    for i in range(10):
        ts = base + datetime.timedelta(seconds=0.5 * i)
        results.append(await engine.evaluate(make_event(ts=ts, track_id=1)))

    fired_count = sum(1 for r in results if r == ["r1"])
    assert fired_count == 1
    assert results[0] == ["r1"]


async def TEST_debounce_key_is_composite():
    rule = Rule.model_validate({**make_rule(), "debounce_secs": 60})
    engine = RuleEngine([rule], registry={})

    base = datetime.datetime(2026, 4, 16, 18, 30, 0)
    fired_person_a = await engine.evaluate(make_event(ts=base, person_id=1))
    fired_person_b = await engine.evaluate(make_event(ts=base + datetime.timedelta(seconds=1), person_id=2))

    assert fired_person_a == ["r1"]
    assert fired_person_b == ["r1"]


async def TEST_multiple_rules_all_fire():
    rule_a = Rule.model_validate({**make_rule(), "name": "a"})
    rule_b = Rule.model_validate({**make_rule(), "name": "b"})
    engine = RuleEngine([rule_a, rule_b], registry={})

    fired = await engine.evaluate(make_event())

    assert set(fired) == {"a", "b"}


async def TEST_disabled_rule_never_fires():
    rule = Rule.model_validate({**make_rule(), "enabled": False})
    engine = RuleEngine([rule], registry={})

    fired = await engine.evaluate(make_event())

    assert fired == []


async def TEST_payload_filter_matches_exact_key():
    rule = Rule.model_validate({**make_rule(), "when": {**make_rule()["when"], "payload": {"is_intrusion": True}}})
    engine = RuleEngine([rule], registry={})

    fired_match = await engine.evaluate(make_event(payload={"is_intrusion": True}, track_id=1))
    fired_no_match = await engine.evaluate(make_event(payload={"is_intrusion": False}, track_id=2))

    assert fired_match == ["r1"]
    assert fired_no_match == []


async def TEST_camera_wildcard():
    wildcard_rule = Rule.model_validate({**make_rule(), "name": "wild", "when": {**make_rule()["when"], "camera": "*"}})
    specific_rule = Rule.model_validate({**make_rule(), "name": "specific", "when": {**make_rule()["when"], "camera": "cam2"}})
    engine = RuleEngine([wildcard_rule, specific_rule], registry={})

    fired = await engine.evaluate(make_event(camera_id="cam1"))

    assert fired == ["wild"]
