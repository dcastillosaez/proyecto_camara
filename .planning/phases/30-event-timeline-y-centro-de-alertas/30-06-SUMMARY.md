---
phase: 30-event-timeline-y-centro-de-alertas
plan: 06
subsystem: api
tags: [fastapi, router, alerts, muting, app-config, asyncio-lock, tdd]

# Dependency graph
requires:
  - phase: 30-01
    provides: payload.rules escrito por el motor de reglas — la clave de agrupación
  - phase: 30-02
    provides: EventRepo.query() con ts_from y severity ya indexados
  - phase: 30-05
    provides: convenciones del router v2 (docstring, limiter, parcheo de get_session_factory en tests)
provides:
  - "GET /api/v2/alerts: grupos por regla o por tipo con count, last_ts, muted_until y contadores del badge"
  - "POST /api/v2/alerts/mute y /unmute: silenciado temporal persistido en app_config"
  - "Clave app_config alerts.muted_rules como contrato de silenciado"
affects: [30-09 alertCenter.js, 30-07 marcado de la campana y el cajón]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Agrupación en servidor sobre un conjunto acotado (200 por severidad) con `truncated` en la respuesta, en vez de COUNT por grupo"
    - "Expiración perezosa: sin tarea de fondo — las entradas caducadas se filtran al leer y se purgan en la siguiente escritura"
    - "asyncio.Lock de módulo alrededor del read-modify-write de una única fila de app_config"
    - "Lista blanca de duraciones en vez de entero libre: no existe 'silenciar para siempre'"

key-files:
  created:
    - backend/api/v2/alerts.py
    - tests/test_alerts.py
  modified:
    - backend/main.py

key-decisions:
  - "El silencio es solo de presentación (D-16/D-17): alerts.py no importa ni toca RuleEngine ni run_actions, así que la regla se sigue evaluando y sus acciones siguen grabando y avisando"
  - "Los eventos info entran en el cajón solo si dispararon una regla: si una regla se molestó en disparar, es una alerta aunque su severidad por catálogo sea info"
  - "Se silencia por Rule.name, no por tipo de evento: los grupos type:* llevan mutable=false"
  - "El estado va en app_config vía ConfigRepo y no en una tabla nueva — como mucho hay tantas filas como reglas en rules.yaml y una tabla costaría otra subida de SCHEMA_VERSION"
  - "Un solo sort por (rank de severidad, last_ts) con reverse=True: el doble sort del plan era redundante"

# Metrics
duration: 14min
completed: 2026-08-21
---

# Phase 30 Plan 06: Centro de alertas backend Summary

**El cajón de alertas deja de ser un filtro en el navegador: `GET /api/v2/alerts` devuelve las alertas de la ventana ya agrupadas por la regla que las disparó, ordenadas por severidad y recencia, con los contadores exactos del badge de la campana; `mute`/`unmute` silencian una regla por 15 min, 1 h u 8 h persistiendo en `app_config`.**

## Performance

- **Duration:** ~14 min
- **Tasks:** 2
- **Files modified:** 3 (2 nuevos)
- **Commits:** 4 (2 de tests RED + 2 de implementación)

## Accomplishments

- La agrupación se calcula en el servidor. Antes `dashboard.js` se descargaba una página de eventos, descartaba los `info` y ordenaba por severidad en el cliente; agrupar por regla con ese enfoque habría exigido bajarse el historial entero. Ahora el navegador recibe grupos ya montados con `count`, `last_ts`, `last_event_id` y `zone_id` del último evento.
- Un evento puede pertenecer a varios grupos: si `payload.rules` trae dos nombres, cuenta en los dos. Es lo correcto para el cajón — cada regla merece su propia línea aunque las disparara el mismo evento.
- Los eventos `info` que dispararon una regla sí aparecen. Un cruce de línea es `info` por catálogo, pero si el operador escribió una regla para él, quiere verlo en la campana.
- Los grupos sin regla (`type:INTRUSION`) salen con `mutable: false`. No se puede silenciar "todas las intrusiones", solo la regla concreta que las está generando (D-16).
- El silenciado no toca el motor de reglas. Está verificado por grep en los criterios de aceptación: el módulo no menciona `RuleEngine`, `run_actions` ni desactiva nada. Silenciar desde la UI no puede hacerte perder el clip ni el aviso (T-30-22).
- Expiración sin tarea de fondo: `_load_muted()` descarta al vuelo las entradas cuyo `until` ya pasó, y la siguiente escritura las borra del disco. Un backend que estuvo apagado seis horas arranca con los silencios ya caducados sin hacer nada.
- Duración en lista blanca `(900, 3600, 28800)`. Cualquier otro valor devuelve 400 con un mensaje que enumera las válidas. No hay forma de silenciar indefinidamente (T-30-21).
- El read-modify-write sobre la única fila `alerts.muted_rules` va dentro de un `asyncio.Lock` de módulo, así que dos silenciados simultáneos no se pisan (T-30-23). El `ConfigRepo` se queda agnóstico de negocio.
- Cada `mute` y cada `unmute` emiten `CONFIG_CHANGED` con el nombre de la regla y la duración. Silenciar una alerta crítica deja rastro en el mismo historial que consulta la línea temporal (T-30-20).

## Task Commits

1. **Task 1: GET /api/v2/alerts — agrupación por regla en servidor** — `5a697b5` (test RED, 8 tests / 9 casos) + `84c7597` (feat)
2. **Task 2: mute/unmute con persistencia en app_config** — `0407af2` (test RED, 7 tests) + `2477851` (feat)

## Files Created/Modified

- `backend/api/v2/alerts.py` (nuevo, 163 líneas) — router con prefijo `/api/v2/alerts`, `configure(event_engine)`, `_config_repo()`, `_load_muted()` y los tres endpoints. Constantes `MUTED_KEY`, `MUTE_DURATIONS`, `SEVERITY_RANK`, `PAGE_CAP`.
- `backend/main.py` — `alerts_v2_module.configure(event_engine)` en `lifespan` junto al de `detection`, e `include_router(alerts_v2_router)` tras el de `events`.
- `tests/test_alerts.py` (nuevo, 16 casos) — agrupación por regla y por tipo, exclusión de `info` sin regla, inclusión de `info` con regla, orden por severidad y recencia, ventana temporal, rango de `hours` (parametrizado 0/1000), contadores del badge, persistencia del `until`, rechazo de duración arbitraria y de nombre vacío, exclusión del `active_count`, expiración perezosa con purga al escribir, `unmute` y emisión de `CONFIG_CHANGED`.

## Decisions Made

Las del bloque `key-decisions`. La única que el plan dejaba abierta era el doble `sort` de `list_alerts`: se comprobó que era redundante y quedó uno solo, tal como el propio plan autorizaba.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Bloqueante] `ConfigRepo` construido dentro del `async with _mute_lock` con `get_session_factory()` directo**

- **Found during:** Task 2
- **Issue:** El plan construía el repo con `ConfigRepo(get_session_factory())` inline en `mute_rule`/`unmute_rule`. Los tests parchean `alerts_module.get_session_factory`, así que funcionaba, pero quedaban tres construcciones distintas del mismo repo repartidas por el módulo.
- **Fix:** Extraído el helper `_config_repo()` (mismo patrón que `detection.py`), usado por `_load_muted`, `mute_rule` y `unmute_rule`.
- **Files modified:** `backend/api/v2/alerts.py`
- **Commit:** `84c7597` / `2477851`

### Añadidos sobre lo que el plan enumeraba

- El test de rango de `hours` se parametrizó (`0` y `1000`), así que los 8 tests de la Task 1 son 9 casos y el fichero suma **16** en vez de los 15 que preveía el criterio de aceptación.
- `TEST_mute_rejects_arbitrary_duration` y `TEST_mute_rejects_empty_rule_name` comprueban además que `app_config` sigue vacío tras el rechazo: un 400 que hubiera escrito antes de validar sería peor que no validar.

## Verificación

| Comprobación | Resultado |
|---|---|
| `tests/test_alerts.py` | 16 passed |
| `tests/test_security_regression.py` + `tests/test_events_api.py` | 38 passed |
| Rutas registradas | `['/api/v2/alerts', '/api/v2/alerts/mute', '/api/v2/alerts/unmute']` |
| `grep -c "_mute_lock"` | 3 (definición + los dos `async with`) |
| `grep -c "config_changed"` | 2 (mute y unmute) |
| `grep -c "@limiter.limit(V2_RATE_LIMIT)"` | 3 (uno por endpoint) |
| `grep -cE "rule_engine\|run_actions\|enabled = False"` | 0 — el silencio no toca la evaluación |
| Suite completa | **603 passed, 2 skipped** |

## TDD Gate Compliance

Cada tarea cerró su ciclo RED → GREEN con commits separados (`test(...)` antes de `feat(...)`). Ningún test pasó antes de tiempo: la Task 1 falló en la importación del módulo inexistente y la Task 2 con 7 fallos reales (404 en las rutas y `config_changed` sin llamar).

## Known Stubs

Ninguno. Los tres endpoints leen y escriben datos reales.

## Threat Flags

Ninguna superficie nueva fuera del `<threat_model>` del plan: los tres endpoints heredan la auth global y el rate limit compartido, y el único estado que mutan es la clave `alerts.muted_rules`.

## Self-Check: PASSED

- `backend/api/v2/alerts.py` — FOUND
- `tests/test_alerts.py` — FOUND
- Commits `5a697b5`, `84c7597`, `0407af2`, `2477851` — FOUND
