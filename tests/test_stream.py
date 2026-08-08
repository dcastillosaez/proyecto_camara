"""Tests del feed MJPEG y del ciclo de vida del pipeline.

La captura RTSP (drain, reconexion, backoff) vive ahora en CaptureWorker y
se prueba en tests/test_capture_worker.py; el overlay y el encode, en
tests/test_streaming_worker.py. Aqui queda lo que sigue siendo propio de
la capa web: el endpoint /video_feed y el arranque/parada del pipeline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    async def _finite_generator():
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

    async def _finite_generator():
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

    with patch.object(main_module, "rtsp_stream", pipeline):
        gen = main_module.mjpeg_generator()
        chunk = await anext(gen)
        assert b"--frame" in chunk
        pipeline.client_connected.assert_called_once()
        await gen.aclose()

    pipeline.client_disconnected.assert_called_once()
