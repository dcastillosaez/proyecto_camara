"""Tests del contrato HTTP de /api/v2/analytics: /hourly, /summary, /occupancy y
/persons (Fase 31, OPS-12..OPS-14), mas el criterio 3 (peso del payload).

Cableado: el router construye su AnalyticsRepo con `get_session_factory()`
importado en su propio modulo, asi que basta parchear
`analytics_module.get_session_factory` (mismo criterio que
tests/test_events_api.py, no el global de main.py).

Fechas siempre fijas (nunca la hora actual del sistema): un test que dependiera
del dia en curso rompería en produccion sin que nadie tocara el codigo.
"""

from __future__ import annotations

import datetime
import re
import sqlite3
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import backend.main as main_module
from backend.api.v2 import analytics as analytics_module
from backend.events.types import Event, EventType
from backend.storage import models
from backend.storage.repositories import EventRepo


@pytest_asyncio.fixture
async def sf(tmp_path):
    """Base temporal con una camara, ya parcheada dentro del modulo del router.

    `captures` vive en events.db pero fuera de storage.models (Base distinta en
    backend/database.py, ver 31-04-SUMMARY.md): se crea a mano con sqlite3
    directo, igual que tests/test_repositories.py, porque person_avatars() la
    consulta incluso cuando esta vacia.
    """
    db_file = tmp_path / "analytics_api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS captures ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, "
            "timestamp DATETIME NOT NULL, image_path VARCHAR(255))"
        )
        conn.commit()
    finally:
        conn.close()

    with patch.object(analytics_module, "get_session_factory", return_value=factory):
        yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=main_module.app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_camera_manager():
    """`_camera_manager` es estado global del modulo: se resetea entre tests para
    que la configuracion de un test de /persons no contamine al siguiente."""
    analytics_module.configure(None)
    yield
    analytics_module.configure(None)


def make_event(**overrides) -> Event:
    kwargs = {
        "type": EventType.LINE_CROSSED,
        "camera_id": "cam1",
        "ts": datetime.datetime(2026, 1, 2, 18, 30, 0),
    }
    kwargs.update(overrides)
    return Event(**kwargs)


async def _insert(factory, *events: Event) -> None:
    repo = EventRepo(factory)
    for ev in events:
        await repo.insert(ev)


def _mock_manager(recognizer=None):
    pipeline = MagicMock()
    pipeline.recognizer = recognizer
    manager = MagicMock()
    manager.get.return_value = pipeline
    return manager


# ─── Rango y validacion ──────────────────────────────────────────────────────
async def TEST_range_inverted_returns_422(sf, client):
    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-08-22", "to": "2026-08-01"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "La fecha «Hasta» debe ser posterior a «Desde»."


async def TEST_range_over_90_days_returns_422(sf, client):
    resp = await client.get(
        "/api/v2/analytics/hourly",
        params={"from": "2026-01-01", "to": "2026-05-01"},  # 121 dias
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "El rango máximo es de 90 días."


async def TEST_range_of_exactly_90_days_is_accepted(sf, client):
    resp = await client.get(
        "/api/v2/analytics/hourly",
        params={"from": "2026-01-01", "to": "2026-03-31"},  # 90 dias inclusive
    )
    assert resp.status_code == 200
    assert resp.json()["range"]["days"] == 90


async def TEST_garbage_date_returns_422(sf, client):
    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "ayer", "to": "2026-08-22"}
    )
    assert resp.status_code == 422


async def TEST_hourly_requires_camera_id_when_ambiguous(sf, client):
    """SCALE-03: con dos camaras registradas y sin camera_id, 400 en vez de
    adivinar cual -- mismo contrato en todos los endpoints de este router."""
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))

    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-01", "to": "2026-01-07"}
    )
    assert resp.status_code == 400


# ─── Fase 36 (SCALE-05): camera_id="*" agrega todas las camaras ───────────────
async def TEST_hourly_wildcard_camera_id_aggregates_instead_of_400(sf, client):
    """Con dos camaras registradas, camera_id="*" NO es ambiguo -- es justo el
    modo que pide el agregado total, nunca pasa por resolve_camera_id()."""
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam2", name="Cam 2", enabled=True))
    await _insert(
        sf,
        make_event(camera_id="cam1", ts=datetime.datetime(2026, 1, 2, 14, 30)),
        make_event(camera_id="cam2", ts=datetime.datetime(2026, 1, 2, 14, 45)),
    )

    resp = await client.get(
        "/api/v2/analytics/hourly",
        params={"camera_id": "*", "from": "2026-01-02", "to": "2026-01-02"},
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 2


async def TEST_summary_wildcard_camera_id_sums_every_camera(sf, client):
    await _insert(
        sf,
        make_event(camera_id="cam1", ts=datetime.datetime(2026, 1, 2, 4, 0)),
        make_event(camera_id="cam2", ts=datetime.datetime(2026, 1, 2, 5, 0)),
    )

    resp = await client.get(
        "/api/v2/analytics/summary",
        params={"camera_id": "*", "from": "2026-01-02", "to": "2026-01-02"},
    )

    assert resp.status_code == 200
    assert resp.json()["total"] == 2


async def TEST_occupancy_wildcard_camera_id_sums_every_camera(sf, client):
    await _insert(
        sf,
        make_event(
            camera_id="cam1", type=EventType.ZONE_ENTERED,
            ts=datetime.datetime(2026, 1, 2, 4, 0), zone_id="z1"),
        make_event(
            camera_id="cam2", type=EventType.ZONE_ENTERED,
            ts=datetime.datetime(2026, 1, 2, 5, 0), zone_id="z1"),
    )

    resp = await client.get(
        "/api/v2/analytics/occupancy",
        params={"camera_id": "*", "from": "2026-01-02", "to": "2026-01-02"},
    )

    assert resp.status_code == 200
    assert resp.json()["values"] == [2]


async def TEST_persons_wildcard_camera_id_sums_every_camera(sf, client):
    await _insert(
        sf,
        make_event(
            camera_id="cam1", type=EventType.PERSON_RECOGNIZED,
            ts=datetime.datetime(2026, 1, 2, 10, 0), person_id=7),
        make_event(
            camera_id="cam2", type=EventType.PERSON_RECOGNIZED,
            ts=datetime.datetime(2026, 1, 2, 11, 0), person_id=7),
    )

    resp = await client.get(
        "/api/v2/analytics/persons",
        params={"camera_id": "*", "from": "2026-01-02", "to": "2026-01-02"},
    )

    assert resp.status_code == 200
    assert resp.json()["persons"][0]["visits"] == 2


# ─── /hourly (OPS-12) ────────────────────────────────────────────────────────
async def TEST_hourly_fills_empty_buckets_with_zero(sf, client):
    await _insert(sf, make_event(ts=datetime.datetime(2026, 1, 2, 14, 30)))

    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    body = resp.json()
    assert len(body["values"]) == 24
    assert sum(body["values"]) == 1
    assert body["values"].count(0) == 23


async def TEST_hourly_bucket_switches_to_day_over_seven_days(sf, client):
    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-01", "to": "2026-01-08"}
    )

    body = resp.json()
    assert body["range"]["bucket"] == "day"
    assert len(body["labels"]) == 8


async def TEST_hourly_chart_is_bar_under_48_buckets_and_line_above(sf, client):
    one_day = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-02", "to": "2026-01-02"}
    )
    assert one_day.json()["chart"] == "bar"

    seven_days = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-01", "to": "2026-01-07"}
    )
    assert seven_days.json()["chart"] == "line"


async def TEST_hourly_previous_has_same_length_as_values(sf, client):
    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-01", "to": "2026-01-08"}
    )

    body = resp.json()
    assert len(body["previous"]) == len(body["values"])


async def TEST_hourly_has_previous_is_false_without_prior_data(sf, client):
    await _insert(sf, make_event(ts=datetime.datetime(2026, 1, 2, 14, 30)))

    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    assert resp.json()["has_previous"] is False


async def TEST_hourly_peak_index_points_at_the_max(sf, client):
    ts_low = datetime.datetime(2026, 1, 2, 10, 0)
    ts_high = datetime.datetime(2026, 1, 2, 15, 0)
    await _insert(sf, make_event(ts=ts_low))
    for _ in range(5):
        await _insert(sf, make_event(ts=ts_high))

    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-02", "to": "2026-01-02"}
    )
    body = resp.json()
    assert body["values"][body["peak_index"]] == 5

    empty = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-03", "to": "2026-01-03"}
    )
    assert empty.json()["peak_index"] is None


# ─── /summary (OPS-13) ───────────────────────────────────────────────────────
async def TEST_summary_delta_pct_is_null_without_previous_data(sf, client):
    await _insert(sf, make_event(ts=datetime.datetime(2026, 1, 2, 10, 0)))

    resp = await client.get(
        "/api/v2/analytics/summary", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    assert resp.json()["delta_pct"] is None


async def TEST_summary_delta_pct_is_signed_percentage(sf, client):
    cur_ts = datetime.datetime(2026, 1, 2, 10, 0)
    prev_ts = datetime.datetime(2026, 1, 1, 10, 0)
    for _ in range(12):
        await _insert(sf, make_event(ts=cur_ts))
    for _ in range(10):
        await _insert(sf, make_event(ts=prev_ts))

    resp = await client.get(
        "/api/v2/analytics/summary", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    assert resp.json()["delta_pct"] == 20


async def TEST_summary_peak_label_matches_axis_format(sf, client):
    await _insert(sf, make_event(ts=datetime.datetime(2026, 1, 2, 14, 0)))

    hourly_resp = await client.get(
        "/api/v2/analytics/summary", params={"from": "2026-01-02", "to": "2026-01-02"}
    )
    assert re.match(r"^\d{2}:00$", hourly_resp.json()["peak"]["label"])

    daily_resp = await client.get(
        "/api/v2/analytics/summary", params={"from": "2026-01-01", "to": "2026-01-08"}
    )
    assert re.match(
        r"^\d{1,2} (ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)$",
        daily_resp.json()["peak"]["label"],
    )


# ─── /occupancy (OPS-12) ─────────────────────────────────────────────────────
async def TEST_occupancy_is_ordered_desc_and_truncated_to_ten(sf, client):
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    for i in range(1, 13):
        for _ in range(i):
            await _insert(
                sf, make_event(type=EventType.ZONE_ENTERED, ts=ts, zone_id=f"zona-{i}")
            )

    resp = await client.get(
        "/api/v2/analytics/occupancy", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    body = resp.json()
    assert len(body["labels"]) == 10
    assert body["values"] == sorted(body["values"], reverse=True)
    assert body["total_zones"] == 12
    assert body["truncated"] is True


async def TEST_occupancy_truncated_is_false_with_few_zones(sf, client):
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    await _insert(sf, make_event(type=EventType.ZONE_ENTERED, ts=ts, zone_id="entrada"))

    resp = await client.get(
        "/api/v2/analytics/occupancy", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    assert resp.json()["truncated"] is False


# ─── /persons (OPS-13) ───────────────────────────────────────────────────────
async def TEST_persons_is_ordered_desc_with_visits(sf, client):
    ts = datetime.datetime(2026, 1, 2, 10, 0)
    for person_id in range(1, 4):
        for _ in range(person_id):
            await _insert(
                sf, make_event(type=EventType.PERSON_RECOGNIZED, ts=ts, person_id=person_id)
            )

    resp = await client.get(
        "/api/v2/analytics/persons", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    body = resp.json()
    visits = [p["visits"] for p in body["persons"]]
    assert visits == sorted(visits, reverse=True)
    assert body["persons"][0]["person_id"] == 3


async def TEST_persons_delta_pct_is_null_without_previous_visits(sf, client):
    await _insert(
        sf,
        make_event(
            type=EventType.PERSON_RECOGNIZED,
            ts=datetime.datetime(2026, 1, 2, 10, 0),
            person_id=1,
        ),
    )

    resp = await client.get(
        "/api/v2/analytics/persons", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    assert resp.json()["persons"][0]["delta_pct"] is None


async def TEST_persons_no_recognizer_falls_back_to_generic_name(sf, client):
    await _insert(
        sf,
        make_event(
            type=EventType.PERSON_RECOGNIZED,
            ts=datetime.datetime(2026, 1, 2, 10, 0),
            person_id=5,
        ),
    )
    analytics_module.configure(None)

    resp = await client.get(
        "/api/v2/analytics/persons", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    body = resp.json()
    assert body["persons"][0]["name"] == "Persona 5"
    assert body["recognition_available"] is False


async def TEST_persons_uses_recognizer_names(sf, client):
    await _insert(
        sf,
        make_event(
            type=EventType.PERSON_RECOGNIZED,
            ts=datetime.datetime(2026, 1, 2, 10, 0),
            person_id=1,
        ),
    )
    recognizer = MagicMock()
    recognizer.available = True
    recognizer.list_persons.return_value = [{"id": 1, "name": "Ana"}]
    analytics_module.configure(_mock_manager(recognizer=recognizer))

    resp = await client.get(
        "/api/v2/analytics/persons", params={"from": "2026-01-02", "to": "2026-01-02"}
    )

    body = resp.json()
    assert body["persons"][0]["name"] == "Ana"
    assert body["recognition_available"] is True


# ─── Criterio 3: peso del payload ────────────────────────────────────────────
async def TEST_payload_size_30_days_under_100kb(sf, client):
    base = datetime.datetime(2026, 1, 1, 12, 0)
    for day in range(30):
        await _insert(sf, make_event(ts=base + datetime.timedelta(days=day)))

    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-01", "to": "2026-01-30"}
    )

    assert len(resp.content) < 100 * 1024, f"payload de 30 dias: {len(resp.content)} bytes"


async def TEST_payload_size_7_days_hourly_under_100kb(sf, client):
    base = datetime.datetime(2026, 1, 1, 12, 0)
    for hour in range(0, 168, 3):
        await _insert(sf, make_event(ts=base + datetime.timedelta(hours=hour)))

    resp = await client.get(
        "/api/v2/analytics/hourly", params={"from": "2026-01-01", "to": "2026-01-07"}
    )

    assert len(resp.content) < 100 * 1024, f"payload de 7 dias horario: {len(resp.content)} bytes"


# ─── /heatmap y /heatmap/scale (OPS-12) ──────────────────────────────────────
def _heatmap_manager(*, frame=None, heatmap=None, scale=None):
    """Doble minimo de CameraManager con un pipeline cuyos tres metodos de
    heatmap son parametrizables — mismo patron que tests/test_scene_context.py
    para sustituir `_camera_manager` de un router v2."""
    pipeline = MagicMock()
    pipeline.get_frame.return_value = frame
    pipeline.get_heatmap.return_value = heatmap
    pipeline.get_heatmap_scale.return_value = scale
    manager = MagicMock()
    manager.get.return_value = pipeline
    return manager


async def TEST_heatmap_returns_503_without_camera(sf, client):
    analytics_module.configure(None)

    resp = await client.get("/api/v2/analytics/heatmap", params={"camera_id": "cam1"})

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Cámara sin señal"


async def TEST_heatmap_returns_503_without_frame(sf, client):
    analytics_module.configure(_heatmap_manager(frame=None))

    resp = await client.get("/api/v2/analytics/heatmap", params={"camera_id": "cam1"})

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Cámara sin señal"


async def TEST_heatmap_returns_404_without_activity(sf, client):
    frame = np.zeros((4, 4, 3), np.uint8)
    analytics_module.configure(_heatmap_manager(frame=frame, heatmap=None))

    resp = await client.get("/api/v2/analytics/heatmap", params={"camera_id": "cam1"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Sin actividad acumulada"


async def TEST_heatmap_returns_jpeg(sf, client):
    frame = np.zeros((4, 4, 3), np.uint8)
    img = np.full((4, 4, 3), 128, np.uint8)
    analytics_module.configure(_heatmap_manager(frame=frame, heatmap=img))

    resp = await client.get("/api/v2/analytics/heatmap", params={"camera_id": "cam1"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content[:2] == b"\xff\xd8"


async def TEST_heatmap_scale_returns_peak_mean_and_unit(sf, client):
    frame = np.zeros((4, 4, 3), np.uint8)
    analytics_module.configure(
        _heatmap_manager(frame=frame, scale={"peak": 8.0, "mean": 2.0})
    )

    resp = await client.get("/api/v2/analytics/heatmap/scale", params={"camera_id": "cam1"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["peak"] == 8.0
    assert body["mean"] == 2.0
    assert body["unit"]


async def TEST_heatmap_scale_returns_404_without_activity(sf, client):
    frame = np.zeros((4, 4, 3), np.uint8)
    analytics_module.configure(_heatmap_manager(frame=frame, scale=None))

    resp = await client.get("/api/v2/analytics/heatmap/scale", params={"camera_id": "cam1"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Sin actividad acumulada"


# ─── /export (OPS-15) ────────────────────────────────────────────────────────
_EXPORT_RANGE = {"from": "2026-07-23", "to": "2026-08-22"}


async def TEST_export_csv_sets_attachment_filename(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export",
        params={**_EXPORT_RANGE, "format": "csv", "panel": "hourly"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == (
        "attachment; filename=analitica-hourly-20260723_20260822.csv"
    )
    assert resp.headers["content-type"].startswith("text/csv")


async def TEST_export_csv_starts_with_bom(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export",
        params={**_EXPORT_RANGE, "format": "csv", "panel": "hourly"},
    )

    assert resp.content.startswith(b"\xef\xbb\xbf")


async def TEST_export_csv_hourly_has_one_row_per_bucket(sf, client):
    hourly_resp = await client.get("/api/v2/analytics/hourly", params=_EXPORT_RANGE)
    n_buckets = len(hourly_resp.json()["values"])

    resp = await client.get(
        "/api/v2/analytics/export",
        params={**_EXPORT_RANGE, "format": "csv", "panel": "hourly"},
    )

    text = resp.content.decode("utf-8-sig")
    lines = [line for line in text.split("\n") if line]
    assert lines[0] == "cubo,etiqueta,personas,personas_anterior"
    assert len(lines) - 1 == n_buckets


async def TEST_export_csv_persons_writes_empty_cell_for_null_delta(sf, client):
    await _insert(
        sf,
        make_event(
            type=EventType.PERSON_RECOGNIZED,
            ts=datetime.datetime(2026, 8, 1, 10, 0),
            person_id=1,
        ),
    )

    resp = await client.get(
        "/api/v2/analytics/export",
        params={**_EXPORT_RANGE, "format": "csv", "panel": "persons"},
    )

    text = resp.content.decode("utf-8-sig")
    lines = [line for line in text.split("\n") if line]
    assert lines[0] == "posicion,person_id,nombre,visitas,variacion_pct"
    assert lines[1].endswith(",")


async def TEST_export_csv_without_panel_returns_422(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export", params={**_EXPORT_RANGE, "format": "csv"}
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Falta el panel para exportar en CSV."


async def TEST_export_unknown_panel_returns_422(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export",
        params={**_EXPORT_RANGE, "format": "csv", "panel": "zonas"},
    )

    assert resp.status_code == 422


async def TEST_export_unknown_format_returns_422(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export",
        params={**_EXPORT_RANGE, "format": "pdf", "panel": "hourly"},
    )

    assert resp.status_code == 422


async def TEST_export_json_has_the_four_sections(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export", params={**_EXPORT_RANGE, "format": "json"}
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["content-disposition"] == (
        "attachment; filename=analitica-20260723_20260822.json"
    )
    body = resp.json()
    assert set(body.keys()) == {"range", "summary", "hourly", "occupancy", "persons"}


async def TEST_export_json_matches_panel_endpoints(sf, client):
    await _insert(sf, make_event(ts=datetime.datetime(2026, 8, 1, 10, 0)))

    export_resp = await client.get(
        "/api/v2/analytics/export", params={**_EXPORT_RANGE, "format": "json"}
    )
    hourly_resp = await client.get("/api/v2/analytics/hourly", params=_EXPORT_RANGE)

    assert export_resp.json()["hourly"] == hourly_resp.json()


async def TEST_export_respects_range_validation(sf, client):
    resp = await client.get(
        "/api/v2/analytics/export",
        params={"from": "2026-01-01", "to": "2026-05-01", "format": "csv", "panel": "hourly"},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "El rango máximo es de 90 días."
