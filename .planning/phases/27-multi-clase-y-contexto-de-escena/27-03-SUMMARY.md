---
phase: 27-multi-clase-y-contexto-de-escena
plan: 03
subsystem: pipeline
tags: [supervision, bytetrack, tracking, detection-worker]

requires:
  - phase: 27-02
    provides: "config object_* / context_* + PersonDetector.set_classes()"
provides:
  - "ObjectTracker (backend/tracker.py): sv.ByteTrack propio para objetos, sin smoother ni LineZone"
  - "Particion por class_id en DetectionWorker._loop antes de cualquier tracker"
  - "set_object_classes/get_object_stats/get_object_boxes en DetectionWorker"
  - "7 tests de regresion del riesgo ByteTrack class-agnostic"
affects: ["27-06 (cableado)", "27-07 (fachada de clases)", "27-08 (overlay MJPEG)"]

tech-stack:
  added: []
  patterns:
    - "Un sv.ByteTrack por grupo de clases: la identidad de tracking nunca se comparte entre clases"
    - "Estado de objetos vive en un dict bajo self._lock (DetectionWorker._object_boxes), no en TrackRegistry"

key-files:
  created: []
  modified:
    - backend/tracker.py
    - backend/pipeline/detection.py
    - tests/test_detection_worker.py

key-decisions:
  - "ObjectTracker es un analogo por sustraccion de PersonTracker: mismo ByteTrack+LOST_TRACK_BUFFER+set_frame_rate, sin DetectionsSmoother (congelaria class_id) ni LineZone (conteo es solo de personas)"
  - "La particion por clase ocurre dentro del try de inferencia existente, para que un sv_dets malformado siga cayendo en el mismo except"
  - "self._rate.observe() sigue midiendo solo la via de personas; la via de objetos nunca llama a observe() (mismo patron que ReID Fase 25 y BehaviorAnalyzer Fase 26)"
  - "Docstrings de ObjectTracker reformuladas para no citar literalmente 'DetectionsSmoother'/'LineZone' -- el propio <verify> del plan comprobaba su ausencia por substring en inspect.getsource(), y las citaba en prosa"

patterns-established:
  - "Helper de test _tracked_cls(boxes, tids, class_ids, names): variante de _tracked_at con class_id real y data['class_name'], necesaria porque los helpers previos ponian class_id a ceros"

requirements-completed: [BEH-06]

duration: 35min
completed: 2026-08-17
---

# Phase 27 Plan 03: ObjectTracker y particion por clase Summary

**`ObjectTracker` con `sv.ByteTrack` propio partiendo `sv_dets` por `class_id` antes de cualquier tracker, cerrando el riesgo de que `PersonTracker` reciba detecciones de objeto y el `tracker_id` migre entre clases.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3/3
- **Files modified:** 3

## Accomplishments
- `ObjectTracker` (backend/tracker.py): `sv.ByteTrack` dedicado a objetos, con `set_frame_rate` (mismo calculo que `PersonTracker`), sin `DetectionsSmoother` ni `LineZone`. `PersonTracker` queda intacto (verificado por `git diff` sin lineas `-`).
- `DetectionWorker` parte `sv_dets` por clase (`_split_by_class`, `np.isin` contra `PERSON_CLASS_IDS`) dentro del `try` de inferencia existente. `PersonTracker.update` recibe solo `person_dets`; el `ObjectTracker` opcional recibe `object_dets`.
- Estado de objetos nuevo: `self._object_boxes` bajo `self._lock`, refrescado por `_update_object_boxes` cada frame (sin conservar la foto anterior si no hay objetos). `set_object_classes`, `get_object_stats`, `get_object_boxes` siguen el molde de `set_zones`/`get_zone_stats`.
- `_sync_tracker_frame_rate` propaga el cambio de escalon de `AdaptiveRate` a los DOS trackers.
- 7 tests de regresion nuevos: el que reproduce literalmente el hallazgo del research (un `sv.ByteTrack` compartido SI transfiere el id de una mochila a una persona solapada; con la particion, no), mas los de LineZone, `TrackRegistry`, `class_name`, comportamiento sin clases de objeto configuradas, sincronizacion de FPS y copia defensiva de `get_object_boxes()`.

## Task Commits

1. **Task 1: ObjectTracker en backend/tracker.py** - `e60746a` (feat)
2. **Task 2: Particion por clase en DetectionWorker** - `94dba2c` (feat)
3. **Task 3: Tests de regresion del riesgo ByteTrack** - `35fa430` (test)

## Files Created/Modified
- `backend/tracker.py` - `ObjectTracker` (52 lineas nuevas, `PersonTracker` sin cambios)
- `backend/pipeline/detection.py` - `PERSON_CLASS_IDS`, `_split_by_class`, `_update_object_boxes`, `set_object_classes`, `get_object_stats`, `get_object_boxes`, propagacion de `set_frame_rate` a `ObjectTracker`
- `tests/test_detection_worker.py` - helper `_tracked_cls` + 7 tests `TEST_*` de regresion

## Decisions Made
No se marca la casilla de `BEH-06` en `REQUIREMENTS.md`: el ROADMAP asigna esa
puerta explicitamente a `27-11-PLAN.md` ("Puerta de fase: criterios del ROADMAP +
BEH-06..BEH-09 en REQUIREMENTS.md"), que cerrara BEH-06..BEH-09 de una vez con
trazabilidad completa a los 6 criterios de exito de la fase. Este plan solo
contribuye a BEH-06 (particion class-aware, requisito previo a exponer clases
configurables end-to-end), no lo completa.

Ver el resto de `key-decisions` en el frontmatter. La mas relevante para futuros planes: el docstring de `ObjectTracker` tuvo que reformularse para no citar literalmente los nombres `DetectionsSmoother`/`LineZone` en prosa, porque el propio comando `<verify>` de la Task 1 comprueba su ausencia con un `assert 'DetectionsSmoother' not in src` sobre `inspect.getsource()` de la clase completa (incluyendo docstring). No es una desviacion de comportamiento, solo de redaccion.

## Deviations from Plan

None - plan ejecutado tal como estaba escrito, salvo el ajuste de redaccion de docstring ya documentado arriba (no altera codigo ni tests, se resolvio dentro de la Task 1 antes de commitear).

## Issues Encountered
- El primer intento de `TEST_object_class_does_not_reach_line_zone` movia la persona en pasos de 40-60px por frame; `sv.ByteTrack` matchea por IoU con umbral 0,8 y esos saltos perdian el `tracker_id` entre frames (spawneaba un track nuevo en vez de mover el existente), dando `total=0` cruces. Se redujo el paso a 10px (`range(230, 340, 10)`), consistente con el resto de tests del fichero que ya movian bboxes en incrementos pequeños.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `ObjectTracker` y la particion por clase quedan disponibles para `27-04` (media movil horaria / `ObjectAnalyzer` runtime), `27-06` (cableado en `manager.py`), `27-07` (fachada de clases activas) y `27-08` (overlay MJPEG de objetos) — el contrato de `backend/tracker.py` y `DetectionWorker` documentado en el `<interfaces>` del plan queda cumplido literalmente (mismas firmas, mismos nombres).
- Sin bloqueos. `TrackRegistry`, `backend/pipeline/tracking.py` y `PersonTracker` sin tocar; suite completa 480/480.

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED

All created/modified files and all 3 task commit hashes verified present.
