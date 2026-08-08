"""Event catalog and the Event contract shared by the bus, storage and WebSocket."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class EventType(str, Enum):
    # Personas
    PERSON_ENTERED = "PERSON_ENTERED"
    PERSON_EXITED = "PERSON_EXITED"
    LINE_CROSSED = "LINE_CROSSED"
    ZONE_ENTERED = "ZONE_ENTERED"
    ZONE_EXITED = "ZONE_EXITED"
    # Identidad
    PERSON_RECOGNIZED = "PERSON_RECOGNIZED"
    UNKNOWN_PERSON = "UNKNOWN_PERSON"
    IDENTITY_LOST = "IDENTITY_LOST"
    # Comportamiento
    LOITERING = "LOITERING"
    RUNNING = "RUNNING"
    IMMOBILE = "IMMOBILE"
    CROWD_DETECTED = "CROWD_DETECTED"
    INTRUSION = "INTRUSION"
    # Objetos (emitidos a partir de la Fase 27; catalogados ya para estabilidad del contrato)
    OBJECT_LEFT = "OBJECT_LEFT"
    OBJECT_REMOVED = "OBJECT_REMOVED"
    # Sistema
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    CAMERA_RECOVERED = "CAMERA_RECOVERED"
    RECORDING_STARTED = "RECORDING_STARTED"
    RECORDING_FINISHED = "RECORDING_FINISHED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    DEGRADED_MODE = "DEGRADED_MODE"


DEFAULT_SEVERITY: dict[EventType, Severity] = {
    EventType.INTRUSION: Severity.CRITICAL,
    EventType.UNKNOWN_PERSON: Severity.WARNING,
    EventType.CAMERA_OFFLINE: Severity.CRITICAL,
    EventType.DEGRADED_MODE: Severity.WARNING,
    EventType.UPLOAD_FAILED: Severity.WARNING,
    EventType.OBJECT_LEFT: Severity.WARNING,
    # el resto -> Severity.INFO
}


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType
    camera_id: str
    ts: datetime
    severity: Severity = Severity.INFO
    track_id: int | None = None
    person_id: int | None = None
    person_name: str | None = None
    zone_id: str | None = None
    confidence: float | None = None
    bbox: tuple[int, int, int, int] | None = None
    snapshot_path: str | None = None
    recording_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _apply_default_severity(self) -> Event:
        if "severity" not in self.model_fields_set:
            self.severity = DEFAULT_SEVERITY.get(self.type, Severity.INFO)
        return self
