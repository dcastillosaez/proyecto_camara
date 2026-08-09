"""One-time migration: legacy pickle embedding blobs -> raw numpy float64 bytes.

Run once before removing the pickle fallback from backend/recognizer.py.
Idempotent: a second run reports 0 converted and exits 0. Makes a timestamped
backup of the database before writing anything. Rows whose blob cannot be
converted are left untouched and reported; the script then exits non-zero.

Usage:
    .venv/Scripts/python.exe scripts/migrate_embeddings.py [data/persons.db]
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

_NUMPY_SIZE = 128 * 8  # 128 float64 values = 1024 bytes
_PICKLE_MAGIC = (b"\x80\x03", b"\x80\x04", b"\x80\x05")

_TABLES = [
    ("persons", "id", "encoding"),
    ("face_encodings", "id", "encoding"),
]


def _is_numpy_blob(blob: bytes) -> bool:
    return len(blob) == _NUMPY_SIZE


def _blob_to_numpy_bytes(blob: bytes) -> bytes:
    """Convert a legacy pickle blob to raw numpy float64 bytes. Raises on failure."""
    import pickle  # noqa: PLC0415 — only ever imported here, for the one-time migration
    import numpy as np

    enc = pickle.loads(blob)  # noqa: S301 — trusted local file, one-time migration path
    arr = np.array(enc, dtype=np.float64)
    return arr.tobytes()


def _backup(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def migrate(db_path: str) -> int:
    """Migrate every legacy pickle blob in *db_path* to raw numpy bytes.

    Returns the process exit code: 0 on full success (including "nothing to do"),
    1 if any blob could not be converted.
    """
    path = Path(db_path)
    if not path.exists():
        print(f"Base de datos no encontrada: {path}")
        return 1

    total = 0
    already_numpy = 0
    converted = 0
    failed: list[tuple[str, int]] = []

    conn = sqlite3.connect(str(path))
    try:
        pending: list[tuple[str, str, int, bytes]] = []
        for table, id_col, blob_col in _TABLES:
            cur = conn.execute(f"SELECT {id_col}, {blob_col} FROM {table}")
            for row_id, blob in cur.fetchall():
                total += 1
                if _is_numpy_blob(blob):
                    already_numpy += 1
                    continue
                pending.append((table, id_col, row_id, blob))

        if not pending:
            print(_report(total, already_numpy, converted, failed, backup=None))
            return 0

        backup_path = _backup(path)

        for table, id_col, row_id, blob in pending:
            try:
                new_blob = _blob_to_numpy_bytes(blob)
            except Exception as exc:  # noqa: BLE001 — any failure means "leave the row alone"
                failed.append((table, row_id))
                print(f"  FALLO {table}.{id_col}={row_id}: {exc}")
                continue
            conn.execute(f"UPDATE {table} SET encoding=? WHERE {id_col}=?", (new_blob, row_id))
            converted += 1

        conn.commit()
        print(_report(total, already_numpy, converted, failed, backup=backup_path))
        return 1 if failed else 0
    finally:
        conn.close()


def _report(
    total: int, already_numpy: int, converted: int,
    failed: list[tuple[str, int]], backup: Path | None,
) -> str:
    lines = [
        f"Blobs totales:        {total}",
        f"Ya en formato numpy:  {already_numpy}",
        f"Convertidos:          {converted}",
        f"Fallidos:             {len(failed)}",
    ]
    if backup is not None:
        lines.append(f"Backup:  {backup}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", nargs="?", default="data/persons.db")
    args = parser.parse_args()
    sys.exit(migrate(args.db_path))
