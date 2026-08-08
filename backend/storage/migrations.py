"""Idempotent migration from the v1 schema to the v2 schema (Phase 19).

Runs once, synchronously, before the async app takes over. Records progress in
``app_config['schema_version']`` so re-running is a no-op once complete, and copies
the database file to ``data/backups/`` before any destructive change.
"""

from __future__ import annotations

import datetime
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Callable

from sqlalchemy import Connection, Engine, text

from backend.storage import models

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


def _table_exists(conn: Connection, name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
    ).fetchone()
    return row is not None


def _column_names(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _get_schema_version(conn: Connection) -> int:
    if not _table_exists(conn, "app_config"):
        return 0
    row = conn.execute(text("SELECT value FROM app_config WHERE key='schema_version'")).fetchone()
    if not row or row[0] is None:
        return 0
    value = row[0]
    # SQLite NUMERIC affinity silently coerces a JSON-encoded bare int ("2") to a
    # real integer at storage time — handle both the coerced and the raw-text form.
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(json.loads(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _backup_db(engine: Engine) -> Path | None:
    """Copy the live DB file to data/backups/ before touching the schema."""
    db_path = engine.url.database
    if not db_path or db_path == ":memory:" or not Path(db_path).exists():
        return None
    backups_dir = Path(db_path).parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backups_dir / f"events-{ts}.db"
    shutil.copy2(db_path, backup_path)
    logger.info("Backed up %s -> %s", db_path, backup_path)
    return backup_path


def _add_missing_columns(conn: Connection, table: str, orm_model) -> None:
    """Add any column present on the v2 ORM model but missing from the live v1 table."""
    existing = _column_names(conn, table)
    for column in orm_model.__table__.columns:
        if column.name in existing:
            continue
        default_clause = " DEFAULT 'cam1'" if column.name == "camera_id" else ""
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column.name} {column.type}{default_clause}"))
        logger.info("Added column %s.%s", table, column.name)


def _ensure_columns(conn: Connection, table: str, columns: dict[str, str]) -> None:
    """Add each (name -> SQL type) column to *table* if it doesn't already exist."""
    existing = _column_names(conn, table)
    for name, sql_type in columns.items():
        if name in existing:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
        logger.info("Added legacy column %s.%s", table, name)


def _migrate_v1_to_v2(conn: Connection) -> None:
    # 1. The v1 "events" table (backend.database.CrossingEvent) collides with the
    #    new typed "events" table. Rename it out of the way first; it is never deleted.
    if _table_exists(conn, "events") and not _table_exists(conn, "crossing_events"):
        if "direction" in _column_names(conn, "events"):
            conn.execute(text("ALTER TABLE events RENAME TO crossing_events"))
            logger.info("Renamed legacy events table -> crossing_events")

    # 2. Create every v2 table that doesn't exist yet. Idempotent by nature.
    models.Base.metadata.create_all(conn)

    # 3. Extend pre-existing v1 tables with the new columns (nullable, camera_id defaulted).
    if _table_exists(conn, "zones"):
        _add_missing_columns(conn, "zones", models.Zone)
        # backend/database.py's legacy Zone ORM still owns zone CRUD and uses
        # polygon_json (not the v2 `polygon` JSON column) — guarantee it exists
        # even on a table create_all() just created fresh with only the v2 shape.
        _ensure_columns(conn, "zones", {"polygon_json": "TEXT", "created_at": "DATETIME"})
    if _table_exists(conn, "recordings"):
        _add_missing_columns(conn, "recordings", models.Recording)
        # backend/database.py's legacy Recording ORM (gdrive_id/upload_status/duration_secs)
        # still owns upload tracking — guarantee its columns too, even on a table that
        # create_all() just created fresh with only the v2 shape (no prior v1 table to extend).
        _ensure_columns(conn, "recordings", {
            "gdrive_id": "VARCHAR(100)",
            "upload_status": "VARCHAR(20) DEFAULT 'pending'",
            "duration_secs": "FLOAT",
            "created_at": "DATETIME",
        })

    # 4. Register the default camera.
    existing_cam = conn.execute(text("SELECT id FROM cameras WHERE id='cam1'")).fetchone()
    if existing_cam is None:
        conn.execute(
            text(
                "INSERT INTO cameras (id, name, enabled, created_at) "
                "VALUES ('cam1', 'Camara 1', 1, :now)"
            ),
            {"now": datetime.datetime.now().isoformat(sep=" ")},
        )

    # 5. Convert crossing_events rows into typed LINE_CROSSED events. Deterministic
    #    ids (uuid5) + INSERT OR IGNORE make this safe to re-run.
    if _table_exists(conn, "crossing_events"):
        rows = conn.execute(
            text("SELECT id, timestamp, direction, person_name, is_intrusion FROM crossing_events")
        ).fetchall()
        for row in rows:
            event_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"crossing_events:{row.id}"))
            payload: dict = {"direction": row.direction, "is_intrusion": bool(row.is_intrusion)}
            if row.person_name:
                payload["person_name"] = row.person_name
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO events (id, camera_id, type, ts, severity, payload) "
                    "VALUES (:id, 'cam1', 'LINE_CROSSED', :ts, 'info', :payload)"
                ),
                {"id": event_id, "ts": row.timestamp, "payload": json.dumps(payload)},
            )
        logger.info("Migrated %d crossing_events rows -> LINE_CROSSED events", len(rows))

    # 6. Record schema version.
    conn.execute(text("DELETE FROM app_config WHERE key='schema_version'"))
    conn.execute(
        text("INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', :v, :now)"),
        {"v": json.dumps(SCHEMA_VERSION), "now": datetime.datetime.now().isoformat(sep=" ")},
    )


MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    (2, "esquema v2 completo", _migrate_v1_to_v2),
]


def run_migrations(engine: Engine) -> None:
    """Bring the database up to SCHEMA_VERSION. No-op if already current."""
    with engine.connect() as conn:
        current = _get_schema_version(conn)
    if current >= SCHEMA_VERSION:
        return

    _backup_db(engine)

    with engine.begin() as conn:
        for target_version, name, migration_fn in MIGRATIONS:
            if current >= target_version:
                continue
            logger.info("Running migration -> v%s: %s", target_version, name)
            migration_fn(conn)
