---
phase: 27-multi-clase-y-contexto-de-escena
plan: 02
subsystem: config
tags: [pydantic-settings, yolo26n, detector, multi-clase]

# Dependency graph
requires:
  - phase: 27-01
    provides: "ObjectAnalyzer (dominio puro) — no consumido directamente por este plan"
provides:
  - "D-03: yolo_model_path por defecto pasa a yolo26n.pt"
  - "10 parametros object_* + 4 context_* en Settings con validate_object_params"
  - "PersonDetector.set_classes() — mutacion en caliente sin recargar el modelo"
affects: [27-03, 27-06, 27-07, 27-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "set_classes() muta self._classes con rebind atomico (STORE_ATTR bajo el GIL), mismo patron que PersonTracker.set_frame_rate"
    - "validate_object_params sigue el molde de validate_behavior_params: bucle sobre nombres + mensajes que explican la consecuencia"

key-files:
  created: []
  modified:
    - backend/config.py
    - backend/detector.py
    - tests/test_config.py
    - tests/test_detector.py

key-decisions:
  - "D-03: yolo_model_path default = yolo26n.pt (end2end=True, NMS-free), corrige la deriva respecto a CLAUDE.md"
  - "object_class_ids no puede contener la clase 0 (person): rechazo explicito en validate_object_params para no desviar personas del PersonTracker/LineZone"
  - "set_classes() no necesita lock: rebind de lista completa es atomico bajo el GIL; la regla dura es nunca mutar in-place (append/clear)"

patterns-established:
  - "Bloques de config con comentario de cabecera '--- Tema (Fase N — IDs) ---' + parrafo que justifica los defaults y sus consecuencias si se cambian"

requirements-completed: [BEH-06, BEH-07, BEH-08, BEH-09]

# Metrics
duration: ~25min
completed: 2026-08-17
---

# Phase 27 Plan 02: Config multi-clase y set_classes() en caliente Summary

**Modelo por defecto corregido a yolo26n.pt (D-03), 14 parametros nuevos (object_*/context_*) con validador de rango, y PersonDetector.set_classes() para cambiar clases activas sin recargar el modelo**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-08-17T13:00:21Z
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments
- `yolo_model_path` corregido de `yolov8n.pt` a `yolo26n.pt` (D-03), alineado con CLAUDE.md
- 10 parametros `object_*` y 4 `context_*` con defaults del research, mas `validate_object_params` que rechaza las 6 configuraciones imposibles (incluida la clase 0/person en `object_class_ids`)
- `PersonDetector.set_classes()`: mutacion en caliente de `self._classes` sin recargar el modelo ni reiniciar el `DetectionWorker`
- Criterio 6 del ROADMAP verificado con benchmark real (p50 con 1 clase vs 6 clases, margen del 15%)

## Task Commits

1. **Task 1: D-03 + los dos bloques de config + validate_object_params** - `cf45f01` (feat)
2. **Task 2: PersonDetector.set_classes() — mutar la instancia viva** - `2a04856` (feat)
3. **Task 3: Tests de config, de set_classes y benchmark del criterio 6** - `96d5d11` (test)

**Plan metadata:** (pendiente — commit final de este summary)

## Files Created/Modified
- `backend/config.py` - D-03, bloques "Multi-clase y objetos" / "Contexto de escena", `validate_object_params`
- `backend/detector.py` - `PersonDetector.set_classes()`
- `tests/test_config.py` - 3 tests nuevos (default yolo26n, defaults object_*/context_*, rechazo de valores imposibles)
- `tests/test_detector.py` - 2 tests nuevos (`TEST_set_classes_changes_next_inference`, `TEST_multiclass_latency_under_15_percent`)

## Decisions Made
- D-03 se aplica en este plan (no en otro) porque el criterio 6 se mide **despues**: `yolo26n.pt` es NMS-free y cambia la ruta de post-proceso sobre la que se mide la latencia.
- `set_classes()` no necesita lock (a diferencia de `set_frame_rate`, que sí lo usa): el rebind de la lista completa es un unico `STORE_ATTR`, atomico bajo el GIL.
- `yolo_classes` (`config.py:57`, valor `[0]`) no se toca: sigue siendo el valor inicial: la BD gana en tiempo de ejecucion (27-RESEARCH Q6).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `object_class_ids`, `object_person_radius_px` y el resto de parametros `object_*`/`context_*` quedan disponibles para `27-03` (tracker por sustraccion) y planes posteriores.
- `PersonDetector.set_classes()` queda disponible para el router de clases activas de `27-07` sin necesidad de reiniciar el pipeline.
- `bus.jpg` de `ultralytics/assets` usado como frame de benchmark real; no requiere fixtures nuevas en el repo.

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED
