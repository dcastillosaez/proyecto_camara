---
phase: 30-event-timeline-y-centro-de-alertas
plan: 05
subsystem: api
tags: [fastapi, router, pagination, cursor, media, rate-limit, tdd]

# Dependency graph
requires:
  - phase: 30-02
    provides: EventRepo.query() con tipo multi-valor y filtro por regla, más EventRepo.count()
  - phase: 30-03
    provides: EventRepo.track_scope() y EventRepo.assign_person(), y RecordingRepo.by_trigger_event_ids()
  - phase: 30-04
    provides: snapshot_url() en deps.py y Event.snapshot_path ya escrito en disco
provides:
  - "Router backend/api/v2/events.py con los cuatro endpoints de la fase"
  - "GET /api/v2/events: envelope {events, cursor, total, media} con filtros combinables y type repetido"
  - "GET /api/v2/events/{id}: detalle con bloque media siempre presente (cuatro claves, null si no hay nada)"
  - "GET /api/v2/events/{id}/track-scope: previsualización del alcance retroactivo, sin escribir"
  - "POST /api/v2/events/{id}/assign-person: aplica la identidad al bloque contiguo del track"
affects: [30-08 línea temporal, 30-11 marcar como persona, 30-06 centro de alertas]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mapa `media` como clave hermana del evento, nunca dentro del objeto Event: el DTO es el contrato persistido y también viaja por el WS"
    - "Una consulta de medios por página (by_trigger_event_ids con <=200 ids), nunca una por fila"
    - "COUNT(*) condicionado a (cursor is None and has_filters) — el resto de páginas devuelven total: null"
    - "Endpoint viejo borrado en el mismo commit que registra el router, para que nunca convivan dos rutas iguales"

key-files:
  created:
    - backend/api/v2/events.py
    - tests/test_events_api.py
  modified:
    - backend/main.py

key-decisions:
  - "El envelope conserva las claves events/cursor: dashboard.js:274 (Fase 29) ya las consume; total y media solo se añaden"
  - "media va como mapa hermano indexado por event_id, no dentro del evento — meterlo dentro arrastraría campos de presentación al mensaje WS"
  - "total solo en la primera página y solo con filtros activos (Pitfall 9 / T-30-15)"
  - "El cursor corrupto se traduce a 400 'cursor invalido', nunca a un 500 con traza (T-30-16)"
  - "assign-person recibe un person_id ya enrolado y valida ge=1; el enrolado sigue en /api/enroll_face con sus propias validaciones (T-30-19)"
  - "Los tests parchean events_module.get_session_factory en vez del global de main.py — el router construye sus repos con ese símbolo"

# Metrics
duration: 18min
completed: 2026-08-21
---

# Phase 30 Plan 05: Router de eventos v2 Summary

**`GET /api/v2/events` deja de ser un endpoint suelto en `main.py` y pasa a un router propio con cuatro rutas: lista paginada por cursor con `total` condicional y mapa `media` resuelto en una sola consulta, detalle, previsualización del alcance de un track y asignación retroactiva de identidad.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2
- **Files modified:** 3 (2 nuevos)
- **Commits:** 4 (2 de tests RED + 2 de implementación)

## Accomplishments

- La línea temporal ya tiene todo lo que necesita del servidor en una sola llamada: los eventos, el cursor de la página siguiente, cuántas coincidencias hay en total (cuando hay filtros) y, para cada evento que tenga algo, la URL de su clip, su miniatura y su captura. Antes había que adivinar los medios fila a fila.
- El filtro por tipo admite el parámetro repetido (`?type=INTRUSION&type=UNKNOWN_PERSON`), que es lo que exige el selector múltiple de la UI-SPEC, y se añade el filtro por nombre de regla que 30-02 había preparado en el repositorio.
- El mapa `media` cuesta **una** consulta por página: `by_trigger_event_ids()` recibe hasta 200 ids de golpe. El vínculo real es `recordings.trigger_event_id`, no `events.recording_id` — esa columna nunca se escribe.
- El endpoint viejo desaparece en el mismo commit en que se registra el router. Nunca hubo un estado intermedio con dos rutas `/api/v2/events` compitiendo por el orden de registro (Pitfall 10).
- Los cuatro endpoints llevan `@limiter.limit(V2_RATE_LIMIT)` y el de lista `pagination_limit()`, así que los dos tests de regresión de seguridad que recorren `app.routes` siguen verdes sin tocarlos.
- `track-scope` y `assign-person` van separados a propósito: el frontend puede enseñar "se aplicará también a los N eventos anteriores de este track" antes de que el operador confirme, sin haber escrito nada.

## Task Commits

1. **Task 1: Router con lista paginada, media y total** — `a3bb2a2` (test RED, 10 tests) + `b630f5f` (feat)
2. **Task 2: track-scope y assign-person** — `675eae6` (test RED, 7 tests) + `ee993eb` (feat)

## Files Created/Modified

- `backend/api/v2/events.py` (nuevo, 165 líneas) — router con prefijo `/api/v2/events`, helpers `_event_repo()`/`_recording_repo()`, `_media_map()` y los cuatro endpoints. Molde copiado de `recordings.py`.
- `backend/main.py` — borrado `api_v2_events` (33 líneas, Fase 19) y su comentario sustitutivo; `include_router(events_v2_router)` tras el de `context`; import de `pagination_limit` retirado al quedarse sin uso.
- `tests/test_events_api.py` (nuevo, 17 tests) — envelope, tipo repetido, 400 en enum inválido, `total` condicional en dos páginas encadenadas con cursor real, `media` con solo las claves que tienen algo, cap de `limit`, detalle y 404, las tres formas de `track-scope` y las tres de `assign-person`.

## Decisions Made

Las del bloque `key-decisions`. Todas venían fijadas por el plan y el bloque `<interfaces>`; no hubo que resolver ninguna ambigüedad de contrato.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Bloqueante] `pagination_limit` quedó importado sin uso en `main.py`**

- **Found during:** Task 1
- **Issue:** Era el único consumidor de ese símbolo en `main.py`, y al borrar el endpoint viejo el import quedó huérfano.
- **Fix:** Retirado de la línea de import de `backend.api.v2.deps`; `V2_RATE_LIMIT`, `v2_limiter` y `snapshot_url` siguen en uso.
- **Files modified:** `backend/main.py`
- **Commit:** `b630f5f`

### Añadidos sobre lo que el plan enumeraba

- El plan listaba 8 tests para la Task 1 y 6 para la Task 2 (14 en total); el fichero tiene **17**. Los tres extra son: cobertura del detalle (`TEST_get_event_returns_event_and_media`, `TEST_get_event_404_for_unknown_event`) — el plan pedía implementar el endpoint pero no lo listaba en `<behavior>` — y el desdoblamiento de la validación de `person_id` en dos casos parametrizados (`0` y `-3`), que el propio texto del criterio contemplaba.
- `_EMPTY_MEDIA` como constante de módulo: el bloque de cuatro claves a `null` lo necesitan tanto `_media_map()` como el detalle. Se devuelve siempre con `dict(...)` para no compartir el mismo objeto entre respuestas.
- Guarda `if not events: return {}` al principio de `_media_map()`, para que una página vacía no llegue a construir la consulta.

## Verificación

| Comprobación | Resultado |
|---|---|
| `tests/test_events_api.py` | 17 passed |
| `tests/test_security_regression.py` | 21 passed (incluye rate limit y cap de `limit` de todos los v2) |
| `tests/test_repositories.py` | verde |
| Rutas registradas | `['/api/v2/events', '/api/v2/events/{event_id}', '/api/v2/events/{event_id}/assign-person', '/api/v2/events/{event_id}/track-scope']` |
| `grep -c "@limiter.limit(V2_RATE_LIMIT)"` en el router | 4 (uno por endpoint) |
| `grep "@app.get(\"/api/v2/events\")"` en `main.py` | 0 matches |
| Suite completa | **587 passed, 2 skipped** |

## TDD Gate Compliance

Cada tarea cerró su ciclo RED → GREEN con commits separados (`test(...)` antes de `feat(...)`). Ningún test pasó antes de tiempo: la Task 1 falló en la importación del módulo inexistente y la Task 2 con 5 fallos reales sobre el router ya existente.

## Known Stubs

Ninguno. Los cuatro endpoints devuelven datos reales de la base.

## Self-Check: PASSED

- `backend/api/v2/events.py` — FOUND
- `tests/test_events_api.py` — FOUND
- Commits `a3bb2a2`, `b630f5f`, `675eae6`, `ee993eb` — FOUND
