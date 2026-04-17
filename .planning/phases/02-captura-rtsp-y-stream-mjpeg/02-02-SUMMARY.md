---
phase: 02-captura-rtsp-y-stream-mjpeg
plan: 02
subsystem: api
tags: [fastapi, mjpeg, streaming, rtsp, asyncio, pytest-asyncio]

# Dependency graph
requires:
  - phase: 02-01
    provides: RTSPStream con drain thread, start/stop/get_frame API

provides:
  - FastAPI app con lifespan startup/shutdown
  - Endpoint GET /video_feed que sirve stream MJPEG multipart/x-mixed-replace
  - mjpeg_generator async con JPEG quality 80 y sleep 0.033s
  - 9 tests unitarios + integracion todos GREEN

affects: [03-deteccion-yolo, 04-conteo-y-tracking, 05-websocket-y-dashboard]

# Tech tracking
tech-stack:
  added: [pytest-asyncio>=0.23, fastapi StreamingResponse, asynccontextmanager lifespan]
  patterns:
    - lifespan context manager para gestionar RTSPStream global en FastAPI
    - mjpeg_generator como async generator con CancelledError handling
    - Tests de streaming con finite generator mock (patch mjpeg_generator)
    - ASGITransport + httpx.AsyncClient para tests de integracion async

key-files:
  created: []
  modified:
    - backend/main.py
    - tests/test_stream.py
    - requirements.txt

key-decisions:
  - "Tests de streaming con finite generator mock: patch mjpeg_generator en lugar de patch RTSPStream, evita colgarse en el infinite loop"
  - "rtsp_stream como global en main.py (no app.state): compatible con el generador async y mas simple"

patterns-established:
  - "Infinite MJPEG generator: CancelledError capturado, sleep 0.033s para ceder control al event loop"
  - "Tests async de streaming: reemplazar el generador por version finita via patch.object"

requirements-completed: [CAP-03]

# Metrics
duration: 20min
completed: 2026-04-17
---

# Phase 02 Plan 02: FastAPI /video_feed MJPEG endpoint Summary

**FastAPI app con lifespan RTSPStream, endpoint /video_feed MJPEG multipart/x-mixed-replace, 9 tests GREEN incluyendo 3 de integracion async**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-17T06:28:15Z
- **Completed:** 2026-04-17T06:48:06Z
- **Tasks:** 1 de 2 completadas autonomamente (Task 2 es checkpoint:human-verify)
- **Files modified:** 3

## Accomplishments

- `backend/main.py` implementado con FastAPI app, lifespan asynccontextmanager, RTSPStream global
- Endpoint `GET /video_feed` retorna `StreamingResponse` con `multipart/x-mixed-replace; boundary=frame`
- `mjpeg_generator` codifica frames JPEG quality 80, sleep 0.033s (~30fps), manejo limpio de CancelledError
- 9 tests pasan: 6 unitarios de RTSPStream + 3 de integracion del endpoint
- Servidor uvicorn arrancado en http://0.0.0.0:8000, reconexion RTSP activa

## Task Commits

1. **Task 1: Implementar main.py con FastAPI, lifespan y endpoint /video_feed** - `a71cf16` (feat)

**Task 2 (checkpoint:human-verify):** Pendiente de verificacion manual del usuario.

## Files Created/Modified

- `backend/main.py` - FastAPI app con lifespan, mjpeg_generator y endpoint /video_feed
- `tests/test_stream.py` - Agrega 3 tests de integracion async (content-type, boundary, startup)
- `requirements.txt` - Agrega pytest-asyncio>=0.23

## Decisions Made

- Tests de streaming con patch sobre `mjpeg_generator` (finite version) en lugar de patch sobre RTSPStream: evita que el test se cuelgue con el generador infinito. La alternativa de `asyncio.wait_for` con timeout fallaba porque `ASGITransport` propaga `CancelledError` como `TimeoutError` antes de que el cliente pueda leer headers.
- `rtsp_stream` como variable global en `main.py`: el generador async accede directamente sin necesitar `app.state`, mas simple y funciona con el patron lifespan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pytest-asyncio ausente en requirements.txt**
- **Found during:** Task 1 (verificacion pre-TDD)
- **Issue:** `pytest-asyncio` no estaba instalado ni en requirements.txt, necesario para `@pytest.mark.asyncio`
- **Fix:** `pip install pytest-asyncio`, agregado `pytest-asyncio>=0.23` a requirements.txt
- **Files modified:** requirements.txt
- **Verification:** `.venv/Scripts/python.exe -c "import pytest_asyncio"` OK
- **Committed in:** a71cf16 (Task 1 commit)

**2. [Rule 1 - Bug] Tests de streaming se colgaban con el generador infinito**
- **Found during:** Task 1 (TDD GREEN — intento inicial de tests)
- **Issue:** Tests con `client.stream()` + `asyncio.wait_for()` se colgaban o fallaban con TimeoutError porque ASGITransport no soporta cancelacion limpia durante streaming
- **Fix:** Rediseno de los tests de content-type y boundary para parchear `mjpeg_generator` con una version finita que emite un frame y termina; el test de startup invoca `lifespan` directamente sin streaming
- **Files modified:** tests/test_stream.py
- **Verification:** 9/9 tests GREEN en <1s
- **Committed in:** a71cf16 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Ambos necesarios para que los tests funcionen. Sin scope creep.

## Issues Encountered

- pytest-asyncio mode=STRICT requiere `@pytest.mark.asyncio` explicito en cada test async — manejado correctamente en los 3 tests nuevos.

## User Setup Required

None — no external service configuration required beyond cámara Tapo encendida para verificacion manual.

## Next Phase Readiness

- `backend/main.py` exporta `app` (FastAPI instance) listo para que Phase 03 agregue el pipeline YOLO
- El endpoint `/video_feed` es el punto de integracion visual; Phase 03 modificara `mjpeg_generator` para superponer bounding boxes
- Servidor uvicorn corriendo en http://0.0.0.0:8000 — Task 2 (checkpoint) requiere verificacion visual del usuario

## Self-Check: PASSED

- backend/main.py: FOUND
- tests/test_stream.py: FOUND
- 02-02-SUMMARY.md: FOUND
- commit a71cf16: FOUND

---
*Phase: 02-captura-rtsp-y-stream-mjpeg*
*Completed: 2026-04-17*
