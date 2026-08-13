"""Persistent face recognition — identifies persons across sessions.

Fase 23: orquesta backend/perception/face/{engine,quality,index}.py
(ArcFace/buffalo_s via insightface) instead of calling face_recognition/dlib
directly. The business logic below (consensus buffering, ratio-test
ambiguity handling) is unchanged from the dlib era — only the underlying
detection/embedding/matching primitives changed.

Fase 24: el match ahora es por frame — la agregacion temporal (voto por
mayoria, confirmacion/perdida de identidad) la hacen TemporalVoter e
IdentityStateMachine (backend/perception/face/identity.py) fuera de esta
clase, consumiendo el score que process_crop_scored() expone.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.perception.face.engine import FaceCandidate, FaceEngine
from backend.perception.face.index import IdentityIndex
from backend.perception.face.quality import FaceQualityAssessor

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 512
_EMBEDDING_DTYPE = np.float32


@dataclass
class FaceResult:
    """Resultado de una pasada de reconocimiento sobre un crop (Fase 24).

    `score` es la similitud coseno del mejor match (0.0 si no hubo match). La
    IdentityStateMachine lo necesita para votar; antes de la Fase 24 se calculaba
    en _best_match y se descartaba.
    """

    person_id: int | None
    name: str | None
    is_new: bool
    score: float = 0.0
    ambiguous: bool = False


class PersonRecognizer:
    """
    Detects faces inside person bounding-box crops, extracts 512-dim ArcFace
    embeddings, and matches them against a persistent SQLite store.

    Multiple embeddings per person are supported: each call to enroll_named_face
    for an already-known person adds a new sample, improving match accuracy
    across different lighting conditions, angles and clothing.

    Calling convention (from the RTSP capture thread):
      pid, name, is_new = recognizer.identify_or_register(frame, bbox, tid, frame_num)

    Recognition runs at most once every RECOG_INTERVAL frames per tracker_id,
    and stops retrying once a face has been successfully linked to that id.
    """

    MATCH_MARGIN = 0.10     # min similarity gap over the runner-up person (ratio test)
    RECOG_INTERVAL = 30     # frames between attempts for unidentified tracker IDs
    REVERIFY_INTERVAL = 300  # frames between identity re-checks for identified tracks
    MAX_EMBEDDINGS_PER_PERSON = 20  # cap to keep matching fast
    VISIT_GAP_MINUTES = 5   # min gap since last_seen for a match to count as a new visit

    # Consensus gate for automatic registration (identify_or_register only —
    # manual enrollment via enroll_named_face bypasses it on purpose):
    NEW_PERSON_CONSENSUS = 3    # consistent samples required to register a new person
    CONSENSUS_TOLERANCE = 0.30  # min cosine similarity between samples in the pending buffer

    def __init__(
        self,
        db_path: str = "data/persons.db",
        match_threshold: float = 0.45,
        confirm_threshold: float = 0.55,
        min_face_size_px: int = 60,
        max_blur: float = 100.0,
        max_yaw_deg: float = 40.0,
    ) -> None:
        self._lock = threading.Lock()
        # tracker_id → (person_id, name)  — populated once face is matched
        self._cache: dict[int, tuple[int, str | None]] = {}
        # tracker_id → last frame number where recognition was attempted
        self._last_attempt: dict[int, int] = {}
        # tracker_id → embeddings pending consensus before registering a new person
        self._pending: dict[int, list[np.ndarray]] = {}

        self._match_threshold = match_threshold
        self._confirm_threshold = confirm_threshold  # umbral de confianza de identidad usado por IdentityStateMachine (Fase 24)

        self._engine = FaceEngine()
        self._quality = FaceQualityAssessor(
            min_size_px=min_face_size_px, max_blur=max_blur, max_yaw_deg=max_yaw_deg
        )
        self._index = IdentityIndex()
        self._available = self._engine.available

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

    def process_crop_scored(
        self, crop_bgr: np.ndarray, tracker_id: int
    ) -> FaceResult:
        """
        Run face detection + matching on a person crop (the ArcFace path).
        Safe to call from a worker thread.

        Returns a FaceResult(person_id, name, is_new, score, ambiguous):
          - person_id=None  → no usable face yet (none detected, failed a
                              quality gate, or still gathering consensus
                              samples) — try again later
          - is_new=True     → consensus reached, person just registered
          - is_new=False    → recognised an existing person
          - score           → cosine similarity of the best match (0.0 when
                              no match was attempted)

        Quality gates (MEJORAS.md punto 4, now FaceQualityAssessor): faces
        smaller than face_min_size_px or blurrier than face_max_blur are
        discarded, and a NEW person is only registered after
        NEW_PERSON_CONSENSUS mutually-consistent samples from distinct
        frames of the same track. Matching against already-known persons
        needs a single good sample, as before.

        The match below is per-frame (Fase 24): temporal evidence — majority
        vote across frames, identity confirmation/loss — lives outside this
        class, in TemporalVoter/IdentityStateMachine, which consume the
        score this method returns.
        """
        if not self._available or crop_bgr.size == 0:
            return FaceResult(None, None, False)

        candidates = self._engine.detect(crop_bgr)
        if not candidates:
            return FaceResult(None, None, False)
        cand = self._select_face(candidates, crop_bgr.shape[0])

        x1, y1, x2, y2 = cand.bbox
        face_crop = crop_bgr[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if face_crop.size == 0:
            return FaceResult(None, None, False)
        local_kps = cand.kps - np.array([x1, y1], dtype=cand.kps.dtype)
        quality = self._quality.assess(face_crop, local_kps)
        if not quality.passed:
            return FaceResult(None, None, False)

        enc = self._engine.embed(crop_bgr, cand)
        if enc is None:
            return FaceResult(None, None, False)

        with self._lock:
            cached = self._cache.get(tracker_id)
            pid, name, ambiguous, score = self._best_match(enc)
            if pid is not None:
                # Sin voto por mayoria aqui: el match es por frame y la evidencia
                # temporal la acumula TemporalVoter (Fase 24, FACE-07). Encadenar dos
                # votaciones haria que los parametros configurados no fueran los
                # efectivos.
                self._touch(pid)
                self._cache[tracker_id] = (pid, name)
                self._pending.pop(tracker_id, None)
                return FaceResult(pid, name, False, score, ambiguous)
            if ambiguous or cached is not None:
                # Ambiguous: deciding now risks a wrong identity, and
                # buffering risks registering a duplicate of a known person.
                # Cached: the track already has an identity — an unknown face
                # during re-verify must never seed a NEW person.
                # Either way, skip the sample and wait for a better frame.
                return FaceResult(None, None, False, score, ambiguous)

            # Gate 3 — consensus buffer before registering a new person.
            # An inconsistent sample resets the buffer: it was either an
            # outlier or the earlier samples were junk.
            buf = self._pending.setdefault(tracker_id, [])
            if buf and min(float(np.dot(b, enc)) for b in buf) < self.CONSENSUS_TOLERANCE:
                buf.clear()
            buf.append(enc)
            if len(buf) < self.NEW_PERSON_CONSENSUS:
                return FaceResult(None, None, False, score, ambiguous)

            pid = self._register(buf[0])
            for extra in buf[1:]:
                self._conn.execute(
                    "INSERT INTO face_encodings (person_id, encoding) VALUES (?, ?)",
                    (pid, extra.astype(_EMBEDDING_DTYPE).tobytes()),
                )
                self._person_ids.append(pid)
                self._person_names.append(None)
                self._encodings.append(extra)
                self._index.add(pid, extra)
            self._conn.commit()
            del self._pending[tracker_id]
            self._cache[tracker_id] = (pid, None)
            return FaceResult(pid, None, True, score, ambiguous)

    def process_crop(
        self, crop_bgr: np.ndarray, tracker_id: int
    ) -> tuple[int | None, str | None, bool]:
        """Compatibilidad: process_crop_scored() sin el score ni el flag de ambiguedad.

        El pipeline (RecognitionWorker) usa process_crop_scored desde la Fase 24; esta
        forma se conserva para los llamadores que no necesitan el score.
        """
        r = self.process_crop_scored(crop_bgr, tracker_id)
        return r.person_id, r.name, r.is_new

    def enroll_named_face(self, image_bgr: np.ndarray, name: str) -> int | None:
        """Register or update a person from *image_bgr* with *name*.

        If the face matches an existing person, adds the embedding as an
        additional sample (improving future recognition) and updates the name.
        If no match, registers as a new person.

        Uses plain nearest-neighbour matching on purpose (no ratio test):
        enrollment is user-driven, and rejecting an ambiguous match here
        would create a duplicate of the very person being named. Also skips
        the quality gate on purpose — the user chose this image deliberately.

        Returns the person_id, or None if no face detected.
        """
        if not self._available:
            return None
        candidates = self._engine.detect(image_bgr)
        if not candidates:
            return None
        cand = max(candidates, key=lambda c: c.det_score)
        enc = self._engine.embed(image_bgr, cand)
        if enc is None:
            return None

        with self._lock:
            if self._encodings:
                results = self._index.search(enc, top_k=1)
                if results and results[0][1] >= self._match_threshold:
                    pid = results[0][0]
                    # Update name on all in-memory entries for this person
                    for i, p in enumerate(self._person_ids):
                        if p == pid:
                            self._person_names[i] = name
                    self._conn.execute("UPDATE persons SET name=? WHERE id=?", (name, pid))
                    # Add new embedding sample if under the cap
                    count = self._person_ids.count(pid)
                    if count < self.MAX_EMBEDDINGS_PER_PERSON:
                        blob = enc.astype(_EMBEDDING_DTYPE).tobytes()
                        self._conn.execute(
                            "INSERT INTO face_encodings (person_id, encoding) VALUES (?, ?)",
                            (pid, blob),
                        )
                        self._person_ids.append(pid)
                        self._person_names.append(name)
                        self._encodings.append(enc)
                        self._index.add(pid, enc)
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
        ``_cache``, ``_last_attempt`` and ``_pending`` leak slowly on a
        24/7 process.
        """
        with self._lock:
            for d in (self._cache, self._last_attempt, self._pending):
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
            self._index.rebuild(list(zip(self._person_ids, self._encodings)))
            for tid, (pid, _) in list(self._cache.items()):
                if pid in gone:
                    del self._cache[tid]
            logger.info("PersonRecognizer: purged %d unnamed stale persons", len(gone))
            return len(gone)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _select_face(candidates: list[FaceCandidate], crop_height: int) -> FaceCandidate:
        """
        Pick the face belonging to the tracked person (MEJORAS.md punto 7).

        A person bbox has the head in its upper half; faces of OTHER people
        overlapping the crop (someone walking behind) sit lower. Prefer the
        largest face whose center lies in the upper half of the crop; only
        if none qualifies, fall back to the largest face overall.
        """
        def area(cand: FaceCandidate) -> int:
            x1, y1, x2, y2 = cand.bbox
            return (y2 - y1) * (x2 - x1)

        upper = [
            c for c in candidates if (c.bbox[1] + c.bbox[3]) / 2 < crop_height / 2
        ]
        return max(upper or candidates, key=area)

    def _name_of(self, person_id: int) -> str | None:
        """Name of *person_id*, or None. Must be called with ``_lock`` held."""
        for pid, name in zip(self._person_ids, self._person_names):
            if pid == person_id:
                return name
        return None

    def _best_match(
        self, enc: np.ndarray
    ) -> tuple[int | None, str | None, bool, float]:
        """
        Match *enc* against known persons. Must be called with ``_lock`` held.

        Returns ``(person_id, name, ambiguous, score)``:
          - person_id set   → decisive match
          - ambiguous=True  → a candidate exists above match_threshold but the
                              runner-up person is within MATCH_MARGIN — too
                              risky to decide either way
          - both falsy      → genuinely unknown face
          - score           → cosine similarity of the best match (0.0 if
                              ``ranked`` was empty — no known persons yet)

        Similarities are grouped per person (MEJORAS.md punto 6): a person's
        score is the MAXIMUM similarity among their embeddings, so a person
        with many samples gets no extra nearest-neighbour "tickets" and the
        ratio test (punto 5) compares *persons*, never two samples of the
        same person.
        """
        if not self._person_ids:
            return None, None, False, 0.0
        results = self._index.search(enc, top_k=len(self._person_ids))
        best_per_person: dict[int, float] = {}
        for pid, sim in results:
            if sim > best_per_person.get(pid, float("-inf")):
                best_per_person[pid] = sim
        ranked = sorted(best_per_person.items(), key=lambda kv: -kv[1])
        if not ranked:
            return None, None, False, 0.0
        best_pid, best_sim = ranked[0]
        if best_sim < self._match_threshold:
            return None, None, False, float(best_sim)
        if len(ranked) > 1 and (best_sim - ranked[1][1]) < self.MATCH_MARGIN:
            return None, None, True, float(best_sim)
        return best_pid, self._name_of(best_pid), False, float(best_sim)

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
        """Deserialize a numpy-format ArcFace embedding blob (512 float32).

        Blobs must already be in this format — run scripts/reenroll.py once
        against the database before upgrading if it may still hold 128-d
        legacy-format blobs (dlib embeddings are not convertible to ArcFace
        space; re-enrollment from data/gallery/ is the only path).
        """
        expected_size = _EMBEDDING_DIM * np.dtype(_EMBEDDING_DTYPE).itemsize
        if len(blob) != expected_size:
            raise ValueError(
                f"Embedding blob has unexpected size {len(blob)} bytes (expected {expected_size}). "
                "Run scripts/reenroll.py to rebuild embeddings in ArcFace format first."
            )
        return np.frombuffer(blob, dtype=_EMBEDDING_DTYPE)

    def _load(self) -> None:
        # Primary embeddings (one per person, stored in persons table)
        cur = self._conn.execute("SELECT id, name, encoding FROM persons")
        for pid, name, blob in cur.fetchall():
            enc = self._blob_to_encoding(blob)
            self._person_ids.append(pid)
            self._person_names.append(name)
            self._encodings.append(enc)
            self._index.add(pid, enc)

        # Additional embeddings added via enroll_named_face
        cur = self._conn.execute(
            "SELECT fe.id, fe.person_id, p.name, fe.encoding "
            "FROM face_encodings fe JOIN persons p ON fe.person_id = p.id "
            "ORDER BY fe.person_id, fe.id"
        )
        for feid, pid, name, blob in cur.fetchall():
            enc = self._blob_to_encoding(blob)
            self._person_ids.append(pid)
            self._person_names.append(name)
            self._encodings.append(enc)
            self._index.add(pid, enc)

        persons_count = len(set(self._person_ids))
        logger.info(
            "PersonRecognizer: loaded %d embeddings for %d persons",
            len(self._encodings), persons_count,
        )

    def _register(self, encoding: np.ndarray) -> int:
        blob = encoding.astype(_EMBEDDING_DTYPE).tobytes()
        cur = self._conn.execute(
            "INSERT INTO persons (encoding) VALUES (?)", (blob,)
        )
        self._conn.commit()
        pid = int(cur.lastrowid)
        self._person_ids.append(pid)
        self._person_names.append(None)
        self._encodings.append(encoding)
        self._index.add(pid, encoding)
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
