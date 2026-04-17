---
phase: 02-captura-rtsp-y-stream-mjpeg
plan: 01
subsystem: streaming
tags: [opencv, rtsp, threading, drain-pattern, reconnection, backoff]

requires:
  - phase: 01-scaffolding-y-entorno
    provides: backend/config.py con Settings y get_settings()
provides:
  - RTSPStream class con drain thread, reconexion con backoff, y get_frame() thread-safe
affects: [02-02, 03-deteccion-yolo]

tech-stack:
  added: [opencv-python (cv2.VideoCapture)]
  patterns: [drain thread pattern, exponential backoff reconnection, lock-protected frame copy]

key-files:
  created: [backend/stream.py, tests/conftest.py, tests/test_stream.py]
  modified: []

key-decisions:
  - "Local cap reference en capture_loop para evitar race condition con stop()"
  - "Event-based synchronization en test_backoff_increases en vez de time.sleep"

patterns-established:
  - "Drain thread: hilo daemon lee frames en bucle y guarda solo el ultimo bajo lock"
  - "Reconexion: release + new VideoCapture con backoff exponencial (nunca reutilizar cap tras fallo)"
  - "Thread safety: get_frame() devuelve .copy() bajo threading.Lock"

requirements-completed: [CAP-01, CAP-02]

duration: 4min
completed: 2026-04-16
---

# Phase 2 Plan 1: Captura RTSP y stream MJPEG - RTSPStream Summary

**RTSPStream con drain thread daemon, reconexion automatica con backoff exponencial (1-30s), y acceso thread-safe al ultimo frame via get_frame()**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-16T22:15:06Z
- **Completed:** 2026-04-16T22:19:00Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 3

## Accomplishments
- Clase RTSPStream con patron drain thread que lee frames RTSP en bucle descartando todos excepto el ultimo
- Reconexion automatica con backoff exponencial de 1s a 30s cuando la camara se desconecta
- get_frame() devuelve copia thread-safe del frame, None si no hay frame disponible
- 6 tests unitarios con mocks de cv2.VideoCapture (sin camara real)

## Task Commits

1. **Task 1: Tests unitarios y fixtures (RED)** - `3289eb3` (test)
2. **Task 2: Implementar RTSPStream (GREEN)** - `20d2c97` (feat)

## Files Created/Modified
- `backend/stream.py` - RTSPStream: drain thread + reconexion + get_frame()
- `tests/conftest.py` - Fixtures fake_frame y mock_video_capture compartidas
- `tests/test_stream.py` - 6 tests: drain, copy, reconnect, backoff, stop, none-before-start

## Decisions Made
- Referencia local a `_cap` en el bucle de captura para evitar race condition cuando `stop()` pone `_cap = None` mientras el hilo lee
- En el test de backoff, uso de `threading.Event` para sincronizar en vez de `time.sleep` (que estaba parcheado por el mock)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Race condition entre stop() y _capture_loop()**
- **Found during:** Task 2 (implementacion GREEN)
- **Issue:** `stop()` pone `self._cap = None`, pero el hilo de captura podia leer `self._cap` entre la comprobacion `is None` y el `.read()`, causando `AttributeError: 'NoneType'`
- **Fix:** Variable local `cap = self._cap` al inicio de cada iteracion del bucle
- **Files modified:** backend/stream.py
- **Verification:** 6 tests pasan sin warnings de thread exception
- **Committed in:** 20d2c97

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Fix necesario para correccion. Sin scope creep.

## Issues Encountered
- Test `test_backoff_increases` fallaba inicialmente porque `time.sleep(0.5)` en el test estaba parcheado junto con `backend.stream.time.sleep`. Resuelto usando `threading.Event` para sincronizacion.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RTSPStream listo para ser consumido por el generador MJPEG (plan 02-02)
- API: `RTSPStream(url).start()` / `.get_frame()` / `.stop()`
- El endpoint `/video_feed` del plan 02-02 leera frames via `get_frame()`

---
*Phase: 02-captura-rtsp-y-stream-mjpeg*
*Completed: 2026-04-16*
