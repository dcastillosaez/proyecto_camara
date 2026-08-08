---
phase: 19-event-engine-y-esquema-de-datos-v2
plan: 02
subsystem: events, pipeline, api
tags: [rule-engine, event-engine, notifier, websocket-v2]
requires: ["19-01"]
provides:
  - backend/events/rules.py (RuleEngine, Rule, When, Action, load_rules)
  - backend/events/actions.py (ActionRegistry, ACTIONS, configure)
  - backend/events/engine.py (EventEngine)
  - config/rules.yaml (generado desde .env)
  - scripts/generate_initial_rules.py
  - GET /api/v2/events, GET /api/v2/rules, WS /api/v2/ws
affects:
  - backend/notifier.py (reducido a ejecutor)
  - backend/database.py (delega en EventRepo para el dominio de crossing events)
  - backend/pipeline/detection.py, backend/pipeline/manager.py (event_queue -> event_engine)
  - backend/main.py (lifespan wiring completo)
tech-stack:
  added: [PyYAML]
  patterns:
    - "RuleEngine.evaluate() resuelve acciones via ActionRegistry.get(type) — nunca eval()"
    - "Debounce con clave compuesta (rule, camera_id, person_id|track_id), purgado por TTL"
    - "EventEngine mantiene su propio estado (tracks conocidos, inside-set por zona) y solo emite en transiciones"
    - "Migraciones deben cubrir tanto 'v1 preexistente extendido' como 'v2 recien creado sin columnas legacy' — create_all() no rellena huecos de una tabla que ya existia"
key-files:
  created:
    - backend/events/actions.py
    - backend/events/engine.py
    - config/rules.yaml
    - scripts/generate_initial_rules.py
    - tests/test_rule_engine.py
    - tests/test_actions.py
    - tests/test_event_engine.py
  modified:
    - backend/events/rules.py
    - backend/notifier.py
    - backend/database.py
    - backend/storage/migrations.py
    - backend/storage/models.py
    - backend/storage/repositories.py
    - backend/pipeline/detection.py
    - backend/pipeline/manager.py
    - backend/main.py
    - requirements.txt
    - .env.example
key-decisions:
  - "Extendido When con un campo payload: dict opcional (match exacto AND) para poder traducir is_intrusion (payload de v1) a una regla sin inventar un EventType nuevo. No estaba en la interfaz del plan pero era la unica forma de preservar el comportamiento exacto de ALERT_ON_INTRUSION."
  - "database.py se reescribio para el dominio de crossing events (insert_event, get_events_filtered, get_stats_today, purge_old_events, delete_events_range) delegando en EventRepo; zones/captures/recordings NO se tocaron (la migracion solo les anade columnas, su ORM v1 sigue siendo valido)."
  - "Persistencia/WS/reglas se suscriben al EventBus en orden pero se ejecutan CONCURRENTEMENTE (cada handler en su propio asyncio.Task, por diseno del bus de 19-01). El comentario del plan sobre 'el orden importa para que el evento tenga id antes del WS' no aplica: el id es un uuid4 generado en el cliente al construir el Event, no lo asigna la persistencia."
  - "camera_id, upload_state, enabled etc. en storage/models.py pasaron de default= (Python-side) a server_default= (SQL DEFAULT) — necesario porque backend/database.py sigue insertando en zones/recordings con sus propias clases ORM v1, que no conocen las columnas v2 y por tanto nunca les asignarian el default de Python."
requirements-completed: [EVT-03, EVT-05, RULE-01, RULE-02, RULE-03, RULE-04]
duration: "~2.5h (ejecucion autonoma en worktree aislado)"
completed: "2026-08-09"
---

# Phase 19 Plan 02: RuleEngine, EventEngine y notifier-como-ejecutor Summary

`notifier.py` deja de decidir cuándo alertar — esa lógica vive ahora en `config/rules.yaml`, evaluada por `RuleEngine` con debounce compuesto y condiciones `time_range` que cruzan medianoche. `EventEngine` convierte estado crudo del pipeline (tracks, zonas, cruces) en eventos tipados solo en las transiciones, y `main.py` conecta todo end-to-end: `EventBus` → {persistencia, WebSocket v1/v2, reglas}. Verificado con servidor real arrancado (modelo YOLO cargado, sin cámara RTSP accesible desde este entorno) — los endpoints `/api/v2/rules`, `/api/v2/events`, `/api/stats` y `/api/alerts/status` responden correctamente.

## Qué se construyó

**Task 1 — RuleEngine** (`backend/events/rules.py`): `When`/`Action`/`Rule` Pydantic, `load_rules()` no-fatal (una regla inválida se loguea y el resto sigue operativo), `time_range` que cruza medianoche (`"23:00-06:00"` matchea 23:30 y 02:00, no 12:00), debounce con clave compuesta `(rule, camera_id, person_id|track_id)` purgado por TTL. 11/11 tests (10 del plan + 1 para el filtro `payload` añadido en Task 2).

**Task 2 — ActionRegistry y notifier reducido** (`backend/events/actions.py`, `backend/notifier.py`): 8 acciones registradas (`record`, `snapshot`, `notify`, `telegram`, `webhook`, `log`, `upload_drive`, `set_flag`); dependencias reales (recorder, snapshot, Drive upload) se inyectan vía `configure()` — sin inyectar, cada acción loguea y no falla. `notifier.py` queda con `send_telegram`/`send_webhook`/`test`/`active_channels` únicamente. `scripts/generate_initial_rules.py` traduce `ALERT_ON_INTRUSION`/`ALERT_ON_UNKNOWN`/`ALERT_ON_DETECTION`/`ALERT_COUNT_THRESHOLD` en reglas equivalentes. 5/5 tests.

**Task 3 — EventEngine** (`backend/events/engine.py`): mantiene su propio estado (tracks activos, inside-set por zona, flag de cámara offline) y solo emite en transiciones — nunca por frame. `accumulate_detections()`/`flush_stats()` agregan en memoria y vuelcan una fila por minuto a `detection_stats` (nunca una fila por detección). Integrado en `DetectionWorker`: `event_loop`/`event_queue` desaparecen del constructor, sustituidos por `event_engine: EventEngine | None` que usa `bus.publish_threadsafe()` desde el hilo del worker. 7/7 tests + 73 tests de pipeline/detección sin regresión.

**Task 4 — Integración completa** (`backend/main.py`, `backend/database.py`): `lifespan` instancia `EventBus`/`EventEngine`/`RuleEngine`, carga `config/rules.yaml`, y suscribe tres handlers (persistencia vía `EventRepo`, WebSocket v1-compat + v2, reglas). `/ws` v1 sigue emitiendo el formato `{"type": "detection", ...}` de siempre (vía un handler puente que solo reacciona a `LINE_CROSSED`); `/api/v2/ws` emite el sobre `{"v": 2, "kind": "event", "data": {...}}`. `database.py` reescrito: el dominio de crossing events delega en `EventRepo` (con métodos nuevos `count_since`/`hourly_counts`/`delete_before`/`delete_range`), preservando exactamente la forma de dict que ya consumían los endpoints v1.

## Deviations from Plan

**[Rule 1 - Gap] `When` necesitaba un filtro de `payload` para traducir `is_intrusion`**
Encontrado durante: Task 2. `ALERT_ON_INTRUSION` en v1 depende de `payload["is_intrusion"]` (calculado por el horario de acceso), y ninguno de los campos de `When` (`event`, `zone`, `camera`, `time_range`, `days`, `min_confidence`, `duration_gte`, `person`) puede expresar esa condición. Fix: se añadió `When.payload: dict[str, Any] | None` con match exacto AND. Sin este campo, la única alternativa era invertir `schedule_start`/`schedule_end`/`schedule_days` en un `time_range`/`days` complejo que además no puede expresar la disyunción "fuera de horario O fuera de días" con las reglas AND-only actuales — el filtro de payload es la solución correcta y mínima. Test: `TEST_payload_filter_matches_exact_key`. Commits: 1e64861 (regla generada), 6091dfb→1b224f2 (rules.py, mismo commit que RuleEngine).

**[Rule 1 - Bug] Tablas `zones`/`recordings` recien creadas por `create_all()` carecen de columnas legacy**
Encontrado durante: Task 4, corriendo la suite completa contra una BD nueva. `_migrate_v1_to_v2` solo *extiende* zones/recordings cuando la tabla v1 ya existia (`_add_missing_columns` anade columnas v2 a un v1 existente). En una instalacion nueva (sin `events.db` previo), `create_all()` crea esas tablas con **solo** las columnas v2 — pero `backend/database.py` sigue usando sus propias clases ORM v1 (`polygon_json`, `created_at`, `gdrive_id`, `upload_status`, `duration_secs`) para las operaciones CRUD de zonas/grabaciones, que Task 4 dejo sin tocar deliberadamente (esas tablas no cambian de significado, solo ganan columnas). Fix: `_ensure_columns()` generico que anade las columnas legacy que falten, se ejecute o no el camino de "extender v1". Detectado con 4 fallos en cascada (`polygon_json`, `created_at` en zones; `gdrive_id`/`upload_status`/`duration_secs`, `created_at` en recordings) — cada uno revelado al arreglar el anterior. Tests: `TEST_fresh_db_supports_legacy_zone_and_recording_columns` + toda `test_database.py` en verde. Commit: 09666b6.

**[Rule 1 - Bug] `camera_id`/`upload_state`/`polygon` con default solo de Python, no de SQL**
Encontrado durante: Task 4, mismo run. `models.Recording.camera_id`/`upload_state`/`upload_attempts` y `models.Zone.enabled` usaban `default=` (aplicado solo cuando el ORM v2 construye la fila) — pero las inserciones reales siguen pasando por las clases v1 de `database.py`, que no conocen esas columnas y por tanto nunca les asignan valor, disparando `NOT NULL constraint failed`. Fix: `default=` → `server_default=` (DEFAULT a nivel SQL, aplicado por SQLite sea cual sea el ORM que inserte). `Zone.polygon` (sin ningun default posible razonable para un JSON) paso a `nullable=True` — es un campo v2-only sin escritor todavia; una futura fase que active `ZoneRepo` en la app lo poblara. Commit: 09666b6 (mismo fix que el anterior, un solo commit).

**[Rule 3 - Fuera del boundary del plan, pero necesario] `database.py` reescrito antes de tiempo**
El plan asigna la reescritura de `database.py` sin SQL propio a Task 4, pero el Task 2 (reduccion de `notifier.py`) ya dejaba `main.py` con una llamada rota (`Notifier(alert_on_intrusion=...)`) porque los mismos metodos que Task 2 elimina son los que `_drain_events`/`_camera_watchdog` invocaban. Se opto por dejar `main.py` transitoriamente inconsistente entre los commits de Task 2 y Task 4 (documentado, no se corrio la suite completa en ese intervalo) en vez de escribir un adaptador temporal que se tiraria minutos despues — la suite completa vuelve a estar en verde (232/232) al cerrar Task 4.

**Total deviations:** 4 (1 gap de diseño, 3 bugs de la migración contra BD nueva). **Impacto:** ninguno negativo en el resultado final — los tres bugs de migración habrían roto una instalación nueva (no solo una actualizada desde v1); quedan cerrados y cubiertos por test.

## Issues Encountered

Ninguno bloqueante. `/api/v2/cameras/{id}/health` devuelve 500 en este entorno porque no hay cámara RTSP accesible (IP de LAN privada) — no está relacionado con el trabajo de esta fase (no se tocó ese endpoint) y no se pudo confirmar si es un problema preexistente o solo la falta de cámara real; queda para verificar cuando el usuario pruebe contra la cámara real.

## Next Phase Readiness

**Pendiente — Task 5 (checkpoint, requiere cámara real):** validación en vivo 30 min, prueba de regla de intrusión, prueba de debounce, prueba de regla inválida, paridad de alertas. No ejecutable en este worktree aislado (sin cámara, sin servidor de producción).

**Pendiente — 19-01 Task 5:** migración de la BD real de producción (ver `19-01-SUMMARY.md`, sección "Next Phase Readiness", para los comandos exactos). Debe ejecutarse **antes** de desplegar este branch, con el servidor parado.

Verificado end-to-end salvo cámara real: servidor arrancado con `uvicorn`, modelo YOLO26n cargado, endpoints v1 y v2 respondiendo. Suite completa: **232/232**.

Ready para Fase 20.
