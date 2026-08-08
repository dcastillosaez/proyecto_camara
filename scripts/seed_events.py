"""Populate a v2 schema SQLite DB with synthetic events for perf/analytics testing.

Used by tests/test_repositories.py (query performance over 100k events) and
reusable in Phase 31 (analytics load testing).
"""

from __future__ import annotations

import argparse
import datetime
import json
import random
import sqlite3
import uuid

from backend.events.types import EventType, Severity

_TYPES = [t.value for t in EventType]
_SEVERITIES = [s.value for s in Severity]


def seed_events(
    db_path: str,
    n: int = 100_000,
    days: int = 30,
    camera_id: str = "cam1",
    seed: int = 42,
) -> None:
    """Insert *n* synthetic rows into the `events` table, spread over *days* days."""
    rng = random.Random(seed)
    now = datetime.datetime.now()
    start = now - datetime.timedelta(days=days)
    span_seconds = int((now - start).total_seconds())

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        rows = []
        for _ in range(n):
            ts = start + datetime.timedelta(seconds=rng.randint(0, span_seconds))
            rows.append((
                str(uuid.uuid4()),
                camera_id,
                rng.choice(_TYPES),
                ts.isoformat(sep=" "),
                rng.choice(_SEVERITIES),
                rng.randint(1, 500) if rng.random() < 0.7 else None,
                None,
                None,
                round(rng.uniform(0.4, 0.99), 2) if rng.random() < 0.8 else None,
                None,
                None,
                None,
                json.dumps({}),
            ))
        conn.executemany(
            "INSERT INTO events (id, camera_id, type, ts, severity, track_id, person_id, "
            "zone_id, confidence, bbox, snapshot_path, recording_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path")
    parser.add_argument("-n", "--count", type=int, default=100_000)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--camera-id", default="cam1")
    args = parser.parse_args()
    seed_events(args.db_path, n=args.count, days=args.days, camera_id=args.camera_id)
    print(f"Seeded {args.count} events into {args.db_path}")
