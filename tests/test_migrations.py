"""Tests for backend.storage.migrations — idempotent v1 -> v2 migration."""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import create_engine, text

import backend.database as db_v1
from backend.storage.migrations import SCHEMA_VERSION, run_migrations


def make_v1_db(path, n_crossings=3, with_zone=True, with_recording=True):
    """Build a synthetic v1-schema DB.

    zones/recordings still match backend.database's current ORM (unchanged by
    the v2 migration beyond added columns), but the v1 "events" (crossing
    events) table no longer has a live ORM class post-Task-4 — database.py
    now delegates that domain to EventRepo — so it's declared here as raw DDL,
    matching the schema backend.database.CrossingEvent used to define.
    """
    engine = create_engine(f"sqlite:///{path}")
    db_v1.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp DATETIME NOT NULL, "
            "direction VARCHAR(3) NOT NULL, "
            "person_name VARCHAR(100), "
            "is_intrusion BOOLEAN NOT NULL DEFAULT 0)"
        ))
        now = datetime.datetime(2026, 4, 16, 18, 30, 0)
        for i in range(n_crossings):
            conn.execute(
                text(
                    "INSERT INTO events (timestamp, direction, person_name, is_intrusion) "
                    "VALUES (:ts, :dir, :name, :intr)"
                ),
                {
                    "ts": (now + datetime.timedelta(minutes=i)).isoformat(sep=" "),
                    "dir": "in" if i % 2 == 0 else "out",
                    "name": "Juan" if i == 0 else None,
                    "intr": 1 if i == 1 else 0,
                },
            )
        if with_zone:
            conn.execute(
                text(
                    "INSERT INTO zones (id, name, polygon_json, enabled, created_at) "
                    "VALUES ('z1', 'Jardin', '[[0,0],[1,1]]', 1, :now)"
                ),
                {"now": now.isoformat(sep=" ")},
            )
        if with_recording:
            conn.execute(
                text(
                    "INSERT INTO recordings (filename, upload_status, created_at, duration_secs) "
                    "VALUES ('clip1.mp4', 'uploaded', :now, 12.5)"
                ),
                {"now": now.isoformat(sep=" ")},
            )
    engine.dispose()


def _schema_version(engine) -> int:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT value FROM app_config WHERE key='schema_version'")).fetchone()
    if not row:
        return 0
    value = row[0]
    return int(value) if isinstance(value, (int, float)) else json.loads(value)


def TEST_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)
    with engine.connect() as conn:
        count_after_1 = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()

    run_migrations(engine)
    with engine.connect() as conn:
        count_after_2 = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()
        tables_after_2 = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }

    assert count_after_1 == count_after_2
    assert {"events", "crossing_events", "cameras", "persons", "rules"}.issubset(tables_after_2)


def TEST_backup_created_before_destructive(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path, n_crossings=5)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    backups_dir = tmp_path / "backups"
    assert backups_dir.exists()
    backup_files = list(backups_dir.glob("events-*.db"))
    assert len(backup_files) == 1

    backup_engine = create_engine(f"sqlite:///{backup_files[0]}")
    with backup_engine.connect() as conn:
        # The backup is a snapshot of the pre-migration file — its "events" table
        # still has the v1 CrossingEvent shape at the time of copy.
        count = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()
    assert count == 5
    backup_engine.dispose()


def TEST_crossing_events_preserved(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path, n_crossings=7)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        crossing_count = conn.execute(text("SELECT COUNT(*) FROM crossing_events")).scalar()
        line_crossed_count = conn.execute(
            text("SELECT COUNT(*) FROM events WHERE type='LINE_CROSSED'")
        ).scalar()

    assert crossing_count == 7
    assert line_crossed_count == 7


def TEST_direction_moved_to_payload(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path, n_crossings=2)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT payload FROM events WHERE type='LINE_CROSSED' ORDER BY ts")
        ).fetchall()

    payloads = [json.loads(r[0]) for r in rows]
    assert payloads[0]["direction"] == "in"
    assert payloads[1]["direction"] == "out"


def TEST_camera_id_defaults_to_cam1(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path, n_crossings=1)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        event_cams = {r[0] for r in conn.execute(text("SELECT camera_id FROM events"))}
        zone_cams = {r[0] for r in conn.execute(text("SELECT camera_id FROM zones"))}
        recording_cams = {r[0] for r in conn.execute(text("SELECT camera_id FROM recordings"))}

    assert event_cams == {"cam1"}
    assert zone_cams == {"cam1"}
    assert recording_cams == {"cam1"}


def TEST_schema_version_recorded(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_migration_on_empty_db(tmp_path):
    db_path = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)  # must not raise

    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"events", "cameras", "persons", "rules", "detection_stats"}.issubset(tables)
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_fresh_db_supports_legacy_zone_and_recording_columns(tmp_path):
    """A brand-new DB (no prior v1 data) must still satisfy backend.database's
    legacy Zone/Recording ORM columns (polygon_json, created_at, gdrive_id,
    upload_status, duration_secs) — create_all() alone only produces the v2
    shape, since there's no pre-existing v1 table to extend."""
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        zone_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(zones)"))}
        recording_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(recordings)"))}

    assert {"polygon_json", "created_at"}.issubset(zone_cols)
    assert {"gdrive_id", "upload_status", "duration_secs", "created_at"}.issubset(recording_cols)


def TEST_zones_and_recordings_preserved(tmp_path):
    db_path = tmp_path / "v1.db"
    make_v1_db(db_path, with_zone=True, with_recording=True)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        zone = conn.execute(text("SELECT id, name FROM zones WHERE id='z1'")).fetchone()
        recording = conn.execute(text("SELECT filename FROM recordings WHERE filename='clip1.mp4'")).fetchone()

    assert zone is not None and zone[1] == "Jardin"
    assert recording is not None
