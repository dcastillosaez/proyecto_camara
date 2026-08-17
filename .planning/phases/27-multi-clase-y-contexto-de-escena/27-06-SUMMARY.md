---
phase: 27-multi-clase-y-contexto-de-escena
plan: 06
subsystem: pipeline
tags: [detection-worker, object-analyzer, worker-supervisor, wiring]

# Dependency graph
requires:
  - phase: 27-01
    provides: "ObjectAnalyzer/ObjectObservation/PersonObservation/ObjectFinding — dominio puro"
  - phase: 27-03
    provides: "ObjectTracker + particion por clase en DetectionWorker._loop"
  - phase: 27-04
    provides: "columna kind en get_zones()"
  - phase: 27-05
    provides: "EventEngine.emit_object()"
provides:
  - "DetectionWorker._analyze_objects — alimenta ObjectAnalyzer con anclas BOTTOM_CENTER y emite OBJECT_LEFT/OBJECT_REMOVED"
  - "ObjectAnalyzer/ObjectTracker construidos en CameraPipeline.__init__, fuera de _make_detection"
  - "CameraPipeline.set_detection_classes/get_object_stats/get_object_boxes"
affects: ["27-07", "27-08", "27-09"]

tech-stack:
  added: []
  patterns:
    - "Cuarto precedente (tras FSM Fase 24, ReID Fase 25, BehaviorAnalyzer Fase 26) de estado con estado construido fuera de la factoria del WorkerSupervisor"
    - "_excluded_object_ids/_object_zone_ids reutilizan sv.PolygonZone.trigger() sobre los mismos _zone_states, sin geometria propia"

key-files:
  created: []
  modified:
    - backend/pipeline/detection.py
    - backend/pipeline/manager.py
    - backend/main.py
    - tests/test_detection_worker.py

key-decisions:
  - "findings += self._objects.prune(...) explicito: a diferencia de BehaviorAnalyzer.prune (que devuelve None), el prune de objetos decide OBJECT_REMOVED y su retorno no se puede ignorar"
  - "zone_id de un objeto sale de cualquier zona que lo contenga (no solo exclude_objects); la exclusion es una guarda aparte en el propio ObjectAnalyzer.analyze via excluded=True"

requirements-completed: [BEH-06, BEH-07]

duration: ~45min
completed: 2026-08-17
---

# Phase 27 Plan 06: Cableado del ObjectAnalyzer en DetectionWorker Summary

**`DetectionWorker._analyze_objects` alimenta al `ObjectAnalyzer` con anclas `BOTTOM_CENTER` de objetos y personas, recoge tambien los veredictos de `prune()`, y tanto el analizador como el `ObjectTracker` se construyen en `CameraPipeline.__init__` — fuera de la factoria del `WorkerSupervisor` — para sobrevivir a los reinicios del worker.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 3/3 completados
- **Files modified:** 4

## Accomplishments

- `_analyze_objects(obj_tracked, tracked, captured_at, processed_at)` en `backend/pipeline/detection.py`: mismo patron de aislamiento de fallos que `_analyze_behavior` (try que envuelve `analyze` + `prune`, `except Exception` con `self._exceptions += 1`, emision fuera del try). Construye `ObjectObservation`/`PersonObservation` con anclas `BOTTOM_CENTER` (no centroides) y recoge `findings += self._objects.prune(...)` explicitamente.
- `_excluded_object_ids` / `_object_zone_ids`: reutilizan `sv.PolygonZone.trigger()` sobre los `_zone_states` ya calculados, filtrando por `kind == "exclude_objects"` para la exclusion y sin filtro para el `zone_id` general. `kind` se propaga ahora en `_rebuild_zone_states`.
- `CameraPipeline.__init__` (`backend/pipeline/manager.py`): `self.objects`/`self.object_tracker` se construyen antes de `_make_detection`, gateados por `objects_enabled`, con el comentario del agravante de esta fase (reconstruirlos reabre la ventana de warmup y provoca una rafaga de `OBJECT_LEFT` — `WARNING` — que sube un clip a Drive por cada mueble). `_make_detection` los pasa como kwargs junto a `object_class_ids`.
- `set_detection_classes(classes)`, `get_object_stats()`, `get_object_boxes()` en `CameraPipeline`, siguiendo el molde de `set_zones`/`get_zone_stats`. `set_detection_classes` muta `detector`/`detection` sin reiniciar ningun worker.
- `backend/main.py`: propaga los 10 parametros `object_*`/`objects_enabled` desde `Settings` al `camera_manager.add(...)`.
- 8 tests nuevos `TEST_*` en `tests/test_detection_worker.py`: emision real de `OBJECT_LEFT`, aislamiento de fallos, retorno de `prune` no ignorado, exclusion por zona, supervivencia del analizador y del tracker a un reinicio del worker, `objects_enabled=False` sin analizador/tracker, y `set_detection_classes` sin reiniciar el worker.

## Task Commits

1. **Task 1: DetectionWorker._analyze_objects + zonas de exclusion** - `554002f` (feat)
2. **Task 2: manager.py — construccion fuera de la factoria + fachada; main.py — propagacion** - `8fd81ac` (feat)
3. **Task 3: Tests de cableado y de supervivencia a reinicio** - `a0d8533` (test)

## Files Created/Modified

- `backend/pipeline/detection.py` - `_analyze_objects`, `_excluded_object_ids`, `_object_zone_ids`, `kind` en `_rebuild_zone_states`, llamada en `_loop`, parametro `objects` en el constructor
- `backend/pipeline/manager.py` - `self.objects`/`self.object_tracker` construidos fuera de `_make_detection`, kwargs de la factoria, `set_detection_classes`/`get_object_stats`/`get_object_boxes`, 10 parametros nuevos en `__init__`
- `backend/main.py` - propagacion de `objects_enabled` y los 9 `object_*` de `Settings`
- `tests/test_detection_worker.py` - import de `ObjectAnalyzer`/`ObjectFinding`/`ObjectKind` + 8 tests `TEST_*`

## Decisions Made

Ver `key-decisions` en el frontmatter. Ninguna decision arquitectural nueva fuera de las ya fijadas por el contrato LOCKED del plan (`<interfaces>` de `27-06-PLAN.md`): las firmas de `_analyze_objects`, `set_detection_classes`, `get_object_stats`, `get_object_boxes` y los 10 parametros de `__init__` se implementaron literalmente como las especifica el plan, sin renombrar nada (`objects_enabled` se mantiene tal cual pese a la inconsistencia de conteo del `<verify>`, ver Deviations).

## Deviations from Plan

### Sin desviaciones de codigo o arquitectura

El codigo de produccion y los tests siguen el molde de `_analyze_behavior`/Fase 26 tal como pedia el plan. Las dos desviaciones documentadas abajo son puramente de **conteo en los criterios de aceptacion automatizados** (grep/`-k`), no de comportamiento:

**1. `grep -c "object_" backend/main.py` da 9, no >= 10 como esperaba el plan**
- **Causa:** la linea `objects_enabled=settings.objects_enabled,` contiene la subcadena `objects_` (con "s"), no `object_` (sin "s"), asi que el patron literal del `<verify>` no la cuenta. Las 9 lineas restantes (`object_class_ids` .. `object_max_tracks`) si matchean.
- **Por que no se corrigio:** el nombre `objects_enabled` esta fijado por el contrato `<interfaces>` LOCKED del propio plan (linea 97: `objects_enabled: bool = True,`), consumido literalmente por `main.py` linea a linea con `nombre=settings.nombre`. Renombrarlo para forzar el conteo violaria el contrato que consumen `27-07`/`27-08`/`27-09`.
- **Impacto:** ninguno funcional. Las 10 propagaciones existen; solo el conteo textual del `<verify>` no llega a 10 por la "s" de plural.

**2. `pytest tests/test_detection_worker.py -k object -q` recoge 12 tests, no >= 13**
- **Causa:** el plan asumia que los "7 tests de 27-03" matcheaban todos el filtro `-k object`, pero solo 4 lo hacen (`TEST_object_class_does_not_reach_line_zone`, `TEST_objects_not_in_registry`, `TEST_no_object_classes_behaves_like_today`, `TEST_object_boxes_snapshot_is_a_copy`); los otros 3 (`TEST_bytetrack_ids_do_not_migrate_between_classes`, `TEST_split_by_class_preserves_class_name`, `TEST_sync_frame_rate_reaches_both_trackers`) no contienen la palabra "object" en su nombre. 4 + 8 nuevos = 12.
- **Por que no se corrigio:** renombrar tests ya commiteados por `27-03` esta fuera del alcance de este plan (no son ficheros que este plan deba modificar por logica de negocio, solo por convencion de nombres) y no aporta cobertura nueva.
- **Impacto:** ninguno funcional. Los 8 tests nuevos de este plan siguen la convencion "todos con 'object'" pedida por el plan (verificado: los 8 aparecen en el filtro `-k object`); la suite completa de `test_detection_worker.py` (32/32) y la suite global (500/500) estan verdes.

## Issues Encountered

Ninguno bloqueante. `sv.Detections.empty()` fue necesario para representar "sin personas en el frame" en los tests, ya que `_tracked_cls`/`_tracked_at` con listas vacias producirian un array `xyxy` de forma incorrecta.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `_analyze_objects`, `set_detection_classes`, `get_object_stats`, `get_object_boxes` quedan disponibles con las firmas exactas del contrato LOCKED para `27-07` (PUT de clases activas), `27-08` (overlay MJPEG de objetos) y `27-09` (endpoint de contexto de escena).
- `backend/pipeline/tracking.py`, `PersonTracker` y `backend/perception/behavior.py` sin cambios (verificado por `git diff --stat` vacio en ese rango).
- Suite completa: 500/500 (492 previos + 8 nuevos).

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED

All created/modified files and all 3 task commit hashes verified present.
