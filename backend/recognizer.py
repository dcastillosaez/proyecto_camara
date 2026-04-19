"""Persistent face recognition — identifies persons across sessions."""

from __future__ import annotations

import logging
import pickle
import sqlite3
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    import face_recognition as fr
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.warning("face_recognition not installed — person re-ID disabled. "
                   "Windows/Python 3.12: install a pre-built dlib wheel first, "
                   "then `pip install face-recognition`.")


class PersonRecognizer:
    """
    Detects faces inside person bounding-box crops, extracts 128-dim dlib
    embeddings, and matches them against a persistent SQLite store.

    Calling convention (from the RTSP capture thread):
      pid, name, is_new = recognizer.identify_or_register(frame, bbox, tid, frame_num)

    Recognition runs at most once every RECOG_INTERVAL frames per tracker_id,
    and stops retrying once a face has been successfully linked to that id.
    """

    TOLERANCE = 0.55        # euclidean distance threshold (lower = stricter)
    RECOG_INTERVAL = 30     # frames between attempts for unidentified tracker IDs

    def __init__(self, db_path: str = "data/persons.db") -> None:
        self._available = _AVAILABLE
        self._lock = threading.Lock()
        # tracker_id → (person_id, name)  — populated once face is matched
        self._cache: dict[int, tuple[int, str | None]] = {}
        # tracker_id → last frame number where recognition was attempted
        self._last_attempt: dict[int, int] = {}

        if not self._available:
            return

        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_db()

        self._person_ids: list[int] = []
        self._person_names: list[str | None] = []
        self._encodings: list[np.ndarray] = []
        self._load()

    @property
    def available(self) -> bool:
        return self._available

    def get_cached(self, tracker_id: int) -> tuple[int, str | None] | None:
        """Return (person_id, name) if this tracker_id is already identified."""
        return self._cache.get(tracker_id)

    def identify_or_register(
        self,
        frame_bgr: np.ndarray,
        bbox: tuple[int, int, int, int],
        tracker_id: int,
        frame_number: int,
    ) -> tuple[int | None, str | None, bool]:
        """
        Attempt face recognition for the person in *bbox*.

        Returns (person_id, name, is_new):
          - person_id=None  → no face detected, try again later
          - is_new=True     → first-ever sighting, just registered
          - is_new=False    → recognised an existing person
        """
        if not self._available:
            return None, None, False

        # Already identified this tracker ID — no need to re-run inference
        if tracker_id in self._cache:
            return None, None, False

        # Throttle attempts for unidentified IDs
        last = self._last_attempt.get(tracker_id, -(self.RECOG_INTERVAL + 1))
        if frame_number - last < self.RECOG_INTERVAL:
            return None, None, False
        self._last_attempt[tracker_id] = frame_number

        x1, y1, x2, y2 = bbox
        crop = frame_bgr[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if crop.size == 0:
            return None, None, False

        rgb = np.ascontiguousarray(crop[:, :, ::-1])  # BGR→RGB
        locs = fr.face_locations(rgb, model="hog")
        if not locs:
            return None, None, False

        encodings = fr.face_encodings(rgb, known_face_locations=locs)
        if not encodings:
            return None, None, False
        enc = encodings[0]

        with self._lock:
            if self._encodings:
                dists = fr.face_distance(self._encodings, enc)
                best = int(np.argmin(dists))
                if dists[best] <= self.TOLERANCE:
                    pid = self._person_ids[best]
                    name = self._person_names[best]
                    self._touch(pid)
                    self._cache[tracker_id] = (pid, name)
                    return pid, name, False

            pid = self._register(enc)
            self._cache[tracker_id] = (pid, None)
            return pid, None, True

    def enroll_named_face(self, image_bgr: np.ndarray, name: str) -> int | None:
        """Register (or rename) a person from *image_bgr* with *name*.

        Returns the person_id, or None if no face is detected in the image.
        """
        if not self._available:
            return None
        rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
        locs = fr.face_locations(rgb, model="hog")
        if not locs:
            return None
        encodings = fr.face_encodings(rgb, known_face_locations=locs)
        if not encodings:
            return None
        enc = encodings[0]

        with self._lock:
            if self._encodings:
                dists = fr.face_distance(self._encodings, enc)
                best = int(np.argmin(dists))
                if dists[best] <= self.TOLERANCE:
                    pid = self._person_ids[best]
                    self._person_names[best] = name
                    self._conn.execute("UPDATE persons SET name=? WHERE id=?", (name, pid))
                    self._conn.commit()
                    # Refresh cache entries for this person
                    for tid, (cached_pid, _) in list(self._cache.items()):
                        if cached_pid == pid:
                            self._cache[tid] = (pid, name)
                    return pid
            pid = self._register(enc)
            # Register gave us None name; update it now
            self._conn.execute("UPDATE persons SET name=? WHERE id=?", (name, pid))
            self._conn.commit()
            self._person_names[-1] = name
            return pid

    def list_persons(self) -> list[dict]:
        """Return all known persons ordered by most-recently seen."""
        if not self._available:
            return []
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, name, first_seen, last_seen, visit_count "
                "FROM persons ORDER BY last_seen DESC"
            )
            return [
                {
                    "id": r[0],
                    "name": r[1] or f"Person {r[0]}",
                    "first_seen": r[2],
                    "last_seen": r[3],
                    "visit_count": r[4],
                }
                for r in cur.fetchall()
            ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS persons (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT,
                encoding    BLOB NOT NULL,
                first_seen  TEXT DEFAULT (datetime('now')),
                last_seen   TEXT DEFAULT (datetime('now')),
                visit_count INTEGER DEFAULT 1
            );
        """)
        self._conn.commit()

    def _load(self) -> None:
        cur = self._conn.execute("SELECT id, name, encoding FROM persons")
        for pid, name, blob in cur.fetchall():
            self._person_ids.append(pid)
            self._person_names.append(name)
            self._encodings.append(pickle.loads(blob))
        logger.info("PersonRecognizer: loaded %d known persons", len(self._person_ids))

    def _register(self, encoding: np.ndarray) -> int:
        blob = pickle.dumps(encoding)
        cur = self._conn.execute(
            "INSERT INTO persons (encoding) VALUES (?)", (blob,)
        )
        self._conn.commit()
        pid = int(cur.lastrowid)
        self._person_ids.append(pid)
        self._person_names.append(None)
        self._encodings.append(encoding)
        logger.info("PersonRecognizer: new person registered id=%d", pid)
        return pid

    def _touch(self, person_id: int) -> None:
        self._conn.execute(
            "UPDATE persons SET last_seen=datetime('now'), visit_count=visit_count+1 "
            "WHERE id=?",
            (person_id,),
        )
        self._conn.commit()
