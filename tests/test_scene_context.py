"""Tests for GET /api/v2/analytics/context (Fase 27, criterio 4 del ROADMAP, BEH-08/BEH-09).

Parte 1: funciones puras (_person_counts, _classify_activity) sin BD ni HTTP — fijan el
contrato de "conocida" (identity_state is CONFIRMED) y el de "unknown" (poco historial o
hora parcial). Parte 2: integracion ASGI sobre el endpoint completo, solo forma del JSON y
la garantia de que nunca se filtra identidad.
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.main as main_module
from backend.api.v2 import context as context_module
from backend.config import Settings
from backend.perception.face.identity import IdentityState
from backend.pipeline.tracking import TrackRegistry
from backend.storage import models
from backend.storage.repositories import DetectionStatRepo


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test")


def _tracked(boxes, tids):
    """Objeto minimo con .tracker_id/.xyxy/.confidence, lo unico que lee update_from_detections."""
    tracked = MagicMock()
    tracked.tracker_id = tids
    tracked.xyxy = boxes
    tracked.confidence = [0.9] * len(tids)
    return tracked


@pytest_asyncio.fixture
async def db(tmp_path):
    db_file = tmp_path / "scene_context_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield sf
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_context_wiring():
    yield
    context_module.configure(None)


# ─── Parte 1 — funciones puras ──────────────────────────────────────────────

def TEST_known_requires_confirmed():
    registry = TrackRegistry()
    registry.update_from_detections(_tracked([[0, 0, 10, 10], [20, 20, 30, 30]], [1, 2]), 0.0)
    registry.set_frame_ids({1, 2})
    registry.set_identity_state(1, IdentityState.CONFIRMED)
    registry.set_identity_state(2, IdentityState.CANDIDATE)

    counts = context_module._person_counts(registry)

    assert counts == {"total": 2, "known": 1, "unknown": 0, "pending": 1}


def TEST_person_counts_uses_frame_ids_not_active_ids():
    registry = TrackRegistry()
    registry.update_from_detections(_tracked([[0, 0, 10, 10]], [1]), 0.0)
    # Deliberadamente NO se llama set_frame_ids: el track queda en active_ids() (TTL de
    # prune()) pero no en frame_ids() (visto en el frame actual).

    counts = context_module._person_counts(registry)

    assert counts == {"total": 0, "known": 0, "unknown": 0, "pending": 0}
    assert 1 in registry.active_ids()
    assert 1 not in registry.frame_ids()


def TEST_insufficient_history():
    settings = Settings()
    baseline_entry = {"avg_total": 10.0, "sample_days": 1, "avg_per_minute": 0.16, "mins": 60}
    now_entry = {"avg_total": 5.0, "sample_days": 1, "avg_per_minute": 0.16, "mins": 30}

    out = context_module._classify_activity(baseline_entry, now_entry, 30.0, settings)

    assert baseline_entry["sample_days"] < settings.context_min_sample_days
    assert out["level"] == "unknown"


def TEST_partial_hour_normalised():
    settings = Settings()
    baseline_entry = {"avg_total": 30.0, "sample_days": 5, "avg_per_minute": 0.5, "mins": 300}
    now_entry = {"avg_total": 1.5, "sample_days": 1, "avg_per_minute": 0.5, "mins": 3}

    early = context_module._classify_activity(baseline_entry, now_entry, 3.0, settings)
    assert early["level"] == "unknown"

    now_entry_full = {"avg_total": 15.0, "sample_days": 1, "avg_per_minute": 0.5, "mins": 30}
    later = context_module._classify_activity(baseline_entry, now_entry_full, 30.0, settings)
    assert later["level"] == "normal"


def TEST_activity_ratio_thresholds():
    settings = Settings()
    baseline_entry = {"avg_total": 30.0, "sample_days": 5, "avg_per_minute": 1.0, "mins": 300}

    low = context_module._classify_activity(
        baseline_entry, {"avg_total": 3.0, "sample_days": 1, "avg_per_minute": 1.0, "mins": 30},
        30.0, settings,
    )
    normal = context_module._classify_activity(
        baseline_entry, {"avg_total": 30.0, "sample_days": 1, "avg_per_minute": 1.0, "mins": 30},
        30.0, settings,
    )
    high = context_module._classify_activity(
        baseline_entry, {"avg_total": 60.0, "sample_days": 1, "avg_per_minute": 1.0, "mins": 30},
        30.0, settings,
    )

    assert low["ratio"] < settings.context_low_ratio
    assert low["level"] == "low"
    assert settings.context_low_ratio <= normal["ratio"] <= settings.context_high_ratio
    assert normal["level"] == "normal"
    assert high["ratio"] > settings.context_high_ratio
    assert high["level"] == "high"


# ─── Parte 2 — integracion ASGI ─────────────────────────────────────────────

async def _seed_current_hour(sf, now, days=3):
    repo = DetectionStatRepo(sf)
    hour = now.replace(minute=0, second=0, microsecond=0)
    for day_offset in range(1, days + 1):
        minute = hour - datetime.timedelta(days=day_offset)
        await repo.upsert_minute("cam1", minute, detections=2, unique_tracks=2,
                                  avg_confidence=0.9, max_concurrent=1)
    await repo.upsert_minute("cam1", hour, detections=1, unique_tracks=1,
                              avg_confidence=0.9, max_concurrent=1)


def _mock_manager():
    pipeline = MagicMock()
    pipeline.registry = TrackRegistry()
    pipeline.get_zone_stats.return_value = [{"id": "entrada", "name": "Entrada", "current": 0, "entries": 0}]
    pipeline.get_object_stats.return_value = []
    manager = MagicMock()
    manager.get.return_value = pipeline
    return manager


async def TEST_context_shape(db, monkeypatch):
    sf = db
    now = datetime.datetime.now()
    await _seed_current_hour(sf, now)

    monkeypatch.setattr(context_module, "_stat_repo", lambda: DetectionStatRepo(sf))
    context_module.configure(_mock_manager())

    async with await _client() as client:
        resp = await client.get("/api/v2/analytics/context", params={"camera_id": "cam1"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"timestamp", "camera_id", "hour", "persons", "zones", "objects", "activity"}
    assert set(body["persons"].keys()) == {"total", "known", "unknown", "pending"}


async def TEST_context_never_leaks_person_identity(db, monkeypatch):
    sf = db
    now = datetime.datetime.now()
    await _seed_current_hour(sf, now)

    monkeypatch.setattr(context_module, "_stat_repo", lambda: DetectionStatRepo(sf))
    context_module.configure(_mock_manager())

    async with await _client() as client:
        resp = await client.get("/api/v2/analytics/context", params={"camera_id": "cam1"})

    assert resp.status_code == 200
    assert "person_id" not in resp.text
    assert "person_name" not in resp.text
