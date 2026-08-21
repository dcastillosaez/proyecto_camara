---
phase: 30-event-timeline-y-centro-de-alertas
plan: 02
subsystem: storage
tags: [sqlite, sqlalchemy, indices, migraciones, json1, paginacion]

# Dependency graph
requires:
  - phase: 19-event-engine-y-esquema-v2
    provides: esquema v2, EventRepo.query() con cursor (ts,id) y run_migrations() con backup automático
  - phase: 30-event-timeline-y-centro-de-alertas
    provides: "30-01 persiste payload.rules — sin esa clave el filtro por regla no tendría nada que leer"
provides:
  - "Índice idx_events_ts_id (ts DESC, id DESC): ORDER BY y cursor por valor de fila sin TEMP B-TREE"
  - "SCHEMA_VERSION=3 y _migrate_v2_to_v3(): CREATE INDEX IF NOT EXISTS, idempotente y no destructivo"
  - "_record_version(): cada migración sella su propia versión de destino"
  - "EventRepo._filter_conditions(): condiciones WHERE compartidas por query() y count()"
  - "EventRepo.query(type=EventType|list[EventType], rule=str): multi-tipo y filtro por nombre de regla"
  - "EventRepo.count(): total de coincidencias con los mismos filtros, sin cursor ni limit"
affects: [30-05 router de eventos, 30-08 linea temporal en el frontend, 30-10 centro de alertas, 31 analitica]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Prefijo '+' unario en el término IN multi-valor: desactiva un índice concreto sin tocar el resto del plan"
    - "json_each(payload,'$.rules') dentro de un EXISTS correlacionado, con bindparam"
    - "Helper de condiciones compartido entre la consulta paginada y su COUNT(*) — un solo sitio donde cambia un filtro"

key-files:
  created: []
  modified:
    - backend/storage/models.py
    - backend/storage/migrations.py
    - backend/storage/repositories.py
    - tests/test_migrations.py
    - tests/test_repositories.py

key-decisions:
  - "El nombre del parámetro sigue siendo 'type' (no 'types'): mantenerlo evita tocar los 7 llamadores actuales de query()"
  - "El '+' unario solo se aplica con ≥2 tipos; con uno solo, la igualdad sobre idx_events_type_ts sigue siendo la mejor opción"
  - "count() es un método aparte, no una clave más del retorno de query(): el router decide cuándo pagarlo (primera página y con filtros)"
  - "_record_version() nuevo: _migrate_v1_to_v2 escribía json.dumps(SCHEMA_VERSION), que al subir la constante a 3 habría sellado v3 desde el paso v2"
  - "El bindparam expandido lleva type_=String: sin tipo, SQLAlchemy no puede compilar la consulta con literal_binds y el test de plan de consulta no podría inspeccionar el SQL real"
  - "make_v2_db() hace DROP INDEX del índice nuevo: create_all() lee el __table_args__ de hoy, así que sin el DROP la base de partida ya sería v3 y el test no probaría nada"

patterns-established:
  - "Hallazgo 7 de 30-RESEARCH.md aplicado tal cual: un único índice compuesto en vez de 2^n índices por combinación de filtros"

requirements-completed: []  # OPS-09 avanza (capa de almacenamiento) pero no se cierra: la superficie HTTP llega en 30-05 y la marca 30-12

# Metrics
duration: 15min
completed: 2026-08-20
---

# Phase 30 Plan 02: Índice de la línea temporal y filtros de servidor Summary

**`idx_events_ts_id` con su migración v2→v3, y `EventRepo` capaz de filtrar por varios tipos a la vez y por nombre de regla, con un `count()` para el contador "{N} de {total}".**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-08-20T20:36Z
- **Completed:** 2026-08-20T20:51Z
- **Tasks:** 2 (4 commits: 2 ciclos RED/GREEN)
- **Files modified:** 5

## Accomplishments

- El índice compuesto elimina el `TEMP B-TREE FOR ORDER BY` que arrastraba **toda** consulta filtrada, no solo las lentas. El caso patológico medido (`type IN (3 valores) + severity`) pasa de 54 ms a 0,52 ms @100k — y el test `TEST_multi_type_query_plan_uses_timeline_index` compila el SQL real que produce `_filter_conditions` y comprueba el plan con `EXPLAIN QUERY PLAN`, así que la regresión queda cerrada por prueba, no por comentario.
- El filtro por regla lee `payload.rules`, exactamente la clave que 30-01 empezó a persistir. Las dos piezas encajan sin capa intermedia.
- Ningún llamador existente de `query()` se tocó: `git diff --stat backend/database.py` sale vacío y los 7 puntos de llamada siguen pasando un enum suelto.
- La migración es la más barata posible: `CREATE INDEX IF NOT EXISTS` no altera filas ni columnas, y el `_backup_db()` que ya existía cubre el resto (T-30-07).

## Task Commits

1. **Task 1: Índice y migración v2→v3** — `fdd895a` (test, RED) + `2890a2f` (feat, GREEN)
2. **Task 2: `query()` multi-tipo, filtro por regla y `count()`** — `27e6723` (test, RED) + `d76df78` (feat, GREEN)

## Files Created/Modified

- `backend/storage/models.py` — quinta entrada en `Event.__table_args__`: `Index("idx_events_ts_id", ts.desc(), id.desc())`.
- `backend/storage/migrations.py` — `SCHEMA_VERSION = 3`, `_migrate_v2_to_v3()`, `_record_version()` y la tupla `(3, …)` en `MIGRATIONS`. `run_migrations()` y `_backup_db()` intactos.
- `backend/storage/repositories.py` — `_filter_conditions()` (estático), `query()` con `type: EventType | list[EventType]` y `rule`, y `count()`.
- `tests/test_migrations.py` — `make_v2_db()`, `_index_names()` y 3 tests nuevos.
- `tests/test_repositories.py` — 6 tests nuevos, incluido el de plan de consulta y el de inyección.

## Decisions Made

Las del bloque `key-decisions`. Dos no venían del plan y se explican abajo como desviaciones.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_migrate_v1_to_v2` habría sellado la versión 3 antes de tiempo**
- **Found during:** Task 1
- **Issue:** El paso v1→v2 escribía `json.dumps(SCHEMA_VERSION)` en `app_config`. Al subir la constante a 3, una base v1 recién migrada al paso v2 quedaba marcada como v3 dentro de la misma transacción. Hoy no rompe nada (ambos pasos comparten el `engine.begin()`), pero convierte la versión registrada en una mentira en cuanto alguien añada un paso v4 o mueva la transacción.
- **Fix:** Helper `_record_version(conn, version)` y llamadas explícitas con `2` y `3`.
- **Files modified:** `backend/storage/migrations.py`
- **Commit:** `2890a2f`

**2. [Rule 3 - Blocking] El bindparam expandido no compilaba con `literal_binds`**
- **Found during:** Task 2
- **Issue:** `bindparam("types", expanding=True)` sin `type_` produce `CompileError: No literal value renderer is available for literal value "'INTRUSION'" with datatype NULL`, lo que impedía compilar la consulta para pasársela a `EXPLAIN QUERY PLAN`. Sin eso, el test del Pitfall 2 solo podía probar un SQL escrito a mano, desacoplado de la implementación.
- **Fix:** `bindparam("types", expanding=True, type_=String)` (más el import de `String`).
- **Files modified:** `backend/storage/repositories.py`
- **Commit:** `d76df78`

### Ajustes de método (no de comportamiento)

- El plan describía la base de partida del test de migración como "create_all + schema_version=2". Tal cual, `create_all()` ya crea `idx_events_ts_id` (viene del `__table_args__` modificado en el mismo plan) y el test habría pasado sin migrar nada. `make_v2_db()` añade un `DROP INDEX IF EXISTS` y el test afirma explícitamente que el índice **no** está antes de `run_migrations()`.
- El test de plan de consulta usa 2.000 filas sembradas, no 100.000: sin `ANALYZE`, SQLite elige el plan por heurística de esquema, no por cardinalidad, y el resultado es el mismo con una fracción del tiempo de test.

## Issues Encountered

Ninguno. Los dos ciclos RED/GREEN fallaron y pasaron a la primera (salvo el `CompileError` documentado arriba).

## User Setup Required

None - la migración se aplica sola en el próximo arranque, con backup automático previo.

## Next Phase Readiness

- 30-05 puede montar `GET /api/v2/events` sobre `query()`/`count()` sin lógica SQL propia: `type[]`, `rule`, severidad, zona, cámara, rango y cursor ya están cubiertos.
- La recomendación de coste sigue vigente y sin implementar aguas arriba: `count()` solo debe llamarse con `cursor is None` y con algún filtro activo (T-30-06). El repositorio no lo impone — es responsabilidad del router.
- La base real de `data/events.db` aún no se ha migrado (checkpoint 19-01 Task 5 sigue abierto); subirá de v1 a v3 de una pasada cuando se ejecute.

## Threat Flags

Ninguno. La superficie nueva es interna (métodos de repositorio); el filtro `rule` y el `IN` multi-valor van por bindparam y tienen test de regresión (`TEST_query_rule_filter_is_not_interpolated`).

## Known Stubs

Ninguno.

## Self-Check: PASSED

- `backend/storage/models.py` — FOUND (`idx_events_ts_id`, 8 `Index(` frente a 7 antes)
- `backend/storage/migrations.py` — FOUND (`SCHEMA_VERSION = 3`, `_migrate_v2_to_v3`, `(3, ` en `MIGRATIONS`, `run_migrations` sin cambios en el diff)
- `backend/storage/repositories.py` — FOUND (`_filter_conditions`, `async def count`, `+events.type IN :types`, `json_each`, 4 `bindparam`)
- `backend/database.py` — sin cambios (`git diff --stat` vacío)
- Commits `fdd895a`, `2890a2f`, `27e6723`, `d76df78` — FOUND en `git log`
- Suite completa: **543 passed, 2 skipped** (534 antes + 9 nuevos)

---
*Phase: 30-event-timeline-y-centro-de-alertas*
*Completed: 2026-08-20*
