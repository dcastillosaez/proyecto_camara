"""Tests for backend.storage.migrations — idempotent v1 -> v2 migration."""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import create_engine, text

import backend.database as db_v1
from backend.storage import models
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


def make_v2_db(path):
    """Build a DB in the v2 state: full v2 schema, schema_version=2, and WITHOUT
    the Fase 30 timeline index.

    The DROP is deliberate: create_all() reads today's __table_args__, which already
    declares idx_events_ts_id, so a plain create_all() would hand back a v3-shaped
    database and the migration test would prove nothing. A real v2 file on disk was
    created before that Index() existed.
    """
    engine = create_engine(f"sqlite:///{path}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_events_ts_id"))
        conn.execute(text("DELETE FROM app_config WHERE key='schema_version'"))
        conn.execute(
            text("INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', '2', :now)"),
            {"now": datetime.datetime.now().isoformat(sep=" ")},
        )
    engine.dispose()


def make_v3_db(path):
    """Build a DB in the v3 state: full v2 schema (which already includes the
    Fase 30 timeline index), schema_version=3, and WITHOUT the Fase 31 analytics
    index.

    The DROP is deliberate, same reasoning as make_v2_db(): create_all() already
    declares idx_events_analytics via today's __table_args__, so the test needs a
    starting point where it's absent to prove the migration creates it.
    """
    engine = create_engine(f"sqlite:///{path}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_events_analytics"))
        conn.execute(text("DELETE FROM app_config WHERE key='schema_version'"))
        conn.execute(
            text("INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', '3', :now)"),
            {"now": datetime.datetime.now().isoformat(sep=" ")},
        )
    engine.dispose()


def _index_names(engine, name: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"), {"n": name}
        ).fetchall()
    return [r[0] for r in rows]


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


# ─── v2 -> v3: indice compuesto de la linea temporal (Fase 30, OPS-09) ───────


def TEST_migration_v3_creates_timeline_index(tmp_path):
    db_path = tmp_path / "v2.db"
    make_v2_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    assert _index_names(engine, "idx_events_ts_id") == []  # punto de partida real

    run_migrations(engine)

    assert _index_names(engine, "idx_events_ts_id") == ["idx_events_ts_id"]
    # run_migrations() siempre encadena hasta SCHEMA_VERSION, no se detiene en el
    # escalon v3 (Fase 31 subio SCHEMA_VERSION a 4) — mismo patron dinamico que
    # TEST_schema_version_recorded, no un literal que quede obsoleto en cada fase.
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_migration_v3_is_idempotent(tmp_path):
    db_path = tmp_path / "v2.db"
    make_v2_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)
    run_migrations(engine)  # must not raise

    assert _index_names(engine, "idx_events_ts_id") == ["idx_events_ts_id"]
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_fresh_db_has_timeline_index(tmp_path):
    """Una base nueva lo hereda de Event.__table_args__, sin pasar por la migracion."""
    db_path = tmp_path / "fresh_v3.db"
    engine = create_engine(f"sqlite:///{db_path}")
    models.Base.metadata.create_all(engine)

    assert _index_names(engine, "idx_events_ts_id") == ["idx_events_ts_id"]


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


# ─── v3 -> v4: indice compuesto de analitica (Fase 31, OPS-12/OPS-14) ────────


def TEST_migration_v4_creates_analytics_index(tmp_path):
    db_path = tmp_path / "v3.db"
    make_v3_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    assert _index_names(engine, "idx_events_analytics") == []  # punto de partida real

    run_migrations(engine)

    assert _index_names(engine, "idx_events_analytics") == ["idx_events_analytics"]
    # run_migrations() siempre encadena hasta SCHEMA_VERSION, no se detiene en el
    # escalon v4 (Fase 33 subio SCHEMA_VERSION a 5) — mismo patron dinamico que
    # TEST_migration_v3_creates_timeline_index.
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_migration_v4_is_idempotent(tmp_path):
    db_path = tmp_path / "v3.db"
    make_v3_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)
    run_migrations(engine)  # must not raise

    assert _index_names(engine, "idx_events_analytics") == ["idx_events_analytics"]
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_fresh_db_has_analytics_index(tmp_path):
    """Una base nueva lo hereda de Event.__table_args__, sin pasar por la migracion."""
    db_path = tmp_path / "fresh_v4.db"
    engine = create_engine(f"sqlite:///{db_path}")
    models.Base.metadata.create_all(engine)

    assert _index_names(engine, "idx_events_analytics") == ["idx_events_analytics"]


# ─── v4 -> v5: backfill zones.polygon + siembra de linea de conteo (Fase 33) ──


def make_v4_db_with_legacy_zone(path, seed_line=False, prepopulated_zone_polygon=None):
    """Clona make_v3_db pero deja la BD en estado v4 (indice de analitica ya
    presente via create_all) y anade una zona v1 legacy (`polygon_json` poblado,
    `polygon` NULL) para probar el backfill de la migracion v4->v5.

    `prepopulated_zone_polygon`: si se pasa, inserta ADEMAS una segunda zona con
    `polygon` ya poblado (editada por el editor v2 nuevo) para probar que la
    migracion no la pisa. `seed_line`: si True, inserta una fila en `lines` para
    'cam1' de antemano, para probar que la migracion no duplica el seed.
    """
    engine = create_engine(f"sqlite:///{path}")
    models.Base.metadata.create_all(engine)
    now = datetime.datetime(2026, 4, 16, 18, 30, 0)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_config WHERE key='schema_version'"))
        conn.execute(
            text("INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', '4', :now)"),
            {"now": now.isoformat(sep=" ")},
        )
        # create_all() solo produce la forma v2 pura — polygon_json es la columna
        # legacy que _migrate_v1_to_v2 anade via _ensure_columns() a una BD que SI
        # vino de un v1 real; una BD v4 sintetica real siempre la tiene ya (arrastrada
        # desde v1), asi que se simula aqui explicitamente.
        conn.execute(text("ALTER TABLE zones ADD COLUMN polygon_json TEXT"))
        conn.execute(text("ALTER TABLE zones ADD COLUMN created_at DATETIME"))
        conn.execute(
            text(
                "INSERT INTO zones (id, camera_id, name, polygon_json, polygon, "
                "enabled, kind, created_at) VALUES "
                "('z-legacy', 'cam1', 'Legacy zone', :pj, NULL, 1, NULL, :now)"
            ),
            {"pj": json.dumps([[0, 0], [1, 0], [1, 1]]), "now": now.isoformat(sep=" ")},
        )
        if prepopulated_zone_polygon is not None:
            conn.execute(
                text(
                    "INSERT INTO zones (id, camera_id, name, polygon_json, polygon, "
                    "enabled, kind, created_at) VALUES "
                    "('z-v2', 'cam1', 'Zona v2', NULL, :p, 1, NULL, :now)"
                ),
                {"p": json.dumps(prepopulated_zone_polygon), "now": now.isoformat(sep=" ")},
            )
        if seed_line:
            conn.execute(
                text(
                    "INSERT INTO lines (id, camera_id, name, start_x_frac, "
                    "start_y_frac, end_x_frac, end_y_frac, enabled) VALUES "
                    "('linea-existente', 'cam1', 'Ya configurada', 0.1, 0.2, 0.9, 0.8, 1)"
                )
            )
    engine.dispose()


def TEST_migration_v5_backfills_polygon_from_polygon_json(tmp_path):
    db_path = tmp_path / "v4.db"
    make_v4_db_with_legacy_zone(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        polygon = conn.execute(
            text("SELECT polygon FROM zones WHERE id='z-legacy'")
        ).scalar()

    assert json.loads(polygon) == [[0, 0], [1, 0], [1, 1]]
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_migration_v5_does_not_overwrite_existing_polygon(tmp_path):
    db_path = tmp_path / "v4.db"
    make_v4_db_with_legacy_zone(db_path, prepopulated_zone_polygon=[[9, 9], [8, 8]])
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        polygon = conn.execute(
            text("SELECT polygon FROM zones WHERE id='z-v2'")
        ).scalar()

    assert json.loads(polygon) == [[9, 9], [8, 8]]


def TEST_migration_v5_seeds_default_line_when_lines_empty(tmp_path):
    # line_start_x_frac/etc se retiraron de Settings en el Plan 33-08 (D-01/D-02):
    # la migracion los lee ahora directamente de env/.env (_legacy_line_frac_settings),
    # no del modelo principal — comparamos contra los mismos defaults hardcodeados.
    db_path = tmp_path / "v4.db"
    make_v4_db_with_legacy_zone(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT camera_id, start_x_frac, start_y_frac, end_x_frac, end_y_frac "
                "FROM lines WHERE camera_id='cam1'"
            )
        ).fetchall()

    assert len(rows) == 1
    assert rows[0] == ("cam1", 0.0, 0.5, 1.0, 0.5)


def TEST_migration_v5_does_not_duplicate_existing_line(tmp_path):
    db_path = tmp_path / "v4.db"
    make_v4_db_with_legacy_zone(db_path, seed_line=True)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM lines WHERE camera_id='cam1'")
        ).scalar()

    assert count == 1


def TEST_migration_v5_is_idempotent(tmp_path):
    db_path = tmp_path / "v4.db"
    make_v4_db_with_legacy_zone(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)
    run_migrations(engine)  # must not raise

    with engine.connect() as conn:
        line_count = conn.execute(
            text("SELECT COUNT(*) FROM lines WHERE camera_id='cam1'")
        ).scalar()
        polygon = conn.execute(
            text("SELECT polygon FROM zones WHERE id='z-legacy'")
        ).scalar()

    assert line_count == 1
    assert json.loads(polygon) == [[0, 0], [1, 0], [1, 1]]
    assert _schema_version(engine) == SCHEMA_VERSION


def make_v5_db_with_nullable_system_metrics(path):
    """Base en el estado v5: system_metrics.camera_id todavia NULLABLE (Fase 35).

    DDL a mano (no via el modelo ORM, que ya declara NOT NULL) para reproducir
    exactamente el esquema que una instalacion real llegaria a tener en v5 --
    mismo criterio que make_v1_db con la tabla events legacy.
    """
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE cameras (id VARCHAR(50) PRIMARY KEY, name VARCHAR(100), "
            "enabled BOOLEAN, created_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO cameras (id, name, enabled, created_at) "
            "VALUES ('cam1', 'Camara 1', 1, :now)"
        ), {"now": datetime.datetime(2026, 4, 16).isoformat(sep=" ")})
        conn.execute(text(
            "CREATE TABLE system_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "camera_id VARCHAR(50) REFERENCES cameras(id), "
            "ts DATETIME NOT NULL, metrics JSON NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO system_metrics (camera_id, ts, metrics) VALUES (NULL, :ts, :m)"
        ), {"ts": datetime.datetime(2026, 4, 16, 10, 0, 0).isoformat(sep=" "), "m": '{"cpu": 12.5}'})
        conn.execute(text(
            "INSERT INTO system_metrics (camera_id, ts, metrics) VALUES ('cam1', :ts, :m)"
        ), {"ts": datetime.datetime(2026, 4, 16, 10, 1, 0).isoformat(sep=" "), "m": '{"cpu": 13.0}'})
        conn.execute(text(
            "CREATE TABLE app_config (key VARCHAR(100) PRIMARY KEY, value JSON, updated_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO app_config (key, value, updated_at) VALUES ('schema_version', '5', :now)"
        ), {"now": datetime.datetime(2026, 4, 16).isoformat(sep=" ")})
    engine.dispose()


def TEST_migration_v6_backfills_null_camera_id_in_system_metrics(tmp_path):
    db_path = tmp_path / "v5.db"
    make_v5_db_with_nullable_system_metrics(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        cams = [r[0] for r in conn.execute(text("SELECT camera_id FROM system_metrics ORDER BY id"))]
    assert cams == ["cam1", "cam1"]
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_migration_v6_enforces_not_null_on_system_metrics(tmp_path):
    db_path = tmp_path / "v5.db"
    make_v5_db_with_nullable_system_metrics(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO system_metrics (camera_id, ts, metrics) VALUES (NULL, :ts, :m)"
            ), {"ts": datetime.datetime(2026, 4, 16, 10, 2, 0).isoformat(sep=" "), "m": "{}"})


def TEST_migration_v6_preserves_row_count_and_metrics(tmp_path):
    db_path = tmp_path / "v5.db"
    make_v5_db_with_nullable_system_metrics(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM system_metrics")).scalar()
        metrics = [
            json.loads(r[0])
            for r in conn.execute(text("SELECT metrics FROM system_metrics ORDER BY id"))
        ]
    assert count == 2
    assert metrics == [{"cpu": 12.5}, {"cpu": 13.0}]


def TEST_migration_v6_is_idempotent(tmp_path):
    db_path = tmp_path / "v5.db"
    make_v5_db_with_nullable_system_metrics(db_path)
    engine = create_engine(f"sqlite:///{db_path}")

    run_migrations(engine)
    run_migrations(engine)  # must not raise

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM system_metrics")).scalar()
    assert count == 2
    assert _schema_version(engine) == SCHEMA_VERSION


def TEST_migration_v6_on_db_without_system_metrics_table(tmp_path):
    """Una base v5 sin la tabla (edicion manual, o create_all() futuro que la retire)
    no debe romper la cadena de migraciones -- solo avanzar la version."""
    db_path = tmp_path / "v5.db"
    make_v5_db_with_nullable_system_metrics(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE system_metrics"))

    run_migrations(engine)  # must not raise

    assert _schema_version(engine) == SCHEMA_VERSION
