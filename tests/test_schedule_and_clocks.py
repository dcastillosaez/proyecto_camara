"""BUG-07 y BUG-01: horario que cruza medianoche, relojes y flush de detection_stats."""

from __future__ import annotations

import datetime
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.main as main_module
from backend.events.rules import Rule, RuleEngine, When
from backend.events.types import Event, EventType


def _schedule(start, end, days=(0, 1, 2, 3, 4, 5, 6)):
    return SimpleNamespace(schedule_enabled=True, schedule_start=start, schedule_end=end,
                           schedule_days=list(days))


MONDAY = datetime.datetime(2026, 11, 2)   # lunes


@pytest.mark.parametrize("hour,expected", [(23, True), (2, True), (6, True), (7, False), (12, False), (21, False), (22, True)])
def TEST_night_schedule_crossing_midnight(hour, expected):
    now = MONDAY.replace(hour=hour)
    assert main_module.is_in_access_schedule(_schedule("22:00", "06:00"), now) is expected


def TEST_day_schedule_unchanged():
    s = _schedule("08:00", "22:00", days=[0, 1, 2, 3, 4])
    assert main_module.is_in_access_schedule(s, MONDAY.replace(hour=9)) is True
    assert main_module.is_in_access_schedule(s, MONDAY.replace(hour=23)) is False
    assert main_module.is_in_access_schedule(s, (MONDAY + datetime.timedelta(days=5)).replace(hour=9)) is False


def TEST_overnight_early_hours_belong_to_previous_day():
    s = _schedule("22:00", "06:00", days=[4])                       # solo viernes noche
    saturday_3am = (MONDAY + datetime.timedelta(days=5)).replace(hour=3)
    friday_3am = (MONDAY + datetime.timedelta(days=4)).replace(hour=3)
    assert main_module.is_in_access_schedule(s, saturday_3am) is True
    assert main_module.is_in_access_schedule(s, friday_3am) is False


def TEST_schedule_disabled_always_in():
    s = SimpleNamespace(schedule_enabled=False)
    assert main_module.is_in_access_schedule(s, MONDAY) is True


def TEST_debounce_not_stuck_after_clock_goes_back():
    rule = Rule(name="r", when=When(event=EventType.PERSON_ENTERED), debounce_secs=60,
                actions=[{"type": "log"}])
    engine = RuleEngine([rule], registry={})
    t = datetime.datetime(2026, 10, 25, 2, 30)
    assert engine.match(Event(type=EventType.PERSON_ENTERED, camera_id="cam1", ts=t, track_id=1)) == ["r"]
    back = t - datetime.timedelta(hours=1)          # fin del horario de verano
    assert engine.match(Event(type=EventType.PERSON_ENTERED, camera_id="cam1", ts=back, track_id=1)) == ["r"]
    soon = back + datetime.timedelta(seconds=10)
    assert engine.match(Event(type=EventType.PERSON_ENTERED, camera_id="cam1", ts=soon, track_id=1)) == []


def TEST_clip_deadline_uses_monotonic_clock():
    from backend.pipeline.recording import ClipRequest, RecordingWorker

    worker = RecordingWorker(MagicMock(), MagicMock(), post_buffer_secs=10.0)
    req = ClipRequest(reason="r", trigger_ts=datetime.datetime.now())
    before = time.monotonic()
    deadline = worker._deadline_for(req)
    assert before + 9.5 <= deadline <= time.monotonic() + 10.0
    # Disparo con fecha "futura" tras un salto atras del reloj: cuenta como edad 0.
    future = ClipRequest(reason="r", trigger_ts=datetime.datetime.now() + datetime.timedelta(hours=1))
    assert worker._deadline_for(future) <= time.monotonic() + 10.0
    # Un disparo antiguo no alarga el clip.
    old = ClipRequest(reason="r", trigger_ts=datetime.datetime.now() - datetime.timedelta(hours=1))
    assert worker._deadline_for(old) <= time.monotonic() + 0.1


# ─── BUG-01 ───────────────────────────────────────────────────────────────────
async def TEST_flush_detection_stats_uses_every_pipeline_engine():
    ok_engine = MagicMock()
    ok_engine.flush_stats = AsyncMock(return_value=2)
    bad_engine = MagicMock()
    bad_engine.flush_stats = AsyncMock(side_effect=RuntimeError("bd"))
    other = MagicMock()
    other.flush_stats = AsyncMock(return_value=1)
    pipelines = [MagicMock(camera_id=c, event_engine=e)
                 for c, e in (("cam1", ok_engine), ("cam2", bad_engine), ("cam3", other))]
    manager = MagicMock()
    manager.all.return_value = pipelines
    with patch.object(main_module, "camera_manager", manager), \
         patch.object(main_module, "get_session_factory", MagicMock()):
        flushed = await main_module._flush_detection_stats(datetime.datetime.now())
    assert flushed == 3
    for engine in (ok_engine, bad_engine, other):
        engine.flush_stats.assert_awaited_once()


def TEST_camera_pipeline_keeps_its_event_engine():
    from backend.pipeline.manager import CameraPipeline

    engine = MagicMock()
    pipeline = CameraPipeline("cam1", "rtsp://x", event_engine=engine)
    assert pipeline.event_engine is engine

