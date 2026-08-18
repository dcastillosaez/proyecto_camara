---
phase: 27-multi-clase-y-contexto-de-escena
plan: 04
subsystem: storage
tags: [sqlalchemy, sqlite, repositories, zones]

requires: []
provides:
  - "DetectionStatRepo.hourly_baseline() — media movil por franja horaria sobre unique_tracks, con ventana acotada por until"
  - "kind en Zone legacy (backend/database.py) y en get_zones()"
  - "ConfigRepo con su primer test de roundtrip (list[int] en columna JSON)"
affects: ["27-06 (cableado de exclusion de objetos por zona)", "27-09 (endpoint /api/v2/analytics/context, consume hourly_baseline dos veces)"]

tech-stack:
  added: []
  patterns:
    - "Doble GROUP BY (subquery por dia+hora, luego avg por hora) para media movil sin tabla de agregados nueva"
    - "until como cota superior opcional de ventana temporal, para excluir la hora en curso (parcial) del calculo del baseline"

key-files:
  created: []
  modified:
    - backend/storage/repositories.py
    - backend/database.py
    - tests/test_repositories.py
    - tests/test_database.py

key-decisions:
  - "hourly_baseline() copia literal la query de 27-RESEARCH Q7 (medida: p50 11,2 ms a 525.600 filas, sin indice nuevo) y añade el parametro until que el research dejaba fuera de la firma medida pero ya preveia en prosa"
  - "kind en el Zone legacy es solo lectura en esta fase: no se toca upsert_zone ni el endpoint /api/zones — crear zonas de exclusion desde la UI queda fuera de alcance (lo fija el plan)"
  - "ConfigRepo no se modifica: ya estaba completo (get/set/get_all); esta fase es solo su primer usuario de test"

requirements-completed: []

duration: 25min
completed: 2026-08-17
---

# Phase 27 Plan 04: Media movil horaria y kind de zona Summary

**`DetectionStatRepo.hourly_baseline()` con doble GROUP BY (dia+hora, luego avg entre dias) sobre `unique_tracks`, mas `kind` expuesto en el `Zone` legacy que alimenta al `DetectionWorker`.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments
- `DetectionStatRepo.hourly_baseline(camera_id, since, until=None)` (`backend/storage/repositories.py`): subconsulta `per_day` que suma `unique_tracks` por `(dia, hora)` con `func.strftime`, y query externa que promedia esos totales por hora (`func.avg`), devolviendo `sample_days` y `mins` junto a `avg_total`/`avg_per_minute`. `until` añade una condicion opcional `minute < until` para que el endpoint de `27-09` pueda excluir la hora en curso del baseline. Todos los parametros van ligados (SQLAlchemy `select().where()`); dentro del `text()` del `group_by` solo hay alias literales (`"day"`, `"hour"`).
- `Zone` legacy (`backend/database.py`) gana `kind = Column(String(30), nullable=True)`, copiada caracter a caracter de `storage/models.py:168` para mapear la misma columna fisica (ya garantizada por `_add_missing_columns`). `get_zones()` — la funcion que `main.py:468` usa para alimentar al `DetectionWorker` — ahora expone `kind` en el dict devuelto.
- 5 tests nuevos de `hourly_baseline` (orden de agregacion con datos repartidos en varios minutos por dia, `sample_days`, `until` excluyendo la hora en curso, aislamiento por `camera_id`, ventana vacia) mas `TEST_config_repo_roundtrip_list` (roundtrip de `list[int]`, overwrite y default) en `tests/test_repositories.py`, y `TEST_get_zones_returns_kind` en `tests/test_database.py`.

## Task Commits

1. **Task 1: DetectionStatRepo.hourly_baseline()** - `01967ff` (feat)
2. **Task 2: kind en el Zone legacy de backend/database.py** - `923e095` (feat)
3. **Task 3: Tests del baseline, del kind y del ConfigRepo** - `af3c81c` (test)

## Files Created/Modified
- `backend/storage/repositories.py` - `DetectionStatRepo.hourly_baseline()` (70 lineas nuevas, sin tocar codigo existente)
- `backend/database.py` - `kind` en `Zone` (comentario + 1 columna) y en el dict de `get_zones()` (1 linea)
- `tests/test_repositories.py` - import de `ConfigRepo` + 6 tests `TEST_*` (baseline x5, config_repo x1)
- `tests/test_database.py` - import de `Zone` + `TEST_get_zones_returns_kind`

## Decisions Made
Ver `key-decisions` en el frontmatter. Ninguna requiere ampliacion: las tres son
consecuencia directa del contrato LOCKED del plan (firma exacta de `hourly_baseline`,
alcance de solo-lectura para `kind`).

Se dejan sin marcar los requisitos `BEH-06`/`BEH-07`/`BEH-09` en `REQUIREMENTS.md` porque
el plan `27-11` (puerta de fase) cierra esos tres de una vez con trazabilidad completa a
los criterios de exito — este plan solo aporta las dos piezas de datos, no completa el
requisito end-to-end.

## Deviations from Plan
None - plan ejecutado tal como estaba escrito.

## Issues Encountered
Ninguno. `git diff --stat backend/storage/models.py backend/storage/migrations.py` vacio
en ambas tareas, confirmando que no hizo falta indice nuevo ni migracion (tal como
predecia el research).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `hourly_baseline()` queda disponible para `27-09` (endpoint `/api/v2/analytics/context`),
  que la llamara dos veces con la firma LOCKED de este plan (una para el baseline
  historico con `until`=inicio de la hora en curso, otra para el "ahora" con
  `since`=inicio de la hora en curso).
- `kind` en `get_zones()` queda disponible para `27-06` (cableado de la exclusion de
  objetos por zona en `_rebuild_zone_states`), que ya recibe el dict `z` completo.
- Sin bloqueos. Suite `test_repositories.py` + `test_database.py` + `test_migrations.py`:
  43/43 verdes, sin regresion.

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED

All 4 modified files and all 3 task commit hashes verified present.
