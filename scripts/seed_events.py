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
    persons: int = 0,   # 0 = comportamiento actual (person_id siempre NULL)
    zones: int = 0,     # 0 = comportamiento actual (zone_id siempre NULL)
) -> None:
    """Insert *n* synthetic rows into the `events` table, spread over *days* days.

    persons/zones (Fase 31, OPS-12/OPS-14): con sus defaults en 0 la salida es
    identica a la version previa (person_id/zone_id siempre NULL) — necesario para
    no romper el determinismo de la Fase 30. Cuando se piden, un 35% de las filas
    reciben person_id (1..persons) y un 60% zone_id ("zona-1".."zona-{zones}"),
    las mismas proporciones que uso 31-RESEARCH.md para medir los presupuestos de
    ocupacion por zona y conocidas/desconocidas: sin esto, los tests de la Fase 31
    medirian sobre datos vacios y pasarian por accidente.
    """
    rng = random.Random(seed)
    now = datetime.datetime.now()
    start = now - datetime.timedelta(days=days)
    span_seconds = int((now - start).total_seconds())

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        rows = []
        for _ in range(n):
            # Orden de consumo de rng preservado BYTE A BYTE respecto a la version
            # previa (type -> severity -> track_id -> confidence, el orden real en
            # que Python evaluaba los argumentos del rows.append de izquierda a
            # derecha): con persons=0, zones=0 los bloques `if persons`/`if zones`
            # no consumen rng y la secuencia queda identica a la de hoy.
            ts = start + datetime.timedelta(seconds=rng.randint(0, span_seconds))
            type_ = rng.choice(_TYPES)
            severity = rng.choice(_SEVERITIES)
            track_id = rng.randint(1, 500) if rng.random() < 0.7 else None
            person_id = None
            if persons:
                person_id = rng.randint(1, persons) if rng.random() < 0.35 else None
            zone_id = None
            if zones:
                zone_id = f"zona-{rng.randint(1, zones)}" if rng.random() < 0.60 else None
            confidence = round(rng.uniform(0.4, 0.99), 2) if rng.random() < 0.8 else None
            rows.append((
                str(uuid.uuid4()),
                camera_id,
                type_,
                ts.isoformat(sep=" "),
                severity,
                track_id,
                person_id,
                zone_id,
                confidence,
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
    parser.add_argument("--persons", type=int, default=0,
                        help="Numero de identidades distintas; 35%% de las filas reciben una")
    parser.add_argument("--zones", type=int, default=0,
                        help="Numero de zonas distintas (zona-1..zona-N); 60%% de las filas reciben una")
    args = parser.parse_args()
    seed_events(
        args.db_path, n=args.count, days=args.days, camera_id=args.camera_id,
        persons=args.persons, zones=args.zones,
    )
    print(f"Seeded {args.count} events into {args.db_path}")
