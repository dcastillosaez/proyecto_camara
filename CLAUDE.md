# CLAUDE.md

## Objetivo

Dashboard local para monitorizar una Tapo C212:
RTSP → captura → detección/tracking → eventos → SQLite/WebSocket → dashboard.

Prioridades: **baja latencia, estabilidad, CPU moderada y simplicidad**.

## Reglas de trabajo

- Reportar los tests solo con el resultado (`176/176`, `OK`), salvo fallos relevantes.
- Verificar código y tests antes de modificar arquitectura. No inventar APIs, rutas, variables ni comportamiento.
- No añadir dependencias, frameworks o infraestructura sin necesidad.
- Windows 11 + Python 3.12; venv en `.venv/`.
- Nunca exponer credenciales RTSP en código, logs, commits o respuestas. Usar `CAMERA_URL` desde configuración.
- Trabajar siempre en la raíz del repositorio, nunca en `.claude/worktrees/*`, y no crear worktrees nuevos: no comparten `.env` ni `.venv/`, y el backend arranca sin imagen. Las ramas se usan con normalidad.

### Planificación

GSD ya no es obligatorio. `.planning/` se conserva como documentación: al cerrar trabajo relevante, actualizar `STATE.md` a mano. Los subagentes `gsd-*` están en `~/.claude/_desactivado/agents-gsd-proyecto-camara/` por si vuelve un milestone grande.

Para el estado del proyecto, leer `.planning/STATE.md`, la única fuente de qué está completo y qué falta. `ROADMAP.md`, `REQUIREMENTS.md`, `propuesta_mejora/SPEC_v2.md` y `.planning/STATE-archive.md` (historial) solo se abren si hace falta un detalle concreto, y este último con Grep.

## Stack

| Área | Decisión |
|---|---|
| Backend | FastAPI + Uvicorn |
| Captura | OpenCV / `cv2.VideoCapture` |
| Detección | Ultralytics YOLO26n |
| Tracking y conteo | supervision: ByteTrack + `LineZone` |
| DB | SQLite + SQLAlchemy 2 async + aiosqlite (PostgreSQL y Redis opcionales con `database_url` y `redis_url`) |
| Config | pydantic-settings (`backend/config.py`), sin `python-dotenv` |
| Tiempo real | MJPEG HTTP + WebSocket |
| Frontend | HTML + JS vanilla (módulos ES), sin build step; Chart.js y Tailwind por CDN |
| Red | LAN; no exposición pública |
| GPU | No asumir GPU dedicada; `inference_device` cae a CPU |

No introducir WebRTC, React/Vue, bundlers ni capas equivalentes sin decisión explícita. SQLite sigue siendo el backend por defecto.

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
3. Se descartan frames antes que acumular latencia; `dropped` creciente en `/api/v2/cameras/{id}/health` puede ser normal.
4. Ningún hilo hace `await`.
5. Ninguna corrutina ejecuta inferencia ni CPU pesada.
6. Tracks compartidos → `TrackRegistry`.
7. RTSP perdido → reconexión con backoff.
8. Conteo = tracking/cruce, no suma de detecciones por frame.
9. `tests/test_architecture.py` protege estas reglas.

## Estructura

```text
backend/
  main.py config.py detector.py tracker.py recognizer.py recorder.py database.py
  api/v2/         routers REST
  pipeline/       workers, broker, supervisor y manager (N cámaras)
  events/         motor de eventos, reglas y acciones
  perception/     comportamiento, objetos, rostro y ReID
  inference/      selección de dispositivo
  observability/  métricas y latencia
  storage/        modelos, migraciones y repositorios
frontend/         index.html, css/, js/ (views/, components/)
tests/            tests/e2e = Playwright
data/
```

Las rutas se localizan en `backend/main.py` y `backend/api/v2/`; los parámetros y sus valores por defecto, en `backend/config.py`. `/api/v2/cameras/{id}/health` distingue `capture_fps` y `detection_fps` por diseño.

## Comandos

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt

.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

.venv/Scripts/python.exe -m pytest tests/ -q
```

## Código

- `requirements.txt`: `>=`, sin pins exactos salvo necesidad.
- Workers desacoplados; sin colas de frames ilimitadas ni estado global oculto.
- Evitar copias de imágenes innecesarias. Preferir `stream2` para detección y mantener bajo el buffer de captura.
- Medir latencia y FPS reales antes de optimizar.
- Sin abstracciones prematuras ni dependencias nuevas para funciones pequeñas.

## Tests

Durante la iteración, solo el fichero o `-k <patrón>` afectado: la suite completa tarda minutos y no aporta nada hasta terminar el cambio.

Antes de terminar, pasar los tests afectados, y la suite completa si el cambio toca pipeline, arquitectura, API o configuración. Corregir los fallos, no ocultarlos.

## Jerarquía de fuentes

1. Código + tests actuales.
2. Requisitos explícitos del usuario.
3. Este `CLAUDE.md`.
4. Documentación/GSD.
5. Conocimiento externo.

Si hay contradicción, verificar antes de asumir. Actualizar este documento cuando el código cambie de forma relevante.

## Regla final

> Implementa el cambio mínimo que resuelva el problema sin aumentar innecesariamente latencia, complejidad o acoplamiento.
