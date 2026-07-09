"""Unit tests for backend.stream.RTSPStream (drain thread + reconnection)."""

import time
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
import httpx
from httpx import ASGITransport
from unittest.mock import AsyncMock

from backend.stream import RTSPStream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(value: int) -> np.ndarray:
    """Create a 720p frame filled with *value* (0-255)."""
    frame = np.empty((720, 1280, 3), dtype=np.uint8)
    frame.fill(value)
    return frame


# ---------------------------------------------------------------------------
# Tests — RTSPStream unit
# ---------------------------------------------------------------------------

# ─── Patrón drain: get_frame devuelve el último frame leído ──────────────────
# RTSPStream usa un hilo de captura en bucle tight que descarta todos los
# frames salvo el más reciente. Tras 5 frames con valores 0..4, get_frame()
# debe devolver el frame con valor 4 (pixel[0,0,0]==4).
# Esto garantiza que el dashboard nunca muestra frames acumulados antiguos.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_069_drain_keeps_latest_frame(mock_video_capture):
    """After draining 5 distinct frames, get_frame() returns the last one."""
    frames = [_make_frame(i) for i in range(5)]
    call_count = {"n": 0}

    def _read_side_effect():
        idx = min(call_count["n"], len(frames) - 1)
        call_count["n"] += 1
        return (True, frames[idx].copy())

    cap = mock_video_capture._mock_cap
    cap.read.side_effect = _read_side_effect

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.3)
    stream.stop()

    result = stream.get_frame()
    assert result is not None
    assert result[0, 0, 0] == 4


# ─── get_frame devuelve una copia, no la referencia interna ──────────────────
# Si get_frame devolviera la referencia directa a self._frame, el consumidor
# podría modificar el array (p.ej. cv2.imencode lo hace in-place en algunas
# versiones), corrompiendo el frame almacenado para el siguiente ciclo.
# Se verifica que mutar la copia no afecta a self._frame.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_070_get_frame_returns_copy():
    """The ndarray returned by get_frame() is a copy, not the internal ref."""
    stream = RTSPStream("rtsp://fake")
    stream._frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    frame = stream.get_frame()
    assert frame is not stream._frame
    frame[0, 0, 0] = 255
    assert stream._frame[0, 0, 0] == 0


# ─── Reconexión automática tras fallo de cap.read() ──────────────────────────
# Si cap.read() devuelve (False, None) (cámara desconectada o pérdida de red),
# _capture_loop llama a _reconnect(), que hace release() y crea un nuevo
# VideoCapture. Se verifica que VideoCapture se instancia más de una vez,
# confirmando que el mecanismo de reconexión se activa.
# ─────────────────────────────────────────────────────────────────────────────
@patch("backend.stream.time.sleep")
def TEST_071_reconnect_on_failure(mock_sleep, mock_video_capture):
    """On read() failure, RTSPStream releases and creates a new VideoCapture."""
    good_frame = _make_frame(42)
    cap = mock_video_capture._mock_cap

    cap.read.side_effect = [
        (False, None),
        (False, None),
        (True, good_frame.copy()),
    ] + [(True, good_frame.copy())] * 200

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.3)
    stream.stop()

    assert mock_video_capture.call_count >= 2


# ─── Backoff exponencial en reconexión: 1s → 2s → 4s → 8s → 16s ─────────────
# _reconnect() implementa backoff exponencial para no saturar la red ni la
# cámara con intentos continuos. Se simula una secuencia de 5 fallos de
# isOpened() y se verifica que los delays de time.sleep siguen la progresión
# 1, 2, 4, 8, 16 (capped a 30s). Un backoff incorrecto podría causar
# reconexiones en bucle o esperas innecesariamente largas.
# ─────────────────────────────────────────────────────────────────────────────
@patch("backend.stream.time.sleep")
def TEST_072_backoff_increases(mock_sleep, mock_video_capture):
    """Reconnection delays grow exponentially: 1, 2, 4, 8, 16."""
    import threading as _threading

    cap = mock_video_capture._mock_cap
    reconnected = _threading.Event()

    fail_cap = MagicMock()
    fail_cap.isOpened.return_value = False

    success_cap = MagicMock()
    success_cap.isOpened.return_value = True
    success_cap.read.side_effect = lambda: (
        reconnected.set() or (True, _make_frame(1))
    )

    caps = [cap] + [fail_cap] * 5 + [success_cap] + [success_cap] * 200
    mock_video_capture.side_effect = caps
    cap.read.return_value = (False, None)

    stream = RTSPStream("rtsp://fake")
    stream.start()
    reconnected.wait(timeout=5.0)
    stream.stop()

    sleep_args = [c.args[0] for c in mock_sleep.call_args_list if c.args]
    expected = [1.0, 2.0, 4.0, 8.0, 16.0]
    assert len(sleep_args) >= 5
    for i, exp in enumerate(expected):
        assert sleep_args[i] == exp, f"Delay {i}: expected {exp}, got {sleep_args[i]}"


# ─── stop() llama a VideoCapture.release() ───────────────────────────────────
# Al detener el servidor, stop() debe liberar el recurso de VideoCapture para
# cerrar el socket RTSP correctamente. Sin release(), la cámara mantendría
# la conexión abierta y podría no aceptar nuevas conexiones al reiniciar.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_073_stop_releases_capture(mock_video_capture):
    """After stop(), VideoCapture.release() is called."""
    cap = mock_video_capture._mock_cap
    good_frame = _make_frame(1)
    cap.read.return_value = (True, good_frame)

    stream = RTSPStream("rtsp://fake")
    stream.start()
    time.sleep(0.1)
    stream.stop()
    time.sleep(0.1)

    cap.release.assert_called()


# ─── get_frame devuelve None antes de recibir el primer frame ────────────────
# En los primeros milisegundos tras start(), el hilo de captura aún no ha
# leído ningún frame. El endpoint MJPEG y el grabador deben manejar None
# sin lanzar excepción. Este test verifica el valor inicial de self._frame.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_074_get_frame_none_before_start():
    """Before any frame arrives, get_frame() returns None."""
    stream = RTSPStream("rtsp://fake")
    assert stream.get_frame() is None


# ---------------------------------------------------------------------------
# Integration tests — FastAPI /video_feed endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_jpeg_frame():
    """Return a minimal synthetic BGR frame for JPEG encoding."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ─── /video_feed devuelve Content-Type multipart/x-mixed-replace ─────────────
# El navegador usa el Content-Type para saber que es un stream MJPEG y
# renderizar los frames en el <img> del dashboard. Un Content-Type incorrecto
# mostraría la respuesta como texto o binario en lugar de vídeo.
# Se sustituye mjpeg_generator por un generador finito de un solo frame.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_075_video_feed_returns_mjpeg_content_type(fake_jpeg_frame):
    """GET /video_feed returns multipart/x-mixed-replace content type."""
    import backend.main as main_module
    import cv2

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
    import backend.main as main_module
    import cv2

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


# ─── El lifespan llama a RTSPStream.start() y stop() ─────────────────────────
# El lifespan de FastAPI debe iniciar el stream en startup y detenerlo en
# shutdown. Si start() no se llama, el hilo de captura nunca arranca y no
# llegan frames al dashboard. Si stop() no se llama, el proceso queda zombie
# con el socket RTSP abierto al hacer Ctrl+C.
# ─────────────────────────────────────────────────────────────────────────────
async def TEST_077_app_creates_rtsp_stream_on_startup():
    """Lifespan calls RTSPStream.start() on startup."""
    import backend.main as main_module

    with patch("backend.main.RTSPStream") as MockStream:
        instance = MockStream.return_value
        instance.get_frame.return_value = None

        async with main_module.lifespan(main_module.app):
            pass

        instance.start.assert_called_once()
        instance.stop.assert_called_once()


# ─── Punto 10 (MEJORAS.md): el worker de reconocimiento publica en la cache ──
# El hilo de captura encola (crop, tracker_id) y sigue capturando; el worker
# consume la cola, ejecuta process_crop (el paso dlib caro) y publica el
# resultado en _person_cache. Si el worker no publicara, las etiquetas del
# overlay y los nombres de los eventos nunca aparecerían.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_109_recognition_worker_publishes_cache():
    """The recognition worker consumes the queue and fills _person_cache."""
    import threading

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop.return_value = (7, "Alice", False)

    stream = RTSPStream("rtsp://fake", recognizer=recognizer)
    stream._try_save_capture = MagicMock()  # no tocar data/gallery real
    stream._running = True
    worker = threading.Thread(target=stream._recognition_worker, daemon=True)
    worker.start()

    crop = np.zeros((50, 50, 3), dtype=np.uint8)
    stream._recog_queue.put((crop, 3))

    deadline = time.time() + 2.0
    while time.time() < deadline and 3 not in stream._person_cache:
        time.sleep(0.01)
    stream._running = False
    worker.join(timeout=1.0)

    assert stream._person_cache.get(3) == (7, "Alice")
    recognizer.process_crop.assert_called_once()
    stream._try_save_capture.assert_called_once_with(crop, 7)
