"""Tests for backend.events.types — EventType catalog and Event model."""

import uuid

import pytest
from pydantic import ValidationError

from backend.events.types import Event, EventType, Severity

SPEC_EVENT_TYPES = {
    # Personas
    "PERSON_ENTERED", "PERSON_EXITED", "LINE_CROSSED", "ZONE_ENTERED", "ZONE_EXITED",
    # Identidad
    "PERSON_RECOGNIZED", "UNKNOWN_PERSON", "IDENTITY_LOST",
    # Comportamiento
    "LOITERING", "RUNNING", "IMMOBILE", "CROWD_DETECTED", "INTRUSION",
    # Objetos
    "OBJECT_LEFT", "OBJECT_REMOVED",
    # Sistema
    "CAMERA_OFFLINE", "CAMERA_RECOVERED", "RECORDING_STARTED", "RECORDING_FINISHED",
    "UPLOAD_FAILED", "CONFIG_CHANGED", "DEGRADED_MODE",
}


def TEST_catalog_has_22_types():
    assert len(EventType) == 22


def TEST_catalog_matches_spec():
    assert {e.value for e in EventType} == SPEC_EVENT_TYPES


def TEST_event_generates_uuid():
    e1 = Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00")
    e2 = Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00")
    assert e1.id != e2.id
    uuid.UUID(e1.id)
    uuid.UUID(e2.id)


def TEST_event_requires_type_camera_ts():
    with pytest.raises(ValidationError):
        Event(camera_id="cam1", ts="2026-04-16T18:30:00")
    with pytest.raises(ValidationError):
        Event(type=EventType.LINE_CROSSED, ts="2026-04-16T18:30:00")
    with pytest.raises(ValidationError):
        Event(type=EventType.LINE_CROSSED, camera_id="cam1")


def TEST_event_roundtrip_json():
    e = Event(
        type=EventType.INTRUSION, camera_id="cam1", ts="2026-04-16T18:30:00",
        track_id=7, person_name="Juan", payload={"direction": "in"},
    )
    e2 = Event.model_validate_json(e.model_dump_json())
    assert e2 == e


def TEST_bbox_validates_length():
    with pytest.raises(ValidationError):
        Event(
            type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00",
            bbox=(1, 2, 3),
        )


def TEST_default_severity_is_info():
    e = Event(type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00")
    assert e.severity == Severity.INFO


def TEST_default_severity_applied_from_map():
    e = Event(type=EventType.INTRUSION, camera_id="cam1", ts="2026-04-16T18:30:00")
    assert e.severity == Severity.CRITICAL


def TEST_payload_accepts_arbitrary_keys():
    e = Event(
        type=EventType.LINE_CROSSED, camera_id="cam1", ts="2026-04-16T18:30:00",
        payload={"duration_s": 12.5, "direction": "in"},
    )
    assert e.payload == {"duration_s": 12.5, "direction": "in"}
