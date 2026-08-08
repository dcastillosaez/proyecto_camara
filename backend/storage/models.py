"""SQLAlchemy declarative models for the v2 schema (Phase 19).

12 tables per propuesta_mejora/SPEC_v2.md §7.1, with the indices from §7.2.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    rtsp_url_ref = Column(String(255), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    process_w = Column(Integer, nullable=True)
    process_h = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    last_seen_at = Column(DateTime, nullable=True)


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
    last_seen_at = Column(DateTime, nullable=True)
    visit_count = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    enrolled_from = Column(String(255), nullable=True)


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=False)
    embedding = Column(LargeBinary, nullable=False)  # float32 512D
    model = Column(String(50), nullable=False)
    quality = Column(Float, nullable=True)
    source_image = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=False)
    track_id = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    identity_state = Column(String(30), nullable=True)
    max_confidence = Column(Float, nullable=True)
    reid_embedding = Column(LargeBinary, nullable=True)

    __table_args__ = (Index("idx_tracks_cam", "camera_id", started_at.desc()),)


class Event(Base):
    """Typed event row. Mirrors backend.events.types.Event (the Pydantic contract)."""

    __tablename__ = "events"

    id = Column(String(36), primary_key=True)  # uuid4
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=False)
    type = Column(String(50), nullable=False)
    ts = Column(DateTime, nullable=False)
    severity = Column(String(20), nullable=False)
    track_id = Column(Integer, nullable=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    zone_id = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    bbox = Column(String, nullable=True)  # JSON-encoded [x1, y1, x2, y2]
    snapshot_path = Column(String(255), nullable=True)
    recording_id = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_events_ts", ts.desc()),
        Index("idx_events_type_ts", "type", ts.desc()),
        Index("idx_events_cam_ts", "camera_id", ts.desc()),
        Index("idx_events_person", "person_id", ts.desc()),
    )


class DetectionStat(Base):
    """Aggregated detections per camera per minute — never one row per detection."""

    __tablename__ = "detection_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=False)
    minute = Column(DateTime, nullable=False)
    detections = Column(Integer, nullable=False, default=0)
    unique_tracks = Column(Integer, nullable=False, default=0)
    avg_confidence = Column(Float, nullable=True)
    max_concurrent = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("idx_detstats_minute", "camera_id", minute.desc()),
        UniqueConstraint("camera_id", "minute", name="uq_detection_stats_camera_minute"),
    )


class Recording(Base):
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=False, server_default="cam1")
    filename = Column(String(255), nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_s = Column(Float, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    thumbnail_path = Column(String(255), nullable=True)
    trigger_event_id = Column(String(36), nullable=True)
    reason = Column(String(50), nullable=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=True)
    zone_id = Column(String(50), nullable=True)
    upload_state = Column(String(20), nullable=False, server_default="pending")
    upload_attempts = Column(Integer, nullable=False, server_default="0")
    drive_file_id = Column(String(100), nullable=True)
    local_expires_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("idx_recordings_cam", "camera_id", started_at.desc()),)


class Zone(Base):
    __tablename__ = "zones"

    id = Column(String(50), primary_key=True)
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=False, server_default="cam1")
    name = Column(String(100), nullable=False)
    # Nullable: zones created via the legacy upsert_zone() (backend/database.py)
    # only populate polygon_json, not this v2 column, until Zone editing moves to ZoneRepo.
    polygon = Column(JSON, nullable=True)
    kind = Column(String(30), nullable=True)
    schedule = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default="1")


class Line(Base):
    __tablename__ = "lines"

    id = Column(String(50), primary_key=True)
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=False, server_default="cam1")
    name = Column(String(100), nullable=False)
    start_x_frac = Column(Float, nullable=False)
    start_y_frac = Column(Float, nullable=False)
    end_x_frac = Column(Float, nullable=False)
    end_y_frac = Column(Float, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)


class Rule(Base):
    __tablename__ = "rules"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    definition = Column(JSON, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now)


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now)


class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(50), ForeignKey("cameras.id"), nullable=True)
    ts = Column(DateTime, nullable=False)
    metrics = Column(JSON, nullable=False)
