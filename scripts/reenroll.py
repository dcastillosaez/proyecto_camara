"""One-time migration: rebuild data/persons.db from data/gallery/ using ArcFace.

dlib (128D) and ArcFace (512D) embeddings are not mathematically convertible
— there is no transformation from one space to the other. Re-enrollment
from the gallery captures already saved by the live pipeline (Fase 9) is
the only supported path (23-CONTEXT.md).

Backs up the existing database before touching anything (same convention
as scripts/migrate_embeddings.py). Preserves the original person_id for
each gallery directory and any existing name, so historical events/
recordings in data/events.db (which reference person_id by plain integer,
no cross-database foreign key) keep pointing at the right identity.

Usage (run as a module so `backend` resolves — same convention as
scripts/seed_events.py and scripts/generate_initial_rules.py):
    .venv/Scripts/python.exe -m scripts.reenroll [--gallery-dir data/gallery] [--db-path data/persons.db]
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

from backend.perception.face.engine import FaceEngine
from backend.perception.face.quality import FaceQualityAssessor
from backend.recognizer import PersonRecognizer

_EMBEDDING_DTYPE = np.float32


def _backup(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _read_existing_names(db_path: Path) -> dict[int, str | None]:
    """id -> name from the current (pre-migration) database, if any."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    try:
        return dict(conn.execute("SELECT id, name FROM persons").fetchall())
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE persons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT,
            encoding    BLOB NOT NULL,
            first_seen  TEXT DEFAULT (datetime('now')),
            last_seen   TEXT DEFAULT (datetime('now')),
            visit_count INTEGER DEFAULT 1
        );
        CREATE TABLE face_encodings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id  INTEGER NOT NULL REFERENCES persons(id),
            encoding   BLOB NOT NULL,
            added_at   TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _best_samples(
    engine: FaceEngine, quality: FaceQualityAssessor, image_paths: list[Path],
) -> list[np.ndarray]:
    """Detect + quality-gate + embed each image, best detector confidence first."""
    scored: list[tuple[float, np.ndarray]] = []
    for path in image_paths:
        img = cv2.imread(str(path))
        if img is None:
            continue
        candidates = engine.detect(img)
        if not candidates:
            continue
        cand = max(candidates, key=lambda c: c.det_score)
        x1, y1, x2, y2 = cand.bbox
        face_crop = img[max(0, y1):y2, max(0, x1):x2]
        if face_crop.size == 0:
            continue
        local_kps = cand.kps - np.array([x1, y1], dtype=cand.kps.dtype)
        if not quality.assess(face_crop, local_kps).passed:
            continue
        emb = engine.embed(img, cand)
        if emb is None:
            continue
        scored.append((cand.det_score, emb))
    scored.sort(key=lambda t: -t[0])
    return [emb for _, emb in scored[: PersonRecognizer.MAX_EMBEDDINGS_PER_PERSON]]


def reenroll(gallery_dir: str, db_path: str) -> int:
    """Rebuild *db_path* from *gallery_dir*. Returns the process exit code:
    0 if every named person migrated (anonymous failures are tolerated),
    1 on a hard error or if a NAMED person could not be migrated."""
    gallery = Path(gallery_dir)
    db = Path(db_path)

    if not gallery.exists():
        print(f"Directorio de galeria no encontrado: {gallery}")
        return 1

    engine = FaceEngine()
    if not engine.available:
        print("FaceEngine no disponible — insightface no instalado o el modelo no cargo")
        return 1
    quality = FaceQualityAssessor()

    existing_names = _read_existing_names(db)
    backup_path = _backup(db)

    person_dirs = sorted((d for d in gallery.iterdir() if d.is_dir()), key=lambda d: d.name)
    migrated: list[int] = []
    failed: list[int] = []

    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(str(db))
    _init_schema(conn)

    try:
        for person_dir in person_dirs:
            try:
                person_id = int(person_dir.name)
            except ValueError:
                continue
            images = sorted(person_dir.glob("*.jpg"))
            samples = _best_samples(engine, quality, images)
            if not samples:
                failed.append(person_id)
                continue
            name = existing_names.get(person_id)
            conn.execute(
                "INSERT INTO persons (id, name, encoding) VALUES (?, ?, ?)",
                (person_id, name, samples[0].astype(_EMBEDDING_DTYPE).tobytes()),
            )
            for extra in samples[1:]:
                conn.execute(
                    "INSERT INTO face_encodings (person_id, encoding) VALUES (?, ?)",
                    (person_id, extra.astype(_EMBEDDING_DTYPE).tobytes()),
                )
            migrated.append(person_id)
        conn.commit()
    finally:
        conn.close()

    named_failed = [pid for pid in failed if existing_names.get(pid)]

    print(f"Personas en galeria:      {len(person_dirs)}")
    print(f"Migradas:                 {len(migrated)}")
    print(f"Sin imagen utilizable:    {len(failed)}")
    if failed:
        print(f"  IDs sin migrar: {failed}")
    if named_failed:
        print(f"  ADVERTENCIA: {len(named_failed)} persona(s) CON NOMBRE no migradas: {named_failed}")
    if backup_path is not None:
        print(f"Backup: {backup_path}")

    return 1 if named_failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gallery-dir", default="data/gallery")
    parser.add_argument("--db-path", default="data/persons.db")
    args = parser.parse_args()
    sys.exit(reenroll(args.gallery_dir, args.db_path))
