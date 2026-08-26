"""Tests del feed MJPEG y del ciclo de vida del pipeline.

La captura RTSP (drain, reconexion, backoff) vive ahora en CaptureWorker y
se prueba en tests/test_capture_worker.py; el overlay y el encode, en
tests/test_streaming_worker.py. Aqui queda lo que sigue siendo propio de
la capa web: el endpoint /video_feed y el arranque/parada del pipeline.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
import pytest
from httpx import ASGITransport


@pytest.fixture
def fake_jpeg_frame():
    """Return a minimal synthetic BGR frame for JPEG encoding."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ─── /video_feed devuelve Content-Type multipart/x-mixed-replace ─────────────
# El navegador usa el Content-Type para saber que es un stream MJPEG y
# renderizar los frames en el <img> del dashboard. Un Content-Type incorrecto
# mostraria la respuesta como texto o binario en lugar de video.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_075_video_feed_returns_mjpeg_content_type(fake_jpeg_frame):
    """GET /video_feed returns multipart/x-mixed-replace content type."""
    import cv2

    import backend.main as main_module

    async def _finite_generator(pipeline):
        _, jpeg = cv2.imencode(".jpg", fake_jpeg_frame)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg.tobytes()
            + b"\r\n"
        )

    with patch.object(main_module, "mjpeg_generator", _finite_generator):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            response = await client.get("/video_feed")

    assert response.status_code == 200
    assert "multipart/x-mixed-replace" in response.headers["content-type"]


# ─── Cuerpo de /video_feed contiene el boundary MJPEG y el MIME de imagen ────
# El protocolo MJPEG requiere el separador '--frame' y el header
# 'Content-Type: image/jpeg' antes de cada frame. Sin ellos, el navegador
# no puede delimitar los frames individuales y la imagen se corrompe.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_076_video_feed_contains_jpeg_boundary(fake_jpeg_frame):
    """Response body starts with MJPEG boundary marker."""
    import cv2

    import backend.main as main_module

    async def _finite_generator(pipeline):
        _, jpeg = cv2.imencode(".jpg", fake_jpeg_frame)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg.tobytes()
            + b"\r\n"
        )

    with patch.object(main_module, "mjpeg_generator", _finite_generator):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            response = await client.get("/video_feed")

    assert b"--frame" in response.content
    assert b"Content-Type: image/jpeg" in response.content


# ─── El lifespan arranca y para el pipeline de camara ────────────────────────
# Si start() no se llama, los workers nunca arrancan y no llegan frames al
# dashboard. Si stop_all() no se llama, el proceso queda con hilos vivos y el
# socket RTSP abierto al hacer Ctrl+C.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_077_lifespan_starts_and_stops_camera_pipeline():
    """Lifespan starts the CameraPipeline on startup and stops it on shutdown."""
    import backend.main as main_module

    pipeline = MagicMock()
    pipeline.recognizer = None

    with patch("backend.main.CameraManager") as MockManager:
        manager = MockManager.return_value
        manager.add.return_value = pipeline
        manager.all.return_value = [pipeline]

        async with main_module.lifespan(main_module.app):
            pass

    pipeline.start.assert_called_once()
    manager.stop_all.assert_called_once()


# ─── mjpeg_generator registra conexion y desconexion de cliente ──────────────
# Es lo que permite al StreamingWorker no encodear cuando nadie mira: si el
# generador no avisara al desconectarse, el worker seguiria gastando CPU para
# siempre tras la primera visita al dashboard.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_078_mjpeg_generator_tracks_client_lifecycle():
    """The MJPEG generator signals client connect/disconnect to the pipeline."""
    import backend.main as main_module

    pipeline = MagicMock()
    pipeline.get_jpeg.return_value = b"\xff\xd8fake"

    gen = main_module.mjpeg_generator(pipeline)
    chunk = await anext(gen)
    assert b"--frame" in chunk
    pipeline.client_connected.assert_called_once()
    await gen.aclose()

    pipeline.client_disconnected.assert_called_once()


# ─── _tracks_broadcast_loop publica bboxes normalizados por /ws a ritmo fijo ──
# El overlay del frontend (29-02-PLAN.md) depende de recibir exactamente este
# payload {"type": "tracks", ...} — si el bucle publicara otra forma o llamara
# a get_object_boxes() por error, el overlay dibujaria datos incorrectos.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_tracks_broadcast_loop_sends_normalized_payload():
    """_tracks_broadcast_loop publica {"type": "tracks", ...} usando get_person_boxes()."""
    import backend.main as main_module

    tracks = [{"track_id": 1, "bbox": [0.1, 0.1, 0.2, 0.2], "identity_state": "CONFIRMED", "person_name": "Ana"}]
    pipeline = MagicMock()
    pipeline.camera_id = "cam1"
    pipeline.get_person_boxes.return_value = tracks

    manager = MagicMock()
    manager.all.return_value = [pipeline]

    broadcast_mock = AsyncMock()

    with (
        patch.object(main_module, "camera_manager", manager),
        patch.object(main_module, "_broadcast", broadcast_mock),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])),
    ):
        with pytest.raises(asyncio.CancelledError):
            await main_module._tracks_broadcast_loop(interval=0.01)

    pipeline.get_person_boxes.assert_called_once()
    broadcast_mock.assert_awaited_once_with({
        "type": "tracks",
        "camera_id": "cam1",
        "tracks": tracks,
    })


# ─── Fase 36 (SCALE-05): _start_configured_cameras arranca N camaras del catalogo ──
def _fake_settings(camera_url="rtsp://env-cam1/stream"):
    from types import SimpleNamespace
    return SimpleNamespace(camera_url=camera_url, rtsp_user="", rtsp_pass="")


async def TEST_start_configured_cameras_starts_every_enabled_camera():
    import backend.main as main_module

    rows = [
        {"id": "cam1", "rtsp_url": None, "process_w": None, "process_h": None},
        {"id": "cam2", "rtsp_url": "rtsp://cam2/stream", "process_w": None, "process_h": None},
    ]
    repo = MagicMock()
    repo.list = AsyncMock(return_value=rows)
    pipelines = {"cam1": MagicMock(), "cam2": MagicMock()}
    start_mock = AsyncMock(side_effect=lambda manager, camera, services: pipelines[camera["id"]])

    with patch.object(main_module, "CameraRepo", return_value=repo), \
         patch.object(main_module, "start_camera_pipeline", start_mock):
        primary = await main_module._start_configured_cameras(
            MagicMock(), _fake_settings(), None, object(),
        )

    assert start_mock.await_count == 2
    assert primary is pipelines["cam1"]
    # cam1 sin rtsp_url propia cae al CAMERA_URL de settings (compatibilidad).
    cam1_call = next(c for c in start_mock.await_args_list if c.args[1]["id"] == "cam1")
    assert cam1_call.args[1]["rtsp_url"] == "rtsp://env-cam1/stream"


async def TEST_start_configured_cameras_skips_camera_without_rtsp_url():
    import backend.main as main_module

    rows = [{"id": "cam2", "rtsp_url": None, "process_w": None, "process_h": None}]
    repo = MagicMock()
    repo.list = AsyncMock(return_value=rows)
    start_mock = AsyncMock()

    with patch.object(main_module, "CameraRepo", return_value=repo), \
         patch.object(main_module, "start_camera_pipeline", start_mock):
        primary = await main_module._start_configured_cameras(
            MagicMock(), _fake_settings(), None, object(),
        )

    start_mock.assert_not_awaited()
    assert primary is None


async def TEST_start_configured_cameras_returns_none_with_zero_cameras():
    import backend.main as main_module

    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])

    with patch.object(main_module, "CameraRepo", return_value=repo):
        primary = await main_module._start_configured_cameras(
            MagicMock(), _fake_settings(), None, object(),
        )

    assert primary is None


async def TEST_start_configured_cameras_falls_back_to_first_pipeline_without_cam1():
    """Si el operador borro 'cam1' desde la UI, la primaria pasa a ser la
    primera camara que arranque con exito (no queda sin fachada v1)."""
    import backend.main as main_module

    rows = [{"id": "cam2", "rtsp_url": "rtsp://cam2/stream", "process_w": None, "process_h": None}]
    repo = MagicMock()
    repo.list = AsyncMock(return_value=rows)
    cam2_pipeline = MagicMock()
    start_mock = AsyncMock(return_value=cam2_pipeline)

    with patch.object(main_module, "CameraRepo", return_value=repo), \
         patch.object(main_module, "start_camera_pipeline", start_mock):
        primary = await main_module._start_configured_cameras(
            MagicMock(), _fake_settings(), None, object(),
        )

    assert primary is cam2_pipeline


async def TEST_start_configured_cameras_uses_global_default_process_size_unless_overridden():
    import backend.main as main_module

    rows = [
        {"id": "cam1", "rtsp_url": "rtsp://cam1/stream", "process_w": None, "process_h": None},
        {"id": "cam2", "rtsp_url": "rtsp://cam2/stream", "process_w": 320, "process_h": 240},
    ]
    repo = MagicMock()
    repo.list = AsyncMock(return_value=rows)
    start_mock = AsyncMock(return_value=MagicMock())

    with patch.object(main_module, "CameraRepo", return_value=repo), \
         patch.object(main_module, "start_camera_pipeline", start_mock):
        await main_module._start_configured_cameras(
            MagicMock(), _fake_settings(), (1280, 720), object(),
        )

    by_id = {c.args[1]["id"]: c.args[1] for c in start_mock.await_args_list}
    assert (by_id["cam1"]["process_w"], by_id["cam1"]["process_h"]) == (1280, 720)
    assert (by_id["cam2"]["process_w"], by_id["cam2"]["process_h"]) == (320, 240)


# ─── Fase 36 (SCALE-08): _cpu_rebalance_loop llama a CameraManager.rebalance_fps ──
async def TEST_cpu_rebalance_loop_calls_manager_with_configured_budget():
    import backend.main as main_module

    manager = MagicMock()
    settings = MagicMock()
    settings.cpu_budget_warn_pct = 150.0

    with (
        patch.object(main_module, "camera_manager", manager),
        patch.object(main_module, "get_settings", return_value=settings),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])),
    ):
        with pytest.raises(asyncio.CancelledError):
            await main_module._cpu_rebalance_loop(interval=0.01)

    manager.rebalance_fps.assert_called_once_with(150.0)


async def TEST_cpu_rebalance_loop_skips_tick_without_camera_manager():
    import backend.main as main_module

    with (
        patch.object(main_module, "camera_manager", None),
        patch("asyncio.sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()])),
    ):
        with pytest.raises(asyncio.CancelledError):
            await main_module._cpu_rebalance_loop(interval=0.01)
    # sin camera_manager, el tick no debe lanzar excepcion (ya verificado arriba)


# ─── Fase 36 (SCALE-06): /video_feed acepta camera_id para el selector/mosaico ──
async def _empty_generator(pipeline):
    return
    yield  # pragma: no cover - hace de este un generador vacio, nunca produce nada


async def TEST_video_feed_without_camera_id_uses_primary_pipeline():
    import backend.main as main_module

    primary = MagicMock()
    calls = []

    def _capture(pipeline):
        calls.append(pipeline)
        return _empty_generator(pipeline)

    with patch.object(main_module, "rtsp_stream", primary), \
         patch.object(main_module, "mjpeg_generator", _capture):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            await client.get("/video_feed")

    assert calls == [primary]


async def TEST_video_feed_with_camera_id_resolves_via_camera_manager():
    import backend.main as main_module

    primary = MagicMock()
    other = MagicMock()
    manager = MagicMock()
    manager.get.side_effect = lambda cid: {"cam2": other}.get(cid)
    calls = []

    def _capture(pipeline):
        calls.append(pipeline)
        return _empty_generator(pipeline)

    with patch.object(main_module, "rtsp_stream", primary), \
         patch.object(main_module, "camera_manager", manager), \
         patch.object(main_module, "mjpeg_generator", _capture):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            await client.get("/video_feed", params={"camera_id": "cam2"})

    manager.get.assert_called_once_with("cam2")
    assert calls == [other]


async def TEST_video_feed_with_unknown_camera_id_returns_empty_stream_not_error():
    """Es un <img>, no una API JSON: una camara desconocida da 200 con stream
    vacio, nunca 404 -- mismo criterio de tolerancia que sin pipeline activo."""
    import backend.main as main_module

    manager = MagicMock()
    manager.get.return_value = None

    with patch.object(main_module, "camera_manager", manager):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as client:
            response = await client.get("/video_feed", params={"camera_id": "does-not-exist"})

    assert response.status_code == 200
