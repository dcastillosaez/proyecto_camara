---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 08
subsystem: backend
tags: [fastapi, lifespan, wiring, migrations, pydantic-settings]

# Dependency graph
requires:
  - phase: 33-02
    provides: "ZoneRepo/LineRepo (esquema v2) + migracion v4->v5 con seed de compatibilidad de la linea unica"
  - phase: 33-03
    provides: "backend/api/v2/zones.py — router + configure(camera_manager)"
  - phase: 33-05
    provides: "CameraPipeline.set_lines()/DetectionWorker hot-reload + _rebuild_zone_states leyendo z['polygon'] (lista)"
  - phase: 33-06
    provides: "backend/api/v2/rules.py — router + configure(rule_engine) + rule_from_db_dict()"
  - phase: 33-07
    provides: "backend/api/v2/lines.py — router + configure(camera_manager)"
provides:
  - "backend/main.py lifespan arranca zonas/lineas/reglas 100% desde ZoneRepo/LineRepo/RuleRepo (v2), sin depender de get_zones() v1 ni de Settings.line_*_frac"
  - "Routers /api/v2/zones, /api/v2/lines, /api/v2/rules registrados y wireados (configure()) en backend.main.app"
  - "GET/POST/DELETE /api/zones (v1) retirados; /api/zones/stats se conserva (sin equivalente v2, sin consumidor real detectado)"
  - "config_schema.py: grupo 'linea' (4 FieldDef) sustituido por 'lineas_definidas' (external_source=/api/v2/lines); 'zonas_definidas' apunta a /api/v2/zones"
  - "backend/storage/migrations.py:_migrate_v4_to_v5 lee LINE_*_FRAC de env/.env directamente (_legacy_line_frac_settings), no de Settings"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Modelo BaseSettings efimero (mismo model_config que Settings) para que una migracion historica siga leyendo variables de entorno retiradas del modelo principal, sin resucitarlas ni reimplementar el parseo de .env a mano"
    - "Fallback de arranque unico: RuleRepo vacio -> config/rules.yaml (solo primera vez); en cuanto hay una fila en `rules` el YAML deja de leerse en arranques siguientes"

key-files:
  created: []
  modified:
    - backend/main.py
    - backend/config.py
    - backend/api/v2/config_schema.py
    - backend/storage/migrations.py
    - backend/tracker.py
    - frontend/js/views/timeline.js
    - tests/test_zones_api.py
    - tests/test_lines_api.py
    - tests/test_rules_api.py
    - tests/test_config_api.py
    - tests/test_migrations.py
    - tests/test_tracker.py

key-decisions:
  - "rule_from_db_dict se importa directamente desde backend.api.v2.rules dentro del lifespan (import diferido, mismo patron que el resto de modulos v2) — no hubo ciclo de imports, no hizo falta moverla a backend/events/rules.py"
  - "/api/zones/stats se conserva TAL CUAL bajo su ruta v1: no tiene equivalente v2 en esta fase (recrearlo en zones.py excede el alcance de este plan, ya cerrado en Wave 1) y grep confirmo que no tiene consumidor real (solo docs/README.md lo mencionan)"
  - "_legacy_line_frac_settings() (backend/storage/migrations.py): al retirar line_start_x_frac/etc de Settings (Task 2), la migracion v4->v5 (D-01, Plan 33-02) quedo sin forma de leer el .env legacy para sembrar la linea de compatibilidad — se resolvio con un modelo BaseSettings efimero, scoped a la migracion, que reutiliza el mismo model_config (env_file + case-insensible) sin reimplementar parseo de .env ni reintroducir los campos en el modelo principal"
  - "reconfigure_line() (wrapper de compatibilidad singular sobre reconfigure_lines(), Plan 33-04) se retiro de PersonTracker: confirmado con grep que su unico llamador real (backend/camera.py:194) ya habia migrado en el Plan 33-05; solo quedaban dos tests ejercitando el wrapper directamente, tambien retirados"

patterns-established: []

requirements-completed: [OPS-21, OPS-22, OPS-24]

# Metrics
duration: 20min
completed: 2026-08-24
---

# Phase 33 Plan 08: Integracion backend — wiring v2, arranque desde v2, retirada v1 Summary

**`backend/main.py` arranca el pipeline y el motor de reglas 100% desde `ZoneRepo`/`LineRepo`/`RuleRepo` (v2), con los tres routers nuevos (`/api/v2/zones`, `/api/v2/lines`, `/api/v2/rules`) registrados y wireados, y los endpoints v1 huerfanos (`GET/POST/DELETE /api/zones`, `GET /api/v2/rules` suelto) retirados.**

## Performance

- **Duration:** ~20 min (commits 20:17:01 -> 20:28:52 CEST)
- **Started:** 2026-08-24T18:17:01Z
- **Completed:** 2026-08-24T18:28:52Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- El `lifespan` de `main.py` llama `zones_v2_module.configure(camera_manager)`, `lines_v2_module.configure(camera_manager)` y `rules_v2_module.configure(rule_engine)`, y registra los tres routers junto a los ya existentes.
- `PersonTracker` arranca sin lineas fijas (`PersonTracker(frame_rate=...)`); zonas y lineas reales se cargan desde `ZoneRepo`/`LineRepo` justo despues de `pipeline.start()`, mismo punto/patron que las zonas ya usaban.
- El motor de reglas arranca desde `RuleRepo.list()` (via `rule_from_db_dict`, validando cada fila con `ValidationError` capturada por fila), con fallback exacto a `config/rules.yaml` solo cuando la tabla `rules` esta vacia — comportamiento de arranque unico, documentado en comentario.
- `GET /api/v2/rules` suelto y `GET/POST/DELETE /api/zones` retirados; `/api/zones/stats` se conserva sin cambios (sin equivalente v2, sin consumidor real).
- `config_schema.py`: grupo "Línea de conteo" (4 `FieldDef` obsoletos) sustituido por `lineas_definidas` (`external_source=/api/v2/lines`); `zonas_definidas` apunta a `/api/v2/zones`. `backend/config.py` sin los 4 campos `line_*_frac`.
- `frontend/js/views/timeline.js` migrado de `/api/zones` a `/api/v2/zones` (shape ya compatible, `zoneEditor.js` ya estaba en v2 desde antes).
- Suite completa en verde: **767 passed, 2 skipped**.

## Task Commits

Cada tarea se comiteo de forma atomica:

1. **Task 1: Wiring de routers v2 + arranque desde repositorios v2** - `0d1ccb8` (feat)
2. **Task 2: config_schema.py — retirar linea unica, apuntar external_source a v2** - `75ec3b4` (feat)
3. **Task 3: Suite completa + fix de la migracion v4->v5 + retirada de reconfigure_line** - `250bdcc` (fix)

**Plan metadata:** (este commit) `docs(33-08): completar plan integracion backend`

## Files Created/Modified
- `backend/main.py` — imports de `ZoneRepo`/`LineRepo`/`RuleRepo` (+ `ValidationError`, - `sv`/`get_zones`/`upsert_zone`/`delete_zone`); wiring de `zones_v2`/`lines_v2`/`rules_v2` (`configure()` + `include_router`); tracker sin lineas fijas; carga de reglas desde `RuleRepo` con fallback a YAML; `pipeline.set_zones()`/`pipeline.set_lines()` desde repos v2; retirado `GET /api/v2/rules` suelto y `GET/POST/DELETE /api/zones` (conservado `/api/zones/stats`)
- `backend/config.py` — eliminados `line_start_x_frac`/`line_start_y_frac`/`line_end_x_frac`/`line_end_y_frac`
- `backend/api/v2/config_schema.py` — grupo `linea` sustituido por `lineas_definidas` (`external_source=/api/v2/lines`); `zonas_definidas.external_source` migrado a `/api/v2/zones`
- `backend/storage/migrations.py` — `_legacy_line_frac_settings()` (modelo `BaseSettings` efimero) sustituye la lectura de `get_settings().line_*_frac` en `_migrate_v4_to_v5`
- `backend/tracker.py` — retirado `PersonTracker.reconfigure_line()` (wrapper de compatibilidad sin llamador real)
- `frontend/js/views/timeline.js` — `fetch('/api/zones')` -> `fetch('/api/v2/zones')`
- `tests/test_zones_api.py`/`test_lines_api.py`/`test_rules_api.py` — anadido `TEST_main_imports_with_*_router_registered()` contra `backend.main.app` real
- `tests/test_config_api.py` — assert de `zonas_definidas.external_source` actualizado a `/api/v2/zones`; anadido assert de `lineas_definidas.external_source == /api/v2/lines`
- `tests/test_migrations.py` — `TEST_migration_v5_seeds_default_line_when_lines_empty` compara contra los defaults hardcodeados (`0.0, 0.5, 1.0, 0.5`), no contra `Settings`
- `tests/test_tracker.py` — retirados los dos tests de `reconfigure_line()`

## Decisions Made
Ver `key-decisions` en el frontmatter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_migrate_v4_to_v5` rota por la retirada de `Settings.line_*_frac`**
- **Found during:** Task 3 (suite completa tras Tasks 1-2)
- **Issue:** Al eliminar `line_start_x_frac`/`line_start_y_frac`/`line_end_x_frac`/`line_end_y_frac` de `Settings` (Task 2, siguiendo el plan al pie de la letra), la migracion `_migrate_v4_to_v5` (Plan 33-02, D-01) seguia leyendo `get_settings().line_start_x_frac` etc. para sembrar la linea de compatibilidad — cualquier `init_db()` (es decir, casi toda la suite: 19 failed + 29 errors) lanzaba `AttributeError: 'Settings' object has no attribute 'line_start_x_frac'`.
- **Fix:** `_legacy_line_frac_settings()` — modelo `BaseSettings` efimero, scoped a `migrations.py`, con los mismos 4 campos y el mismo `model_config` (env_file + case-insensible) que `Settings`, para seguir leyendo `LINE_START_X_FRAC`/etc de env/.env sin resucitarlos en el modelo principal ni reimplementar el parseo de `.env` a mano. `tests/test_migrations.py` actualizado para comparar contra los defaults hardcodeados en vez de contra `Settings`.
- **Files modified:** `backend/storage/migrations.py`, `tests/test_migrations.py`
- **Verification:** `pytest tests/test_migrations.py tests/test_phase9.py tests/test_phase10.py tests/test_database.py tests/test_stream.py -q` en verde (antes: 19 failed, 29 errors); suite completa `767 passed, 2 skipped`.
- **Committed in:** `250bdcc` (Task 3)

**2. [Rule 1 - Cleanup] Retirado `PersonTracker.reconfigure_line()` sin llamador real**
- **Found during:** Task 3 (acceptance criteria explicita del plan)
- **Issue:** El plan pedia confirmar si el wrapper de compatibilidad `reconfigure_line()` (Plan 33-04) seguia teniendo algun llamador real tras esta fase.
- **Fix:** Confirmado con grep que `backend/camera.py:194` ya habia migrado a `reconfigure_lines()`/`LineRepo` en el Plan 33-05; el wrapper solo lo ejercitaban dos tests directos en `tests/test_tracker.py`. Se retiro el metodo y los dos tests.
- **Files modified:** `backend/tracker.py`, `tests/test_tracker.py`
- **Verification:** `grep -rn "reconfigure_line(" backend/` sin coincidencias; `pytest tests/test_tracker.py -q` en verde (20 passed).
- **Committed in:** `250bdcc` (Task 3)

---

**Total deviations:** 2 auto-fijados (2 bugs/limpieza, ambos Rule 1)
**Impact on plan:** El primero era bloqueante (rompia `init_db()` en casi toda la suite) y necesario para completar Task 2 tal como estaba escrita en el plan. El segundo es el cierre natural documentado explicitamente en el propio Task 3 del plan. Sin scope creep: ambos fixes son consecuencia directa de las Tasks 1-2 de este mismo plan, no trabajo nuevo.

## Issues Encountered
Ninguno mas alla de las desviaciones documentadas arriba.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Fase 33 backend cerrado: los tres routers v2 (zonas/lineas/reglas) estan wireados y el arranque real (`lifespan`) usa exclusivamente v2 para zonas/lineas/reglas — el gap documentado por 33-04 (linea hardcodeada) y el gap documentado por 33-05 (ruta v1 de zonas rota intencionadamente) quedan cerrados.
- `/api/zones/stats` queda como unico resto v1 activo (documentado, sin consumidor real detectado) — candidato a su propio plan de gap-closure si se decide darle un consumidor v2 en el futuro.
- El wiring de `frontend/js/app.js` (`bindZoneForm` de `zoneEditor.js`, ya no exportado) documentado por 33-10 sigue siendo scope explicito de 33-13 (ola 5) — este plan no lo tocaba (no forma parte de `depends_on` ni de `files_modified`) y no bloqueaba `main.py`/`config_schema.py` para la verificacion de este plan (el backend arranca y la suite pasa sin necesitar ese wiring de frontend).
- Suite completa: 767 passed, 2 skipped — mismo criterio de cierre que 30-12/31-11/32-07.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

Todos los ficheros modificados/creados y los tres commits de tarea (0d1ccb8, 75ec3b4, 250bdcc) verificados presentes.
