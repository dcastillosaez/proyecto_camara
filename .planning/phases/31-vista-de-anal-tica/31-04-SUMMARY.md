---
phase: 31-vista-de-anal-tica
plan: 04
subsystem: database
tags: [sqlalchemy, sqlite, sql-aggregation, analytics, indexed-by]

# Dependency graph
requires:
  - phase: 31-01
    provides: idx_events_analytics (camera_id, ts, person_id, zone_id, track_id) y seed_events(persons=, zones=)
provides:
  - "AnalyticsRepo (backend/storage/repositories.py) con hourly(), summary(), occupancy(), persons_ranking() y person_avatars() — las cuatro agregaciones de la fase resueltas en SQL"
  - "bucket_for()/_bucket_expr(): cubo horario <=7 dias, diario por encima, sobre substr(ts,...) TEXT ISO"
  - "Las cuatro agregaciones medidas por debajo de 0,5s sobre 100.000 eventos con identidad/zona sembradas"
affects: [31-05, 31-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SQL crudo con text() + parametros por diccionario en session.execute(sql, {...}), nunca f-strings con datos del cliente — solo _bucket_expr() se interpola, y devuelve una de dos constantes literales del modulo"
    - "INDEXED BY <nombre> como hint explicito cuando el planner de SQLite elige el indice equivocado (persons_ranking); la migracion que crea el indice queda como precondicion dura de la consulta"
    - "captures vive en events.db bajo una Base de SQLAlchemy distinta de backend.storage.models (backend/database.py); se consulta con SQL crudo sobre el nombre de tabla fisico, nunca via ORM cruzado entre Bases"

key-files:
  created: []
  modified:
    - backend/storage/repositories.py
    - tests/test_repositories.py

key-decisions:
  - "TEST_analytics_summary_returns_peak_and_min se escribio con 2 cubos reales (5 y 34 eventos, total 39) en vez de los '3 cubos de valores 5, 34 y 0' que describia el plan: GROUP BY nunca puede devolver un grupo con COUNT(*)=0 -- un cubo asi no puede aparecer en la CTE. El relleno a cero de cubos completamente vacios es responsabilidad del router (31-05), que conoce el eje completo; summary() solo ve cubos con >=1 evento, documentado en el propio docstring del metodo."
  - "El test de EXPLAIN QUERY PLAN de persons_ranking se nombro TEST_analytics_budget_ranking_uses_analytics_index (con el prefijo 'analytics_budget') en vez de un nombre 'analytics_ranking_*' mas descriptivo, para que `pytest -k analytics_budget` seleccione los 7 tests de la Task 3 tal como exige el criterio de aceptacion literal del plan ('en verde con 7 tests')."
  - "OPS-13 no se marca completo en REQUIREMENTS.md pese a estar en la lista de requirements del frontmatter: el texto del requisito es 'La analitica MUESTRA ranking...', y este plan solo construye el repositorio -- nada se muestra todavia sin el router (31-05) ni la UI de ranking (31-08). Mismo patron que 31-01..31-03 aplicaron a OPS-09/OPS-13 previamente en fases anteriores (avanzar sin cerrar)."

requirements-completed: []

# Metrics
duration: ~25min
completed: 2026-08-23
---

# Phase 31 Plan 04: AnalyticsRepo — agregaciones de analítica en SQL Summary

**`AnalyticsRepo` con las cuatro agregaciones de la Vista de analítica (serie temporal, resumen, ocupación por zona y ranking de personas) resueltas íntegramente en SQL sobre `events`, medidas contra el presupuesto de 500 ms @100k eventos con identidad y zona reales**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- `bucket_for()` decide cubo horario (≤7 días) o diario (>7 días) — decisión de legibilidad, no de tamaño, documentada en el propio docstring para que nadie la "optimice" por peso
- `AnalyticsRepo.hourly()`: serie actual + periodo anterior en una sola consulta, con relleno a cero delegado al router (31-05)
- `AnalyticsRepo.summary()`: total, pico, mínimo (CTE), comparación con el periodo anterior (doble ventana) y conocidas/desconocidas (personas distintas, no eventos) — tres consultas, cada una documentada con su razón de ser
- `AnalyticsRepo.occupancy()`: ocupación por zona filtrada a `ZONE_ENTERED` (una intrusión ya cuenta como entrada), con `COALESCE(z.name, e.zone_id)` contra zonas borradas
- `AnalyticsRepo.persons_ranking()`: la única consulta de la fase que necesita `INDEXED BY idx_events_analytics` — sin el hint SQLite elige `idx_events_person` y hace skip-scan (212,6 ms frente a 26,7 ms medidos @100k)
- `AnalyticsRepo.person_avatars()`: capture más reciente por persona desde `captures` (vive en `events.db`, no en `persons.db`), sin `JOIN persons` ni `ATTACH DATABASE`
- Las cuatro agregaciones verificadas por debajo de 0,5 s sobre 100.000 eventos con `persons=60`/`zones=14` sembrados, más dos tests de regresión que impiden medir sobre datos vacíos y un `EXPLAIN QUERY PLAN` que fija el uso del índice de analítica

## Task Commits

1. **Task 1: AnalyticsRepo con bucket_for, hourly() y summary()** - `a7aad98` (feat)
2. **Task 2: occupancy(), persons_ranking() con INDEXED BY y person_avatars()** - `b1d9781` (feat)
3. **Task 3: Presupuesto del criterio 4 a 100.000 eventos y regresión de datos no vacíos** - `42c18e5` (test)

## Files Created/Modified

- `backend/storage/repositories.py` — `BUCKET_HOUR_MAX_DAYS`, `bucket_for()`, `_bucket_expr()` y `class AnalyticsRepo` (5 métodos públicos) añadidos al final del módulo; import nuevo de `pathlib.Path` para `person_avatars()`
- `tests/test_repositories.py` — 20 tests nuevos: 6 de `hourly()`/`summary()`/`bucket_for`, 7 de `occupancy()`/`persons_ranking()`/`person_avatars()`, 7 de presupuesto @100k y regresión de datos no vacíos (incluido el `EXPLAIN QUERY PLAN`)

## Decisions Made

- **Fuente de datos: `events`, nunca `detection_stats`** — decisión ya cerrada en el propio plan (no de este executor), documentada aquí porque es la premisa de todo el fichero: coherencia con el histograma actual del dashboard, invariante 9 de CLAUDE.md, y `detection_stats` es más caro (60,7 ms frente a 27,0 ms) porque su preagregado es por minuto.
- **`TEST_analytics_summary_returns_peak_and_min` con 2 cubos reales, no 3** — ver Key Decisions arriba. `GROUP BY` no puede devolver un grupo de tamaño 0; el test verifica pico y mínimo sobre cubos que sí existen (5 y 34 eventos, total 39), que es lo que la implementación realmente puede producir.
- **Nombre del test de `EXPLAIN QUERY PLAN` con prefijo `analytics_budget`** — para que el comando de verificación literal del plan (`pytest -k analytics_budget` con 7 tests en verde) se cumpla exactamente como está escrito en el criterio de aceptación de la Task 3.
- **`captures` se crea a mano en el test de `person_avatars`** — la tabla vive en `events.db` pero bajo una `Base` de SQLAlchemy distinta (`backend/database.py`), no `backend.storage.models`; el fixture `db` de este fichero solo ejecuta `models.Base.metadata.create_all()`. Se creó con SQL crudo (`CREATE TABLE IF NOT EXISTS captures (...)`) en el propio test, igual que otros tests del fichero ya usan `sqlite3.connect()` cuando necesitan estado que el fixture no provee.

## Deviations from Plan

### Auto-fixed Issues

None — el plan no dejó ningún bug, funcionalidad crítica faltante ni bloqueo que resolver; los tres ajustes de esta sección son de diseño de tests (documentados arriba en Key Decisions), no correcciones de código de producción.

**Total deviations:** 0 auto-fixed. 3 ajustes de diseño de tests documentados en Key Decisions (interpretación de un `<behavior>` no realizable tal cual estaba escrito, nombrado de test para satisfacer un criterio de aceptación literal, y construcción manual de una tabla ajena al fixture).

## Issues Encountered

Ninguno relevante para el código de producción. El único punto de fricción fue puramente de redacción del plan: el bullet de `<behavior>` de `TEST_analytics_summary_returns_peak_and_min` describe "3 cubos de valores 5, 34 y 0", que es irrealizable con la SQL exacta que el propio plan especifica en `<action>` (`WITH b AS (SELECT bucket, COUNT(*) AS n ... GROUP BY bucket)`: un grupo con `COUNT(*)=0` no puede existir). Resuelto interpretando la intención (verificar pico y mínimo reales) con 2 cubos que sí pueden existir.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- El contrato que consume 31-05 (router `/api/v2/analytics`) ya existe completo: `bucket_for()`, `hourly()`, `summary()`, `occupancy()`, `persons_ranking()` y `person_avatars()`, con las firmas exactas especificadas en `<interfaces>` del plan.
- 31-05 tiene que resolver el relleno a cero del eje completo (cubos vacíos) que `hourly()` deja fuera a propósito, el emparejamiento por posición (no por etiqueta) entre `cur`/`prev` en cubo diario, y el cálculo del porcentaje de variación que `summary()` no calcula.
- 31-09 (export) puede reutilizar los mismos métodos sin tocar `AnalyticsRepo`.
- Suite `tests/test_repositories.py` completa en verde: **59 passed**. `tests/test_architecture.py`: **5 passed**. Suite completa del proyecto (`tests/`): **637 passed, 2 skipped** — mismo recuento de skips que antes de este plan, sin regresiones.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
