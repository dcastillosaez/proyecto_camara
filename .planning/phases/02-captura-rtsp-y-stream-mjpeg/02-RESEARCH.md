# Phase 2: Captura RTSP y stream MJPEG - Research

**Researched:** 2026-04-16
**Domain:** OpenCV RTSP capture + FastAPI MJPEG streaming
**Confidence:** HIGH

## Summary

Esta fase implementa la cadena completa de video: un hilo dedicado captura frames de la camara Tapo C220 via RTSP, los drena activamente para evitar acumulacion de buffer, y los sirve al navegador como stream MJPEG sobre HTTP usando `StreamingResponse` de FastAPI.

Los tres retos tecnicos principales son: (1) evitar que el buffer RTSP acumule frames viejos causando latencia progresiva, (2) reconexion robusta cuando la camara o la red caen, y (3) limpieza correcta del generador MJPEG cuando el navegador se desconecta. Los tres tienen soluciones bien documentadas con OpenCV y FastAPI, sin necesidad de librerias adicionales.

**Recomendacion principal:** Hilo daemon que lee frames en bucle continuo (drain pattern) y guarda solo el ultimo frame en una variable protegida por `threading.Lock`. El endpoint MJPEG lee de esa variable con un generador async que incluye `await asyncio.sleep(0)` para permitir cancelacion limpia.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAP-01 | Captura RTSP en hilo dedicado sin acumular buffer | Drain pattern con threading + `CAP_PROP_BUFFERSIZE=1` |
| CAP-02 | Reconexion automatica con backoff exponencial | Recrear `VideoCapture` en cada reconexion (no reutilizar), backoff con `min(base * 2^n, max_delay)` |
| CAP-03 | Retransmision MJPEG con latencia < 2s en LAN | `StreamingResponse` con `multipart/x-mixed-replace`, frame JPEG codificado con `cv2.imencode` |
</phase_requirements>

## Architecture Patterns

### Estructura de archivos afectados

```
backend/
  config.py      # Ya existe — usar camera_url de aqui
  stream.py      # Implementar: hilo de captura + generador MJPEG
  main.py        # Implementar: app FastAPI + endpoint /video_feed
tests/
  test_stream.py # Nuevo: tests del modulo de streaming
```

### Pattern 1: Drain Thread (hilo de drenaje continuo)

**Que hace:** Un hilo daemon lee frames en bucle lo mas rapido posible, descartando todos excepto el ultimo. Esto impide que el buffer RTSP de OpenCV acumule frames viejos.

**Por que es necesario:** `cv2.VideoCapture` almacena frames en un buffer interno. Si el consumidor lee mas lento de lo que la camara produce (cosa segura si hay procesamiento), los frames se acumulan y el video muestra imagenes de hace segundos o minutos.

**Ejemplo:**

```python
import threading
import cv2

class RTSPStream:
    def __init__(self, url: str):
        self._url = url
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._cap = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                self._reconnect()
                continue
            ret, frame = self._cap.read()
            if not ret:
                self._reconnect()
                continue
            with self._lock:
                self._frame = frame  # Solo guarda el ultimo

    def get_frame(self):
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
```

### Pattern 2: Reconexion con backoff exponencial

**Que hace:** Al perder la conexion, libera el `VideoCapture` actual, espera con backoff exponencial, y crea uno nuevo. Nunca reutiliza un `VideoCapture` que fallo.

**Por que recrear en vez de reutilizar:** El issue opencv/opencv#22677 documenta que `cap.read()` puede quedarse bloqueado indefinidamente tras una reconexion si se reutiliza el mismo objeto `VideoCapture`. La solucion segura es destruir y recrear.

**Ejemplo:**

```python
import time
import logging

logger = logging.getLogger(__name__)

def _reconnect(self):
    """Libera el capture actual y reconecta con backoff."""
    if self._cap:
        self._cap.release()
        self._cap = None

    delay = 1.0
    max_delay = 30.0

    while self._running:
        logger.warning("Intentando reconexion RTSP en %.1fs...", delay)
        time.sleep(delay)

        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                self._cap = cap
                logger.info("Reconexion RTSP exitosa")
                return

        cap.release()
        delay = min(delay * 2, max_delay)
```

**Detalles criticos:**
- Usar `cv2.CAP_FFMPEG` como backend explicitamente (mas fiable que el auto-detect en Windows).
- `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)` para minimizar el buffer interno.
- Verificar con un `cap.read()` real tras `isOpened()`, porque `isOpened()` puede retornar True en conexiones parcialmente establecidas.
- Delay capped a 30 segundos para no hacer esperar demasiado.

### Pattern 3: Generador MJPEG async con limpieza

**Que hace:** Generador async que lee el ultimo frame del hilo de captura, lo codifica como JPEG, y lo sirve con el formato multipart MJPEG. Incluye `await asyncio.sleep()` obligatorio para permitir cancelacion.

**Ejemplo:**

```python
import asyncio
import cv2

BOUNDARY = b"--frame"

async def mjpeg_generator(stream: RTSPStream):
    """Genera frames MJPEG. Se cancela limpiamente al desconectar el cliente."""
    try:
        while True:
            frame = stream.get_frame()
            if frame is None:
                await asyncio.sleep(0.1)  # Esperar a que haya frames
                continue

            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield (
                BOUNDARY + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg.tobytes() + b"\r\n"
            )
            # CRITICO: sin este await el generador no se puede cancelar
            await asyncio.sleep(0.033)  # ~30 fps max
    except asyncio.CancelledError:
        pass  # Cliente desconectado — salir limpiamente
    finally:
        pass  # Aqui se liberarian recursos si los hubiera
```

**El endpoint:**

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(
        mjpeg_generator(rtsp_stream),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
```

### Anti-Patterns a evitar

- **Leer frames en el endpoint HTTP:** Cada request leeria del mismo `VideoCapture`, causando contention y frames perdidos. Siempre leer en un hilo dedicado.
- **`time.sleep()` en generador async:** Bloquea el event loop entero de FastAPI. Usar `await asyncio.sleep()`.
- **Reutilizar `VideoCapture` tras fallo:** Puede causar deadlock en `cap.read()`. Siempre crear uno nuevo.
- **No incluir `await` en el generador:** Sin un punto de `await`, FastAPI no puede cancelar el generador cuando el cliente se desconecta. El generador se queda corriendo como proceso zombi.
- **Copiar frame sin lock:** Data race entre el hilo de captura y el hilo del event loop. Siempre usar `threading.Lock`.

## Don't Hand-Roll

| Problema | No implementar | Usar en su lugar | Por que |
|----------|----------------|------------------|---------|
| Codificacion JPEG | Encoder manual | `cv2.imencode(".jpg", frame)` | OpenCV ya incluye libjpeg optimizado |
| Formato MJPEG multipart | Parser HTTP propio | `StreamingResponse` con `multipart/x-mixed-replace` | Estandar soportado por todos los navegadores |
| Backoff exponencial | Logica ad-hoc con delays fijos | `min(base * 2^n, max_delay)` con jitter opcional | Patron estandar; delays fijos o son muy lentos o hacen spam |

## Common Pitfalls

### Pitfall 1: Buffer RTSP acumula latencia progresiva
**Que pasa:** El video se ve bien los primeros minutos pero luego tiene 10, 20, 60 segundos de retraso.
**Causa raiz:** `VideoCapture` almacena frames en buffer. Si no se drenan mas rapido de lo que llegan, se acumulan.
**Como evitar:** Hilo dedicado que lee en bucle continuo, descartando todos los frames excepto el ultimo. `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)`.
**Senales de alerta:** Latencia que crece con el tiempo. Si a los 5 minutos hay 3s de delay y a los 30 minutos hay 15s, es este problema.

### Pitfall 2: cap.read() se bloquea indefinidamente
**Que pasa:** Tras una desconexion de red, el hilo de captura se queda colgado en `cap.read()` y nunca retorna.
**Causa raiz:** Bug documentado en OpenCV (issue #22677). `isOpened()` retorna True pero `read()` se bloquea.
**Como evitar:** No reutilizar un `VideoCapture` tras fallo. Hacer `cap.release()` y crear uno nuevo. Opcionalmente, usar un timeout con threading para detectar bloqueo.
**Senales de alerta:** CPU al 0% en el hilo de captura, sin frames nuevos.

### Pitfall 3: Generador MJPEG no se cancela al desconectar cliente
**Que pasa:** Al cerrar el navegador, el generador sigue corriendo en el servidor consumiendo CPU.
**Causa raiz:** Si el generador no tiene puntos de `await`, Starlette no puede inyectar la cancelacion.
**Como evitar:** Incluir `await asyncio.sleep()` en cada iteracion del generador. Envolver en `try/except asyncio.CancelledError`.
**Senales de alerta:** Procesos que consumen CPU creciente con cada conexion/desconexion de clientes.

### Pitfall 4: Data race en el frame compartido
**Que pasa:** El frame se corrompe intermitentemente causando artefactos visuales o crashes en `imencode`.
**Causa raiz:** El hilo de captura escribe el frame mientras el generador MJPEG lo lee, sin sincronizacion.
**Como evitar:** `threading.Lock` protegiendo escritura y lectura del frame. Devolver `.copy()` del frame.
**Senales de alerta:** Errores esporadicos en `cv2.imencode`, frames con artefactos.

### Pitfall 5: Calidad JPEG demasiado alta consume ancho de banda
**Que pasa:** El stream se ve lento o con stuttering en dispositivos moviles por WiFi.
**Causa raiz:** JPEG al 95% produce frames de 200-500 KB cada uno. A 30 fps = 6-15 MB/s.
**Como evitar:** Usar `cv2.IMWRITE_JPEG_QUALITY` en 70-80. A 720p con calidad 80, cada frame pesa ~40-80 KB, manejable en WiFi.
**Senales de alerta:** Ancho de banda alto, frames que se saltan en el navegador.

## Code Examples

### Inicializacion del VideoCapture con opciones optimas para Tapo

```python
def _create_capture(url: str) -> cv2.VideoCapture:
    """Crea un VideoCapture configurado para RTSP fiable."""
    # CAP_FFMPEG es mas estable que el auto-detect en Windows
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap
```

**Nota sobre stream2 vs stream1:** El CLAUDE.md recomienda `stream2` (720p) para deteccion. En esta fase (sin deteccion) se puede usar cualquiera, pero es mejor usar `stream2` desde el principio para que la fase 3 no requiera cambios en la URL. La config actual (`config.py`) tiene `stream1`; hay que cambiarla a `stream2` o hacerla configurable.

### Lifecycle del stream con FastAPI

```python
from contextlib import asynccontextmanager

rtsp_stream = RTSPStream(get_settings().camera_url)

@asynccontextmanager
async def lifespan(app: FastAPI):
    rtsp_stream.start()
    yield
    rtsp_stream.stop()

app = FastAPI(lifespan=lifespan)
```

### Test sin camara real (mock del VideoCapture)

```python
import numpy as np
from unittest.mock import MagicMock, patch

def make_fake_frame():
    """Frame sintetico 720p para tests."""
    return np.zeros((720, 1280, 3), dtype=np.uint8)

def test_get_frame_returns_copy():
    """El frame devuelto es una copia, no referencia directa."""
    stream = RTSPStream("rtsp://fake")
    stream._frame = make_fake_frame()
    frame = stream.get_frame()
    assert frame is not stream._frame

async def test_video_feed_endpoint():
    """El endpoint devuelve StreamingResponse con content-type correcto."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/video_feed", timeout=2.0)
        assert response.status_code == 200
        assert "multipart/x-mixed-replace" in response.headers["content-type"]
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.0+ (ya instalado) |
| Config file | Ninguno especifico — `pytest tests/ -v` |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/test_stream.py -v -x` |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAP-01 | Hilo de captura drena buffer, solo guarda ultimo frame | unit (mock cv2) | `pytest tests/test_stream.py::test_drain_keeps_latest_frame -x` | No — Wave 0 |
| CAP-02 | Reconexion con backoff tras fallo de cap.read() | unit (mock cv2) | `pytest tests/test_stream.py::test_reconnect_on_failure -x` | No — Wave 0 |
| CAP-03 | Endpoint /video_feed retorna MJPEG stream valido | integration (httpx) | `pytest tests/test_stream.py::test_video_feed_mjpeg -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python.exe -m pytest tests/test_stream.py -v -x`
- **Per wave merge:** `.venv/Scripts/python.exe -m pytest tests/ -v`
- **Phase gate:** Full suite green antes de verificacion

### Wave 0 Gaps
- [ ] `tests/test_stream.py` — tests para RTSPStream y endpoint /video_feed
- [ ] Fixture con frame sintetico numpy y mock de cv2.VideoCapture

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | Si | 3.12.x | — |
| OpenCV | Captura RTSP | Si | 4.13.0 | — |
| FastAPI | Endpoint MJPEG | Si | 0.136.0 | — |
| Camara Tapo C220 | Stream RTSP | No verificable en CI | — | Mock en tests, prueba manual en LAN |

**Missing dependencies con fallback:**
- Camara RTSP: los tests unitarios usan mocks de cv2.VideoCapture con frames sinteticos. La verificacion real requiere la camara conectada en LAN.

## State of the Art

| Enfoque antiguo | Enfoque actual | Cuando cambio | Impacto |
|-----------------|----------------|---------------|---------|
| `@app.on_event("startup")` | `lifespan` context manager | FastAPI 0.109+ | Usar lifespan para iniciar/parar el hilo de captura |
| `requests` para test HTTP | `httpx.AsyncClient` con `ASGITransport` | FastAPI 0.100+ | Tests async sin levantar servidor real |
| Generador sync para MJPEG | Generador async con `await asyncio.sleep` | Starlette mejoras de cancelacion | Necesario para limpieza correcta al desconectar |

## Open Questions

1. **Comportamiento de `CAP_PROP_BUFFERSIZE` en Windows 11**
   - Lo que sabemos: La documentacion de OpenCV dice que esta propiedad existe, pero no todos los backends la soportan.
   - Lo que no esta claro: Si el backend FFMPEG en Windows 11 la respeta realmente.
   - Recomendacion: Usarla igualmente (no hace dano si se ignora). El drain thread es la solucion real; `BUFFERSIZE=1` es un bonus.

2. **Timeout para `cap.read()` bloqueante**
   - Lo que sabemos: En ciertos escenarios de reconexion, `cap.read()` se bloquea indefinidamente.
   - Lo que no esta claro: La frecuencia con la Tapo C220 especificamente.
   - Recomendacion: Implementar deteccion por timeout como mejora opcional. En v1, recrear `VideoCapture` en cada reconexion deberia ser suficiente.

## Sources

### Primary (HIGH confidence)
- [FastAPI StreamingResponse docs](https://fastapi.tiangolo.com/advanced/custom-response/) — patron de generador async
- [OpenCV VideoCapture RTSP issue #22677](https://github.com/opencv/opencv/issues/22677) — bug de read() bloqueante y workarounds

### Secondary (MEDIUM confidence)
- [Stop Burning CPU on Dead FastAPI Streams](https://jasoncameron.dev/posts/fastapi-cancel-on-disconnect) — patron de cancelacion con disconnect detection
- [FastAPI issue #1342](https://github.com/fastapi/fastapi/issues/1342) — discusion sobre limpieza de StreamingResponse
- [RTSP Camera Streaming with OpenCV and Threading](https://github.com/god233012yamil/How-to-Stream-a-Camera-Using-OpenCV-and-Threads) — patron de hilo de captura

### Tertiary (LOW confidence)
- Ninguna fuente sin verificar usada.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — OpenCV y FastAPI son las librerias ya decididas, versiones verificadas en el entorno
- Architecture: HIGH — Patron drain thread + MJPEG generator es el estandar de la industria, documentado extensamente
- Pitfalls: HIGH — Problemas como buffer acumulado y read() bloqueante estan bien documentados en issues de OpenCV

**Research date:** 2026-04-16
**Valid until:** 2026-05-16 (stack estable, sin cambios esperados)
