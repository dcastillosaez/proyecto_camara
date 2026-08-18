---
phase: 27-multi-clase-y-contexto-de-escena
plan: 07
subsystem: api
tags: [fastapi, app-config, hot-config, detection-classes, rate-limiting]

# Dependency graph
requires:
  - phase: 27-02
    provides: "PersonDetector.set_classes() y config.yolo_classes/object_class_ids"
  - phase: 27-04
    provides: "ConfigRepo.get/set sobre app_config"
  - phase: 27-06
    provides: "CameraPipeline.set_detection_classes() — fachada sobre detector + reparto persona/objeto"
provides:
  - "GET/PUT /api/v2/detection/classes — contrato LOCKED consumido por 27-09 y 27-10"
  - "backend.main._resolve_active_classes() — precedencia app_config > env var, fila vacia = ausente"
  - "Primer endpoint del proyecto que muta la configuracion del pipeline en caliente, con CONFIG_CHANGED como rastro"
affects: ["27-09", "27-10", "27-11"]

tech-stack:
  added: []
  patterns:
    - "Router v2 con configure(camera_manager, event_engine) via globals de modulo (molde metrics.py), nunca el global rtsp_stream de main.py"
    - "Orden validar -> 400 -> persistir -> propagar bajo guarda -> emitir CONFIG_CHANGED, mismo molde que POST /api/zones"
    - "app_config gana sobre la env var; fila [] persistida se trata como ausente (Pitfall 3)"

key-files:
  created:
    - backend/api/v2/detection.py
    - tests/test_detection_config_api.py
  modified:
    - backend/main.py

key-decisions:
  - "Persistir en app_config ANTES de propagar al pipeline: si el proceso muere entre ambos pasos, el arranque siguiente (precedencia BD > env var) aplica lo que el operador pidio en vez de perderlo"
  - "La clase 'person' (id 0) es indesactivable en el backend (LOCKED_CLASS_IDS) — decision cerrada con el usuario; sin ella caerian LineZone, identidad, ReID y comportamiento"
  - "_resolve_active_classes() extraida a funcion modulo-privada en main.py (mejora aceptable permitida por el plan) para poder testear la precedencia sin arrancar el lifespan completo"
  - "Tests cablean via detection_module.configure(mock_manager, mock_engine) en vez de parchear el global de main.py, y sustituyen ConfigRepo con un doble de prueba (_config_repo parcheado) para no tocar la base de datos real del proyecto"

requirements-completed: [BEH-06]

duration: ~25min
completed: 2026-08-17
---

# Phase 27 Plan 07: Router de clases activas — GET/PUT en caliente con persistencia Summary

**GET/PUT `/api/v2/detection/classes` en `backend/api/v2/detection.py`: cuatro validaciones con 400 explicito (vacia, fuera de rango, duplicados, sin "person"), persistencia en `app_config` antes de propagar al pipeline via `set_detection_classes`, y `CONFIG_CHANGED` como rastro de auditoria.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-08-17
- **Tasks:** 3/3
- **Files modified:** 3 (2 nuevos, 1 modificado)

## Accomplishments
- Router `backend/api/v2/detection.py` con `GET /classes` (catalogo de 6 clases + activas + locked) y `PUT /classes` (las 4 validaciones + persistencia + propagacion + evento)
- `backend/main.py`: precedencia `app_config` > env var `YOLO_CLASSES` al construir el detector, con `_resolve_active_classes()` tratando una fila `[]` como ausente; `include_router` y `configure(camera_manager, event_engine)` cableados
- 8 tests nuevos en `tests/test_detection_config_api.py` (GET, 4 rechazos con `detail` verificado, camino feliz, orden persistir-antes-de-propagar, precedencia de arranque)

## Task Commits

Each task was committed atomically:

1. **Task 1: backend/api/v2/detection.py — router GET/PUT con validacion estricta** - `ebfa411` (feat)
2. **Task 2: main.py — precedencia app_config > env var, include_router y configure** - `9ad86c8` (feat)
3. **Task 3: tests/test_detection_config_api.py** - `d8402ae` (test)

_No hubo commit de metadata de plan separado; este SUMMARY se commitea junto con STATE/ROADMAP/REQUIREMENTS._

## Files Created/Modified
- `backend/api/v2/detection.py` - Router nuevo: `AVAILABLE_CLASSES` (6 clases COCO), `LOCKED_CLASS_IDS={0}`, `CONFIG_KEY="yolo_classes"`, `configure()`, `GET/PUT /classes`
- `backend/main.py` - `ConfigRepo` importado; `_resolve_active_classes()` module-level; lectura de `persisted_classes` antes de construir `PersonDetector`; `detection_v2_module.configure(camera_manager, event_engine)`; `pipeline.set_detection_classes(active_classes)` tras `camera_manager.add(...)`; `include_router(detection_v2_router)`
- `tests/test_detection_config_api.py` - 8 tests `TEST_*` cubriendo GET, los 4 rechazos 400 (con aserciones sobre `detail`), el camino feliz completo con mocks de `camera_manager`/`event_engine`, el orden persistir->propagar, y `_resolve_active_classes()`

## Decisions Made
- Ver `key-decisions` en el frontmatter. Ninguna decision arquitectonica nueva: todas ya estaban cerradas por el usuario en el research (T-27-27/T-27-28) o eran continuaciones directas del molde de `recordings.py`/`metrics.py`/`POST /api/zones`.

## Deviations from Plan

**1. [Rule 2 — mejora permitida explicitamente por el plan] Extraccion de `_resolve_active_classes()` en `main.py`**
- **Found during:** Task 3 (diseno de `TEST_empty_persisted_row_is_treated_as_absent`)
- **Issue:** La logica de precedencia BD > env var vivia inline dentro del `lifespan` de `main.py`, sin forma razonable de testearla sin arrancar el ciclo de vida completo de la app
- **Fix:** Se extrajo a una funcion modulo-privada `_resolve_active_classes(persisted, settings_value)` — el propio plan preveia esta mejora como aceptable ("es la unica linea de logica del Task 2")
- **Files modified:** `backend/main.py`
- **Verification:** `pytest tests/test_detection_config_api.py::TEST_empty_persisted_row_is_treated_as_absent` verde; comportamiento identico verificado con `pytest tests/test_security_regression.py` y la suite completa
- **Committed in:** `d8402ae` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (mejora de testabilidad explicitamente prevista por el plan)
**Impact on plan:** Ninguno fuera de alcance. No cambia el comportamiento observable de `main.py`, solo lo hace testeable sin lifespan.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Requirements traceability

`BEH-06` (clases configurables mas alla de "persona") queda **contribuido pero no marcado** en `REQUIREMENTS.md`: siguiendo la convencion ya establecida en `27-06-SUMMARY.md` (donde tampoco se marco), el ROADMAP asigna el cierre formal de BEH-06/BEH-07 a la puerta de fase `27-11`, porque el criterio completo requiere ademas el panel visual del dashboard (`27-10`) con el checkbox de "person" marcado y deshabilitado. Este plan cierra la mitad backend del criterio 1 del ROADMAP.

## Next Phase Readiness
- Contrato LOCKED de `backend/api/v2/detection.py` (`router`, `configure()`, shape de `GET`/`PUT`) listo para que `27-09` (endpoint de contexto) comparta `main.py` sin colisiones, y para que `27-10` (panel frontend) consuma el endpoint tal cual esta documentado en `<interfaces>` del plan
- Suite completa verde: 508/508 (500 previos de `27-06` + 8 nuevos de este plan)
- Sin bloqueos para continuar con `27-08`..`27-11`

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED

- FOUND: backend/api/v2/detection.py
- FOUND: tests/test_detection_config_api.py
- FOUND: .planning/phases/27-multi-clase-y-contexto-de-escena/27-07-SUMMARY.md
- FOUND: ebfa411 (Task 1 commit)
- FOUND: 9ad86c8 (Task 2 commit)
- FOUND: d8402ae (Task 3 commit)
