"""Persistent face recognition — identifies persons across sessions."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import Counter, deque
from pathlib import Path

import cv2
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

    Multiple embeddings per person are supported: each call to enroll_named_face
    for an already-known person adds a new sample, improving match accuracy
    across different lighting conditions, angles and clothing.

    Calling convention (from the RTSP capture thread):
      pid, name, is_new = recognizer.identify_or_register(frame, bbox, tid, frame_num)

    Recognition runs at most once every RECOG_INTERVAL frames per tracker_id,
    and stops retrying once a face has been successfully linked to that id.
    """

    TOLERANCE = 0.55        # euclidean distance threshold (lower = stricter)
    MATCH_MARGIN = 0.10     # min distance gap over the runner-up person (ratio test)
    RECOG_INTERVAL = 30     # frames between attempts for unidentified tracker IDs
    REVERIFY_INTERVAL = 300  # frames between identity re-checks for identified tracks
    VOTE_WINDOW = 5         # majority vote over the last N decisive matches per track
    MAX_EMBEDDINGS_PER_PERSON = 20  # cap to keep matching fast
    VISIT_GAP_MINUTES = 5   # min gap since last_seen for a match to count as a new visit

    # Quality gates for automatic registration (identify_or_register only —
    # manual enrollment via enroll_named_face bypasses them on purpose):
    MIN_FACE_SIZE = 60          # px — embeddings from smaller faces are unreliable
    BLUR_THRESHOLD = 60.0       # min Laplacian variance of the face crop
    NEW_PERSON_CONSENSUS = 3    # consistent samples required to register a new person
    CONSENSUS_TOLERANCE = 0.40  # max distance between samples in the pending buffer
    # MEJORAS.md punto 9.1: below this crop side (px), HOG runs with an extra
    # upsample pass — more detections on small/distant persons, at CPU cost
    # paid only for small crops (the recognition worker absorbs it).
    SMALL_CROP_PX = 240

    def __init__(self, db_path: str = "data/persons.db") -> None:
        self._available = _AVAILABLE
        self._lock = threading.Lock()
        # tracker_id → (person_id, name)  — populated once face is matched
        self._cache: dict[int, tuple[int, str | None]] = {}
        # tracker_id → last frame number where recognition was attempted
        self._last_attempt: dict[int, int] = {}
        # tracker_id → embeddings pending consensus before registering a new person
        self._pending: dict[int, list[np.ndarray]] = {}
        # tracker_id → last VOTE_WINDOW matched person_ids (identity majority vote)
        self._votes: dict[int, deque[int]] = {}

        if not self._available:
            return

        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_db()

        # Flat parallel lists — one entry per (person, embedding) pair.
        # A person with N embeddings appears N times in these lists.
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

    def should_attempt(self, tracker_id: int, frame_number: int) -> bool:
        """
        Cheap gate for the capture thread (MEJORAS.md punto 10): return True
        when a recognition attempt is due for this track — RECOG_INTERVAL
        frames for unidentified tracks, REVERIFY_INTERVAL for identified
        ones. A True result marks the attempt, so the caller is expected to
        follow through (enqueue the crop for the recognition worker).
        """
        if not self._available:
            return False
        with self._lock:
            cached = self._cache.get(tracker_id)
            interval = self.REVERIFY_INTERVAL if cached is not None else self.RECOG_INTERVAL
            last = self._last_attempt.get(tracker_id, -(interval + 1))
            if frame_number - last < interval:
                return False
            self._last_attempt[tracker_id] = frame_number
            return True

    def identify_or_register(
        self,
        frame_bgr: np.ndarray,
        bbox: tuple[int, int, int, int],
        tracker_id: int,
        frame_number: int,
    ) -> tuple[int | None, str | None, bool]:
        """
        Attempt face recognition for the person in *bbox*.

        Convenience wrapper: gating (``should_attempt``) + crop + heavy work
        (``process_crop``). The live pipeline calls the two halves from
        different threads instead — the capture thread gates and enqueues,
        a dedicated worker runs ``process_crop`` (MEJORAS.md punto 10).
        """
        if not self.should_attempt(tracker_id, frame_number):
            return None, None, False
        x1, y1, x2, y2 = bbox
        crop = frame_bgr[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if crop.size == 0:
            return None, None, False
        return self.process_crop(crop, tracker_id)

    def process_crop(
        self, crop_bgr: np.ndarray, tracker_id: int
    ) -> tuple[int | None, str | None, bool]:
        """
        Run face detection + matching on a person crop (the expensive dlib
        path, 100-500 ms on CPU). Safe to call from a worker thread.

        Returns (person_id, name, is_new):
          - person_id=None  → no usable face yet (none detected, failed a
                              quality gate, or still gathering consensus
                              samples) — try again later
          - is_new=True     → consensus reached, person just registered
          - is_new=False    → recognised an existing person

        Quality gates (MEJORAS.md punto 4): faces smaller than MIN_FACE_SIZE
        or blurrier than BLUR_THRESHOLD are discarded, and a NEW person is
        only registered after NEW_PERSON_CONSENSUS mutually-consistent
        samples from distinct frames of the same track. Matching against
        already-known persons needs a single good sample, as before.

        Identified tracks are re-verified every REVERIFY_INTERVAL frames
        (MEJORAS.md punto 8): each decisive match casts a vote, and the
        majority of the last VOTE_WINDOW votes wins — a wrong first match
        no longer sticks to the track forever. Callers get the corrected
        identity through the normal return value.
        """
        if not self._available or crop_bgr.size == 0:
            return None, None, False
        crop = crop_bgr

        rgb = np.ascontiguousarray(crop[:, :, ::-1])
        upsample = 2 if min(crop.shape[:2]) < self.SMALL_CROP_PX else 1
        locs = fr.face_locations(
            rgb, number_of_times_to_upsample=upsample, model="hog"
        )
        if not locs:
            return None, None, False

        # Gate 1 — minimum face size
        locs = [
            loc for loc in locs
            if (loc[2] - loc[0]) >= self.MIN_FACE_SIZE
            and (loc[1] - loc[3]) >= self.MIN_FACE_SIZE
        ]
        if not locs:
            return None, None, False
        top, right, bottom, left = self._select_face(locs, crop.shape[0])

        # Gate 2 — blur filter on the face region
        gray = cv2.cvtColor(rgb[top:bottom, left:right], cv2.COLOR_RGB2GRAY)
        if cv2.Laplacian(gray, cv2.CV_64F).var() < self.BLUR_THRESHOLD:
            return None, None, False

        encodings = fr.face_encodings(
            rgb, known_face_locations=[(top, right, bottom, left)]
        )
        if not encodings:
            return None, None, False
        enc = encodings[0]

        with self._lock:
            cached = self._cache.get(tracker_id)
            pid, name, ambiguous = self._best_match(enc)
            if pid is not None:
                # Majority vote over the last VOTE_WINDOW decisive matches:
                # the winner — not necessarily this sample — is the identity.
                votes = self._votes.setdefault(
                    tracker_id, deque(maxlen=self.VOTE_WINDOW)
                )
                votes.append(pid)
                winner = Counter(votes).most_common(1)[0][0]
                winner_name = name if winner == pid else self._name_of(winner)
                if cached is not None and cached[0] != winner:
                    logger.info(
                        "PersonRecognizer: re-verify corrected tracker %d: "
                        "person %d → %d", tracker_id, cached[0], winner,
                    )
                self._touch(winner)
                self._cache[tracker_id] = (winner, winner_name)
                self._pending.pop(tracker_id, None)
                return winner, winner_name, False
            if ambiguous or cached is not None:
                # Ambiguous: deciding now risks a wrong identity, and
                # buffering risks registering a duplicate of a known person.
                # Cached: the track already has an identity — an unknown face
                # during re-verify must never seed a NEW person.
                # Either way, skip the sample and wait for a better frame.
                return None, None, False

            # Gate 3 — consensus buffer before registering a new person.
            # An inconsistent sample resets the buffer: it was either an
            # outlier or the earlier samples were junk.
            buf = self._pending.setdefault(tracker_id, [])
            if buf and float(np.max(fr.face_distance(buf, enc))) > self.CONSENSUS_TOLERANCE:
                buf.clear()
            buf.append(enc)
            if len(buf) < self.NEW_PERSON_CONSENSUS:
                return None, None, False

            pid = self._register(buf[0])
            for extra in buf[1:]:
                self._conn.execute(
                    "INSERT INTO face_encodings (person_id, encoding) VALUES (?, ?)",
                    (pid, extra.tobytes()),
                )
                self._person_ids.append(pid)
                self._person_names.append(None)
                self._encodings.append(extra)
            self._conn.commit()
            del self._pending[tracker_id]
            self._cache[tracker_id] = (pid, None)
            return pid, None, True

    def enroll_named_face(self, image_bgr: np.ndarray, name: str) -> int | None:
        """Register or update a person from *image_bgr* with *name*.

        If the face matches an existing person, adds the embedding as an
        additional sample (improving future recognition) and updates the name.
        If no match, registers as a new person.

        Uses plain nearest-neighbour matching on purpose (no ratio test):
        enrollment is user-driven, and rejecting an ambiguous match here
        would create a duplicate of the very person being named.

        Returns the person_id, or None if no face detected.
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
                    # Update name on all in-memory entries for this person
                    for i, p in enumerate(self._person_ids):
                        if p == pid:
                            self._person_names[i] = name
                    self._conn.execute("UPDATE persons SET name=? WHERE id=?", (name, pid))
                    # Add new embedding sample if under the cap
                    count = self._person_ids.count(pid)
                    if count < self.MAX_EMBEDDINGS_PER_PERSON:
                        blob = enc.tobytes()
                        self._conn.execute(
                            "INSERT INTO face_encodings (person_id, encoding) VALUES (?, ?)",
                            (pid, blob),
                        )
                        self._person_ids.append(pid)
                        self._person_names.append(name)
                        self._encodings.append(enc)
                        logger.info(
                            "PersonRecognizer: added embedding sample %d/%d for person id=%d name=%s",
                            count + 1, self.MAX_EMBEDDINGS_PER_PERSON, pid, name,
                        )
                    self._conn.commit()
                    for tid, (cached_pid, _) in list(self._cache.items()):
                        if cached_pid == pid:
                            self._cache[tid] = (pid, name)
                    return pid

            pid = self._register(enc)
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
                "SELECT p.id, p.name, p.first_seen, p.last_seen, p.visit_count, "
                "COUNT(fe.id) as sample_count "
                "FROM persons p "
                "LEFT JOIN face_encodings fe ON fe.person_id = p.id "
                "GROUP BY p.id ORDER BY p.last_seen DESC"
            )
            return [
                {
                    "id": r[0],
                    "name": r[1] or f"Person {r[0]}",
                    "first_seen": r[2],
                    "last_seen": r[3],
                    "visit_count": r[4],
                    "sample_count": 1 + r[5],  # primary embedding + additional
                }
                for r in cur.fetchall()
            ]

    def prune(self, active_tracker_ids: set[int]) -> None:
        """
        Drop per-track state for tracker_ids no longer active (MEJORAS.md
        punto 12). ByteTrack ids grow monotonically, so without pruning
        ``_cache``, ``_last_attempt``, ``_pending`` and ``_votes`` leak
        slowly on a 24/7 process.
        """
        with self._lock:
            for d in (self._cache, self._last_attempt, self._pending, self._votes):
                for tid in list(d):
                    if tid not in active_tracker_ids:
                        del d[tid]

    def purge_unnamed(self, days: int) -> int:
        """
        Delete anonymous one-off passers-by not seen for *days* days
        (MEJORAS.md punto 15): rows with no name and visit_count == 1.
        Named persons are never touched. Returns the number of persons
        removed. Safe to call from any thread.
        """
        if not self._available or days <= 0:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM persons WHERE name IS NULL AND visit_count = 1 "
                "AND last_seen < datetime('now', ?)",
                (f"-{days} days",),
            )
            gone = {r[0] for r in cur.fetchall()}
            if not gone:
                return 0
            marks = ",".join("?" * len(gone))
            ids = list(gone)
            self._conn.execute(
                f"DELETE FROM face_encodings WHERE person_id IN ({marks})", ids
            )
            self._conn.execute(f"DELETE FROM persons WHERE id IN ({marks})", ids)
            self._conn.commit()

            kept = [
                (p, n, e)
                for p, n, e in zip(self._person_ids, self._person_names, self._encodings)
                if p not in gone
            ]
            self._person_ids = [p for p, _, _ in kept]
            self._person_names = [n for _, n, _ in kept]
            self._encodings = [e for _, _, e in kept]
            for tid, (pid, _) in list(self._cache.items()):
                if pid in gone:
                    del self._cache[tid]
            logger.info("PersonRecognizer: purged %d unnamed stale persons", len(gone))
            return len(gone)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _select_face(
        locs: list[tuple[int, int, int, int]], crop_height: int
    ) -> tuple[int, int, int, int]:
        """
        Pick the face belonging to the tracked person (MEJORAS.md punto 7).

        A person bbox has the head in its upper half; faces of OTHER people
        overlapping the crop (someone walking behind) sit lower. Prefer the
        largest face whose center lies in the upper half of the crop; only
        if none qualifies, fall back to the largest face overall.
        """
        def area(loc: tuple[int, int, int, int]) -> int:
            top, right, bottom, left = loc
            return (bottom - top) * (right - left)

        upper = [
            loc for loc in locs if (loc[0] + loc[2]) / 2 < crop_height / 2
        ]
        return max(upper or locs, key=area)

    def _name_of(self, person_id: int) -> str | None:
        """Name of *person_id*, or None. Must be called with ``_lock`` held."""
        for pid, name in zip(self._person_ids, self._person_names):
            if pid == person_id:
                return name
        return None

    def _best_match(self, enc: np.ndarray) -> tuple[int | None, str | None, bool]:
        """
        Match *enc* against known persons. Must be called with ``_lock`` held.

        Returns ``(person_id, name, ambiguous)``:
          - person_id set   → decisive match
          - ambiguous=True  → a candidate exists within TOLERANCE but the
                              runner-up person is closer than MATCH_MARGIN —
                              too risky to decide either way
          - both falsy      → genuinely unknown face

        Distances are grouped per person (MEJORAS.md punto 6): a person's
        score is the minimum distance among their embeddings, so a person
        with many samples gets no extra nearest-neighbour "tickets" and the
        ratio test (punto 5) compares *persons*, never two samples of the
        same person.
        """
        if not self._encodings:
            return None, None, False
        dists = fr.face_distance(self._encodings, enc)
        best_per_person: dict[int, float] = {}
        for pid, d in zip(self._person_ids, dists):
            d = float(d)
            if d < best_per_person.get(pid, float("inf")):
                best_per_person[pid] = d
        ranked = sorted(best_per_person.items(), key=lambda kv: kv[1])
        best_pid, best_d = ranked[0]
        if best_d > self.TOLERANCE:
            return None, None, False
        if len(ranked) > 1 and ranked[1][1] - best_d < self.MATCH_MARGIN:
            return None, None, True
        name = next(
            n for p, n in zip(self._person_ids, self._person_names) if p == best_pid
        )
        return best_pid, name, False

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
            CREATE TABLE IF NOT EXISTS face_encodings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id  INTEGER NOT NULL REFERENCES persons(id),
                encoding   BLOB NOT NULL,
                added_at   TEXT DEFAULT (datetime('now'))
            );
        """)
        self._conn.commit()

    @staticmethod
    def _blob_to_encoding(blob: bytes) -> np.ndarray:
        """Deserialize a numpy-format embedding blob.

        Blobs must already be in raw numpy float64 format — run
        scripts/migrate_embeddings.py once against the database before
        upgrading if it may still hold blobs from the old serialization format.
        """
        _NUMPY_SIZE = 128 * 8  # 128 float64 values = 1024 bytes
        if len(blob) != _NUMPY_SIZE:
            raise ValueError(
                f"Embedding blob has unexpected size {len(blob)} bytes (expected {_NUMPY_SIZE}). "
                "Run scripts/migrate_embeddings.py to convert legacy-format blobs first."
            )
        return np.frombuffer(blob, dtype=np.float64)

    def _load(self) -> None:
        # Primary embeddings (one per person, stored in persons table)
        cur = self._conn.execute("SELECT id, name, encoding FROM persons")
        for pid, name, blob in cur.fetchall():
            self._person_ids.append(pid)
            self._person_names.append(name)
            self._encodings.append(self._blob_to_encoding(blob))

        # Additional embeddings added via enroll_named_face
        cur = self._conn.execute(
            "SELECT fe.id, fe.person_id, p.name, fe.encoding "
            "FROM face_encodings fe JOIN persons p ON fe.person_id = p.id "
            "ORDER BY fe.person_id, fe.id"
        )
        for feid, pid, name, blob in cur.fetchall():
            self._person_ids.append(pid)
            self._person_names.append(name)
            self._encodings.append(self._blob_to_encoding(blob))

        persons_count = len(set(self._person_ids))
        logger.info(
            "PersonRecognizer: loaded %d embeddings for %d persons",
            len(self._encodings), persons_count,
        )

    def _register(self, encoding: np.ndarray) -> int:
        blob = encoding.tobytes()
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
        # visit_count only increments when the previous sighting is older than
        # VISIT_GAP_MINUTES — re-matches within the same stay (e.g. ByteTrack
        # losing and re-acquiring the track) do not inflate the visit count.
        self._conn.execute(
            "UPDATE persons SET "
            "visit_count = visit_count + (last_seen < datetime('now', ?)), "
            "last_seen = datetime('now') "
            "WHERE id=?",
            (f"-{self.VISIT_GAP_MINUTES} minutes", person_id),
        )
        self._conn.commit()
