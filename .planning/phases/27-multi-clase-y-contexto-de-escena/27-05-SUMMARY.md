---
phase: 27-multi-clase-y-contexto-de-escena
plan: 05
subsystem: events
tags: [event-engine, pydantic, object-detection, audit-trail]

# Dependency graph
requires:
  - phase: 27-01
    provides: "ObjectFinding/ObjectKind — dominio puro de ObjectAnalyzer (OBJECT_LEFT/OBJECT_REMOVED)"
provides:
  - "EventEngine.emit_object() — traduce ObjectFinding al catalogo de eventos tipados"
  - "EventEngine.config_changed() — trazabilidad de cambios de configuracion en caliente"
affects: [27-06, 27-07, 27-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tabla de traduccion Kind->EventType a nivel de modulo (_OBJECT_EVENT_TYPE), mismo molde que _BEHAVIOR_EVENT_TYPE"
    - "emit_* nunca compone el payload (lo hace finding.magnitudes()) ni pasa severity= explicita salvo camera_offline/degraded_mode"

key-files:
  created: []
  modified:
    - backend/events/engine.py
    - tests/test_event_engine.py

key-decisions:
  - "emit_object no pasa severity= explicita: OBJECT_LEFT hereda WARNING del catalogo y por tanto cruza upload_min_severity, subiendo el clip a Google Drive — decision ya cerrada con el usuario (T-27-19)"
  - "bbox viaja como campo de primer nivel del Event (finding.bbox), no dentro del payload — los eventos de objeto llevan caja, los de comportamiento no"
  - "config_changed() es la unica mitigacion de repudio disponible sin roles en el sistema (ASVS V4, T-27-20)"

patterns-established:
  - "emit_object() calcado de emit_behavior(): tabla de traduccion a nivel de modulo + guarda None + _publish sin severity="

requirements-completed: [BEH-06, BEH-07]

# Metrics
duration: 15min
completed: 2026-08-17
---

# Phase 27 Plan 05: emit_object() + config_changed() en EventEngine Summary

**`EventEngine.emit_object()` traduce `ObjectFinding` al catalogo de eventos (OBJECT_LEFT/OBJECT_REMOVED) sin forzar severidad, y `config_changed()` deja rastro de auditoria de cambios de configuracion de deteccion.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_OBJECT_EVENT_TYPE` (tabla de modulo) + `emit_object()`: traduce `ObjectKind.LEFT`/`REMOVED` a `EventType.OBJECT_LEFT`/`OBJECT_REMOVED`, con `bbox` como campo de primer nivel y payload via `finding.magnitudes()` — sin componer nada en `EventEngine` y sin pasar `severity=` (la severidad la decide el catalogo: WARNING para LEFT, INFO para REMOVED).
- `config_changed(now, **detail)`: publica `CONFIG_CHANGED` con el detalle del cambio, primer emisor de ese tipo desde que existe en el catalogo (Fase 19).
- 5 tests nuevos en `tests/test_event_engine.py`: traduccion de los 2 `ObjectKind`, payload sin `None` con `duration_s` literal, severidad desde el catalogo (WARNING/INFO), bbox de primer nivel (no en payload), y `config_changed` con detalle arbitrario.

## Task Commits

1. **Task 1: `_OBJECT_EVENT_TYPE` + `emit_object()` + `config_changed()`** - `c916186` (feat)
2. **Task 2: `TEST_emit_object_*` + `TEST_config_changed_is_emitted_with_detail`** - `8128490` (test)

## Files Created/Modified
- `backend/events/engine.py` - import de `ObjectFinding`/`ObjectKind`, `_OBJECT_EVENT_TYPE`, `emit_object()`, `config_changed()`
- `tests/test_event_engine.py` - import de `ObjectFinding`/`ObjectKind` + 5 `TEST_*` nuevos

## Decisions Made
- `emit_object` calcado de `emit_behavior` (mismo molde de tabla de traduccion + guarda `if event_type is None: return`), sin componer payload en `EventEngine` — el dominio (`ObjectFinding.magnitudes()`) sigue siendo el unico responsable de las claves del payload.
- El docstring original propuesto en el plan usaba literalmente `severity=` y `upload_min_severity="warning"` como texto explicativo, lo que casualmente coincidia con el propio patron que el `<verify>` automatizado busca (`'severity=' not in src`) — reescrito sin el caracter `=` pegado a `severity` para no autoinvalidar la propia verificacion, preservando el significado.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring de `emit_object` invalidaba su propio `<verify>` automatizado**
- **Found during:** Task 1
- **Issue:** El texto de comentario propuesto por el plan contenia las subcadenas literales `severity=` (en la frase "NO se pasa `severity=` a proposito") y `upload_min_severity="warning"` (que termina en `severity="`), ambas dentro del docstring de `emit_object`. El comando `<verify>` de la propia Task 1 usa `inspect.getsource()` y comprueba `'severity=' not in src` — como `getsource` incluye el docstring, el check fallaba aunque el codigo (la llamada real a `_publish`) nunca pasa `severity=`.
- **Fix:** Reformulado el docstring sin la subcadena literal `severity=` ("A proposito no se fuerza la severidad desde aqui...", `upload_min_severity: "warning"` con dos puntos en vez de igual), preservando el mismo contenido explicativo.
- **Files modified:** `backend/events/engine.py`
- **Verification:** El comando `<verify>` de la Task 1 imprime `OK`
- **Committed in:** `c916186` (parte del commit de Task 1, sin commit separado)

---

**Total deviations:** 1 auto-fixed (1 bug de texto/verificacion)
**Impact on plan:** Cosmetico — no cambia el comportamiento de `emit_object`, solo el texto del docstring para que el `<verify>` automatizado del propio plan pase. Sin impacto en alcance.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `emit_object()` y `config_changed()` quedan listos para que `27-06` los cablee desde `_analyze_objects` en `DetectionWorker` y `27-07` desde el router PUT de clases activas.
- `backend/events/types.py` y `backend/perception/objects.py` sin cambios (`git diff --stat` vacio), tal como exigia el plan.
- Suite completa: 492/492 (487 previos + 5 nuevos).

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED
