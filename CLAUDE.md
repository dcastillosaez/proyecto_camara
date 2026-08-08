# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estilo de respuesta

Respuestas **cortas y precisas**. El objetivo es ahorrar tokens:

- Ir al grano: el resultado primero, sin preámbulo ni recapitulación de lo ya hecho.
- No repetir en el chat lo que ya está en el código, el diff o el mensaje de commit.
- Nada de resúmenes largos al terminar una tarea: 2-4 líneas bastan.
- Al ejecutar tests, reportar el marcador (`176/176`), no volcar la salida.
- Reservar la explicación extensa para decisiones de diseño no obvias, hallazgos inesperados o cuando el usuario la pida.
- Los mensajes de commit y los documentos sí van completos — la brevedad es solo para el chat.

## Descripción del proyecto

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta personas en tiempo real con YOLO y muestra estadísticas de actividad (conteo acumulado, histograma por hora, últimos eventos).

**URL de la cámara:** `rtsp://192.168.1.132:554/stream1`

## Stack

| Capa | Tecnología |
|------|-----------|
| Captura de vídeo | OpenCV (`cv2.VideoCapture`) |
| Detección | YOLOv8 nano (`ultralytics`) |
| Backend | FastAPI + Uvicorn |
| Streaming web | MJPEG multipart sobre HTTP |
| Tiempo real | WebSocket (FastAPI) |
| Base de datos | SQLite vía `aiosqlite` + `databases` |
| Frontend | HTML + Tailwind CDN + Chart.js |

## Comandos de desarrollo

Ejecutar **siempre desde** `F:\Documentos\IA\Proyecto_Camara` (raíz del proyecto), con el venv activado o usando la ruta explícita al intérprete.

```bash
# Instalar dependencias
.venv/Scripts/python.exe -m pip install -r requirements.txt

# Arrancar el servidor (Windows — usar python.exe -m uvicorn, NO el script uvicorn directo)
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Con recarga automática (desarrollo)
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Correr tests
pytest tests/ -v

# Test de un solo módulo
pytest tests/test_detector.py -v

# Verificar que el stream RTSP es accesible
python -c "import cv2; cap=cv2.VideoCapture('rtsp://192.168.1.132:554/stream1'); print(cap.isOpened()); cap.release()"
```

## Arquitectura

```
backend/
  main.py        — FastAPI app, monta rutas y WebSocket
  pipeline/      — Pipeline de vídeo desacoplado (v2.0, fases 17-18)
    broker.py      — FrameBroker: fan-out latest-frame, un slot por suscriptor
    capture.py     — CaptureWorker: solo captura RTSP, reescalado y publicación
    detection.py   — DetectionWorker: YOLO + ByteTrack + zonas + heatmap
    streaming.py   — StreamingWorker: overlay + encode JPEG para MJPEG
    recording.py   — RecordingWorker: alimenta al ClipRecorder desde el broker
    recognition.py — RecognitionWorker: reconocimiento facial con ritmo propio
    tracking.py    — TrackRegistry: estado compartido de tracks entre workers
    rate.py        — AdaptiveRate: FPS por escalones según latencia real
    supervisor.py  — WorkerSupervisor: reinicia workers caídos, modo degradado
    manager.py     — CameraPipeline (fachada) + CameraManager (N cámaras)
  detector.py    — Wrapper de YOLO; recibe frame BGR, devuelve detecciones
  tracker.py     — ByteTrack + LineZone: IDs persistentes y conteo de cruces
  recognizer.py  — Reconocimiento facial persistente (dlib/face_recognition)
  recorder.py    — ClipRecorder: graba .mp4 mientras hay personas en escena
  database.py    — Modelos SQLite (events, zones, captures, recordings)
  config.py      — Variables (URL cámara, umbral confianza, FPS objetivo…)
frontend/
  index.html     — Dashboard único: vídeo + métricas + gráficas
  app.js         — WebSocket listener, actualiza Chart.js y contadores DOM
data/
  events.db      — SQLite generado en runtime
tests/
```

### Flujo de datos

Invariante central: **la captura nunca espera a la IA**. Cada worker consume
del broker a su propio ritmo y solo se pierde frames a sí mismo.

```
Cámara RTSP
  └─► CaptureWorker (hilo) ─► FrameBroker (latest-frame, slot por suscriptor)
        │
        ├─► StreamingWorker  ─► /video_feed (MJPEG) → <img> del dashboard
        ├─► RecordingWorker  ─► ClipRecorder → .mp4 → Google Drive
        ├─► RecognitionWorker ─► identidades → TrackRegistry
        └─► DetectionWorker (YOLO → ByteTrack → LineZone)
                 │                    │
                 ├─► TrackRegistry ◄──┘  (estado compartido entre workers)
                 └─► event_queue ─► database.py ─► WebSocket ─► app.js
```

### Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Sirve `index.html` |
| GET | `/video_feed` | Stream MJPEG |
| WS | `/ws` | Push de eventos en tiempo real (JSON) |
| GET | `/api/stats` | Resumen: total hoy, por hora (últimas 24 h) |
| GET | `/api/v2/cameras/{id}/health` | Salud del pipeline: `capture_fps` y `detection_fps` (distintos a propósito), estado de workers, `degraded`, stats del broker |

### Modelo de evento (WebSocket / API)

```json
{
  "type": "detection",
  "timestamp": "2026-04-16T18:30:00",
  "total_today": 42,
  "last_hour": 7
}
```

## Decisiones de diseño

- **MJPEG sobre HTTP** en lugar de WebRTC para simplicidad: no requiere STUN/TURN y funciona en LAN sin latencia perceptible.
- **YOLO26n** (nano) para mantener la inferencia baja en CPU modesta. Si hay GPU disponible, subir de modelo.
- **Línea virtual de conteo** en lugar de contar detecciones por frame: evita contar la misma persona varias veces mientras está en escena.
- **SQLite** es suficiente para el volumen de datos (pocos eventos/hora); no se necesita PostgreSQL.
- El frontend es HTML estático servido por FastAPI; no hay build step ni framework JS pesado.
- **Perder frames antes que acumular latencia**: el broker entrega solo el último frame a cada suscriptor. `dropped` creciente en `/api/v2/.../health` es señal de buen funcionamiento, no de error.
- **Ningún hilo hace `await`, ninguna corrutina hace inferencia**: invariante verificado por `tests/test_architecture.py` con análisis AST.

## Variables de entorno (`.env`)

```
CAMERA_URL=rtsp://192.168.1.132:554/stream1
YOLO_CONFIDENCE=0.45
DB_PATH=data/events.db
HOST=0.0.0.0
PORT=8000
```

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Tapo Dashboard**

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta personas en tiempo real con YOLOv8 y muestra estadísticas de actividad: personas contadas hoy, histograma de actividad por hora, y feed de vídeo en directo con las detecciones marcadas. Todo accesible desde cualquier dispositivo de la red local sin depender de la nube.

**Core Value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo integrado en el mismo panel.

### Constraints

- **Hardware**: Sin GPU dedicada confirmada — YOLOv8n para mantener inferencia <50 ms en CPU
- **Red**: Solo LAN — no se diseña para exposición pública
- **Stack**: Python 3.11+, FastAPI, OpenCV, Ultralytics YOLOv8, SQLite, HTML+JS vanilla con Chart.js
- **Streaming**: MJPEG sobre HTTP (no WebRTC) — suficiente para LAN, sin infraestructura de señalización
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

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
- **38.9 ms en CPU** vs 56.1 ms de YOLO11n (y peor aún para YOLOv8n)
- **Sin NMS**: inferencia nativa end-to-end, menos código, menos latencia
- **Mismo paquete**: `pip install ultralytics`, misma API `YOLO("yolo26n.pt")`
- **22% menos parámetros** que YOLOv8n con precisión igual o superior
### Por qué supervision en vez de implementar el conteo a mano
- Asigna IDs únicos a cada persona detectada (tracking)
- Cuenta cruces en ambas direcciones (in/out)
- Soporta conteo por clase desde v0.27
- Evita el error clásico de contar la misma persona múltiples veces

### Repo fuente de supervision
Clonado (shallow, no versionado — ver `.gitignore`) en `third_party/supervision/` para consultar código fuente y ejemplos: https://github.com/roboflow/supervision
### Por qué pydantic-settings y no python-dotenv
### Patrón correcto para MJPEG en FastAPI
### Notas sobre OpenCV con cámaras Tapo
- La Tapo C220 soporta RTSP en `rtsp://user:pass@IP:554/stream1` (alta resolución) y `stream2` (baja resolución)
- **Usar `stream2`** (720p) para detección: reduce carga de CPU sin afectar la precisión de YOLO26n a 640px
- `cv2.VideoCapture` con RTSP sobre TCP es más fiable que UDP en redes WiFi: usar `cv2.CAP_PROP_FOURCC` o el parámetro `?tcp` en la URL no siempre funciona; la forma robusta es `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)` para evitar acumulación de frames
- Si la conexión se pierde, `cap.read()` devuelve `(False, None)`. Hay que implementar reconexión automática con backoff
## Installation
# Crear entorno virtual
# Core
# Visión
# Base de datos
# Configuración
# Frontend (Chart.js via CDN, no se instala)
# <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1"></script>
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

- **Python 3.12** obligatorio. Crear venv con `py -3.12 -m venv .venv`. Activar con `.venv/Scripts/activate` (Windows).
- **Imports directos** con `.venv/Scripts/python.exe` en scripts de verificacion para evitar problemas de activacion en subshells.
- **Modulos placeholder**: solo docstring de una linea, sin funciones vacias. Cada fichero importable sin error.
- **requirements.txt** con `>=` (no pins exactos). Sin `databases` (encode) ni `python-dotenv`.
- **Config**: `backend/config.py` con `pydantic-settings` BaseSettings + `@lru_cache` para singleton.
- **No pyproject.toml** hasta Phase 8. No Docker, no pre-commit hooks en v1.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

- **Entorno**: Windows 11, Python 3.12 via `py -3.12`, venv en `.venv/` (Scripts/, no bin/)
- **Estructura**: `backend/` (main, pipeline/, detector, tracker, recognizer, recorder, database, config), `frontend/` (index.html, app.js), `tests/`, `data/`
- **Flujo de datos**: Camara RTSP → CaptureWorker → FrameBroker → {Detection, Streaming, Recording, Recognition} workers → TrackRegistry / event_queue → database.py (SQLite async) → WebSocket → frontend
- **Streaming**: MJPEG sobre HTTP via FastAPI StreamingResponse
- **DB**: SQLite WAL mode, aiosqlite + SQLAlchemy 2.0 async
- **Frontend**: HTML+JS vanilla, Chart.js CDN, sin build step
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
