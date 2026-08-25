---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 06
subsystem: backend
tags: [fastapi, rules-engine, crud, validation]

# Dependency graph
requires:
  - phase: 33-01
    provides: "RuleEngine.would_match() (envoltorio publico sin efectos sobre _matches) + RuleRepo.get() — ya cerrados antes de este plan"
provides:
  - "backend/api/v2/rules.py — router, configure(rule_engine), rule_from_db_dict() — CRUD de reglas contra RuleRepo + POST /{id}/test"
affects: ["33-08 (wiring de configure(rule_engine) desde el lifespan de main.py + retirada del GET /api/v2/rules viejo)", "33-12 (frontend consumidor, ya construido, espera este shape exacto)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Validacion explicita con RuleIn.model_validate() dentro de try/except ValidationError en vez de tipar el parametro FastAPI directamente — evita el shape nativo de error 422 en lista, replica backend/api/v2/config.py:219-220"
    - "rule_from_db_dict() como unico punto de reconstruccion Rule<-fila BD, nunca se asume que definition ya es un Rule valido"

key-files:
  created:
    - backend/api/v2/rules.py
    - tests/test_rules_api.py
  modified: []

key-decisions:
  - "actions=[] se rechaza con un @field_validator explicito en RuleIn (regla de negocio de la Fase 33), sin tocar el modelo Action/Rule compartido con el motor de reglas en produccion"
  - "_reload_engine() descarta filas corruptas de forma individual (igual que load_rules()) aunque en teoria no deberian existir, porque el router ya valida en escritura"

patterns-established: []

requirements-completed: [OPS-24, RULE-05]

# Metrics
duration: ~25min
completed: 2026-08-24
---

# Phase 33 Plan 06: Router /api/v2/rules Summary

**CRUD de reglas validado contra los mismos modelos Pydantic (`Rule`/`When`/`Action`) que el motor de reglas ya usa en producción, más `POST /{id}/test` que evalúa una regla persistida contra los últimos 500 eventos sin tocar el debounce real.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 1/1 completada
- **Files modified:** 2 (ambos nuevos)

## Accomplishments
- `backend/api/v2/rules.py`: router `prefix="/api/v2/rules"` con `GET`, `POST` (upsert), `DELETE /{rule_id}`, `POST /{rule_id}/test`, todos con `@limiter.limit(V2_RATE_LIMIT)`.
- `POST`/`PUT` nunca tipa `body` como `RuleIn` — recibe `dict[str, Any]`, valida explícitamente con `RuleIn.model_validate()` y relanza `HTTPException(422, detail={"errors": [...]})`, mismo shape ya establecido en `config.py` y ya esperado por `frontend/js/views/rules-editor.js` (Plan 33-12).
- `rule_from_db_dict()` reconstruye `Rule` completo a partir de la fila de BD (`name`/`enabled` como columnas + `definition` JSON), nunca asumiendo que `definition` ya es válido.
- `_reload_engine()` recarga `RuleEngine` tras cada mutación, descartando filas corruptas individualmente sin tirar abajo el reload completo.
- `POST /{id}/test` usa `RuleEngine.would_match()` (cerrado en 33-01) sobre `EventRepo.query(limit=500)`, puro — verificado con test que llama dos veces seguidas y confirma resultado idéntico.

## Task Commits

Each task was committed atomically (RED/GREEN, `tdd="true"`):

1. **Task 1 — RED: tests fallidos** - `739f71c` (test)
2. **Task 1 — GREEN: implementación del router** - `097985e` (feat)

**Plan metadata:** (este commit, pendiente)

## Files Created/Modified
- `backend/api/v2/rules.py` (152 líneas) — router, `configure()`, `_rule_repo()`/`_event_repo()`, `rule_from_db_dict()`, `_reload_engine()`, `RuleIn`, 4 endpoints.
- `tests/test_rules_api.py` (218 líneas) — 9 tests contra una app FastAPI local con `RuleRepo`/`EventRepo` mockeados vía `patch.object`.

## Decisions Made
- Verificación de RED real: se renombró temporalmente `backend/api/v2/rules.py` antes de escribir la implementación definitiva en disco, se confirmó el `ImportError` de colección de pytest, y se restauró el fichero — cumple el gate fail-fast de la ejecución TDD a nivel de plan.
- `actions=[]` se valida en `RuleIn` (router), no en `Action`/`Rule` compartidos — es una regla de negocio específica de la Fase 33 (T-33-12 del threat model), documentada así para no divergir del modelo que ya usa el motor de reglas en producción.

## Deviations from Plan

None — el plan ya llegaba con la corrección del contrato de error 422 aplicada (`body: dict[str, Any]` + validación explícita), y se implementó literalmente tal cual estaba escrito.

## Issues Encountered

Ninguno. Suite completa relanzada al tocar un router de `/api/v2` (regla de `CLAUDE.md`): `758 passed, 2 skipped` en 207.62s, sin regresiones.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `backend/api/v2/rules.py` listo para que el Plan 33-08 lo registre con `app.include_router()`, llame `configure(rule_engine)` desde el lifespan, y retire el `GET /api/v2/rules` viejo de `main.py:1005-1010`.
- El contrato de error 422 (`{"detail":{"errors":[...]}}`) y el de `/test` (`{"would_fire", "total_checked"}`) ya coinciden exactamente con lo que `frontend/js/views/rules-editor.js` (Plan 33-12) espera — sin cambios pendientes de ese lado.
- Sin bloqueos conocidos para 33-08.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: backend/api/v2/rules.py
- FOUND: tests/test_rules_api.py
- FOUND: 739f71c
- FOUND: 097985e
