---
phase: 30-event-timeline-y-centro-de-alertas
plan: 03
subsystem: storage
tags: [sqlalchemy, sqlite, tracking, identidad, retroactivo, bytetrack]

# Dependency graph
requires:
  - phase: 30-event-timeline-y-centro-de-alertas
    provides: "30-02 dejó EventRepo con _filter_conditions()/query()/count(); este plan añade métodos hermanos en la misma clase"
  - phase: 19-event-engine-y-esquema-v2
    provides: "esquema v2 (events.track_id, recordings.trigger_event_id) y EventRepo.get()"
provides:
  - "TRACK_GAP_SECS=60.0 y TRACK_WINDOW_HOURS=6: las dos cotas que hacen seguro operar por track_id"
  - "EventRepo.track_scope(): previsualización del alcance retroactivo, sin escribir nada"
  - "EventRepo.assign_person(): UPDATE por lista explícita de ids + downgrade de severidad de UNKNOWN_PERSON"
  - "RecordingRepo.by_trigger_event_ids(): mapa evento → clip de una página en una sola consulta"
affects: [30-05 router de eventos, 30-08 línea temporal, 30-10 centro de alertas]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bloque contiguo calculado en Python sobre un SELECT ya acotado: SQLite no tiene window functions de gap en esta versión del código y la lista cabe siempre en memoria"
    - "case() en el values() de un update(): una sola sentencia para dos columnas con reglas distintas"
    - "Session factory que explota como aserción de corto-circuito (test de lista vacía)"

key-files:
  created: []
  modified:
    - backend/storage/repositories.py
    - tests/test_repositories.py

key-decisions:
  - "El bloque contiguo se recorre en Python, no en SQL: el SELECT ya viene acotado por camera_id+ventana, así que son decenas de filas y el corte por hueco es un bucle trivial frente a una CTE recursiva"
  - "track_scope() devuelve None (no un dict vacío) cuando el evento no existe o no tiene track_id: el router de 30-05 necesita distinguir 404 de 'sin alcance'"
  - "assign_person() no reabre la sesión para releer: devuelve len(ids) del scope, que es exactamente el conjunto del WHERE ... IN"
  - "by_trigger_event_ids() ordena por id ASC y sobrescribe el dict: el último gana, sin GROUP BY ni subconsulta de MAX(id)"

patterns-established:
  - "Toda operación por track_id lleva las tres cotas juntas — camera_id, ventana y hueco — o no es segura (30-RESEARCH.md Pitfall 3)"

requirements-completed: []  # OPS-08 avanza (capa de almacenamiento); la superficie HTTP llega en 30-05 y la marca 30-12

# Metrics
duration: 12min
completed: 2026-08-20
---

# Phase 30 Plan 03: Asignación retroactiva de identidad y mapa evento → clip Summary

**`track_scope()`, `assign_person()` y `by_trigger_event_ids()`: las tres operaciones que necesita "Marcar como persona", con la triple cota que impide que un `track_id` reciclado le ponga tu nombre a un desconocido de anteayer.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3 (6 commits: 3 ciclos RED/GREEN)
- **Files modified:** 2
- **Tests:** 12 nuevos (5 + 4 + 3). Suite completa **555 passed, 2 skipped** (543 antes)

## Accomplishments

- El riesgo que motivaba el plan queda cerrado por prueba, no por comentario: `TEST_track_scope_ignores_homonym_track_from_another_day` y `TEST_assign_person_does_not_touch_homonym_track` montan dos eventos con `track_id=7` separados 48 h y comprueban que el segundo ni se lee ni se escribe. Sin las cotas, un `UPDATE ... WHERE track_id = 7` habría alcanzado a los dos.
- `assign_person()` nunca menciona `track_id` en su `WHERE`: `grep -c "where(models.Event.track_id" backend/storage/repositories.py` → 0. El conjunto a actualizar lo calcula `track_scope()` y viaja como lista explícita de ids por `Event.id.in_()`, parametrizado (T-30-10).
- El downgrade de severidad va en la misma sentencia que el `person_id`, con un `CASE`: un `UNKNOWN_PERSON` deja de ser advertencia al ganar identidad y el resto de tipos conserva la suya. El test lo prueba con un `LINE_CROSSED` marcado explícitamente como `warning`, que sigue en `warning` después.
- `by_trigger_event_ids()` resuelve la miniatura de toda una página con una consulta. El vínculo es `recordings.trigger_event_id`, no `events.recording_id` — esa columna existe en el modelo pero nadie la escribe.

## Task Commits

1. **Task 1: `track_scope()`** — `4131fe8` (test, RED) + `eeacc0d` (feat, GREEN)
2. **Task 2: `assign_person()`** — `e644316` (test, RED) + `8f64923` (feat, GREEN)
3. **Task 3: `by_trigger_event_ids()`** — `704dce3` (test, RED) + `7c140f8` (feat, GREEN)

## Files Created/Modified

- `backend/storage/repositories.py` — constantes `TRACK_GAP_SECS`/`TRACK_WINDOW_HOURS` a nivel de módulo (con el porqué documentado en el propio comentario), `EventRepo.track_scope()`, `EventRepo.assign_person()`, `RecordingRepo.by_trigger_event_ids()`, y `case`/`update` añadidos al import de SQLAlchemy.
- `tests/test_repositories.py` — helpers `_seed_track()` y `_make_recording()`, más 12 tests en dos bloques comentados nuevos.

## Decisions Made

Las del bloque `key-decisions`. Ninguna cambió el contrato de `<interfaces>` del plan.

## Deviations from Plan

### Ajustes de método (no de comportamiento)

- **`TEST_assign_person_downgrades_unknown_person_severity` usa `warning` en el evento de control, no `info`.** El plan proponía un `LINE_CROSSED` con `severity="info"`; tal cual, el test pasaría igualmente aunque el `CASE` bajase la severidad de *todos* los tipos, porque el valor esperado y el valor incorrecto coinciden. Con `warning` explícito, la rama `else_` del `CASE` queda realmente probada.
- **`TEST_by_trigger_event_ids_empty_input` no usa la fixture `db`.** Para afirmar "sin ejecutar consulta" hace falta que abrir sesión sea un fallo observable: el test construye el repositorio con una factoría que lanza `AssertionError` al invocarse. Si alguien quita el `if not ids: return {}`, el test explota.
- **El plan citaba `RecordingRepo.insert()`**; el método real es `create()` + `finalize()`. El helper de test usa los dos.

No hubo auto-fixes de las Reglas 1–3: los tres ciclos RED/GREEN fallaron y pasaron a la primera.

## Issues Encountered

Ninguno.

## User Setup Required

None — los tres métodos son internos y todavía no tienen llamador. La superficie HTTP llega en 30-05.

## Next Phase Readiness

- **30-05** puede montar `POST /api/v2/events/{id}/assign-person` sobre `assign_person()` y un `GET .../track-scope` (o el mismo endpoint en modo *dry-run*) sobre `track_scope()`, sin lógica SQL propia. El contrato de retorno ya trae `count` y `event_ids` para el diálogo de confirmación ("se aplicará a N eventos anteriores").
- **30-08** tiene el mapa de miniaturas: el router debe llamar a `by_trigger_event_ids([e.id for e in page])` una vez por página, nunca por fila.
- Aviso de coste que el repositorio **no** impone y el router debe respetar: `by_trigger_event_ids()` está pensado para ≤200 ids (una página). `events.track_id` sigue sin índice — el `SELECT` de `track_scope()` se apoya en `idx_events_cam_ts` gracias a la cota de `camera_id`+ventana, así que la ausencia de índice por `track_id` no duele mientras esas dos cotas sigan ahí.

## Threat Flags

Ninguno. La superficie nueva es interna (métodos de repositorio). Las tres amenazas del `<threat_model>` quedan mitigadas y con test:

| Threat ID | Mitigación aplicada | Test |
|-----------|--------------------|------|
| T-30-08 | Triple cota (`camera_id` + ventana ±6 h + hueco 60 s) y `WHERE id IN (lista)` | `TEST_assign_person_does_not_touch_homonym_track`, `TEST_track_scope_ignores_homonym_track_from_another_day` |
| T-30-09 | El `UPDATE` alcanza como mucho el bloque contiguo; el `SELECT` previo va acotado | `TEST_assign_person_updates_only_contiguous_block` (los de fuera del bloque quedan intactos) |
| T-30-10 | `Event.id.in_()` / `Recording.trigger_event_id.in_()` de SQLAlchemy, parametrizado | cubierto por construcción; precedente de 30-02 en `TEST_query_rule_filter_is_not_interpolated` |

## Known Stubs

Ninguno.

## TDD Gate Compliance

Los tres ciclos tienen su commit `test(...)` en RED antes del `feat(...)` en GREEN. Ningún test pasó antes de tiempo. No hizo falta fase REFACTOR.

## Self-Check: PASSED

- `backend/storage/repositories.py` — FOUND (`async def track_scope`, `async def assign_person`, `async def by_trigger_event_ids`, `models.Event.id.in_(ids)`, `trigger_event_id.in_(ids)`, 0 matches de `where(models.Event.track_id`)
- `tests/test_repositories.py` — FOUND (12 tests nuevos)
- Commits `4131fe8`, `eeacc0d`, `e644316`, `8f64923`, `704dce3`, `7c140f8` — FOUND en `git log`
- Suite completa: **555 passed, 2 skipped**

---
*Phase: 30-event-timeline-y-centro-de-alertas*
*Completed: 2026-08-20*
