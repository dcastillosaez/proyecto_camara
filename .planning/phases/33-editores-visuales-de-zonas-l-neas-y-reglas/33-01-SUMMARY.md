---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 01
subsystem: database
tags: [sqlalchemy, sqlite, repository-pattern, rule-engine, pydantic]

# Dependency graph
requires: []
provides:
  - "LineRepo (list/upsert/delete/_to_dict) sobre backend/storage/models.py:Line"
  - "RuleRepo.get(rule_id) — lectura de una regla sin mutar estado"
  - "RuleEngine.would_match(when, event) — evaluacion pura sin efectos de debounce"
  - "is_schedule_active(schedule, now=None) — horario propio de zona/linea"
affects: [33-02, 33-03, 33-05, 33-06, 33-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Repositorio async con session_factory + _to_dict estatico, mismo molde que ZoneRepo/RuleRepo"
    - "Envoltorio publico sin efectos secundarios sobre una funcion de modulo privada (would_match -> _matches)"

key-files:
  created: []
  modified:
    - backend/storage/repositories.py
    - backend/events/rules.py
    - tests/test_repositories.py
    - tests/test_rule_engine.py

key-decisions:
  - "LineRepo se coloca inmediatamente despues de RuleRepo (agrupado con los repos de configuracion de camara), replicando el molde exacto de ZoneRepo sin campo updated_at (el modelo Line no lo tiene)"
  - "would_match() delega en _matches() sin tocar self._last_fired: probar una regla nunca debe consumir su ventana de debounce en produccion"

patterns-established:
  - "Repos nuevos (Line, futuros) copian el molde de ZoneRepo: list(camera_id=None)/upsert/delete/_to_dict estatico"

requirements-completed: [OPS-22, OPS-23, RULE-05]

# Metrics
duration: 25min
completed: 2026-08-24
---

# Phase 33 Plan 01: LineRepo + RuleRepo.get() + would_match() + is_schedule_active() Summary

**LineRepo (CRUD de lineas de conteo v2) y RuleRepo.get() en repositories.py, mas RuleEngine.would_match() puro e is_schedule_active() reutilizando el parseo de rango horario existente en rules.py — cimiento de datos/motor para los routers y el rebuild de zonas del resto de la Fase 33.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 completadas
- **Files modified:** 4 (2 fuente, 2 test)

## Accomplishments
- `LineRepo` operativo con la misma forma que `ZoneRepo` (list/upsert/delete/_to_dict), listo para el router `/api/v2/lines` (Plan 33-07)
- `RuleRepo.get(rule_id)` disponible para `POST /rules/{id}/test` (Plan 33-06)
- `RuleEngine.would_match()` publico, verificado que no consume el debounce de `match()` en produccion (RULE-05)
- `is_schedule_active()` publica, cubre horario sin restriccion, filtro de dias, cruce de medianoche y combinacion de ambos (OPS-23)

## Task Commits

Each task was committed atomically (TDD: RED confirmado por ImportError antes de cada GREEN):

1. **Task 1: LineRepo + RuleRepo.get(rule_id)** - `a9db65f` (feat)
2. **Task 2: RuleEngine.would_match() publico + is_schedule_active()** - `9540df9` (feat)

**Plan metadata:** (este commit) `docs(33-01): completar plan LineRepo/RuleRepo/would_match/is_schedule_active`

## Files Created/Modified
- `backend/storage/repositories.py` - Anadidos `RuleRepo.get()` y la clase `LineRepo` completa (list/upsert/delete/_to_dict)
- `backend/events/rules.py` - Anadidos `RuleEngine.would_match()` (metodo publico) e `is_schedule_active()` (funcion de modulo)
- `tests/test_repositories.py` - 6 tests nuevos `TEST_LineRepo_*`/`TEST_rule_get_*`
- `tests/test_rule_engine.py` - 6 tests nuevos `TEST_would_match_*`/`TEST_is_schedule_active_*`

## Decisions Made
- Ninguna decision arquitectonica nueva — el plan ya fijaba el molde exacto (ZoneRepo como analogo, `_matches`/`_parse_time_range`/`_time_in_range` ya existentes) y se siguio tal cual.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. Los dos tasks siguieron el molde de `33-PATTERNS.md` sin necesidad de auto-fixes.

## Issues Encountered

None.

## Known Stubs

Ninguno — este plan no toca UI ni renderizado; son piezas de datos/motor puras consumidas por planes posteriores (33-05, 33-06, 33-07).

## Threat Flags

Ninguna superficie nueva de red/auth/esquema: `LineRepo`/`RuleRepo.get()` son metodos de acceso a datos ya modelados (`models.Line`, `models.Rule`) sin exponerse aun via API, y `would_match()`/`is_schedule_active()` son funciones puras sin I/O. Cubierto por el threat model del propio plan (T-33-01, aceptado).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `LineRepo` y `RuleRepo.get()` listos para los routers `/api/v2/lines` (33-07) y `/api/v2/rules/{id}/test` (33-06).
- `is_schedule_active()` lista para el rebuild de zonas con horario propio (33-05).
- `would_match()` lista para el endpoint de prueba de reglas contra los ultimos 500 eventos (33-06).
- Sin bloqueos conocidos para el resto de la Fase 33.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: `.planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-01-SUMMARY.md`
- FOUND: commit `a9db65f`
- FOUND: commit `9540df9`
