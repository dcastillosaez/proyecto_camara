"""Tests for Phase 9: face recognition, enrolment, and person-name tracking."""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import pytest_asyncio
import supervision as sv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.database as db_module
from backend.recognizer import PersonRecognizer
from backend.tracker import PersonTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_detections(tracker_ids: list[int]) -> sv.Detections:
    n = len(tracker_ids)
    xyxy = np.array([[i * 100, 100, i * 100 + 50, 300] for i in range(n)], dtype=np.float32)
    det = sv.Detections(
        xyxy=xyxy,
        confidence=np.ones(n, dtype=np.float32) * 0.9,
        class_id=np.zeros(n, dtype=int),
    )
    det.tracker_id = np.array(tracker_ids)
    return det


# ---------------------------------------------------------------------------
# Tracker — tracker_id in crossing events
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker():
    return PersonTracker(start=sv.Point(0, 360), end=sv.Point(1280, 360))


def test_crossing_in_includes_tracker_id(tracker):
    """IN crossing event must carry the tracker_id of the crossing person."""
    det = _fake_detections([7])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert len(crossings) == 1
    assert crossings[0]["tracker_id"] == 7
    assert crossings[0]["direction"] == "in"


def test_crossing_out_includes_tracker_id(tracker):
    """OUT crossing event must carry the tracker_id of the crossing person."""
    det = _fake_detections([42])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([False]), np.array([True]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert len(crossings) == 1
    assert crossings[0]["tracker_id"] == 42
    assert crossings[0]["direction"] == "out"


def test_no_crossing_produces_no_events(tracker):
    """When nobody crosses, crossing list is empty."""
    det = _fake_detections([1, 2])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([False, False]), np.array([False, False]))),
    ):
        _, crossings = tracker.update(sv.Detections.empty())

    assert crossings == []


def test_same_tracker_id_not_counted_twice(tracker):
    """The same tracker_id cannot generate two crossing events."""
    det = _fake_detections([5])
    with (
        patch.object(tracker._byte_tracker, "update_with_detections", return_value=det),
        patch.object(tracker._line_zone, "trigger", return_value=(np.array([True]), np.array([False]))),
    ):
        _, c1 = tracker.update(sv.Detections.empty())
        _, c2 = tracker.update(sv.Detections.empty())

    assert len(c1) == 1
    assert len(c2) == 0


# ---------------------------------------------------------------------------
# Database — person_name column
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def isolated_db(tmp_path):
    """Swap the global engine/session factory for an isolated temp DB."""
    db_file = tmp_path / "test_events.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    await db_module.init_db()
    yield

    db_module._engine, db_module._session_factory = orig_engine, orig_sf
    await engine.dispose()


@pytest.mark.asyncio
async def test_insert_event_stores_person_name(isolated_db):
    """insert_event persists person_name when provided."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0), "Alice")
    events = await db_module.get_recent_events(10)
    assert events[0]["person_name"] == "Alice"


@pytest.mark.asyncio
async def test_insert_event_person_name_nullable(isolated_db):
    """insert_event accepts None person_name (anonymous crossing)."""
    await db_module.insert_event("out", datetime.datetime(2026, 1, 1, 12, 0), None)
    events = await db_module.get_recent_events(10)
    assert events[0]["person_name"] is None


@pytest.mark.asyncio
async def test_get_recent_events_includes_person_name_key(isolated_db):
    """Every event dict returned by get_recent_events has a 'person_name' key."""
    await db_module.insert_event("in", datetime.datetime(2026, 1, 1, 12, 0))
    events = await db_module.get_recent_events(10)
    assert "person_name" in events[0]


@pytest.mark.asyncio
async def test_migration_adds_column_to_existing_db(tmp_path):
    """init_db is idempotent — calling it twice does not raise."""
    db_file = tmp_path / "migrate.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    orig_engine, orig_sf = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, sf

    try:
        await db_module.init_db()
        await db_module.init_db()  # second call must not raise
    finally:
        db_module._engine, db_module._session_factory = orig_engine, orig_sf
        await engine.dispose()


# ---------------------------------------------------------------------------
# PersonRecognizer — enroll_named_face
# ---------------------------------------------------------------------------


def _make_mock_fr(face_found: bool = True, distance: float = 0.8, encoding=None):
    enc = encoding if encoding is not None else np.random.rand(128).astype(np.float64)
    m = MagicMock()
    m.face_locations.return_value = [(0, 50, 50, 0)] if face_found else []
    m.face_encodings.return_value = [enc] if face_found else []
    m.face_distance.return_value = np.array([distance])
    return m, enc


def test_enroll_named_face_no_face_returns_none(tmp_path):
    """Returns None when no face is detected in the provided image."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    mock_fr, _ = _make_mock_fr(face_found=False)
    with patch("backend.recognizer.fr", mock_fr):
        result = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Bob")
    assert result is None


def test_enroll_named_face_registers_new_person(tmp_path):
    """Registers a new person and returns a positive integer ID."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    mock_fr, _ = _make_mock_fr(face_found=True, distance=0.8)
    with patch("backend.recognizer.fr", mock_fr):
        pid = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Carol")
    assert pid is not None and pid > 0
    assert any(p["name"] == "Carol" for p in r.list_persons())


def test_enroll_named_face_updates_existing_person(tmp_path):
    """Renames an existing matched person instead of creating a duplicate."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    enc = np.random.rand(128).astype(np.float64)

    # Register "Dave" (no existing match)
    mock_new = MagicMock()
    mock_new.face_locations.return_value = [(0, 50, 50, 0)]
    mock_new.face_encodings.return_value = [enc]
    mock_new.face_distance.return_value = np.array([0.8])
    with patch("backend.recognizer.fr", mock_new):
        pid1 = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Dave")

    # Rename to "David" — same encoding, low distance → match
    mock_upd = MagicMock()
    mock_upd.face_locations.return_value = [(0, 50, 50, 0)]
    mock_upd.face_encodings.return_value = [enc]
    mock_upd.face_distance.return_value = np.array([0.1])
    with patch("backend.recognizer.fr", mock_upd):
        pid2 = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "David")

    assert pid1 == pid2
    persons = r.list_persons()
    assert any(p["name"] == "David" for p in persons)
    assert not any(p["name"] == "Dave" for p in persons)


def test_enroll_named_face_unavailable_returns_none(tmp_path):
    """Returns None immediately when face_recognition library is unavailable."""
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    r._available = False
    result = r.enroll_named_face(np.zeros((100, 100, 3), dtype=np.uint8), "Eve")
    assert result is None


# ---------------------------------------------------------------------------
# API — POST /api/enroll_face
# ---------------------------------------------------------------------------

import httpx
from httpx import ASGITransport

import backend.main as main_module


@pytest.mark.asyncio
async def test_enroll_face_503_when_recognizer_unavailable():
    """Returns 503 when the recognizer reports the library is not installed."""
    mock_stream = MagicMock()
    mock_stream._recognizer = MagicMock()
    mock_stream._recognizer.available = False

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Test", "use_current_frame": "true"})

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_enroll_face_422_when_no_face_detected():
    """Returns 422 when enroll_named_face finds no face in the image."""
    mock_stream = MagicMock()
    mock_stream._recognizer = MagicMock()
    mock_stream._recognizer.available = True
    mock_stream.get_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_stream._recognizer.enroll_named_face = MagicMock(return_value=None)

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Ghost", "use_current_frame": "true"})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_enroll_face_success_returns_person_id():
    """Returns 200 with person_id and name on successful enrolment."""
    mock_stream = MagicMock()
    mock_stream._recognizer = MagicMock()
    mock_stream._recognizer.available = True
    mock_stream.get_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_stream._recognizer.enroll_named_face = MagicMock(return_value=3)

    with patch.object(main_module, "rtsp_stream", mock_stream):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/enroll_face", data={"name": "Frank", "use_current_frame": "true"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["person_id"] == 3
    assert body["name"] == "Frank"
