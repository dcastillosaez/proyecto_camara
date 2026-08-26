# Fase 37 — Backends opcionales: PostgreSQL y Redis

**Estado**: COMPLETA. Ejecutada a mano en una sola sesión sin `gsd-sdk` (no
disponible; mismo patrón que las Fases 34/35/36 — este fichero hace de plan y
bitácora únicos, no el formato estándar PLAN.md/SUMMARY.md por sub-tarea).

**Requirements**: SCALE-09, SCALE-10 — **Spec**: `propuesta_mejora/SPEC_v2.md` ADR-06
**Depends on**: Fase 36 (completa, ver `.planning/phases/36-multi-camara-runtime-ui/`)

## Objetivo

Permitir escalar almacenamiento (SQLite → PostgreSQL) y bus de eventos
(in-process → Redis pub/sub) sin reescribir el código de negocio, manteniendo
SQLite/in-process como el default y la ruta soportada de primera clase.

## Decisiones de alcance (acordadas con el usuario antes de tocar código)

1. **Verificación real, no solo teórica**: se levantaron contenedores Docker
   temporales de PostgreSQL 16 y Redis 7 y se corrió la suite dirigida contra
   ellos de verdad, no solo se razonó sobre el código. Esto encontró 2 bugs
   reales de portabilidad que un razonamiento puramente teórico no habría
   detectado (ver "Hallazgos reales" abajo).
2. **Alcance completo en una sesión**: PostgreSQL (repositorios) + Redis
   (EventBus) — no se dividió en dos entregas.
3. **Estrategia SQL**: rama por dialecto dentro de cada repositorio (no
   reescritura a SQLAlchemy Core neutral), para no perder los hints de
   rendimiento medidos y documentados en las Fases 30/31 (`INDEXED BY`, el
   `+` unario, `substr` en vez de `strftime`).

## Diseño

### 1. Config — `backend/config.py`, `backend/api/v2/config_schema.py`

Dos campos nuevos en `Settings`, ambos vacíos por defecto (comportamiento sin
cambios): `database_url` (URL SQLAlchemy async completa; vacío = SQLite sobre
`db_path`, como siempre) y `redis_url` (`redis://host:6379/0`; vacío = bus
in-process, como siempre). Añadidos también a `config_schema.py` (grupo
"servidor" de la sección Cámara) con `type="secret"` — ambas URLs pueden llevar
credenciales embebidas, mismo tratamiento que `ssl_certfile`/`dashboard_user` —
y `applies="restart_server"` (cambiar de motor exige reinicio completo, no hay
ruta de aplicación en caliente). Necesario para no romper
`TEST_all_fields_covers_every_settings_attribute` (Fase 32), que exige
cobertura 1:1 entre `Settings.model_fields` y `config_schema.all_fields()`.

### 2. Engine — `backend/database.py`

`_get_engine()`: con `database_url` vacío, comportamiento idéntico a las Fases
1-36 (`sqlite+aiosqlite:///{db_path}`). Con valor, se usa esa URL tal cual.

`init_db()` ramifica por `engine.dialect.name`:
- **sqlite** (default): exactamente el camino de siempre — migraciones
  incrementales v1→v6 de `storage/migrations.py`, `PRAGMA journal_mode=WAL`,
  `create_all` para `captures` (legacy).
- **cualquier otro dialecto** (postgresql): `storage.models.Base.metadata.create_all`
  (esquema v2 completo de una sola vez) + `create_all` de `captures` +
  `_bootstrap_fresh_schema()`, que siembra `cam1` y sella
  `schema_version=SCHEMA_VERSION` — espejo mínimo de los pasos 4 y 6 de
  `_migrate_v1_to_v2`, sin el resto del historial SQLite-only.

  **Decisión deliberada**: las migraciones incrementales de
  `storage/migrations.py` (`ALTER TABLE ... RENAME`, `PRAGMA table_info`,
  `sqlite_master`, reconstrucción de tabla para `SET NOT NULL`, `INSERT OR
  IGNORE`) siguen siendo 100% SQLite-only y NO se han portado a Postgres.
  Postgres nunca ha tenido una instalación v1 real que migrar — reescribir ese
  historial para un segundo dialecto no aporta nada, solo riesgo. Toda
  instalación Postgres arranca "en fresco" con el esquema v2 completo.

### 3. Repositorios — `backend/storage/repositories.py`

`_dialect_of(session_factory)`: resuelve `session_factory.kw["bind"].dialect.name`
una sola vez, sin abrir sesión ni hacer I/O — permite que `EventRepo` y
`AnalyticsRepo` cacheen `self._dialect` en el constructor sin cambiar su firma
pública (`session_factory` como único argumento), así que **ninguno de los
~15 call sites existentes** (`main.py`, `backend/api/v2/*.py`,
`backend/pipeline/factory.py`) necesitó tocarse.

Ramas por dialecto, todas con el mismo resultado final, nunca con SQL de
usuario sin parametrizar:
- `EventRepo._filter_conditions`: multi-tipo usa `IN` normal de SQLAlchemy Core
  en Postgres (el `+` unario que desactiva el índice en SQLite es un error de
  tipo sobre VARCHAR en Postgres); el filtro `rule=` usa
  `jsonb_array_elements_text(COALESCE(payload -> 'rules', '[]'::json)::jsonb)`
  en vez de `json_each` (específico de SQLite).
- `EventRepo.hourly_counts`: `to_char(ts, 'HH24')` en vez de `strftime("%H", ts)`.
- `AnalyticsRepo._bucket_expr`: `to_char(ts, 'YYYY-MM-DD[ HH24]')` en vez de
  `substr(ts,1,10/13)` — en Postgres `ts` es tipo `timestamp`, no TEXT, así que
  `substr` no aplica.
- `AnalyticsRepo.persons_ranking`: `INDEXED BY idx_events_analytics` se omite
  por completo en Postgres (sintaxis SQLite; el planner de Postgres no necesita
  el hint con `ANALYZE`).

### 4. EventBus — `backend/events/bus.py`

`EventBusBase` (ABC): contrato común. `InProcessBus` = implementación exacta de
las Fases 1-36, sin cambio de comportamiento. `EventBus = InProcessBus` se
mantiene como alias retro-compatible — los ~10 archivos que ya importan
`EventBus` (incluidos tests) siguen funcionando sin tocar una línea.

`RedisBus` (nuevo): publica/consume por un canal pub/sub de Redis
(`redis.asyncio`), serializando `Event` con `model_dump_json()`/
`model_validate_json()`. `publish_threadsafe` usa
`asyncio.run_coroutine_threadsafe` (a diferencia de `InProcessBus`, que solo
encola de forma síncrona, aquí `publish()` es una llamada de red real).
`queue_depth` siempre es 0 (Redis gestiona su propio buffering, no hay cola
local que medir).

`create_event_bus(settings, loop)`: única fábrica — con `redis_url` vacío
devuelve `InProcessBus` (comportamiento de siempre), con valor devuelve
`RedisBus`. `backend/main.py` (`lifespan`) es el único call site que cambia:
`event_bus = create_event_bus(settings, loop=loop)` +
`await event_bus.start()` al arrancar, `await event_bus.close()` al parar
(ambos no-op en `InProcessBus`, reales en `RedisBus`).

## Hallazgos reales (solo aparecieron al verificar contra Postgres de verdad)

Verificado manualmente contra un contenedor `postgres:16-alpine` (Docker) antes
de escribir los tests permanentes — ninguno de estos dos bugs era visible
razonando sobre el código o corriendo solo contra SQLite:

1. **`AnalyticsRepo.occupancy()`**: `GROUP BY e.zone_id` con `z.name` (de un
   `LEFT JOIN`) en el `SELECT` sin agregar — ilegal en SQL estándar. SQLite lo
   tolera (relaja la regla cuando hay dependencia funcional implícita vía la
   PK); Postgres lo rechaza con `GroupingError`. Fix: `GROUP BY e.zone_id, z.name`
   (funciona igual en ambos dialectos, sin rama).
2. **`AnalyticsRepo.persons_ranking()`**: `HAVING cur > 0` referenciando el
   alias `cur` definido en el propio `SELECT` — extensión no estándar que
   SQLite acepta; Postgres la rechaza con `UndefinedColumnError` (a diferencia
   de `ORDER BY`, donde Postgres sí permite alias). Fix: repetir la expresión
   agregada completa en `HAVING` (portable, sin rama).
3. **(No es un bug de código, es una diferencia de comportamiento real y
   documentada aquí)**: SQLite no exige claves foráneas salvo
   `PRAGMA foreign_keys=ON` (que este proyecto no activa); Postgres las exige
   siempre. Insertar un `person_id`/`zone_id`/`camera_id` que no exista en su
   tabla referenciada funciona en SQLite y falla con `ForeignKeyViolationError`
   en Postgres. No se ha encontrado ningún sitio de producción que inserte una
   referencia inválida (el código siempre crea la persona/zona/cámara antes de
   referenciarla), pero es un riesgo real a tener en cuenta si una instalación
   Postgres empieza a fallar con `IntegrityError` donde la misma operación
   "funcionaba" en SQLite.

## Verificación

- **PostgreSQL**: `tests/integration/test_postgres_repositories.py` (7 tests,
  se saltan sin `TEST_POSTGRES_URL`) — dialecto resuelto, filtro multi-tipo
  (rama `IN`), filtro `rule=` (rama `jsonb`), `hourly_counts` (`to_char`),
  `occupancy` (bug 1 fijado), `persons_ranking` (bug 2 fijado), `init_db()`
  completo arrancando de una base Postgres vacía. Ejecutado contra
  `postgres:16-alpine` real vía Docker: **7 passed**.
- **Redis**: `tests/integration/test_redis_bus.py` (6 tests, se saltan sin
  `TEST_REDIS_URL`) — `RedisBus` es `EventBusBase`, entrega a un subscriber
  local, **fan-out entre dos instancias `RedisBus` distintas** (el caso real
  que justifica su existencia: dos "procesos" comparten bus vía el canal
  Redis), `publish_threadsafe` desde un hilo, y que `create_event_bus` elige
  la implementación correcta según `redis_url`. Ejecutado contra `redis:7-alpine`
  real vía Docker: **6 passed**.
- **Arquitectura**: `tests/test_architecture.py::test_raw_sql_text_stays_in_storage_module`
  (nuevo) — protege el criterio 1 de forma permanente: cualquier `sqlalchemy.text(...)`
  fuera de `storage/repositories.py`/`storage/migrations.py` rompe el test,
  salvo la única excepción documentada (`PRAGMA journal_mode=WAL`, ya dentro de
  la rama `if dialect == "sqlite"`).
- **Regresión SQLite** (default, sin tocar nada): suite completa,
  **852 passed, 15 skipped** (los 15 = 7 Postgres + 6 Redis, sin las variables
  de entorno, + 2 preexistentes de otras fases), sin ninguna regresión.

## Fuera de alcance (decisión, no descuido)

- **`backend/recognizer.py` / `persons.db`**: sigue usando `sqlite3` síncrono
  crudo, sin pasar por `storage/repositories.py`. Es una base de datos
  *separada* de `events.db` (nombres de personas/embeddings faciales), fuera
  del ámbito de "todo el acceso a datos" que persigue esta fase (que habla del
  almacenamiento principal de eventos/analítica, el que de verdad necesita
  escalar). No se ha tocado.
- **Migraciones incrementales para Postgres**: como se explica arriba, Postgres
  arranca siempre con el esquema v2 completo — no hay (ni tiene sentido que
  haya) un camino v1→v6 para un dialecto que nunca tuvo una v1.
- **CI contra Postgres/Redis reales**: no hay ningún job de CI que levante
  contenedores — los dos tests de integración se saltan por defecto y solo se
  ejecutan localmente con las variables de entorno correspondientes (mismo
  patrón de riesgo documentado que el job `e2e` de la Fase 34).

## Cuándo merece la pena migrar (criterio 5)

**PostgreSQL**, cuando ocurra alguna de estas condiciones — ninguna es el caso
en una instalación típica de una sola cámara doméstica/LAN:
- Más de una instancia del backend necesita escribir en la misma base de
  eventos a la vez (SQLite con WAL soporta un escritor concurrente; múltiples
  procesos backend escribiendo eventos de cámaras distintas es el caso real
  que empujaría a Postgres).
- El volumen de eventos supera lo que un fichero SQLite gestiona con
  comodidad en el hardware disponible (de referencia: los benchmarks de las
  Fases 30/31 miden con soltura hasta 100.000 eventos; por encima de varios
  millones, con escrituras concurrentes, Postgres empieza a tener ventaja
  real).
- Se necesita replicación, backups gestionados por un motor de BD, o acceso
  concurrente desde herramientas externas (BI, dashboards de terceros) sin
  bloquear el fichero SQLite.

**Redis** (`RedisBus`), cuando:
- El backend deja de ser un único proceso — por ejemplo, si en el futuro se
  separa la ingesta de eventos (pipeline) de la capa HTTP/WebSocket en
  procesos distintos, o se ejecutan varias réplicas del backend detrás de un
  balanceador. `InProcessBus` es, por diseño, un bus de un solo proceso: sus
  suscriptores solo existen en la memoria de ese proceso.
- Se quiere que un proceso externo (un worker de análisis, un script de
  alertas) reciba eventos en tiempo real sin pasar por HTTP/WebSocket.

**Ninguna de las dos** es necesaria para el caso de uso actual del proyecto
(una a pocas cámaras Tapo en LAN, un único proceso backend) — de ahí que
SQLite/in-process sigan siendo el default y la ruta soportada de primera
clase (criterio 4).
