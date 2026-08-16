---
phase: 26-an-lisis-de-comportamiento
plan: 02
subsystem: config
tags: [pydantic-settings, config, validation, behavior-analysis]

# Dependency graph
requires: []
provides:
  - "10 parametros behavior_* en Settings con defaults locked de SPEC_v2.md §5.7"
  - "validate_behavior_params: rechaza umbrales <= 0, crowd_threshold < 1 y run_window_secs > 12.0"
affects: [26-04-manager-main-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Guarda de coherencia entre config y supuesto de dominio (run_window_secs <= 12.0 vs centroid_history maxlen=150 @ 12 FPS)"

key-files:
  created: []
  modified:
    - backend/config.py
    - tests/test_config.py

key-decisions:
  - "run_window_secs limitado a 12.0 s para que ninguna configuracion pueda romper el supuesto de historial corto siempre disponible del BehaviorAnalyzer"
  - "loiter_require_zone=False por defecto (fallback D-02): sin zonas configuradas, LOITERING sigue siendo emitible"

patterns-established:
  - "Validadores de rango agrupados al final de la clase Settings, uno por bloque de fase, con mensaje que explica la consecuencia y no solo el rango"

requirements-completed: [BEH-01, BEH-02, BEH-03]

# Metrics
duration: 10min
completed: 2026-08-16
---

# Phase 26 Plan 02: Configuracion de umbrales de comportamiento Summary

**10 parametros behavior_* en Settings con validador que impide romper el supuesto de historial corto (run_window_secs <= 12.0) via configuracion**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-08-16
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments
- Bloque de configuracion "Analisis de comportamiento (Fase 26 — BEH-01..BEH-05)" en `backend/config.py` con los 10 campos y defaults exactos del SPEC_v2.md §5.7
- `validate_behavior_params` (`@model_validator(mode="after")`) que rechaza umbrales <= 0, `crowd_threshold < 1` y, criticamente, `run_window_secs > 12.0` (limite impuesto por `centroid_history` deque de 150 muestras a 12 FPS)
- 3 tests `TEST_behavior_*` en `tests/test_config.py`: defaults, positividad de umbrales y cota de `run_window_secs`

## Task Commits

Each task was committed atomically:

1. **Task 1: Bloque de config de comportamiento y validador de rango** - `0b6668a` (feat)
2. **Task 2: Tests de defaults y de rango en tests/test_config.py** - `ec6c746` (test)

_Nota: plan `autonomous: true`, sin checkpoints._

## Files Created/Modified
- `backend/config.py` - 10 campos `behavior_*` (bloque tras `reid_max_gallery_entries`) + `validate_behavior_params`
- `tests/test_config.py` - `TEST_behavior_defaults_match_spec`, `TEST_behavior_params_must_be_positive`, `TEST_behavior_run_window_capped_by_history`

## Decisions Made
- `run_window_secs` acotado a `<= 12.0` s: es la misma clase de guarda que `validate_identity_params` (impide una configuracion que nunca podria cumplirse), aqui contra el limite real de `centroid_history` (tracking.py:47, maxlen=150) al peor caso de FPS (rate.py:26, STEPS[0]=12.0)
- No se toco `DEFAULT_SEVERITY` en `backend/events/types.py` (D-01) ni `config/rules.yaml` (diferido explicitamente por CONTEXT) — confirmado con `git diff --stat` vacio en ambos

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Los 10 parametros `behavior_*` estan disponibles para que `26-04` (wiring de manager/main) los use al instanciar `BehaviorAnalyzer`
- `backend/events/types.py` y `config/rules.yaml` permanecen sin cambios, tal como exige el criterio de aceptacion de este plan

---
*Phase: 26-an-lisis-de-comportamiento*
*Completed: 2026-08-16*

## Self-Check: PASSED
