# CLAUDE.md

## Objetivo

Dashboard local para monitorizar una Tapo C212:
RTSP → captura → detección/tracking → eventos → SQLite/WebSocket → dashboard.

Prioridades: **baja latencia, estabilidad, CPU moderada y simplicidad**.

## Reglas de trabajo

- Respuestas **breves y directas**; resultado primero.
- No repetir código, diffs, logs ni contexto ya visible.
- En tests: solo resultado (`176/176`, `OK`, etc.), salvo fallos relevantes.
- Explicar solo decisiones no obvias, riesgos, trade-offs o lo pedido.
- No añadir dependencias, frameworks o infraestructura sin necesidad.
- Verificar código/tests antes de modificar arquitectura.
- No inventar APIs, rutas, variables, archivos o comportamiento.
- Windows 11 + Python 3.12.
- Nunca exponer credenciales RTSP en código, logs, commits o respuestas.

### GSD

Antes de editar, usar:
- `/gsd:quick` → cambios pequeños/documentación.
- `/gsd:debug` → bugs/investigación.
- `/gsd:execute-phase` → trabajo planificado.

No editar fuera de GSD salvo petición explícita.

## Stack / restricciones

| Área | Decisión |
|---|---|
| Runtime | Python 3.12 |
| Backend | FastAPI + Uvicorn |
| Captura | OpenCV / `cv2.VideoCapture` |
| Detección | Ultralytics YOLO26n |
| Tracking | supervision + ByteTrack |
| Conteo | `LineZone` / cruce de línea |
| DB | SQLite + SQLAlchemy 2 async + aiosqlite |
| Config | pydantic-settings |
| Streaming | MJPEG HTTP |
| Tiempo real | WebSocket |
| Frontend | HTML + JS vanilla |
| Gráficas | Chart.js CDN |
| Red | LAN; no exposición pública |
| GPU | No asumir GPU dedicada |

No introducir WebRTC, Docker, PostgreSQL, React/Vue, bundlers ni capas equivalentes sin decisión explícita.

## Arquitectura

```text
RTSP
  │
  ▼
CaptureWorker
  │
  ▼
FrameBroker (latest-frame, 1 slot/suscriptor)
  ├──► StreamingWorker ──► /video_feed ──► dashboard
  ├──► RecordingWorker ──► ClipRecorder
  ├──► RecognitionWorker ─► TrackRegistry
  └──► DetectionWorker
          └─► YOLO26n → ByteTrack → LineZone
                    │
                    ├─► TrackRegistry
                    └─► event_queue → SQLite → WebSocket → frontend
```

### Invariantes críticos

1. La captura **nunca espera a la IA**.
2. Cada worker consume del broker a su ritmo.
3. Se descartan frames antes que acumular latencia.
4. `dropped` creciente en `/api/v2/cameras/{id}/health` puede ser normal.
5. Ningún hilo hace `await`.
6. Ninguna corrutina ejecuta inferencia.
7. Tracks compartidos → `TrackRegistry`.
8. RTSP debe reconectar con backoff.
9. Conteo = tracking/cruce, no suma de detecciones por frame.
10. Los tests de arquitectura deben proteger estas reglas.

## Estructura

```text
backend/
  main.py
  config.py
  detector.py
  tracker.py
  recognizer.py
  recorder.py
  database.py
  pipeline/
    broker.py capture.py detection.py streaming.py
    recording.py recognition.py tracking.py rate.py
    supervisor.py manager.py
frontend/
  index.html app.js
tests/
data/
```

Responsabilidades:

- `broker.py`: fan-out del último frame.
- `capture.py`: RTSP, captura, resize y publicación.
- `detection.py`: YOLO, tracking, zonas/heatmap.
- `streaming.py`: overlay + JPEG + MJPEG.
- `recording.py`: alimentación del grabador.
- `recognition.py`: reconocimiento a su propio ritmo.
- `tracking.py`: estado compartido.
- `rate.py`: FPS adaptativo por latencia.
- `supervisor.py`: reinicio/mode degradado.
- `manager.py`: `CameraPipeline` + N cámaras.

## API

| Método | Ruta | Uso |
|---|---|---|
| GET | `/` | Dashboard |
| GET | `/video_feed` | MJPEG |
| WS | `/ws` | Eventos |
| GET | `/api/stats` | Estadísticas |
| GET | `/api/v2/cameras/{id}/health` | Salud del pipeline |

Evento:

```json
{
  "type": "detection",
  "timestamp": "2026-04-16T18:30:00",
  "total_today": 42,
  "last_hour": 7
}
```

`health` distingue `capture_fps` y `detection_fps` por diseño.

## Configuración

```text
CAMERA_URL
YOLO_CONFIDENCE=0.45
DB_PATH=data/events.db
HOST=0.0.0.0
PORT=8000
```

- `backend/config.py`: `pydantic-settings` + `BaseSettings` + `@lru_cache`.
- No usar `python-dotenv`.
- No hardcodear credenciales.
- Preferir `stream2` para detección cuando sea suficiente.
- Mantener bajo el buffer de captura para evitar frames antiguos.

## Comandos

Desde la raíz del proyecto:

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt

.venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

.venv/Scripts/python.exe -m pytest tests/ -v

.venv/Scripts/python.exe -m pytest tests/test_detector.py -v
```

Para RTSP, usar `CAMERA_URL` desde configuración; no copiar credenciales al comando/chat.

## Código y rendimiento

- Python 3.12 obligatorio; venv en `.venv/`.
- `requirements.txt`: `>=`, no pins exactos salvo necesidad.
- No `databases` (encode), Docker, pre-commit ni `pyproject.toml` antes de la fase prevista.
- Módulos placeholder: docstring de una línea e importables.
- Mantener workers desacoplados.
- Preferir cambios pequeños y verificables.
- No colas ilimitadas de frames.
- Evitar copias de imágenes innecesarias.
- Detector puede ir a menor FPS que captura.
- Streaming/grabación no bloquean detección.
- Medir latencia/FPS reales antes de optimizar.
- RTSP perdido → backoff + reconexión recuperable.
- No ejecutar CPU pesado en el event loop.
- No crear estado global oculto.

## Frontend

HTML + JS vanilla, sin build step. Chart.js por CDN. WebSocket para eventos y MJPEG para vídeo. Priorizar vídeo, personas, actividad y salud. Evitar dependencias visuales innecesarias.

## Tests

Antes de terminar:
1. Tests afectados.
2. Suite completa si toca pipeline, arquitectura, API o configuración.
3. Corregir fallos, no ocultarlos.
4. Mantener `tests/test_architecture.py` como barrera contra `await`/inferencia en workers y acoplamiento captura↔IA.
5. Reportar solo el resultado relevante.

## Criterios de diseño

**Preferir:** simplicidad, desacoplamiento, latest-frame, degradación controlada, configuración explícita, observabilidad y tests de invariantes.

**Evitar:** overengineering, abstracciones prematuras, dependencias nuevas por funciones pequeñas, buffers que añadan latencia, CPU pesada en el event loop, estado global oculto y lógica duplicada.

## Jerarquía de fuentes

1. Código + tests actuales.
2. Requisitos explícitos del usuario.
3. Este `CLAUDE.md`.
4. Documentación/GSD.
5. Conocimiento externo.

Si hay contradicción, verificar antes de asumir. Actualizar este documento cuando el código haya cambiado de forma relevante.

## Regla final

> Implementa el cambio mínimo que resuelva el problema sin aumentar innecesariamente latencia, complejidad o acoplamiento.
