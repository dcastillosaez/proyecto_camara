---
phase: 31-vista-de-anal-tica
plan: 02
subsystem: pipeline
tags: [opencv, heatmap, colormap, detection-worker]

# Dependency graph
requires:
  - phase: 18-desacoplar-pipeline
    provides: "DetectionWorker.compose_heatmap() y _heat_mask acumulado bajo self._lock"
provides:
  - "compose_heatmap() con rampa perceptualmente uniforme COLORMAP_INFERNO en vez de JET"
  - "DetectionWorker.heatmap_scale() -> {peak, mean} | None, lectura thread-safe puntual"
affects: [31-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lectura puntual thread-safe: copiar el estado mutable bajo self._lock, calcular fuera del lock (mismo molde que get_object_boxes/compose_heatmap)"

key-files:
  created: []
  modified:
    - backend/pipeline/detection.py
    - tests/test_detection_worker.py

key-decisions:
  - "heatmap_scale() devuelve None tanto sin mascara como con pico 0, mismo criterio que compose_heatmap, para que el endpoint de 31-06 distinga 404 (sin actividad) de 503 (sin frame)"
  - "El endpoint v1 /api/heatmap y backend/main.py no se tocan en este plan; heredan INFERNO por reusar compose_heatmap"

patterns-established: []

requirements-completed: [OPS-12]

# Metrics
duration: 6min
completed: 2026-08-23
---

# Phase 31 Plan 02: Colormap INFERNO y heatmap_scale() Summary

**compose_heatmap cambia de JET a INFERNO (D-13) y DetectionWorker gana heatmap_scale() para exponer pico/media de la mascara acumulada sin sacar la mascara del proceso.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-08-23T10:44:00Z
- **Completed:** 2026-08-23T10:49:55Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `compose_heatmap` usa `cv2.COLORMAP_INFERNO`; ninguna referencia a `COLORMAP_JET` sobrevive en `backend/`
- `DetectionWorker.heatmap_scale()` nuevo: `{"peak": float, "mean": float}` o `None`, copiando `_heat_mask` bajo `self._lock` (mismo patron que `compose_heatmap`/`get_object_boxes`)
- 4 tests nuevos cubren los tres casos de `heatmap_scale` (sin mascara, pico 0, valores reales con `pytest.approx`) y una guarda de regresion del colormap (parcheo de `cv2.applyColorMap`, comprobando el segundo argumento)

## Task Commits

Each task was committed atomically:

1. **Task 1: COLORMAP_INFERNO y heatmap_scale() en DetectionWorker** - `f76e86d` (feat)
2. **Task 2: Tests de heatmap_scale y guarda del colormap** - `38ea996` (test)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `backend/pipeline/detection.py` - `compose_heatmap` con INFERNO; `heatmap_scale()` nuevo justo despues
- `tests/test_detection_worker.py` - 4 tests `TEST_heatmap_scale_*` y `TEST_compose_heatmap_uses_inferno_colormap`

## Decisions Made
- Se eligio la variante de parcheo (`unittest.mock.patch("cv2.applyColorMap", wraps=...)`) para la guarda del colormap en vez de inspeccion de fuente, porque el montaje `_worker_for_zones()` ya permite llamar a `compose_heatmap` con un frame sintetico (mismo camino que `test_heatmap_accumulates_and_renders`)
- Sin cambios de comportamiento respecto al plan; se siguio la accion tal cual estaba especificada

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Pipeline listo para que 31-06 publique `GET /api/v2/analytics/heatmap` (INFERNO ya activo, sin cambios adicionales necesarios) y `GET /api/v2/analytics/heatmap/scale` (consume `heatmap_scale()` directamente, respetando la semantica documentada en `<interfaces>`: unidad "frames de deteccion con presencia", escala siempre relativa, `None` -> 404).

El endpoint v1 `/api/heatmap` en `backend/main.py` no fue tocado y hereda INFERNO automaticamente por compartir `compose_heatmap`.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
