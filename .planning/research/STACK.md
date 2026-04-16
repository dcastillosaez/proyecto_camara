# Technology Stack

**Proyecto:** Tapo Dashboard
**Investigado:** 2026-04-16
**Confianza general:** HIGH

## Recommended Stack

### Core Framework

| Tecnología | Versión | Propósito | Por qué |
|------------|---------|-----------|---------|
| Python | 3.12.x | Runtime | Estable, soporte hasta oct 2028, rendimiento sólido. 3.13 tiene features experimentales (free-threaded) que no necesitamos; 3.12 es la apuesta segura en producción |
| FastAPI | >=0.115 | API REST + WebSocket + MJPEG | StreamingResponse nativo para MJPEG, soporte WebSocket integrado, async-first. La alternativa (Flask) no tiene async nativo ni WebSocket sin extensiones |
| Uvicorn | >=0.30 | Servidor ASGI | El servidor recomendado por FastAPI. Ligero, rápido, soporta reload en desarrollo |

### Visión por computador

| Tecnología | Versión | Propósito | Por qué |
|------------|---------|-----------|---------|
| opencv-python | 4.13.x | Captura RTSP + procesamiento de frames | `cv2.VideoCapture` con RTSP es el estándar de facto. Hay proyectos específicos con cámaras Tapo C200/C220 que validan la fiabilidad. Alternativas como ffmpeg-python o aiortc añaden complejidad sin beneficio real para captura simple |
| ultralytics | >=8.4 | Detección de personas (YOLO26n) | **YOLO26 nano** en lugar de YOLOv8n: 38.9 ms vs 56.1 ms en CPU (31% más rápido), sin NMS (inferencia más simple), misma API `ultralytics`. El proyecto especifica YOLOv8n pero YOLO26n es estrictamente superior en CPU y se instala con el mismo paquete |
| supervision | >=0.27 | Conteo por cruce de línea + tracking | `LineZone` + `ByteTrack` resuelven exactamente el requisito de "línea virtual de conteo". Evita reimplementar tracking y lógica de cruce desde cero. Mantenido por Roboflow, compatible con la API de detecciones de Ultralytics |

### Base de datos

| Tecnología | Versión | Propósito | Por qué |
|------------|---------|-----------|---------|
| aiosqlite | >=0.20 | Driver async para SQLite | Necesario para no bloquear el event loop de FastAPI al escribir eventos de detección. Ligero, sin servidor, perfecto para volumen bajo de escrituras |
| SQLAlchemy | >=2.0 | ORM + migraciones | Motor async con `sqlite+aiosqlite://`. Modelos declarativos, soporte maduro. SQLModel es una capa extra innecesaria para un esquema tan simple (una tabla de eventos) |

### Frontend

| Tecnología | Versión | Propósito | Por qué |
|------------|---------|-----------|---------|
| HTML + JS vanilla | - | Dashboard SPA | Sin build step, carga instantánea, mantenimiento trivial. Un solo archivo HTML basta |
| Chart.js | 4.5.x | Histograma de actividad por hora | 11 KB core, API simple para bar charts, CDN disponible. No hay razón para usar algo más pesado (D3, ECharts) ni más nicho (Chartist, que está abandonado) |

### Configuración

| Tecnología | Versión | Propósito | Por qué |
|------------|---------|-----------|---------|
| pydantic-settings | >=2.0 | Gestión de configuración | Validación de tipos automática, lectura de `.env` integrada, `@lru_cache` para singleton. `python-dotenv` solo carga variables sin validar; con `pydantic-settings` el server falla al arrancar si falta la URL de la cámara, no en runtime |

### Dependencias de soporte

| Librería | Propósito | Cuándo usarla |
|----------|-----------|---------------|
| websockets | Transporte WebSocket | Requerido por FastAPI para endpoints WS |
| numpy | Manipulación de arrays de frames | Viene con opencv-python, no hay que instalarlo aparte |
| Jinja2 | Templating HTML (opcional) | Solo si se quiere servir el HTML desde FastAPI con variables inyectadas |

## Rejected Alternatives

| Categoría | Recomendado | Alternativa rechazada | Motivo del rechazo |
|-----------|-------------|----------------------|-------------------|
| Framework web | FastAPI | Flask | Sin async nativo, sin WebSocket sin flask-socketio, más lento para streaming |
| Framework web | FastAPI | Django | Excesivo para un dashboard local, ORM propio que no necesitamos |
| Captura vídeo | OpenCV (cv2) | ffmpeg-python | Añade subprocess de ffmpeg, más difícil de depurar, cv2 ya funciona con Tapo RTSP |
| Captura vídeo | OpenCV (cv2) | aiortc | Diseñado para WebRTC, no para captura RTSP simple |
| Detección | YOLO26n | YOLOv8n | 31% más lento en CPU, más parámetros, mismo paquete `ultralytics` |
| Detección | YOLO26n | YOLOv9/YOLOv10 | Paquetes separados, menos mantenidos, sin ventaja clara sobre YOLO26 |
| Detección | YOLO26n | YOLO11n | 56.1 ms vs 38.9 ms en CPU, YOLO26 lo supera en todas las métricas |
| Tracking | supervision (ByteTrack) | Implementación manual | Reimplementar cruce de línea es propenso a errores; supervision ya lo resuelve con `LineZone` |
| DB | aiosqlite + SQLAlchemy | SQLModel | Capa extra sobre SQLAlchemy sin beneficio para un esquema de una tabla |
| DB | aiosqlite + SQLAlchemy | databases (encode) | Proyecto con mantenimiento irregular, SQLAlchemy 2.0 async es el estándar |
| DB | SQLite | PostgreSQL | Sin usuarios concurrentes, volumen bajo, un solo proceso. PostgreSQL es matar moscas a cañonazos |
| Config | pydantic-settings | python-dotenv | Sin validación de tipos, errores se descubren en runtime en vez de al arrancar |
| Charts | Chart.js | D3.js | Excesivo para un histograma y un contador. D3 requiere mucho código para cosas simples |
| Charts | Chart.js | Apache ECharts | 1 MB+ de bundle, funcionalidad innecesaria para este caso |
| Streaming | MJPEG sobre HTTP | WebRTC | Requiere STUN/TURN, señalización compleja, innecesario en LAN |

## Version Matrix

| Paquete | Versión mínima | Versión verificada | Confianza |
|---------|---------------|-------------------|-----------|
| Python | 3.12.0 | 3.12.x (soporte activo) | HIGH |
| fastapi | 0.115.0 | 0.128+ disponible en PyPI | HIGH |
| uvicorn[standard] | 0.30.0 | Disponible en PyPI | HIGH |
| opencv-python | 4.10.0 | 4.13.0.92 (feb 2026) | HIGH |
| ultralytics | 8.4.0 | 8.4.38 en PyPI (incluye YOLO26) | HIGH |
| supervision | 0.25.0 | 0.27.0 en PyPI | HIGH |
| aiosqlite | 0.20.0 | Disponible en PyPI | HIGH |
| sqlalchemy[asyncio] | 2.0.0 | 2.0.x disponible | HIGH |
| pydantic-settings | 2.0.0 | 2.x disponible | HIGH |
| websockets | 12.0 | Disponible en PyPI | HIGH |
| chart.js (CDN) | 4.4.0 | 4.5.1 disponible | HIGH |

## Key Rationale

### Por qué YOLO26n en lugar de YOLOv8n

El PROJECT.md especifica YOLOv8n, pero YOLO26n (enero 2026) lo sustituye directamente:

- **38.9 ms en CPU** vs 56.1 ms de YOLO11n (y peor aún para YOLOv8n)
- **Sin NMS**: inferencia nativa end-to-end, menos código, menos latencia
- **Mismo paquete**: `pip install ultralytics`, misma API `YOLO("yolo26n.pt")`
- **22% menos parámetros** que YOLOv8n con precisión igual o superior

El requisito de <50 ms en CPU se cumple holgadamente con YOLO26n. Con YOLOv8n habría que vigilarlo.

### Por qué supervision en vez de implementar el conteo a mano

El cruce de línea virtual es el feature más complejo del proyecto. `supervision.LineZone` + `ByteTrack`:

- Asigna IDs únicos a cada persona detectada (tracking)
- Cuenta cruces en ambas direcciones (in/out)
- Soporta conteo por clase desde v0.27
- Evita el error clásico de contar la misma persona múltiples veces

Implementar esto desde cero requiere: tracker (Kalman filter + Hungarian algorithm), lógica de cruce de semiplano, gestión de IDs perdidos. supervision lo resuelve en ~10 líneas.

### Por qué pydantic-settings y no python-dotenv

FastAPI ya depende de Pydantic. `pydantic-settings` extiende esto a configuración:

```python
class Settings(BaseSettings):
    camera_url: str = "rtsp://192.168.1.132:554/stream1"
    yolo_confidence: float = 0.5
    server_port: int = 8000

    model_config = SettingsConfigDict(env_file=".env")
```

Si `camera_url` falta o `yolo_confidence` no es un float, el servidor no arranca. Con `python-dotenv` el error aparece cuando ya estás procesando frames.

### Patrón correcto para MJPEG en FastAPI

Errores comunes que hay que evitar:

1. **No usar `await anyio.sleep(0)`** en el generador: el evento de cancelación del cliente nunca se procesa y el generador sigue corriendo tras desconexión
2. **Olvidar los boundary markers**: cada frame debe ir precedido de `b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"` y seguido de `b"\r\n"`
3. **Media type incorrecto**: debe ser exactamente `"multipart/x-mixed-replace; boundary=frame"`
4. **No liberar la captura OpenCV**: `cv2.VideoCapture.release()` debe llamarse al cerrar; si no, el stream RTSP queda abierto y la cámara rechaza nuevas conexiones

Implementación correcta resumida:

```python
async def generate_frames():
    cap = cv2.VideoCapture("rtsp://...")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # ... detección YOLO aquí ...
            _, buffer = cv2.imencode(".jpg", frame)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n"
                   + buffer.tobytes() + b"\r\n")
            await anyio.sleep(0)  # permite cancelación
    finally:
        cap.release()

@app.get("/video")
async def video_feed():
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
```

### Notas sobre OpenCV con cámaras Tapo

- La Tapo C220 soporta RTSP en `rtsp://user:pass@IP:554/stream1` (alta resolución) y `stream2` (baja resolución)
- **Usar `stream2`** (720p) para detección: reduce carga de CPU sin afectar la precisión de YOLO26n a 640px
- `cv2.VideoCapture` con RTSP sobre TCP es más fiable que UDP en redes WiFi: usar `cv2.CAP_PROP_FOURCC` o el parámetro `?tcp` en la URL no siempre funciona; la forma robusta es `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)` para evitar acumulación de frames
- Si la conexión se pierde, `cap.read()` devuelve `(False, None)`. Hay que implementar reconexión automática con backoff

## Installation

```bash
# Crear entorno virtual
python -m venv .venv
.venv/Scripts/activate  # Windows

# Core
pip install fastapi uvicorn[standard] websockets

# Visión
pip install opencv-python ultralytics supervision

# Base de datos
pip install sqlalchemy[asyncio] aiosqlite

# Configuración
pip install pydantic-settings

# Frontend (Chart.js via CDN, no se instala)
# <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1"></script>
```

## Sources

- [FastAPI StreamingResponse docs](https://fastapi.tiangolo.com/advanced/custom-response/)
- [FastAPI WebSocket docs](https://fastapi.tiangolo.com/advanced/websockets/)
- [FastAPI Settings docs](https://fastapi.tiangolo.com/advanced/settings/)
- [Ultralytics YOLO26 docs](https://docs.ultralytics.com/models/yolo26/)
- [YOLO26 vs YOLO11 comparison](https://docs.ultralytics.com/compare/yolo26-vs-yolo11/)
- [Ultralytics PyPI](https://pypi.org/project/ultralytics/)
- [Supervision LineZone docs](https://supervision.roboflow.com/detection/tools/line_zone/)
- [Supervision count objects crossing line](https://supervision.roboflow.com/develop/notebooks/count-objects-crossing-the-line/)
- [opencv-python PyPI](https://pypi.org/project/opencv-python/)
- [FastAPI PyPI](https://pypi.org/project/fastapi/)
- [Chart.js docs](https://www.chartjs.org/docs/)
- [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Tapo C200 + OpenCV reference project](https://github.com/eidelen/tapo-recorder)
- [YOLO26 Roboflow analysis](https://blog.roboflow.com/yolo26/)
- [Python versions status](https://devguide.python.org/versions/)
