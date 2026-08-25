---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 03
subsystem: api
tags: [fastapi, pydantic, zones, hot-reload, validation]

# Dependency graph
requires: []
provides:
  - "backend/api/v2/zones.py — router prefix=/api/v2/zones (GET, POST upsert, DELETE /{zone_id})"
  - "configure(camera_manager) — punto de wiring para el lifespan de main.py (Plan 33-08)"
affects: [33-08, 33-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pydantic field_validator para validacion semantica (rango [0,1], kind cerrado, dry-run de schedule) en vez del patron dict(ZoneBody) debil de v1"
    - "Hot-reload multi-camara: _push_hot_reload itera camera_manager.all() y filtra zone_repo.list(camera_id=pipeline.camera_id) por pipeline, nunca push global"

key-files:
  created:
    - backend/api/v2/zones.py
    - tests/test_zones_api.py
  modified: []

key-decisions:
  - "kind='exclude_objects' se mantiene como cuarto valor de _KIND_VALUES sin remapear (heredado de la Fase 27, 33-RESEARCH.md Pitfall 2), tal como especificaba el plan"
  - "schedule se valida con un dry-run de is_schedule_active envuelto en try/except -> ValueError -> 422; no se usa para logica de negocio aqui (eso vive en el pipeline, Plan 33-05)"

requirements-completed: [OPS-21, OPS-23]

# Metrics
duration: 15min
completed: 2026-08-24
---

# Phase 33 Plan 03: Router /api/v2/zones (CRUD, validacion, hot-reload) Summary

**Nuevo router `/api/v2/zones` (GET/POST-upsert/DELETE) sobre `ZoneRepo`, con validacion Pydantic de poligono (>=3 puntos, coordenadas en [0,1]), `kind` cerrado a un vocabulario de 4 valores (incluye `exclude_objects` heredado de la Fase 27) y `schedule` verificado con un dry-run de `is_schedule_active`, empujando el cambio a todos los pipelines de camara vivos tras cada mutacion.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 1 completada
- **Files modified:** 2 (1 fuente, 1 test)

## Accomplishments
- `backend/api/v2/zones.py`: router completo con `ZoneIn` (Pydantic), `_KIND_VALUES`, `_push_hot_reload` multi-camara y `configure()` para el wiring del Plan 33-08
- Validacion de rango [0,1] por punto del poligono, ausente en el v1 legacy (`backend/main.py`), exigida por 33-RESEARCH.md
- Hot-reload filtrado por `camera_id` de cada pipeline, no un push global — el proyecto corre 1 camara hoy pero el router es multi-camara-shaped
- 11 tests en `tests/test_zones_api.py` cubriendo los 10 casos del `<behavior>` del plan (GET con/sin filtro, POST valido con default `camera_id`, POST sin `camera_manager` configurado, `exclude_objects`, poligono corto, punto fuera de rango, `kind` invalido, `schedule` invalido, DELETE 404 y DELETE con hot-reload)

## Task Commits

1. **Task 1: Router /api/v2/zones — CRUD, validacion, hot-reload** - `93f2565` (feat)

**Plan metadata:** (este commit) `docs(33-03): completar plan router /api/v2/zones`

## Files Created/Modified
- `backend/api/v2/zones.py` (nuevo) - `router`, `ZoneIn`, `_KIND_VALUES`, `configure()`, `_zone_repo()`, `_push_hot_reload()`, `list_zones`, `upsert_zone`, `delete_zone`
- `tests/test_zones_api.py` (nuevo) - app FastAPI local + `ZoneRepo`/`CameraManager` mockeados, 11 tests `TEST_*`

## Decisions Made
- Ninguna desviacion de las decisiones del plan; `kind`/`schedule`/rango de poligono implementados exactamente como especifica el `<action>`.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. La unica diferencia frente al pseudo-codigo del plan es de forma, no de comportamiento: la validacion de `id`/`name`/`polygon`/`kind`/`schedule` se implemento como `field_validator`s de Pydantic en vez de comprobaciones imperativas sueltas, tal como el propio plan pedia explicitamente ("las validaciones semanticas van en un `@field_validator`").

## Issues Encountered

Ninguno.

## Known Stubs

Ninguno — el router es funcional end-to-end contra `ZoneRepo` real; solo el wiring de `camera_manager` en `backend.main` queda pendiente para el Plan 33-08 (documentado como tal en el propio plan, no es un stub).

## Threat Flags

Ninguna superficie nueva fuera del threat model del plan (T-33-03..T-33-06): validacion de poligono/kind/schedule y rate limit heredado, todos ya cubiertos por los tests.

## User Setup Required

None - no requiere configuracion externa.

## Next Phase Readiness

- `backend/api/v2/zones.py` listo para ser incluido en `backend.main` y cableado con `configure(camera_manager)` en el Plan 33-08.
- El editor visual de zonas (Plan 33-10) ya tiene el contrato HTTP completo (`{"zones": [...]}` en los tres verbos) para consumir sin logica de validacion propia.
- Sin bloqueos conocidos para el resto de la Fase 33.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: `backend/api/v2/zones.py`
- FOUND: `tests/test_zones_api.py`
- FOUND: `.planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-03-SUMMARY.md`
- FOUND: commit `93f2565`
