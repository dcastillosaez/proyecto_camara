"""Tests for backend.events.rules — RuleEngine validation, matching and debounce."""

from __future__ import annotations

import datetime
import textwrap

import pytest

from backend.events.rules import Rule, RuleEngine, is_schedule_active, load_rules
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


BEHAVIOR_RULES_YAML = textwrap.dedent("""
    version: 1
    rules:
      - name: merodeo_prolongado
        enabled: true
        when:
          event: LOITERING
          duration_gte: 120
        debounce_secs: 300
        actions: [ {type: notify} ]

      - name: carrera_detectada
        when: {event: RUNNING}
        actions: [ {type: log} ]

      - name: inmovilidad_prolongada
        when: {event: IMMOBILE, duration_gte: 60}
        actions: [ {type: log} ]

      - name: aglomeracion
        when: {event: CROWD_DETECTED}
        actions: [ {type: notify} ]
    """)


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


def TEST_behavior_events_usable_as_when_event(tmp_path):
    """Criterio 5: When.event es de tipo EventType (rules.py:25), asi que Pydantic valida
    contra el enum COMPLETO — los cuatro eventos de comportamiento, que existen en el
    catalogo desde la Fase 19, cargan desde un YAML real sin tocar una linea del
    RuleEngine."""
    path = tmp_path / "rules.yaml"
    path.write_text(BEHAVIOR_RULES_YAML, encoding="utf-8")

    rules, errors = load_rules(str(path))

    assert errors == []
    assert {r.name for r in rules} == {
        "merodeo_prolongado",
        "carrera_detectada",
        "inmovilidad_prolongada",
        "aglomeracion",
    }


async def TEST_behavior_duration_gte_reads_duration_s(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(BEHAVIOR_RULES_YAML, encoding="utf-8")
    rules, errors = load_rules(str(path))
    assert errors == []
    engine = RuleEngine(rules, registry={})

    fired_over = await engine.evaluate(
        make_event(type=EventType.LOITERING, payload={"duration_s": 130.0}, track_id=1)
    )
    fired_under = await engine.evaluate(
        make_event(type=EventType.LOITERING, payload={"duration_s": 90.0}, track_id=2)
    )
    fired_wrong_key = await engine.evaluate(
        make_event(type=EventType.LOITERING, payload={"duration": 130.0}, track_id=3)
    )

    assert fired_over == ["merodeo_prolongado"]
    assert fired_under == []
    assert fired_wrong_key == [], (
        "duration_gte lee event.payload['duration_s'] (rules.py:88-91); con la clave "
        "'duration' (nombre equivocado) event.payload.get('duration_s') devuelve None y "
        "la regla NO debe disparar — si dispara, el criterio 5 se cumple a medias y en "
        "silencio (Pitfall 8)."
    )


async def TEST_behavior_zone_filter_uses_first_class_zone_id(tmp_path):
    """Demuestra por que zone_id va como campo de primer nivel del Event y no dentro
    del payload (rules.py:75-76)."""
    yaml_text = textwrap.dedent("""
        version: 1
        rules:
          - name: merodeo_zona
            when: {event: LOITERING, zone: "z1"}
            actions: [ {type: notify} ]
        """)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    rules, errors = load_rules(str(path))
    assert errors == []
    engine = RuleEngine(rules, registry={})

    fired_in_zone = await engine.evaluate(
        make_event(type=EventType.LOITERING, zone_id="z1", track_id=1)
    )
    fired_no_zone = await engine.evaluate(
        make_event(type=EventType.LOITERING, zone_id=None, track_id=2)
    )

    assert fired_in_zone == ["merodeo_zona"]
    assert fired_no_zone == []


# --- Fase 33 (RULE-05): would_match() publico y sin efectos secundarios -----------


async def TEST_would_match_agrees_with_match_result():
    rule = Rule.model_validate(make_rule(zone="jardin"))
    engine = RuleEngine([rule], registry={})

    event_in_zone = make_event(zone_id="jardin")
    event_out_zone = make_event(zone_id="otra")

    assert engine.would_match(rule.when, event_in_zone) is True
    assert engine.would_match(rule.when, event_out_zone) is False


async def TEST_would_match_does_not_affect_debounce_state():
    """would_match() no debe alterar self._last_fired: probar una regla con
    debounce activo no debe consumir su ventana de debounce en produccion."""
    rule = Rule.model_validate({**make_rule(), "debounce_secs": 60})
    engine = RuleEngine([rule], registry={})
    base = datetime.datetime(2026, 4, 16, 18, 30, 0)
    event = make_event(ts=base, track_id=1)

    fired = await engine.evaluate(event)
    assert fired == ["r1"]

    # Sin would_match(), un segundo evento inmediato quedaria debounced.
    for _ in range(5):
        assert engine.would_match(rule.when, event) is True

    second_event = make_event(ts=base + datetime.timedelta(seconds=1), track_id=1)
    fired_second = await engine.evaluate(second_event)
    assert fired_second == [], "would_match() no debe haber consumido el debounce"


# --- Fase 33 (OPS-23): is_schedule_active() — horario propio de zona --------------


def TEST_is_schedule_active_none_is_always_true():
    assert is_schedule_active(None) is True
    assert is_schedule_active({}) is True


def TEST_is_schedule_active_respects_days_filter():
    tuesday = datetime.datetime(2026, 4, 14, 10, 0)
    assert tuesday.weekday() == 1
    assert is_schedule_active({"days": [0]}, now=tuesday) is False
    assert is_schedule_active({"days": [1]}, now=tuesday) is True


def TEST_is_schedule_active_time_range_crosses_midnight():
    schedule = {"time_range": "23:00-06:00"}
    inside = datetime.datetime(2026, 4, 17, 0, 30)
    outside = datetime.datetime(2026, 4, 17, 12, 0)
    assert is_schedule_active(schedule, now=inside) is True
    assert is_schedule_active(schedule, now=outside) is False


def TEST_is_schedule_active_combines_days_and_time_range():
    schedule = {"time_range": "09:00-17:00", "days": [0, 1, 2, 3, 4]}
    saturday_morning = datetime.datetime(2026, 4, 18, 10, 0)
    assert saturday_morning.weekday() == 5
    assert is_schedule_active(schedule, now=saturday_morning) is False
