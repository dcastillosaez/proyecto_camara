---
phase: 30-event-timeline-y-centro-de-alertas
plan: 01
subsystem: api
tags: [eventbus, asyncio, websocket, sqlite, rules, fastapi]

# Dependency graph
requires:
  - phase: 19-event-engine-y-esquema-v2
    provides: EventBus, EventRepo, RuleEngine y los cuatro suscriptores concurrentes que este plan colapsa
  - phase: 29-vista-de-operaciones
    provides: precedente de añadir un mensaje nuevo (type "tracks") al /ws existente en vez de abrir otra conexión
provides:
  - "RuleEngine.match(): evaluación pura y síncrona de reglas, con bookkeeping de debounce"
  - "RuleEngine.run_actions(): ejecución diferida de las acciones lentas (Telegram/webhook/grabación)"
  - "make_event_pipeline(): suscriptor único ordenado del EventBus (reglas → payload.rules → INSERT → broadcast → acciones)"
  - "_broadcast_event(): mensaje {\"type\": \"event\", \"event\": {...}, \"media\": {...}} por el /ws legacy"
  - "payload.rules persistido en SQLite (base auditable de OPS-11)"
affects: [30-04 snapshots y media, 30-08 linea temporal en el frontend, 30-10 centro de alertas]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Suscriptor único ordenado en el bus: el orden lo garantiza el lenguaje (una sola corrutina), no el scheduler"
    - "Corte puro/impuro: parte síncrona sin E/S antes del INSERT, parte lenta en fire-and-forget después"
    - "Inyección de dependencias en la fábrica (broadcast_*, schedule) para probar secuencias sin levantar la app"

key-files:
  created: []
  modified:
    - backend/events/rules.py
    - backend/main.py
    - tests/test_event_bus.py

key-decisions:
  - "El bookkeeping de debounce vive en match(), no en run_actions(): una regla casada cuenta como disparada aunque sus acciones corran después"
  - "media va como bloque hermano de event en el mensaje WS, nunca dentro del Event de Pydantic (el contrato persistido no lleva campos de presentación)"
  - "_broadcast_event() no llama a mark_ws_sent(): lo hace _broadcast_v2 y marcarlo dos veces contaminaría la métrica EVENT_TO_WS"
  - "Tres bloques try independientes dentro del pipeline (reglas / INSERT / broadcast): un fallo en un paso no impide los siguientes"
  - "_broadcast_v1_compat sigue en fire-and-forget porque consulta la BD (get_stats_today) y bloquearía el pipeline"

patterns-established:
  - "Pattern 2 de 30-RESEARCH.md: un solo subscribe() por bus cuando el orden importa"
  - "schedule= inyectable en los tests para ejecutar las corrutinas diferidas de forma explícita (sin RuntimeWarning)"

requirements-completed: []  # OPS-10 y OPS-11 quedan avanzados (base backend), no cerrados: los marca 30-12 con evidencia

# Metrics
duration: 24min
completed: 2026-08-20
---

# Phase 30 Plan 01: Suscriptor único ordenado del EventBus Summary

**Los cuatro suscriptores concurrentes del `EventBus` colapsan en un pipeline único que evalúa las reglas antes del `INSERT`, persiste `payload.rules` y emite el `Event` tipado completo por el `/ws` legacy.**

## Performance

- **Duration:** ~24 min
- **Started:** 2026-08-20T20:36Z
- **Completed:** 2026-08-20T21:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Condición de carrera de D-14 cerrada por construcción: `payload.rules` ya no se pierde, porque las reglas se evalúan y se escriben en el evento *antes* de que `EventRepo.insert()` lo lea. Antes se perdía **siempre**, no "a veces" — `_apply_rules` mutaba el evento después de que `_persist_event` lo hubiera escrito.
- `RuleEngine` partido en una parte pura/síncrona (`match()`) y otra lenta/asíncrona (`run_actions()`), con `evaluate()` conservado como wrapper compatible. Los 14 tests de `tests/test_rule_engine.py` pasan **sin haberse tocado**, que es la prueba de que el corte no cambió el comportamiento.
- Un webhook colgado ya no puede impedir que el evento se persista ni que llegue al navegador: `run_actions()` va después del `INSERT` y en fire-and-forget (mitiga T-30-03).
- El `/ws` que el frontend realmente escucha emite ahora el `Event` completo (`id`, `severity`, `zone_id`, `bbox`, `payload`) más un bloque `media` con las cuatro claves a `null` — el contrato literal que consumen 30-08 y 30-10.

## Task Commits

1. **Task 1: Partir `RuleEngine.evaluate()` en `match()` + `run_actions()`** — `14dcac5` (refactor)
2. **Task 2: `make_event_pipeline()` y `_broadcast_event()`** — `0297614` (feat)
3. **Task 3: Tests de la carrera cerrada** — `182fdb2` (test)

## Files Created/Modified

- `backend/events/rules.py` — `match()` (síncrono, sin efectos, con debounce), `run_actions()` (conserva el logging de acción desconocida/fallida), `evaluate()` como wrapper.
- `backend/main.py` — `_broadcast_event()`, `make_event_pipeline()` y un único `event_bus.subscribe("event_pipeline", ...)` en `lifespan()` sustituyendo a los cuatro anteriores.
- `tests/test_event_bus.py` — 4 tests nuevos con `EventRepo` real sobre SQLite temporal (fixture `repo`), `schedule` inyectado que colecciona corrutinas y `RuleEngine` construido a mano sin YAML.

## Decisions Made

Las del bloque `key-decisions` del frontmatter. Todas venían fijadas por el plan y por `30-RESEARCH.md`; no hubo que decidir nada nuevo durante la ejecución.

## Deviations from Plan

None - plan executed exactly as written.

Tres criterios de aceptación se cumplen a nivel de código pero no a nivel de `grep` literal, porque los textos que el propio plan mandaba escribir contienen las cadenas buscadas:

| Criterio | Esperado | Real | Motivo |
|---|---|---|---|
| `sed -n '/def match/,/def run_actions/p' \| grep -c await` | 0 | 2 | Las dos apariciones están en el docstring de `match()` que el plan dicta literalmente ("sin await", "un await ahi reabriria"). El cuerpo no tiene ningún `await`. |
| `grep -n "_persist_event\|_apply_rules"` | 0 | 1 | El comentario de sustitución que el plan dicta menciona `_apply_rules` para explicar qué se eliminó. Las funciones ya no existen. |
| `grep -c "mark_ws_sent"` | 1 | 2 | La segunda está en el docstring de `_broadcast_event()` explicando que **no** lo llama. La única llamada real sigue en `_broadcast_v2`. |

## Issues Encountered

- La primera pasada de la suite completa falló en `tests/test_upload_queue.py::TEST_failed_upload_emits_event` (1 failed, 533 passed). El test pasa aislado, pasa con su fichero completo y pasa en una segunda ejecución de la suite completa (534 passed, 2 skipped). Es un flake de temporización preexistente: el test espera un `asyncio.sleep(0.05)` fijo a que termine una subida lanzada en background, y bajo la carga de la suite entera ese margen se queda corto. **Fuera del alcance de este plan** (no toca `UploadQueue` ni el bus); anotado como candidato a endurecer con un `wait_until()` en lugar de un sleep fijo.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- El contrato del mensaje `{"type": "event", "event": {...}, "media": {...}}` está fijado y verificado; 30-08/30-10 pueden consumirlo literalmente.
- `media` sale con las cuatro claves a `null`; 30-04 rellena `snapshot_url` sin cambiar la forma del mensaje.
- `payload.rules` ya se persiste, así que el histórico auditable de OPS-11 empieza a poblarse desde el primer evento que case una regla.
- T-30-02 (XSS almacenado vía nombre de regla) queda explícitamente pendiente de 30-08: el backend no renderiza, la mitigación es `textContent` en el frontend.

## Known Stubs

- `media` en `_broadcast_event()` sale siempre con `recording_id`, `clip_url`, `thumbnail_url` y `snapshot_url` a `null`. Es intencional y está documentado en el `<interfaces>` del plan: 30-04 rellena `snapshot_url` y la forma del mensaje no cambia.

## Self-Check: PASSED

- `backend/events/rules.py` — FOUND (`def match`, `async def run_actions`, `async def evaluate`)
- `backend/main.py` — FOUND (`make_event_pipeline`, `_broadcast_event`, 1 solo `event_bus.subscribe(`)
- `tests/test_event_bus.py` — FOUND (4 tests nuevos, 11 en el fichero)
- Commits `14dcac5`, `0297614`, `182fdb2` — FOUND en `git log`
- Suite completa: 534 passed, 2 skipped

---
*Phase: 30-event-timeline-y-centro-de-alertas*
*Completed: 2026-08-20*
