---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 05
subsystem: detection
tags: [linezone, polygonzone, hot-reload, schedule, bytetrack, supervision]

# Dependency graph
requires:
  - phase: 33-01
    provides: is_schedule_active(schedule, now) en backend/events/rules.py
  - phase: 33-04
    provides: "PersonTracker.reconfigure_lines(lines) con N lineas independientes, cada dict {id, name, start, end} en pixeles"
provides:
  - "DetectionWorker.set_lines()/_update_lines(): hot-reload de lineas de conteo con el mismo patron dirty-flag que zonas, conversion fraccion->pixel en cada rebuild"
  - "CameraPipeline.set_lines(lines) -- facade simetrico a set_zones"
  - "_rebuild_zone_states lee z['polygon'] (lista) en vez de json.loads(z['polygon_json'])"
  - "Horario propio de zona (OPS-23) funcionalmente activo: is_schedule_active() bloquea trigger() de zonas fuera de su ventana"
  - "backend/camera.py:/resolution ya no calcula pixeles de linea a mano ni llama reconfigure_line"
affects: [33-07, 33-08, 33-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Molde dirty-flag simetrico para lineas (_lines/_lines_dirty/_line_frame_size), clonado literalmente del ya existente para zonas"
    - "Gating de horario por continue antes de trigger(), no por filtrado previo de la lista de zonas -- conserva el estado (current=0/entries=0) en get_zone_stats() en vez de ocultar la zona"

key-files:
  created:
    - tests/test_pipeline_lines.py
  modified:
    - backend/pipeline/detection.py
    - backend/pipeline/manager.py
    - backend/camera.py
    - tests/test_detection_worker.py

key-decisions:
  - "El endpoint POST /camera/resolution deja de devolver line_start/line_end en la respuesta (esos valores vivian del calculo eliminado) -- verificado con grep que ningun consumidor de frontend (videoCanvas.js incluido) los lee, asi que no rompe nada en silencio"
  - "_tracker_ref se conserva en camera.py (solo para el guard de disponibilidad 503) aunque ya no se usa para reconfigurar nada -- retirarlo del todo es un cambio de firma de set_refs() fuera del alcance declarado de este plan"
  - "Import de supervision (sv) retirado de camera.py y de json en detection.py por quedar sin ningun uso tras los cambios"

patterns-established:
  - "Zona con schedule=None se comporta identico a una zona sin la clave schedule (is_schedule_active trata ambos casos igual) -- no hace falta migrar zonas existentes al anadir el campo"

requirements-completed: [OPS-21, OPS-22, OPS-23]

# Metrics
duration: 6min
completed: 2026-08-24
---

# Phase 33 Plan 05: Hot-reload de lineas + horario de zona + limpieza camera.py Summary

**DetectionWorker gana `set_lines()` simetrico a `set_zones()` (dirty-flag + conversion fraccion->pixel hacia `PersonTracker.reconfigure_lines()`), las zonas migran de `polygon_json` (string) a `polygon` (lista) y el horario propio de una zona ahora bloquea de verdad su `trigger()` fuera de la ventana configurada.**

## Performance

- **Duration:** 6 min (commits 19:42:00 -> 19:43:42 CEST)
- **Started:** 2026-08-24T17:42:00Z
- **Completed:** 2026-08-24T17:43:42Z
- **Tasks:** 2
- **Files modified:** 5 (4 modificados + 1 test nuevo)

## Accomplishments
- `DetectionWorker.set_lines()`/`_update_lines()` recalculan las lineas de conteo en pixeles cuando cambian o cuando cambia la resolucion del frame, con el mismo gate `_line_frame_size != (fw, fh)` que ya usan las zonas — verificado con dos tests que cruzan 720p -> 1080p sin volver a llamar `set_lines`.
- `_rebuild_zone_states` deja de depender de `json.loads(z["polygon_json"])`: lee `z["polygon"]` directamente, ya como lista de `[x_frac, y_frac]` (forma que produce `ZoneRepo._to_dict()` tras el Plan 33-08).
- El horario de zona (OPS-23) deja de ser un dato inerte: `_update_zones_and_heat` salta `trigger()` para cualquier zona cuyo `schedule` no este activo en el instante actual (`is_schedule_active`), sin tocar el resto del ciclo (heatmap, `process_zone`, conteo de objetos excluidos).
- `CameraPipeline.set_lines()` (facade identico a `set_zones()`) y `POST /camera/resolution` sin calculo manual de linea — confia en el rebuild automatico del siguiente frame, igual que zonas.

## Task Commits

Cada tarea se comiteo de forma atomica (Task 1 con ciclo TDD completo, RED antes que GREEN):

1. **Task 1 RED: tests de hot-reload de lineas y gating de horario** - `f94a9b5` (test)
2. **Task 1 GREEN: DetectionWorker.set_lines() + zonas leen polygon + gating de horario** - `cca6ee4` (feat)
3. **Task 2: CameraPipeline.set_lines() + retirar recalculo manual en camera.py** - `6411d97` (feat)

**Plan metadata:** (este commit) `docs(33-05): completar plan hot-reload de lineas y horario de zona`

## Files Created/Modified
- `backend/pipeline/detection.py` — `set_lines()`, `_update_lines()`, gating de horario en `_update_zones_and_heat`, `_rebuild_zone_states` migrado a `polygon` (lista); import de `json` retirado (sin uso), import de `is_schedule_active` anadido
- `backend/pipeline/manager.py` — `CameraPipeline.set_lines()` (facade)
- `backend/camera.py` — `POST /resolution` sin calculo de `new_start`/`new_end` ni `reconfigure_line`; import de `supervision` retirado
- `tests/test_pipeline_lines.py` (nuevo) — 4 tests: conversion fraccion->pixel de lineas, recalculo automatico al cambiar resolucion, gating de horario bloquea `trigger()`, zona sin horario sin regresion
- `tests/test_detection_worker.py` — las 3 construcciones `set_zones([{"polygon_json": json.dumps(...)}])` migradas a `{"polygon": [...]}`, con el `import json` local retirado por quedar sin uso en esas tres funciones

## Decisions Made
Ver `key-decisions` en el frontmatter.

## Deviations from Plan

None - plan ejecutado tal como estaba escrito. Los dos retiros de imports sin uso (`sv` en `camera.py`, `json` en `detection.py`) son limpieza directa derivada de las acciones que el propio plan pedia, no cambios adicionales de alcance.

## TDD Gate Compliance

Task 1 (`tdd="true"`) siguio el ciclo RED/GREEN completo y verificado, no solo declarado: se aislo temporalmente el cambio de produccion (`git stash` de `backend/pipeline/detection.py`) para confirmar que los 7 tests afectados (4 nuevos de `test_pipeline_lines.py` + 3 migrados de `test_detection_worker.py`) fallaban realmente contra el codigo previo (`7 failed, 34 passed`) antes de comitear el gate RED (`f94a9b5`). Tras restaurar la implementacion se confirmo `41 passed` y se comiteo el gate GREEN (`cca6ee4`). No hizo falta REFACTOR (sin duplicacion ni limpieza pendiente tras el GREEN).

## Issues Encountered
Ninguno.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- El contrato `set_lines(lines: list[dict])` con claves `id/name/start_x_frac/start_y_frac/end_x_frac/end_y_frac/enabled` queda fijado para que el Plan 33-07 (`backend/api/v2/lines.py`) lo consuma tras persistir en `LineRepo`.
- `_rebuild_zone_states` ya asume la forma `polygon` (lista) de `ZoneRepo._to_dict()`: esto ROMPE intencionadamente `backend/main.py:get_zones()` (v1, sigue usando `polygon_json`) hasta que el Plan 33-08 (Wave 4) actualice ese llamador — documentado explicitamente en el plan, no es una regresion de este plan.
- `backend/camera.py:194` ya no llama `reconfigure_line`; el wrapper de compatibilidad en `PersonTracker.reconfigure_line` (Plan 33-04) queda sin ningun caller real en el codigo de produccion — candidato a retirar en un plan futuro si se confirma que no lo usa nada mas.
- No se relanzo la suite completa (`pytest tests/ -q`): el plan lo deja explicitamente para el Plan 33-08, que es quien conecta este codigo con `LineRepo`/`ZoneRepo` reales desde el arranque.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

Todos los ficheros modificados/creados y los tres commits de tarea (f94a9b5, cca6ee4, 6411d97) verificados presentes.
