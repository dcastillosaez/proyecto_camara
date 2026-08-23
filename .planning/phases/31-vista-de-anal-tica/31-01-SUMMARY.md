---
phase: 31-vista-de-anal-tica
plan: 01
subsystem: database
tags: [sqlalchemy, sqlite, migrations, seed-data, indexing]

# Dependency graph
requires:
  - phase: 30-event-timeline-y-centro-de-alertas
    provides: idx_events_ts_id (Fase 30) y el patron de migracion idempotente que 31-02 a 31-04 dan por sentado
provides:
  - "idx_events_analytics (camera_id, ts, person_id, zone_id, track_id) declarado en Event.__table_args__ y creado por _migrate_v3_to_v4"
  - "SCHEMA_VERSION=4, con la migracion v3->v4 registrada en MIGRATIONS"
  - "scripts/seed_events.py puede sembrar person_id/zone_id reales via --persons/--zones (35%/60%)"
  - "guarda de formato de Event.ts (TEXT ISO ancho fijo), precondicion de substr() en AnalyticsRepo"
affects: [31-02, 31-03, 31-04, 31-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Indices nuevos: Index() aditivo en __table_args__ + migracion _migrate_vN_to_vM con CREATE INDEX IF NOT EXISTS + _record_version(conn, N) literal"
    - "seed_events(): parametros aditivos con default 0 que preservan el consumo de rng byte a byte del comportamiento previo"

key-files:
  created: []
  modified:
    - scripts/seed_events.py
    - backend/storage/models.py
    - backend/storage/migrations.py
    - tests/test_migrations.py
    - tests/test_repositories.py

key-decisions:
  - "El orden de extraccion de variables en seed_events() se reordeno respecto al borrador del plan (type/severity antes que track_id/confidence) para preservar EXACTAMENTE el orden de consumo de random.Random que tenia el codigo inline original — el plan avisaba de este riesgo explicitamente"
  - "TEST_migration_v3_creates_timeline_index y TEST_migration_v3_is_idempotent (Fase 30) comparaban schema_version contra el literal 3; con SCHEMA_VERSION=4, run_migrations() sobre una base v2 encadena hasta v4, asi que se cambiaron a comparar contra la constante SCHEMA_VERSION"

requirements-completed: [OPS-12, OPS-14]

# Metrics
duration: ~35min
completed: 2026-08-23
---

# Phase 31 Plan 01: Índice de analítica y siembra con identidad/zona Summary

**Índice compuesto `idx_events_analytics` con su migración v3→v4, y `seed_events.py` extendido para sembrar `person_id`/`zone_id` reales sin romper el determinismo de la Fase 30**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- `idx_events_analytics (camera_id, ts, person_id, zone_id, track_id)` declarado en `Event.__table_args__` (bases nuevas) y creado por `_migrate_v3_to_v4` (bases existentes), con `SCHEMA_VERSION=4`
- `scripts/seed_events.py` acepta `--persons`/`--zones`; con los defaults produce filas byte a byte idénticas a las de antes del cambio (determinismo verificado con `TEST_query_performance_100k` y los presupuestos @10k de la Fase 30)
- Guarda de formato: `TEST_datetime_storage_format_is_fixed_width_iso` cae si `Event.ts` deja de serializarse como TEXT ISO de ancho fijo, precondición silenciosa de la que dependerán las agregaciones de 31-04

## Task Commits

1. **Task 1: Sembrar identidad y zona en scripts/seed_events.py** - `7203c95` (feat)
2. **Task 2: idx_events_analytics en models.py y migración v3 -> v4** - `1dcc013` (feat)
3. **Task 3: Guarda del formato de almacenamiento de DateTime** - `82f627c` (test)

## Files Created/Modified
- `scripts/seed_events.py` - parámetros `persons`/`zones` aditivos (default 0), CLI `--persons`/`--zones`
- `backend/storage/models.py` - sexto `Index` en `Event.__table_args__`: `idx_events_analytics`
- `backend/storage/migrations.py` - `SCHEMA_VERSION=4`, `_migrate_v3_to_v4` registrada en `MIGRATIONS`
- `tests/test_migrations.py` - `make_v3_db`, terna de tests v3→v4, y corrección de dos tests preexistentes de la Fase 30 (ver Deviations)
- `tests/test_repositories.py` - `TEST_seed_events_populates_persons_and_zones`, `TEST_seed_events_defaults_leave_person_and_zone_null`, `TEST_datetime_storage_format_is_fixed_width_iso`

## Decisions Made
- Orden de consumo de `rng` en `seed_events()`: el plan proponía extraer `track_id`/`confidence` antes que `type`/`severity`, pero el código original los evaluaba en el orden `type → severity → track_id → confidence` (evaluación de tupla izquierda a derecha). Se reordenó la extracción para preservar exactamente esa secuencia — el propio plan advertía de este riesgo y pedía verificar con el test de determinismo si no coincidía. Verificado: `TEST_query_performance_100k` y los tres presupuestos @10k de la Fase 30 siguen en verde sin tocar sus asserts.
- `_record_version(conn, 4)` con el literal, nunca `SCHEMA_VERSION` — mismo criterio que ya exigía la Fase 30, verificado con `grep -c "_record_version(conn, SCHEMA_VERSION)" == 0`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Dos tests preexistentes de la Fase 30 comparaban schema_version contra el literal 3**
- **Found during:** Task 2, al correr `pytest tests/test_migrations.py -q`
- **Issue:** `TEST_migration_v3_creates_timeline_index` y `TEST_migration_v3_is_idempotent` partían de una base v2 y aserteaban `_schema_version(engine) == 3` tras `run_migrations()`. Al subir `SCHEMA_VERSION` a 4, `run_migrations()` encadena todas las migraciones pendientes (v2→v3→v4) en una sola llamada, así que la base termina en v4, no en v3 — comportamiento correcto de `run_migrations()`, no una regresión.
- **Fix:** Se cambiaron ambos asserts de `== 3` a `== SCHEMA_VERSION` (constante ya importada en el fichero), igual que ya hacía `TEST_schema_version_recorded` para no quedar obsoleto en cada fase futura. El índice que cada test verifica (`idx_events_ts_id`) no se tocó.
- **Files modified:** `tests/test_migrations.py`
- **Verification:** `pytest tests/test_migrations.py -q` → 15 passed
- **Committed in:** `1dcc013` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1)
**Impact on plan:** Ajuste necesario y directamente causado por el propio cambio de esta tarea (subir `SCHEMA_VERSION`). Sin scope creep — no se tocó ninguna otra aserción ni comportamiento de la Fase 30.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- El contrato que consumen 31-04 (`AnalyticsRepo`) y 31-05 (router) ya existe: `idx_events_analytics` con las 5 columnas exactas medidas en 31-RESEARCH.md, y `seed_events(..., persons=N, zones=M)` para poblar datos de prueba reales.
- La guarda de formato de `Event.ts` deja constancia explícita de que `substr(ts,1,N)` depende de un detalle de serialización de SQLAlchemy; si algún día cambia, este test (no una gráfica) es el que debe caer.
- Suite completa verificada: 613 passed, 2 skipped (sin cambios respecto al recuento previo a esta fase, `test_architecture.py`/`test_security_regression.py`/`test_rule_engine.py` incluidos).

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
