---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 02
subsystem: database
tags: [sqlalchemy, sqlite, migrations, schema-evolution]

# Dependency graph
requires: []
provides:
  - "_migrate_v4_to_v5: backfill zones.polygon desde polygon_json + seed de una Line por defecto desde Settings.line_*_frac"
  - "SCHEMA_VERSION = 5"
affects: [33-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Migracion idempotente con doble guard (columna existe / fila ya sembrada), mismo molde que _migrate_v3_to_v4 y _migrate_v1_to_v2"
    - "Import diferido de backend.config dentro de la funcion de migracion para evitar coste de import en el modulo top-level"

key-files:
  created: []
  modified:
    - backend/storage/migrations.py
    - tests/test_migrations.py

key-decisions:
  - "Guard adicional _column_names(conn, 'zones') antes del UPDATE de polygon_json: una BD que nace directamente en v2+ (via models.Base.metadata.create_all) nunca tuvo esa columna legacy, y sin el guard el UPDATE lanzaba OperationalError sobre esas BDs sinteticas (make_v2_db/make_v3_db de los tests existentes)"
  - "Los dos tests preexistentes que comparaban _schema_version(engine) contra el literal 4 se actualizaron a SCHEMA_VERSION dinamico (mismo patron ya usado por TEST_migration_v3_creates_timeline_index) — run_migrations() siempre encadena hasta la version mas alta, no se detiene en un escalon intermedio"

requirements-completed: [OPS-21, OPS-22, OPS-23]

# Metrics
duration: 20min
completed: 2026-08-24
---

# Phase 33 Plan 02: Migracion v4->v5 (backfill zones.polygon + seed de linea) Summary

**Migracion `_migrate_v4_to_v5` idempotente en `backend/storage/migrations.py`: copia `polygon_json` (v1) a `polygon` (v2) solo donde esta ultima es NULL, y siembra una fila real en `lines` desde `Settings.line_*_frac` si `cam1` no tiene ninguna — protege la continuidad de zonas legacy y de la linea de conteo unica antes de que Plan 33-08 haga que el pipeline lea exclusivamente de `ZoneRepo`/`LineRepo`.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 1 completada
- **Files modified:** 2 (1 fuente, 1 test)

## Accomplishments
- `SCHEMA_VERSION` 4 -> 5, `_migrate_v4_to_v5` registrada en `MIGRATIONS`
- Backfill de `zones.polygon` desde `polygon_json` solo donde `polygon IS NULL` — nunca pisa un poligono ya editado por el editor v2 nuevo
- Seed de una fila en `lines` para `cam1` con los valores de `Settings.line_start_x_frac`/etc. solo si la tabla esta vacia para esa camara — nunca duplica
- 6 tests nuevos que cubren backfill, no-overwrite, seed, no-duplicado e idempotencia sobre una BD v4 sintetica con zona legacy real

## Task Commits

1. **Task 1: Migracion v4->v5 — backfill de zonas.polygon + seed de linea por defecto** - `95e20d0` (feat)

**Plan metadata:** (este commit) `docs(33-02): completar plan migracion v4->v5`

## Files Created/Modified
- `backend/storage/migrations.py` - `SCHEMA_VERSION = 5`, funcion `_migrate_v4_to_v5` con guard de columna (`polygon_json` puede no existir en una BD nacida ya en v2+) y guard de fila existente en `lines`, entrada en `MIGRATIONS`
- `tests/test_migrations.py` - `make_v4_db_with_legacy_zone()` (BD v4 sintetica con zona legacy `polygon_json` poblado + `polygon` NULL, opciones para zona v2 ya editada y linea preexistente), 6 tests `TEST_migration_v5_*`, mas correccion de 2 asserts preexistentes (`_schema_version(engine) == 4` literal -> `== SCHEMA_VERSION` dinamico) rotos por el nuevo escalon de la cadena de migracion

## Decisions Made
- Guard de columna `polygon_json in _column_names(conn, "zones")` no estaba en el pseudo-codigo del plan (`<action>`) pero era necesario: sin el, `run_migrations()` sobre cualquier BD sintetica de test que nace ya en v2 (via `models.Base.metadata.create_all()`, sin pasar por `_migrate_v1_to_v2`) rompia con `OperationalError: no such column: polygon_json`. Aplicado como Rule 1 (bug bloqueante descubierto al ejecutar los tests preexistentes v3/v4 tras encadenar hasta v5).
- Los 2 asserts preexistentes con el literal `4` se corrigieron a `SCHEMA_VERSION` (Rule 1 — bug de test, no de produccion): ya eran fragiles ante cualquier subida futura de version, y el propio fichero ya tenia el patron correcto documentado en `TEST_migration_v3_creates_timeline_index`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Guard de columna faltante para `polygon_json` en `_migrate_v4_to_v5`**
- **Found during:** Task 1 (primera ejecucion de `pytest tests/test_migrations.py`)
- **Issue:** El pseudo-codigo del plan asumia que `zones.polygon_json` siempre existe en cualquier BD que llegue a la migracion v4->v5. Las BDs sinteticas de test que nacen directamente en v2+ (`make_v2_db`/`make_v3_db`, via `models.Base.metadata.create_all()`) nunca pasan por `_migrate_v1_to_v2` y por tanto nunca ganan esa columna legacy — el `UPDATE zones SET polygon = polygon_json ...` lanzaba `OperationalError: no such column: polygon_json` sobre ellas en cuanto `run_migrations()` encadenaba hasta v5.
- **Fix:** Anadido guard `"polygon_json" in _column_names(conn, "zones")` junto al guard de tabla existente, antes de ejecutar el `UPDATE`.
- **Files modified:** `backend/storage/migrations.py`
- **Commit:** `95e20d0`

**2. [Rule 1 - Bug] Asserts de version hardcodeados rotos por el nuevo escalon v5**
- **Found during:** Task 1 (misma ejecucion de tests)
- **Issue:** `TEST_migration_v4_creates_analytics_index` y `TEST_migration_v4_is_idempotent` comparaban `_schema_version(engine) == 4` literal. Al subir `SCHEMA_VERSION` a 5, `run_migrations()` siempre encadena hasta la version mas alta (no se detiene en v4), asi que ambos asserts fallaban aunque el comportamiento migrado fuera correcto.
- **Fix:** Cambiados a `_schema_version(engine) == SCHEMA_VERSION`, mismo patron ya usado (y documentado con comentario) por `TEST_migration_v3_creates_timeline_index` para el mismo problema en la subida v3->v4.
- **Files modified:** `tests/test_migrations.py`
- **Commit:** `95e20d0`

## Issues Encountered

Ninguno bloqueante mas alla de los dos auto-fixes documentados arriba.

## Known Stubs

Ninguno — plan puramente de esquema/migracion, sin UI ni renderizado.

## Threat Flags

Ninguna superficie nueva: la migracion opera sobre `data/events.db` con los mismos privilegios y el mismo backup automático (`_backup_db()`) que las migraciones v1-v4 ya cubrian. Cubierto por el threat model del propio plan (T-33-02, mitigado con los guards `WHERE polygon IS NULL` / `SELECT COUNT(*)` antes de sembrar).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Zonas v1 legacy (`polygon_json`) ahora tambien legibles via `polygon` (columna v2) sin migracion manual — listo para el editor visual de zonas (33-05/33-06).
- Instalaciones con linea unica configurada por `.env` conservan esa linea como fila real en `lines` tras actualizar — Plan 33-08 puede migrar el arranque del pipeline a leer exclusivamente de `LineRepo` sin riesgo de perder la configuracion existente.
- Sin bloqueos conocidos para el resto de la Fase 33.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: `.planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-02-SUMMARY.md`
- FOUND: commit `95e20d0`
