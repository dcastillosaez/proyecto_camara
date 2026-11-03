"""Fase 6: cambios de configuración en caliente (BUG-03) y trabajo fuera del loop (PERF-01)."""

from __future__ import annotations

import inspect
import time
from unittest.mock import MagicMock, patch

import httpx
from httpx import ASGITransport

import backend.main as main_module
from backend.pipeline.manager import CameraPipeline
from backend.pipeline.supervisor import WorkerStatus, WorkerSupervisor
from tests.test_workers_isolation import _Clock, _FakeWorker, _wait_for


def TEST_supervised_restart_is_not_a_crash():
    made: list[_FakeWorker] = []

    def _make():
        w = _FakeWorker()
        made.append(w)
        return w

    sup = WorkerSupervisor(interval=0.05, max_restarts=3, window=60.0, clock=_Clock())
    sup.register("capture", _make)
    sup.start_all()
    for _ in range(5):                       # 5 cambios en < 60 s: antes FAILED al 3.º
        sup.restart("capture")
    time.sleep(0.2)
    status = sup.status()["capture"]
    sup.stop_all()
    assert status == WorkerStatus.RUNNING
    assert len(made) == 6
    assert all(w.stopped >= 1 for w in made[:-1])   # cada instancia vieja se paró


def TEST_restart_before_start_only_stops():
    made: list[_FakeWorker] = []
    sup = WorkerSupervisor(interval=0.05)
    sup.register("w", lambda: made.append(_FakeWorker()) or made[-1])
    sup.restart("w")
    assert made == [] and sup.status()["w"] == WorkerStatus.STOPPED


def TEST_capture_start_is_idempotent(mock_video_capture):
    from backend.pipeline.broker import FrameBroker
    from backend.pipeline.capture import CaptureWorker

    worker = CaptureWorker("cam1", "rtsp://fake", FrameBroker())
    worker.start()
    first = worker._thread
    worker.start()
    assert worker._thread is first           # nunca dos hilos sobre el mismo VideoCapture
    worker.stop(2.0)


def TEST_set_process_size_three_times_keeps_capture_alive(mock_video_capture):
    pipeline = CameraPipeline("cam1", "rtsp://fake", supervisor_interval=0.05)
    pipeline.start()
    try:
        for size in ((640, 360), (1280, 720), (960, 540)):
            pipeline.set_process_size(*size)
        assert pipeline.capture._process_size == (960, 540)
        assert _wait_for(lambda: pipeline.capture.is_alive())
        time.sleep(0.3)                       # varios ciclos de supervisión
        assert pipeline.worker_status()["capture"] == "running"
        assert pipeline.supervisor.get("capture") is pipeline.capture
    finally:
        pipeline.stop()


async def TEST_resolution_endpoint_resolves_pipeline_from_manager():
    from backend import camera as camera_module

    pipeline = MagicMock()
    pipeline.get_native_resolution.return_value = (1920, 1080)
    pipeline.get_process_size.return_value = (1280, 720)
    manager = MagicMock()
    manager.get.return_value = pipeline
    camera_module.set_refs(manager, "cam1")
    try:
        out = await camera_module.get_resolutions()
        assert out["native"] == {"width": 1920, "height": 1080}
        await camera_module.set_resolution(camera_module.ResolutionRequest(width=640, height=360))
        pipeline.set_process_size.assert_called_once_with(640, 360)
        manager.get.assert_called_with("cam1")
    finally:
        camera_module.set_refs(None)


def TEST_blocking_pipeline_work_runs_in_threads():
    from backend.api.v2 import cameras, config
    from backend.pipeline import factory

    assert "asyncio.to_thread(pipeline.set_process_size" in inspect.getsource(config)
    assert "asyncio.to_thread(_camera_manager.remove" in inspect.getsource(cameras)
    src = inspect.getsource(factory.start_camera_pipeline)
    assert "asyncio.to_thread(\n        build_camera_pipeline" in src
    assert "asyncio.to_thread(pipeline.start)" in src


async def TEST_persons_is_paginated_and_off_the_loop():
    recognizer = MagicMock()
    recognizer.available = True
    recognizer.list_persons_page.return_value = ([{"id": 3, "name": "Ana"}], 42)
    stream = MagicMock(recognizer=recognizer)
    with patch.object(main_module, "rtsp_stream", stream), \
         patch("backend.main.asyncio.to_thread", wraps=main_module.asyncio.to_thread) as to_thread:
        async with httpx.AsyncClient(transport=ASGITransport(app=main_module.app),
                                     base_url="http://test") as client:
            resp = await client.get("/persons", params={"limit": 10, "offset": 20})
    assert resp.status_code == 200
    assert resp.json()["total"] == 42
    recognizer.list_persons_page.assert_called_once_with(10, 20)
    assert to_thread.called


def TEST_list_persons_page_sql(tmp_path):
    from backend.recognizer import PersonRecognizer

    rec = PersonRecognizer.__new__(PersonRecognizer)
    import sqlite3
    import threading

    rec._available = True
    rec._lock = threading.Lock()
    rec._conn = sqlite3.connect(":memory:", check_same_thread=False)
    rec._conn.executescript(
        "CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, first_seen TEXT, last_seen TEXT, visit_count INT);"
        "CREATE TABLE face_encodings (id INTEGER PRIMARY KEY, person_id INT);"
    )
    for i in range(5):
        rec._conn.execute("INSERT INTO persons VALUES (?, NULL, '2026-01-01', ?, 1)", (i + 1, f"2026-01-0{i + 1}"))
    rows, total = rec.list_persons_page(2, 1)
    assert total == 5
    assert [r["id"] for r in rows] == [4, 3]
    assert len(rec.list_persons()) == 5
