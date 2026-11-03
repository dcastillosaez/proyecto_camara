"""Fase 4: INTRUSION, acciones upload_drive/snapshot, reglas por defecto y estado de Drive."""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport

import backend.main as main_module
from backend.config import Settings
from backend.events.bus import EventBus
from backend.events.engine import EventEngine
from backend.events.rules import Action, Rule
from backend.events.types import Event, EventType, Severity

NOW = datetime.datetime(2026, 4, 16, 23, 30)


def _engine():
    bus = EventBus(loop=asyncio.get_event_loop())
    received: list = []

    async def capture(event):
        received.append(event)

    bus.subscribe("capture", capture)
    return EventEngine(bus, camera_id="cam1"), received


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0.01)


async def TEST_out_of_schedule_crossing_emits_intrusion():
    engine, received = _engine()
    engine.emit_line_crossing({"direction": "in", "timestamp": NOW, "tracker_id": 3,
                               "is_intrusion": True, "line_id": "l1"})
    engine.emit_line_crossing({"direction": "in", "timestamp": NOW, "tracker_id": 4,
                               "is_intrusion": False})
    await _settle()
    types = [e.type for e in received]
    assert types.count(EventType.LINE_CROSSED) == 2
    intrusion = [e for e in received if e.type == EventType.INTRUSION]
    assert len(intrusion) == 1 and intrusion[0].track_id == 3
    assert intrusion[0].severity == Severity.CRITICAL


async def TEST_entering_a_restricted_zone_emits_intrusion():
    engine, received = _engine()
    engine.process_zone("z1", {5}, NOW, kind="restricted")
    engine.process_zone("z2", {6}, NOW, kind="counting")
    await _settle()
    intrusion = [e for e in received if e.type == EventType.INTRUSION]
    assert [(e.track_id, e.zone_id) for e in intrusion] == [(5, "z1")]


def TEST_default_rules_record_intrusion_and_unknown_not_object_left():
    from scripts.generate_initial_rules import build_rules

    doc = build_rules(Settings())
    by_event = {r["when"]["event"]: [a["type"] for a in r["actions"]] for r in doc["rules"]}
    assert "record" in by_event["INTRUSION"]
    assert "record" in by_event["UNKNOWN_PERSON"]
    assert "OBJECT_LEFT" not in by_event
    for rule in doc["rules"]:
        Rule.model_validate(rule)


def TEST_shipped_rules_yaml_matches_the_agreed_defaults():
    from backend.events.rules import load_rules

    rules, errors = load_rules("config/rules.yaml")
    assert errors == []
    events = {r.when.event: [a.type for a in r.actions] for r in rules}
    assert events[EventType.INTRUSION] == ["notify", "record"]
    assert events[EventType.UNKNOWN_PERSON] == ["notify", "record"]


def TEST_retired_options_are_gone():
    fields = set(Settings.model_fields)
    assert not {"recording_tail_secs", "alert_on_intrusion", "alert_on_unknown",
                "alert_on_detection"} & fields
    assert "url_ref" not in Action.model_fields
    # Una regla antigua con url_ref se sigue cargando.
    assert Action.model_validate({"type": "webhook", "url_ref": "alert_webhook_url"}).type == "webhook"


async def TEST_upload_drive_and_snapshot_actions_call_their_hooks():
    """Antes upload_drive y snapshot solo registraban 'sin hook' en el log."""
    from backend.events import actions as event_actions

    ev = Event(type=EventType.UNKNOWN_PERSON, camera_id="cam1", ts=NOW)
    upload, snapshot = AsyncMock(), AsyncMock()
    with patch.object(event_actions, "_upload_hook", upload), \
         patch.object(event_actions, "_snapshot_hook", snapshot):
        await event_actions.ACTIONS.get("upload_drive")(ev, Action(type="upload_drive"), "r")
        await event_actions.ACTIONS.get("snapshot")(ev, Action(type="snapshot"), "r")
    upload.assert_awaited_once()
    snapshot.assert_awaited_once()


def TEST_lifespan_wires_upload_and_snapshot_hooks():
    import inspect

    src = inspect.getsource(main_module.lifespan)
    assert "upload_hook=_upload_hook" in src and "snapshot_hook=_snapshot_hook" in src
    assert "force_upload=True" in src
    assert 'pre_secs=getattr(action, "pre_secs", None)' in src


async def TEST_forced_snapshot_ignores_disabled_setting_and_missing_bbox(tmp_path):
    frame = __import__("numpy").zeros((90, 160, 3), dtype="uint8")
    pipeline = MagicMock()
    pipeline.get_frame.return_value = frame
    manager = MagicMock()
    manager.get.return_value = pipeline
    settings = Settings(snapshot_enabled=False, snapshot_dir="data/snapshots")
    ev = Event(type=EventType.INTRUSION, camera_id="cam1", ts=NOW)
    with patch.object(main_module, "camera_manager", manager), \
         patch.object(main_module, "get_settings", return_value=settings), \
         patch.object(main_module.cv2, "imwrite", return_value=True) as imwrite:
        assert await main_module._capture_event_snapshot(ev) is None
        path = await main_module._capture_event_snapshot(ev, force=True)
    assert path and path.endswith(f"{ev.id}.jpg")
    assert imwrite.call_args.args[1].shape == (90, 160, 3)   # frame completo


async def TEST_upload_status_endpoint_reports_pause():
    from backend.api.v2 import recordings as rec_module

    queue = MagicMock()
    queue.status = {"paused": True, "reason": "token caducado", "since": "2026-01-01T00:00:00"}
    with patch.object(rec_module, "_upload_queue", queue), \
         patch.object(rec_module.RecordingRepo, "count_by_upload_state", AsyncMock(return_value=4)):
        async with httpx.AsyncClient(transport=ASGITransport(app=main_module.app),
                                     base_url="http://test") as client:
            resp = await client.get("/api/v2/recordings/upload-status")
    assert resp.status_code == 200
    assert resp.json() == {"paused": True, "reason": "token caducado",
                           "since": "2026-01-01T00:00:00", "pending": 4}
