---
phase: 26-an-lisis-de-comportamiento
plan: 04
subsystem: pipeline
tags: [detection-worker, behavior, camera-pipeline, supervisor, dwell-time]

requires:
  - phase: 26-01
    provides: "BehaviorAnalyzer.analyze()/prune() (dominio puro, reloj inyectado)"
  - phase: 26-02
    provides: "TrackState.centroid_history (deque) usado por RUNNING"
  - phase: 26-03
    provides: "EventEngine.emit_behavior() y process_zone(now_monotonic=...)"
provides:
  - "DetectionWorker._analyze_behavior(): ejecuta el analizador una vez por frame procesado, aislado de fallos (self._exceptions), sin contaminar self._rate.observe()"
  - "DetectionWorker._zone_membership_snapshot(): reutiliza st[\"inside\"] del frame actual sin volver a disparar sv.PolygonZone"
  - "CameraPipeline.behavior: construido FUERA de _make_detection, sobrevive a los reinicios del supervisor, gateado por behavior_enabled"
  - "main.py propaga los 10 settings de comportamiento a camera_manager.add"
  - "process_zone recibe now_monotonic=processed_at en produccion -> ZONE_EXITED lleva duration_s (BEH-04 cerrado end-to-end)"
affects: [26-05]

tech-stack:
  added: []
  patterns:
    - "Aislamiento de fallos calcado de RecognitionWorker._sync_identity: guarda de None, try con la llamada al dominio + prune dentro, except incrementa self._exceptions y retorna, bucle de emision de eventos FUERA del try"
    - "Estado con memoria (latches/anclas) construido FUERA de la factoria del WorkerSupervisor (mismo patron que identity_fsm de la Fase 24 y reid_engine/reid_gallery de la Fase 25), pasado como kwarg DENTRO de la factoria"
    - "Los ids del frame se toman de tracked.tracker_id directamente, nunca de self._registry.frame_ids() dentro de un metodo que corre antes de _emit_track_lifecycle (evita ver el frame anterior)"

key-files:
  created: []
  modified:
    - backend/pipeline/detection.py
    - backend/pipeline/manager.py
    - backend/main.py
    - tests/test_detection_worker.py

key-decisions:
  - "behavior: BehaviorAnalyzer | None = None se añade AL FINAL de la firma de DetectionWorker.__init__ (default None) para no romper los ~20 tests existentes que construyen el worker con argumentos posicionales cortos"
  - "_zone_membership_snapshot() lee st[\"inside\"], YA calculado por _update_zones_and_heat en el mismo frame con sv.PolygonZone.trigger() -- recalcularlo hubiera duplicado la inferencia geometrica y podido divergir de get_zone_stats()"
  - "_analyze_behavior se inserta en _loop DESPUES de self._rate.observe(inference_latency) (linea 171, ya ejecutada antes de la linea 179) para que el analizador nunca contamine avg_latency ni el escalon de AdaptiveRate"
  - "BehaviorAnalyzer se construye en CameraPipeline.__init__ ANTES del bloque if detector is not None and tracker is not None, gateado solo por behavior_enabled (no depende de detector/tracker) para poder verificarlo con un grep simple: BehaviorAnalyzer( nunca aparece dentro de _make_detection"

requirements-completed: [BEH-01, BEH-02, BEH-03, BEH-04, BEH-05]

duration: ~25min
completed: 2026-08-16
---

# Phase 26 Plan 04: Cableado del BehaviorAnalyzer al pipeline Summary

**DetectionWorker ejecuta el BehaviorAnalyzer una vez por frame con aislamiento de fallos, CameraPipeline lo construye fuera del WorkerSupervisor para sobrevivir a reinicios, y process_zone recibe el reloj monotonico del frame en produccion.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-16T03:10:00Z (aprox.)
- **Completed:** 2026-08-16T03:35:00Z (aprox.)
- **Tasks:** 3
- **Files modified:** 4 (backend/pipeline/detection.py, backend/pipeline/manager.py, backend/main.py, tests/test_detection_worker.py)

## Accomplishments
- `DetectionWorker._analyze_behavior` ejecuta `BehaviorAnalyzer.analyze()` + `.prune()` una vez por frame procesado, entre `_update_zones_and_heat` y `_emit_crossings`, con el mismo molde de aislamiento de fallos que `RecognitionWorker._sync_identity`
- `_zone_membership_snapshot()` reutiliza `st["inside"]` del frame actual sin volver a disparar `sv.PolygonZone.trigger()`
- `process_zone()` recibe `now_monotonic=processed_at` en produccion, cerrando BEH-04 (ZONE_EXITED con `duration_s`) fuera de los tests unitarios
- `CameraPipeline.behavior` se construye FUERA de `_make_detection` (sobrevive a los reinicios del `WorkerSupervisor`, igual que `identity_fsm` y `reid_gallery`) y se pasa como ultimo kwarg dentro de la factoria
- `main.py` propaga los 10 settings de comportamiento (`behavior_enabled`, `loiter_secs`, `loiter_radius_px`, `loiter_require_zone`, `run_speed_px_s`, `run_window_secs`, `immobile_secs`, `immobile_radius_px`, `crowd_threshold`, `behavior_max_tracks`) a `camera_manager.add`
- 7 tests nuevos de cableado end-to-end en `tests/test_detection_worker.py` (444 -> 451)

## Task Commits

Each task was committed atomically:

1. **Task 1: Enganche en DetectionWorker._loop con aislamiento de fallos** - `e2f2f46` (feat)
2. **Task 2: Construccion FUERA de la factoria en manager.py y propagacion en main.py** - `886a24b` (feat)
3. **Task 3: Tests de supervivencia al reinicio y de desactivacion** - `bed85b2` (test)

**Plan metadata:** (pendiente, commit de este documento)

## Files Created/Modified
- `backend/pipeline/detection.py` - `behavior` en `__init__`, `_analyze_behavior()`, `_zone_membership_snapshot()`, enganche en `_loop`, `now_monotonic=processed_at` en `process_zone`
- `backend/pipeline/manager.py` - `self.behavior` construido fuera de `_make_detection`, 10 parametros nuevos en `CameraPipeline.__init__`, `behavior=self.behavior` dentro de la factoria
- `backend/main.py` - propagacion de los 10 settings de comportamiento a `camera_manager.add`
- `tests/test_detection_worker.py` - 7 tests nuevos: 4 de cableado en `_analyze_behavior`/`_zone_membership_snapshot`, 3 de supervivencia/desactivacion/umbrales via `CameraPipeline`

## Decisions Made
- Ver `key-decisions` en el frontmatter. Ninguna decision arquitectonica nueva: el plan seguia al pie de la letra el patron ya establecido por `identity_fsm` (Fase 24) y `reid_engine`/`reid_gallery` (Fase 25).

## Deviations from Plan

None - plan executed exactly as written. Los 3 tasks se implementaron literalmente segun las acciones especificadas, incluidos los nombres de metodos, el orden del enganche en `_loop` y la ubicacion de la construccion del analizador en `manager.py`.

## Issues Encountered

El venv del proyecto (`F:/Documentos/IA/Proyecto_Camara/.venv`) no existe dentro del worktree — vive en la raiz del repo principal. Se uso la ruta absoluta indicada en el propio plan (`F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe`) para todos los comandos de verificacion y tests, sin necesidad de crear un venv nuevo.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Las 5 fuentes de comportamiento (LOITERING, RUNNING, IMMOBILE, CROWD, dwell-time de zonas) estan cableadas de punta a punta: dominio puro (26-01) -> traduccion a eventos (26-03) -> ejecucion en el pipeline real (26-04)
- `behavior_enabled=False` deja el pipeline completamente funcional sin el analizador, verificado por test
- Pendiente 26-05 (checkpoint de fase / verificacion de criterios de aceptacion de extremo a extremo)

---
*Phase: 26-an-lisis-de-comportamiento*
*Completed: 2026-08-16*

## Self-Check: PASSED

Todos los ficheros declarados existen y los 3 hashes de commit (`e2f2f46`, `886a24b`, `bed85b2`) estan en `git log`.
