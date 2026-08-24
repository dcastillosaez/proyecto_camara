---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 04
subsystem: detection
tags: [tracker, bytetrack, linezone, supervision, events]

# Dependency graph
requires:
  - phase: 33-01
    provides: LineRepo/RuleRepo y RuleEngine.would_match() publico (no consumidos aun por este plan)
  - phase: 33-02
    provides: migracion v4->v5 con seed de la linea de conteo unica ('linea-1'/'Linea de conteo')
provides:
  - "PersonTracker con N lineas independientes (self._lines), cada una con su propio LineZone y contadores"
  - "reconfigure_lines(lines: list[dict]) que sustituye la lista completa conservando conteo por id repetido"
  - "get_counts() por line_id: {line_id: {name, in, out, total}}"
  - "crossings con line_id/line_name propagados hasta emit_line_crossing (payload)"
affects: [33-05, 33-07, 33-08, 33-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Molde de lista-de-estado por-linea (self._lines), igual que _zone_states en detection.py para zonas"
    - "ByteTrack/DetectionsSmoother compartidos entre todas las lineas — solo el conteo es por-linea"
    - "Wrapper de compatibilidad temporal (reconfigure_line) documentado con el caller real y el plan que lo retira"

key-files:
  created: []
  modified:
    - backend/tracker.py
    - backend/events/engine.py
    - backend/main.py
    - tests/test_tracker.py
    - tests/test_phase9.py
    - tests/test_detection_worker.py

key-decisions:
  - "reconfigure_lines conserva in_count/out_count/crossed_ids de las lineas cuyo id se repite; solo las lineas nuevas arrancan en cero"
  - "reconfigure_line(start, end) singular se mantiene como wrapper de compatibilidad sobre reconfigure_lines hasta que 33-05 retire su unico caller (backend/camera.py:194)"
  - "backend/main.py (fuera de files_modified del plan) se ajusto igualmente: su construccion PersonTracker(start=..., end=...) ya no compila con la firma nueva y rompe el arranque real de la app; se migro a lines=[{id: 'linea-1', name: 'Linea de conteo', ...}] replicando la convencion de la siembra v4->v5 de migrations.py — el Plan 33-08 sustituye este bloque por la carga real desde LineRepo"
  - "emit_line_crossing usa crossing.get('line_id')/.get('line_name') (nunca acceso directo) para tolerar crossings del wrapper legacy que no llevan esas claves"

requirements-completed: [OPS-22]

# Metrics
duration: 5min
completed: 2026-08-24
---

# Phase 33 Plan 04: PersonTracker — refactor a N lineas de conteo Summary

**PersonTracker pasa de un unico LineZone fijo a una lista de lineas independientes (self._lines) con conteo propio por linea, ByteTrack compartido, y crossings identificados por line_id/line_name propagados hasta el payload de emit_line_crossing.**

## Performance

- **Duration:** 5 min (commits 17:33:08 -> 17:38:30 CEST)
- **Started:** 2026-08-24T15:33:08Z
- **Completed:** 2026-08-24T15:38:30Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- `PersonTracker` soporta N lineas independientes con conteo propio (`in`/`out`/`total`) por `line_id`, manteniendo ByteTrack y el suavizado de detecciones COMPARTIDOS.
- `reconfigure_lines()` sustituye la lista completa de lineas sin recrear `self._byte_tracker`, conservando el conteo acumulado de las lineas cuyo `id` se repite.
- Cada crossing emitido por `update()` identifica su linea de origen (`line_id`/`line_name`); `emit_line_crossing` propaga ambas claves al payload del evento sin romper el contrato previo (`direction`/`is_intrusion`).
- Los 4 callers de `PersonTracker(...)` con firma posicional antigua en `tests/test_detection_worker.py` quedaron migrados a `lines=[...]`, y se verifico con grep en todo el repo que no queda ninguna construccion con la firma antigua.

## Task Commits

Cada tarea se comiteo de forma atomica:

1. **Task 1: PersonTracker — de una linea a N lineas con conteo independiente** - `984e698` (feat)
2. **Task 2: emit_line_crossing propaga line_id/line_name + migracion de PersonTracker(...) en test_detection_worker.py** - `a364f72` (feat)

**Plan metadata:** (este commit) `docs(33-04): completar plan refactor PersonTracker a N lineas`

## Files Created/Modified
- `backend/tracker.py` - `PersonTracker` con `self._lines` (lista de `{id, name, zone, in_count, out_count, crossed_ids}`), `reconfigure_lines()`, `get_counts()` por linea, `reconfigure_line()` como wrapper de compatibilidad
- `backend/events/engine.py` - `emit_line_crossing` anade `line_id`/`line_name` al payload via `.get()`
- `backend/main.py` - construccion de `PersonTracker` en `lifespan()` migrada a `lines=[{"id": "linea-1", "name": "Linea de conteo", ...}]` (fix de bloqueo, ver Deviations)
- `tests/test_tracker.py` - migrado a `lines=[...]`, asserts sobre `get_counts()["l1"]`, tests nuevos de N lineas/reconfigure_lines/conservacion de conteo/ByteTrack compartido
- `tests/test_phase9.py` - fixture y patches migrados a `lines=[...]` / `tracker._lines[0]["zone"]`
- `tests/test_detection_worker.py` - las 4 construcciones posicionales de `PersonTracker(...)` migradas a `lines=[...]`; assert de `get_counts()["total"]` migrado a `get_counts()["l1"]["total"]`

## Decisions Made
- Ver `key-decisions` en el frontmatter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrada la construccion de `PersonTracker` en `backend/main.py`**
- **Found during:** Verificacion final (grep de firma antigua en todo el repo, tras Task 2)
- **Issue:** El plan solo listaba `backend/tracker.py`, `backend/events/engine.py` y tres ficheros de test en `files_modified`. `backend/main.py:460` construye `PersonTracker(start=..., end=..., frame_rate=...)` con la firma antigua; con la firma nueva (`lines`, `frame_rate`) esa llamada lanza `TypeError` en el arranque real de la app (`lifespan()`). Ningun test de la suite ejercita `lifespan()` (los `TestClient(app)` existentes no usan `with`, asi que no disparan el startup), por lo que la suite completa seguia en verde a pesar del bloqueo — pero el servidor real no arrancaria.
- **Fix:** Migrada la construccion a `PersonTracker(lines=[{"id": "linea-1", "name": "Linea de conteo", "start": ..., "end": ...}], frame_rate=...)`, reusando el mismo `id`/`name` que la siembra de `migrations.py:_migrate_v4_to_v5` (D-01) para no introducir una segunda convencion de nombres. El Plan 33-08 (ya planificado, `33-08-PLAN.md:88-221`) sustituye explicitamente este bloque por la carga real desde `LineRepo`.
- **Files modified:** `backend/main.py`
- **Verification:** `python -c "import ast; ast.parse(open('backend/main.py').read())"` (sintaxis valida); grep de `PersonTracker\(\s*(start|sv\.Point|line_start)` en todo el repo sin coincidencias; suite completa (`pytest tests/ -q`) en verde, 745 passed / 2 skipped.
- **Committed in:** `a364f72` (parte del commit de Task 2)

---

**Total deviations:** 1 auto-fijado (1 bloqueante)
**Impact on plan:** Necesario para que la app arrancase realmente tras el cambio de firma de `PersonTracker.__init__`; sin este fix el codigo pasaba tests pero rompia en produccion. Sin scope creep: no se toco la logica de `LineRepo`/hot-reload, que sigue siendo responsabilidad explicita del Plan 33-08.

## Issues Encountered
Ninguno mas alla de la desviacion documentada arriba.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `PersonTracker` ya soporta el plural de lineas que el CRUD del Plan 33-07 y el hot-reload del Plan 33-05 necesitan.
- `backend/camera.py:194` sigue llamando a `reconfigure_line(start, end)` (wrapper de compatibilidad); el Plan 33-05 lo migra a `reconfigure_lines`/`LineRepo` y retira el wrapper.
- `backend/main.py` sigue construyendo una unica linea fija desde `Settings`; el Plan 33-08 la sustituye por la carga real de N lineas desde `LineRepo`.
- El endpoint `/counts` de `main.py` ahora devuelve la forma anidada por `line_id` (`{"linea-1": {"name", "in", "out", "total"}}`) en vez de la forma plana anterior — ningun test de la suite depende de esa forma, pero cualquier consumidor de frontend que la lea directamente (fuera del alcance de este plan) necesitara actualizarse en una fase posterior de UI.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

All modified files and both task commits (984e698, a364f72) verified present.
