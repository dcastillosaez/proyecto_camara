---
phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados
plan: 04
subsystem: pipeline+events
tags: [tracking, events, event-engine, shared-state]

# Dependency graph
requires:
  - phase: 24-02
    provides: "IdentityState, IdentityTransition en backend/perception/face/identity.py"
provides:
  - "TrackState.identity_state + TrackRegistry.set_identity_state — estado de identidad legible por streaming/sampler/API"
  - "EventEngine.emit_identity(transition, ...) — traduce IdentityTransition a PERSON_RECOGNIZED/UNKNOWN_PERSON/IDENTITY_LOST"
affects: [24-05, 24-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Traductor estatico (_identity_event_type) separado del metodo publico que delega en _publish, siguiendo el patron ya usado por emit_line_crossing/camera_offline"
    - "identity_state hereda el mismo esquema de escritor unico que person_id/person_name (RecognitionWorker via setter con lock)"

key-files:
  created: []
  modified:
    - backend/pipeline/tracking.py
    - backend/events/engine.py
    - tests/test_track_registry.py
    - tests/test_event_engine.py

key-decisions:
  - "emit_identity nunca pasa severity= explicitamente, para que UNKNOWN_PERSON conserve el WARNING por defecto del catalogo (_apply_default_severity solo actua si severity no esta en model_fields_set)"
  - "_identity_event_type devuelve None para las transiciones intermedias (CANDIDATE, TEMPORARILY_LOST): esos estados los lee la UI directamente del TrackRegistry, no generan evento"

requirements-completed: [FACE-08, FACE-09]

# Metrics
duration: 15min
completed: 2026-08-13
---

# Phase 24 Plan 04: identity_state en TrackRegistry y EventEngine.emit_identity Summary

**`TrackState` gana el campo `identity_state` (con setter thread-safe en `TrackRegistry`) y `EventEngine` gana `emit_identity()`, el traductor que convierte una `IdentityTransition` de la FSM en uno de los tres eventos de identidad del catálogo (`PERSON_RECOGNIZED`/`UNKNOWN_PERSON`/`IDENTITY_LOST`), cerrando dos puntas sueltas abiertas desde la Fase 19.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-13
- **Completed:** 2026-08-13
- **Tasks:** 2
- **Files modified:** 4 (0 creados, 4 modificados)

## Accomplishments
- Cada track del `TrackRegistry` expone `identity_state` (default `IdentityState.UNKNOWN`), con `set_identity_state()` protegido por el mismo `RLock` que `set_identity`, y sin romper a los lectores existentes (`streaming.py`, `sampler.py`, `manager.py`, `recognition.py`) — verificado con la suite completa de esos ficheros.
- `EventEngine.emit_identity()` publica los 3 eventos de identidad delegando siempre en `_publish` (nunca construye `Event` a mano), con payload trazable (`state`, `previous_state`, `votes`, `window`).
- `UNKNOWN_PERSON` conserva su severidad `WARNING` por defecto del catálogo — verificado explícitamente sin pasar `severity=` en ningún punto de `emit_identity`.
- Las transiciones silenciosas (`emits=False`, misma visita) y las intermedias (`CANDIDATE`, `TEMPORARILY_LOST` como destino) no publican ningún evento.
- Suite completa: **371/371** (antes 361, +10 tests netos: 4 de `identity_state` en `TrackRegistry`, 6 de `emit_identity` en `EventEngine`).

## Task Commits

Each task was committed atomically:

1. **Task 1: identity_state en TrackState y set_identity_state en TrackRegistry** - `ac71eb3` (feat)
2. **Task 2: EventEngine.emit_identity — los 3 eventos de identidad** - `4458e66` (feat)

**Plan metadata:** (pendiente — commit final de este SUMMARY/STATE/ROADMAP)

## Files Created/Modified
- `backend/pipeline/tracking.py` - campo `identity_state` en `TrackState`, setter `set_identity_state`, docstring de escritor único ampliado, import de `IdentityState`
- `backend/events/engine.py` - `_identity_event_type` (traductor estático) y `emit_identity` (método público), import de `IdentityState`/`IdentityTransition`
- `tests/test_track_registry.py` - 4 tests `TEST_*` de `identity_state`
- `tests/test_event_engine.py` - 6 tests `TEST_identity_*` sobre un `EventBus` real

## Decisions Made
Ver `key-decisions` en el frontmatter. Resumen:
- Sin `severity=` explícita en `emit_identity`, para no pisar el `WARNING` por defecto de `UNKNOWN_PERSON`.
- `_identity_event_type` devuelve `None` para estados intermedios (`CANDIDATE`, `TEMPORARILY_LOST`) — la UI los lee directamente del `TrackRegistry`, no como evento.

## Deviations from Plan

None - plan ejecutado tal cual estaba escrito. Los dos ficheros de test ya seguían la convención `TEST_*`/`test_*` mixta existente en el repo (pytest los recoge a ambos); los tests nuevos usan `TEST_*` según pide el plan.

## Nota lateral (documentada, sin actuar)

`config/rules.yaml` tiene una regla `persona_desconocida` basada en `event: LINE_CROSSED` + `person: unknown`. Ahora que `UNKNOWN_PERSON` se emite de verdad, añadir una regla nueva para ese tipo sin retirar la existente duplicaría notificaciones. No se toca `config/rules.yaml` en este plan — queda anotado para cuando se cablee el pipeline real (24-05/24-06).

## Issues Encountered
Ninguno.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `TrackRegistry.set_identity_state()` y `EventEngine.emit_identity()` listos para que `24-05` los cablee desde `RecognitionWorker` (que ya produce `IdentityTransition` vía `IdentityStateMachine` desde 24-02).
- Sin bloqueos para continuar con `24-05`.

---
*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Completed: 2026-08-13*

## Self-Check: PASSED

Ficheros modificados y los 2 commits de tareas (`ac71eb3`, `4458e66`) verificados en disco/`git log`.
