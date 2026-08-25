---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 07
subsystem: backend
tags: [fastapi, lines, crud, validation, hot-reload]

# Dependency graph
requires:
  - phase: 33-01
    provides: "LineRepo (list/upsert/delete/_to_dict) — ya cerrado antes de este plan"
  - phase: 33-05
    provides: "CameraPipeline.set_lines() para hot-reload sin reiniciar — ya cerrado antes de este plan"
provides:
  - "backend/api/v2/lines.py — router, configure(camera_manager), _line_repo() — CRUD de lineas contra LineRepo con validacion de rango/longitud minima"
affects: ["33-08 (wiring de configure(camera_manager) desde el lifespan de main.py)", "33-11 (frontend consumidor, ya construido, espera el shape nativo de error 422 de FastAPI)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Modelo Pydantic tipado normal (LineIn) como parametro FastAPI, sin el patron try/except de config.py/rules.py — shape nativo de error 422 de FastAPI, mismo contrato que /api/v2/zones (33-03), consumido literal por el frontend de 33-11"
    - "@model_validator(mode=\"after\") para la validacion de longitud minima (distancia euclidea entre start/end), separado de los @field_validator de rango por coordenada"

key-files:
  created:
    - backend/api/v2/lines.py
    - tests/test_lines_api.py
  modified: []

key-decisions:
  - "Longitud minima 0.001 en fraccion normalizada (no en pixeles) — coherente con el resto de coordenadas del router, que ya viven en [0,1]"
  - "camera_id por defecto \"cam1\" (igual que zones.py) para mantener el mismo contrato entre editores visuales de la Fase 33"

patterns-established: []

requirements-completed: [OPS-22]

# Metrics
duration: ~15min
completed: 2026-08-24
---

# Phase 33 Plan 07: Router /api/v2/lines Summary

**CRUD de lineas de conteo sobre `LineRepo`, con validacion de rango `[0,1]` por coordenada y de longitud minima (rechaza lineas degeneradas) vía `@model_validator`, y hot-reload multi-cámara idéntico al patrón de `/api/v2/zones`.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 1/1 completada
- **Files modified:** 2 (ambos nuevos)

## Accomplishments
- `backend/api/v2/lines.py`: router `prefix="/api/v2/lines"` con `GET`, `POST` (upsert), `DELETE /{line_id}`, todos con `@limiter.limit(V2_RATE_LIMIT)`.
- `LineIn` valida cada `*_frac` en `[0,1]` con `@field_validator`, y rechaza líneas degeneradas (distancia euclídea start→end `< 0.001`) con `@model_validator(mode="after")` — mensaje `"linea degenerada: inicio y fin son el mismo punto"`.
- `POST`/`DELETE` tipan `body: LineIn` directamente (sin el patrón try/except de `config.py`/`rules.py`) — shape nativo de error 422 de FastAPI, tal como exige el contrato ya consumido por el frontend de 33-11.
- `_push_hot_reload()` empuja `line_repo.list(camera_id=pipeline.camera_id)` a `pipeline.set_lines(...)` para cada pipeline vivo — sin transformar el shape de `LineRepo._to_dict()`.
- Sin `camera_manager` configurado (`configure(None)`, estado por defecto y en tests), el CRUD sigue funcionando sin excepción.

## Task Commits

Each task was committed atomically (RED/GREEN, `tdd="true"`):

1. **Task 1 — RED: tests fallidos** - `5e8d7b6` (test)
2. **Task 1 — GREEN: implementación del router** - `140484e` (feat)

**Plan metadata:** (este commit, pendiente)

## Files Created/Modified
- `backend/api/v2/lines.py` (123 líneas) — router, `configure()`, `_line_repo()`, `LineIn`, `_push_hot_reload()`, 3 endpoints.
- `tests/test_lines_api.py` (156 líneas) — 8 tests contra una app FastAPI local con `LineRepo`/`CameraManager` mockeados vía `patch.object`, mismo patrón que `tests/test_zones_api.py`.

## Decisions Made
- Verificación de RED real: se renombró temporalmente `backend/api/v2/lines.py` (ya escrito en disco) a `.bak`, se confirmó el `ImportError` de colección de pytest, se restauró el fichero y se relanzó en verde — cumple el gate fail-fast de la ejecución TDD a nivel de plan.
- Se replicó el molde de `zones.py` casi literal (mismo `_camera_manager`/`configure()`/`_push_hot_reload()`), sustituyendo `polygon`/`kind`/`schedule` por el segmento de dos puntos y su validación de longitud mínima.

## Deviations from Plan

None — el plan ya llegaba con la nota de contrato de error 422 nativo aplicada (`LineIn` tipado directo, sin try/except), y se implementó literalmente tal cual estaba escrito.

## Issues Encountered

Ninguno. Suite completa relanzada al tocar un router de `/api/v2` (regla de `CLAUDE.md`): `766 passed, 2 skipped` en 207.19s, sin regresiones.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `backend/api/v2/lines.py` listo para que el Plan 33-08 lo registre con `app.include_router()` y llame `configure(camera_manager)` desde el lifespan.
- El contrato de error 422 nativo de FastAPI ya coincide exactamente con lo que el frontend de 33-11 espera — sin cambios pendientes de ese lado.
- Sin bloqueos conocidos para 33-08.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: backend/api/v2/lines.py
- FOUND: tests/test_lines_api.py
- FOUND: 5e8d7b6
- FOUND: 140484e
