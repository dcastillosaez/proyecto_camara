---
phase: 19-event-engine-y-esquema-de-datos-v2
plan: 01
subsystem: events, storage
tags: [event-bus, sqlalchemy, migrations, pydantic]
requires: []
provides:
  - backend/events/types.py (EventType, Event, Severity, DEFAULT_SEVERITY)
  - backend/events/bus.py (EventBus)
  - backend/storage/models.py (esquema v2, 12 tablas)
  - backend/storage/repositories.py (EventRepo, DetectionStatRepo, RecordingRepo, ZoneRepo, RuleRepo, ConfigRepo)
  - backend/storage/migrations.py (run_migrations, SCHEMA_VERSION)
  - scripts/seed_events.py
affects:
  - data/events.db (migracion real pendiente — ver "Next")
tech-stack:
  added: []
  patterns:
    - "Un unico objeto Event (Pydantic) viaja por bus, BD y WebSocket — sin DTOs intermedios"
    - "EventBus: cola interna acotada + consumer task; publish() no bloquea nunca, descarta el evento mas antiguo al llenarse"
    - "Paginacion por cursor (ts, id) en base64, sin OFFSET"
key-files:
  created:
    - backend/events/__init__.py
    - backend/events/types.py
    - backend/events/bus.py
    - backend/storage/__init__.py
    - backend/storage/models.py
    - backend/storage/repositories.py
    - backend/storage/migrations.py
    - scripts/seed_events.py
    - scripts/__init__.py
    - tests/test_event_types.py
    - tests/test_event_bus.py
    - tests/test_repositories.py
    - tests/test_migrations.py
  modified: []
key-decisions:
  - "El primer objetivo del catalogo no cabia con el nombre de tabla real: backend/database.py define CrossingEvent con __tablename__='events' (no 'crossing_events' como asumia el plan). La migracion renombra ALTER TABLE events RENAME TO crossing_events antes de crear el nuevo esquema, resolviendo la colision de nombres y preservando el dato tal como pide el plan (crossing_events sobrevive, no se borra)."
  - "app_config.value (columna JSON) sufre coercion de afinidad NUMERIC en SQLite: un valor JSON-encoded que parece un entero puro ('2') se almacena como INTEGER real, no como texto. _get_schema_version() maneja ambos casos (int o str-JSON) al leer."
  - "IDs de eventos migrados son deterministas (uuid5 sobre el id original de crossing_events) + INSERT OR IGNORE, para que re-ejecutar la migracion sea idempotente incluso si se resetea manualmente schema_version."
  - "zones y recordings v1 se extienden con ALTER TABLE ADD COLUMN generico (diff contra el modelo ORM v2), no solo camera_id como sugeria el texto del plan — necesario para que RecordingRepo/ZoneRepo funcionen contra una BD migrada de verdad."
requirements-completed: [EVT-01, EVT-02, EVT-04, DB-10, DB-11, DB-12, DB-13, DB-14]
duration: "~1h (ejecucion autonoma en worktree aislado)"
completed: "2026-08-08"
---

# Phase 19 Plan 01: Event Engine contract y esquema de datos v2 Summary

Catálogo de 22 `EventType` + `Event` Pydantic como contrato único, `EventBus` async con fan-out aislado por handler y cola acotada, esquema v2 de 12 tablas con 7 índices, y migración idempotente v1→v2 con backup automático — verificado con datos sintéticos, no contra la base de datos real (ver "Next").

## Qué se construyó

**Task 1 — Catálogo de eventos** (`backend/events/types.py`): `EventType` con los 22 valores exactos de `SPEC_v2.md` §6.1, `Severity` (info/warning/critical), `Event` Pydantic con `id` autogenerado (uuid4), validación de `bbox` como tupla de 4 enteros (gratis vía tipado), y un `model_validator` que aplica `DEFAULT_SEVERITY` por tipo solo si el usuario no especificó severidad explícitamente (usa `model_fields_set`, no un sentinel). 9/9 tests.

**Task 2 — EventBus** (`backend/events/bus.py`): cola interna `asyncio.Queue(maxsize=1000)` + un consumer task que hace fan-out a cada suscriptor en su propia `asyncio.Task` (aislamiento de excepciones). `publish()` es no bloqueante por diseño: nunca tiene un punto de suspensión real, así que `publish_threadsafe()` (usado por los workers de la Fase 18, que son hilos) puede empujar eventos vía `loop.call_soon_threadsafe` sin awaitear nada. Al llenarse la cola se descarta el evento más antiguo y se contabiliza en `stats["dropped"]`. 7/7 tests, incluyendo verificación de identidad (`is`) entre los tres suscriptores.

**Task 3 — Esquema v2 y repositorios** (`backend/storage/`): 12 tablas declarativas (`cameras`, `persons`, `face_embeddings`, `tracks`, `events`, `detection_stats`, `recordings`, `zones`, `lines`, `rules`, `app_config`, `system_metrics`) con los 7 índices de `SPEC_v2.md` §7.2. `EventRepo` con paginación por cursor `(ts, id)` codificado en base64 (sin `OFFSET`, estable bajo inserción concurrente). `DetectionStatRepo.upsert_minute()` acumula en la fila del minuto en vez de insertar una fila por detección. `scripts/seed_events.py` genera eventos sintéticos vía `sqlite3` crudo (no ORM) para que la carga de 100k filas sea rápida — reutilizable en la Fase 31. Consulta filtrada sobre 100k eventos: por debajo de 500 ms. 6/6 tests.

**Task 4 — Migraciones idempotentes** (`backend/storage/migrations.py`): `run_migrations(engine)` sincrono, con guarda de versión en `app_config['schema_version']` (no-op si ya está al día), backup a `data/backups/events-{ts}.db` antes de tocar el esquema, y `_migrate_v1_to_v2` que resuelve la colisión de nombres (ver decisión abajo), extiende `zones`/`recordings` con las columnas nuevas, registra la cámara `cam1`, y convierte cada fila de `crossing_events` en un evento `LINE_CROSSED` con `payload={"direction": ..., "is_intrusion": ..., "person_name": ...}`. 8/8 tests, incluyendo migración de una BD sintética construida con los modelos v1 reales de `backend/database.py` (no SQL copiado a mano).

## Deviations from Plan

**[Rule 1 - Bug/mismatch] La tabla v1 real se llama `events`, no `crossing_events`**
Encontrado durante: Task 4. El plan y el CONTEXT.md asumen que la tabla de cruces v1 se llama `crossing_events`, pero `backend/database.py:CrossingEvent.__tablename__` es literalmente `"events"` — el mismo nombre que la nueva tabla v2 de eventos tipados necesita. Fix: la migración renombra `events` → `crossing_events` (`ALTER TABLE events RENAME TO crossing_events`) como primer paso, antes de `create_all()`. Esto satisface la letra del plan ("no borrar crossing_events") y resuelve la colisión de nombres de la única forma consistente con el código real. Verificado con `TEST_crossing_events_preserved` y `TEST_migration_is_idempotent`. Commit: f063ca2.

**[Rule 1 - Bug] Afinidad NUMERIC de SQLite corrompe silenciosamente `schema_version`**
Encontrado durante: Task 4 (tests en verde). `app_config.value` es columna `JSON`; SQLite no reconoce `"JSON"` como texto e infiere afinidad `NUMERIC`, así que un valor JSON-encoded que parece un entero puro (`"2"`) se almacena como `INTEGER` real, no como cadena — `json.loads()` sobre el valor leído lanza `TypeError`. Fix: `_get_schema_version()` distingue `int`/`float` de `str` antes de parsear. Verificado con `TEST_schema_version_recorded` y `TEST_migration_on_empty_db`. Commit: f063ca2.

**[Rule 1 - Gap] `zones`/`recordings` necesitan más que `camera_id`**
Encontrado durante: Task 4. El texto del plan solo menciona añadir `camera_id` a `zones` y `recordings`, pero el modelo ORM v2 de `Recording` tiene 14 columnas más que el v1 (`started_at`, `duration_s`, `upload_state`, etc. — ver `SPEC_v2.md` §7.1). `create_all()` no altera tablas existentes, así que sin extender explícitamente esas columnas, `RecordingRepo` fallaría contra una BD migrada de verdad. Fix: `_add_missing_columns()` genérico que diffea el modelo ORM contra `PRAGMA table_info` real y añade lo que falte (nullable, `camera_id` con `DEFAULT 'cam1'`). Commit: f063ca2.

**Total deviations:** 3 auto-fixed (2 bugs de colisión/afinidad, 1 gap de alcance). **Impacto:** ninguno negativo — los tres eran necesarios para que la migración funcionara contra datos reales; sin ellos, Task 5 (migración real) habría fallado o corrompido `schema_version`.

## Issues Encountered

Ninguno bloqueante. Advertencia no relacionada con esta fase: `face_recognition_models` emite un `UserWarning` de `pkg_resources` deprecado (preexistente, fuera de alcance).

## Next Phase Readiness

**Pendiente — Task 5 (checkpoint, requiere accion manual):** migrar `data/events.db` real. Esta sesión corre en un worktree aislado (`F:\...\worktrees\event-engine-schema-v2-653038`) sin la base de datos de producción ni el servidor en ejecución — el checkpoint del plan exige parar el servidor real y ejecutar la migración contra el `data/events.db` del repositorio principal. Pasos para el usuario, una vez este plan esté mergeado a `main`:

```bash
# 1. Parar el servidor
# 2. Backup manual adicional
copy data\events.db data\events.db.pre-v2

# 3. Conteos previos
.venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('data/events.db'); [print(t, c.execute(f'select count(*) from {t}').fetchone()[0]) for t in ('events','zones','captures','recordings')]"

# 4. Ejecutar la migracion
.venv/Scripts/python.exe -c "from sqlalchemy import create_engine; from backend.storage.migrations import run_migrations; run_migrations(create_engine('sqlite:///data/events.db'))"

# 5. Verificar: select count(*) from events where type='LINE_CROSSED' debe coincidir con el conteo previo de la tabla events (v1)
```

Ready for `19-02` (Event Engine, RuleEngine, integración) — no depende de que la migración real ya se haya ejecutado, solo del esquema/código de este plan, que ya está completo y testeado.
