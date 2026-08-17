---
phase: 27-multi-clase-y-contexto-de-escena
plan: 08
subsystem: streaming
tags: [opencv, mjpeg, streaming, pull-pattern, object-tracking]

# Dependency graph
requires:
  - phase: 27-03
    provides: "DetectionWorker.get_object_boxes() con el shape {track_id, class_id, class_name, bbox}"
  - phase: 27-06
    provides: "CameraPipeline.get_object_boxes() como fachada de solo lectura sobre DetectionWorker"
provides:
  - "StreamingWorker dibuja las cajas de objetos trackeados en magenta sobre el feed MJPEG"
  - "Cableado pull (no push) entre CameraPipeline y StreamingWorker via Callable inyectado"
affects: ["27-09"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inyeccion de Callable[[], list[dict]] de solo lectura en el constructor de un worker, igual que registry/tracker — no un segundo registry ni un setter tipo set_zone_overlay"

key-files:
  created: []
  modified:
    - backend/pipeline/streaming.py
    - backend/pipeline/manager.py
    - tests/test_streaming_worker.py
    - tests/test_detection_worker.py

key-decisions:
  - "Objetos en magenta (255, 0, 255) BGR, distinto del naranja de zonas (0, 200, 255) y de los colores de sv.BoxAnnotator para personas"
  - "Via pull: object_boxes es un parametro del constructor, no un setter. set_zone_overlay se descarta como molde por no tener llamadores"

patterns-established:
  - "Un worker de streaming/render que necesita estado de otro hilo lo recibe como Callable inyectado en el constructor, resuelto en cada llamada (no snapshot congelado), para sobrevivir a reinicios del supervisor"

requirements-completed: [BEH-06]

duration: 8min
completed: 2026-08-17
---

# Phase 27 Plan 08: Overlay de objetos en el feed MJPEG Summary

**StreamingWorker dibuja las cajas de los objetos trackeados en magenta, leyendo `CameraPipeline.get_object_boxes` via un Callable inyectado en el constructor (patron pull, no push).**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-17T13:56:00Z
- **Completed:** 2026-08-17T14:04:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- `StreamingWorker.__init__` acepta `object_boxes: Callable[[], list[dict]] | None = None` y `_annotate` dibuja cada caja en magenta `(255, 0, 255)` con etiqueta `class_name #track_id`, tras el bloque de zonas y antes del `return out`.
- `manager.py._make_streaming` pasa `object_boxes=self.get_object_boxes` (metodo bound de `CameraPipeline`), sin logica nueva ni un segundo registry — un reinicio del supervisor sigue leyendo el estado vivo de `self.detection` porque el metodo bound se resuelve en cada llamada.
- 4 tests nuevos: 3 en `test_streaming_worker.py` (dibujo presente, lista vacia sin cambios, sin proveedor sin cambios) y 1 en `test_detection_worker.py` (identidad de referencia del Callable cableado por la factoria del supervisor).

## Task Commits

1. **Task 1: StreamingWorker — parametro `object_boxes` + dibujo en `_annotate`** - `f525168` (feat)
2. **Task 2: manager.py — cablear `self.get_object_boxes` a `StreamingWorker`** - `ab09084` (feat)
3. **Task 3: Tests — dibujo del overlay y cableado del proveedor** - `0b52681` (test)

**Plan metadata:** (pendiente, se añade tras este resumen)

## Files Created/Modified
- `backend/pipeline/streaming.py` - `Callable` importado; constructor con `object_boxes`; bloque de dibujo en magenta en `_annotate`
- `backend/pipeline/manager.py` - `_make_streaming` pasa `object_boxes=self.get_object_boxes`
- `tests/test_streaming_worker.py` - 3 tests nuevos sobre `_annotate` en aislamiento (sin hilo ni broker)
- `tests/test_detection_worker.py` - 1 test de identidad de referencia sobre la factoria `_make_streaming`

## Decisions Made
- Magenta `(255, 0, 255)` BGR para objetos, ya cerrado con el usuario en 27-RESEARCH.md Open Question #1.
- Via pull (inyeccion en constructor) en vez de push (`set_zone_overlay`), siguiendo el patron vivo del fichero (`registry`, `tracker`).

## Deviations from Plan

None - plan ejecutado tal cual estaba escrito. Una unica nota sobre un detalle menor de la propia especificacion del plan, sin impacto en el codigo:

- El criterio de aceptacion de la Tarea 3 pide `pytest tests/test_streaming_worker.py -k object_overlay -q` con >= 3 tests recogidos, pero los tres nombres de test exigidos textualmente en `<behavior>` solo coinciden 2 de 3 con el filtro `object_overlay` (`TEST_streaming_worker_without_object_boxes_provider` no contiene esa subcadena). El propio texto de la accion aclara la intencion real: "Nombres `TEST_*` con \"object\" u \"overlay\" para que `pytest -k object` los recoja" — con `-k object` se recogen los 3, verificado. Se respetaron los nombres exactos del plan sin renombrar.

## Issues Encountered

Durante la Tarea 3, al añadir el test a `tests/test_detection_worker.py` con `Edit`, el `old_string` no incluia la ultima linea del fichero (`pipeline.detection.stop.assert_not_called()`, fuera del rango leido previamente), lo que partio en dos el test `TEST_set_object_detection_classes_does_not_restart_worker` al insertar el test nuevo en medio. Se detecto al ejecutar la suite (`AttributeError: 'NoneType' object has no attribute 'stop'`) y se corrigio moviendo esa linea de vuelta a su test original antes de re-ejecutar; verificado con la suite completa en verde.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`StreamingWorker` y `CameraPipeline` quedan con el unico punto de acoplamiento streaming<->objetos permitido por 27-PATTERNS.md, listo para que `27-09` (contexto de escena via API) reuse el mismo shape de `get_object_boxes()` sin tocar `streaming.py`. Sin bloqueos.

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED

Todos los ficheros modificados existen en disco y los 3 commits de tareas (`f525168`, `ab09084`, `0b52681`) estan en el historial.
