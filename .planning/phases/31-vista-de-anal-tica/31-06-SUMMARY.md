---
phase: 31-vista-de-anal-tica
plan: 06
subsystem: api
tags: [fastapi, opencv, heatmap, rate-limit, camera-pipeline]

# Dependency graph
requires:
  - phase: 31-02
    provides: "compose_heatmap() con INFERNO y DetectionWorker.heatmap_scale() -> {peak, mean} | None"
  - phase: 31-05
    provides: "backend/api/v2/analytics.py con /hourly, /summary, /occupancy, /persons y el molde del router"
provides:
  - "GET /api/v2/analytics/heatmap — JPEG del mapa de calor compuesto sobre el ultimo frame"
  - "GET /api/v2/analytics/heatmap/scale — peak/mean/unit de la mascara acumulada"
  - "CameraPipeline.get_heatmap_scale() — pasarela hacia DetectionWorker.heatmap_scale()"
affects: [31-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "503 antes que 404: primero se comprueba pipeline/frame (sin senal), despues el resultado de compose/scale (sin actividad) — mismo orden en los dos endpoints"
    - "OpenCV pesado (compose_heatmap) siempre en asyncio.to_thread, igual que /api/heatmap v1 en main.py"

key-files:
  created: []
  modified:
    - backend/api/v2/analytics.py
    - backend/pipeline/manager.py
    - tests/test_analytics_api.py

key-decisions:
  - "El endpoint v1 /api/heatmap y backend/main.py no se tocan: sigue existiendo sin cambios y hereda INFERNO por compartir compose_heatmap con el v2 (decision ya tomada en 31-02)"
  - "unit va en el JSON de /heatmap/scale, no como constante fija del cliente, para que quien lea la respuesta cruda vea la unidad junto al numero (frames de deteccion con presencia, no personas)"
  - "/heatmap y /heatmap/scale no aceptan from/to: el heatmap no respeta el rango de la vista por D-12, y aceptar el parametro para ignorarlo mentiria en la firma"

patterns-established: []

requirements-completed: [OPS-12]

# Metrics
duration: 18min
completed: 2026-08-23
---

# Phase 31 Plan 06: Heatmap v2 (JPEG + escala) Summary

**GET /api/v2/analytics/heatmap (JPEG compuesto) y GET /api/v2/analytics/heatmap/scale (peak/mean/unit), con 503 (sin camara) y 404 (sin actividad) como dos respuestas distintas, a diferencia del /api/heatmap v1 que las funde en un solo 404.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-08-23T11:40:00Z
- **Completed:** 2026-08-23T11:58:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `CameraPipeline.get_heatmap_scale()` nuevo, pasarela con la misma guarda `if self.detection` que el resto del fichero
- `GET /api/v2/analytics/heatmap` devuelve JPEG calidad 85, `GET /api/v2/analytics/heatmap/scale` devuelve `{peak, mean, unit}`, ambos con `@limiter.limit(V2_RATE_LIMIT)` y comprobando pipeline/frame antes que actividad
- Ninguna composicion de OpenCV ocurre en el event loop: `get_frame()` es lectura barata sin `to_thread`, `get_heatmap`/`get_heatmap_scale` si van por `asyncio.to_thread`
- 6 tests nuevos con un doble minimo de pipeline (`MagicMock` con `get_frame`/`get_heatmap`/`get_heatmap_scale` parametrizables) cubren los cuatro caminos del heatmap y los dos de la escala, incluida la comprobacion del JPEG real (`resp.content[:2] == b"\xff\xd8"`)
- `/api/heatmap` v1 y `backend/main.py` sin cambios; suite completa **664 passed, 2 skipped**

## Task Commits

Each task was committed atomically:

1. **Task 1: get_heatmap_scale() en CameraPipeline y los dos endpoints v2** - `ff2bb38` (feat)
2. **Task 2: Tests de los dos endpoints con un pipeline doble** - `04f8164` (test)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `backend/pipeline/manager.py` - `get_heatmap_scale()` nuevo, justo despues de `get_heatmap()`
- `backend/api/v2/analytics.py` - dos endpoints `/heatmap` y `/heatmap/scale`, import de `cv2`/`Response`, docstring del modulo actualizado
- `tests/test_analytics_api.py` - bloque de 6 tests `TEST_heatmap_*` con doble de pipeline y helper `_heatmap_manager()`

## Decisions Made
Ninguna fuera de las ya fijadas en el plan (ver `key-decisions` en el frontmatter). Se siguio el orden de comprobaciones del bloque `<interfaces>` al pie de la letra.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Los dos endpoints del contrato de `<interfaces>` estan listos para que 31-10 los consuma en el panel 3: `GET /api/v2/analytics/heatmap` para el `<img>` y `GET /api/v2/analytics/heatmap/scale` para la leyenda numerica (0 / 50% / pico como constantes del cliente, valor absoluto en el `title`). Recordar en 31-10 que la unidad es "frames de deteccion con presencia", no personas.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
