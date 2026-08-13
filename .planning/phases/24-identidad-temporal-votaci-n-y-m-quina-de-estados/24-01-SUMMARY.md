---
phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados
plan: 01
subsystem: perception
tags: [identity, voting, config, pydantic-settings, temporal-voter]

# Dependency graph
requires:
  - phase: 23-insightface-arcface
    provides: "FaceEngine, FaceQualityAssessor, IdentityIndex — embeddings 512D y umbrales de match/confirm ya en Settings"
provides:
  - "TemporalVoter: ventana deslizante de votos por track con veredicto por mayoría + ratio"
  - "IdentityState (4 estados) e IdentityTransition (dataclass) — base para la FSM de 24-02"
  - "5 parámetros de identidad en Settings con validación cruzada de rangos"
affects: [24-02, 24-03, 24-04, 24-05, 24-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Módulo de dominio puro sin reloj propio: métodos que dependen de tiempo reciben `now: float` (mismo patrón que AdaptiveRate.should_process)"
    - "Ratio de veredicto sobre el total de votos de la ventana (incluidos los None), no solo los votos con match"

key-files:
  created:
    - backend/perception/face/identity.py
    - tests/test_temporal_voting.py
  modified:
    - backend/config.py
    - tests/test_config.py

key-decisions:
  - "Confianza agregada = media de los scores del ganador, no el máximo, para que un único frame afortunado no confirme una identidad"
  - "El denominador del ratio (min_ratio) es len(votes) completo, no solo los votos con match: hace que A,B,A,B,... alternado dé 4/8=0.5 < 0.6 y no confirme ninguna identidad (criterio 3 de la fase)"
  - "TemporalVoter no usa locks: vive en un solo hilo (RecognitionWorker._loop), a diferencia de TrackRegistry"

patterns-established:
  - "Configuración imposible aborta el arranque vía @model_validator(mode='after') en vez de degradar en silencio (ASVS V5)"

requirements-completed: [FACE-07]

# Metrics
duration: 25min
completed: 2026-08-13
---

# Phase 24 Plan 01: Config e identidad temporal (TemporalVoter) Summary

**TemporalVoter con ventana deslizante de votos por track (deque+Counter) y 5 parámetros de identidad temporal añadidos a Settings con validación cruzada de rangos.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-08-13T06:45:00Z
- **Completed:** 2026-08-13T07:10:10Z
- **Tasks:** 2
- **Files modified:** 4 (2 creados, 2 modificados)

## Accomplishments
- `Settings` expone `identity_vote_window`, `identity_min_votes`, `identity_min_ratio`, `identity_lost_ttl_secs`, `identity_revalidate_after_secs` con los defaults de SPEC_v2.md §5.5 y un validador cruzado que aborta el arranque ante configuraciones imposibles.
- `backend/perception/face/identity.py`: `IdentityState` (4 estados), `IdentityTransition` (dataclass) y `TemporalVoter`, dominio puro sin `time` ni `threading`.
- Criterio 3 de la fase (identidades alternadas A,B,A,B,... no confirman ninguna) cubierto por test automatizado, cumpliendo el ciclo TDD RED→GREEN completo.

## Task Commits

Each task was committed atomically:

1. **Task 1: Añadir los 5 parámetros de identidad a Settings con validación de rangos** - `64753be` (feat)
2. **Task 2: Crear identity.py (RED)** - `09a6c95` (test)
3. **Task 2: Crear identity.py (GREEN)** - `4879a99` (feat)

**Plan metadata:** (pendiente — commit final de este SUMMARY/STATE/ROADMAP)

_Nota: Task 2 llevaba `tdd="true"`; se ejecutó como RED (tests fallando por `ModuleNotFoundError`, commit `09a6c95`) seguido de GREEN (implementación, commit `4879a99`). No hizo falta REFACTOR._

## Files Created/Modified
- `backend/config.py` - 5 parámetros de identidad temporal + `@model_validator(mode="after")` con validación cruzada de rangos
- `tests/test_config.py` - 3 tests `TEST_identity_*` (defaults, ventana < min_votes, ratio fuera de rango)
- `backend/perception/face/identity.py` - `IdentityState`, `IdentityTransition`, `TemporalVoter` (dominio puro)
- `tests/test_temporal_voting.py` - 8 tests `TEST_*` cubriendo veredicto, agregación de confianza, ventana deslizante, reset, prune y el criterio 3 (alternancia)

## Decisions Made
- Confianza agregada como media (no máximo) de los scores del ganador — ver `key-decisions` arriba.
- Ratio calculado sobre `len(votes)` completo (incluye votos `None`), no solo los que tienen match — es la pieza que resuelve el criterio 3.
- Sin locks en `TemporalVoter`: vive en un único hilo (`RecognitionWorker._loop`), a diferencia del lock de `tracking.py` que el plan explícitamente indicó no copiar.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. El plan ya incluía el código concreto de `identity.py` y del validador; solo se completaron los cuerpos de `votes_for()` y `matched_votes()`, que el plan dejaba con docstring sin `return` explícito (comportamiento evidente por el propio docstring, no un cambio de diseño).

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `TemporalVoter`, `IdentityState` e `IdentityTransition` listos para que 24-02 construya `IdentityStateMachine` encima.
- Los 5 parámetros de `Settings` ya validados y disponibles para inyectar en la FSM sin más configuración.
- Sin bloqueos para continuar con la Wave 1 restante / Wave 2 de la fase.

---
*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Completed: 2026-08-13*

## Self-Check: PASSED

Todos los ficheros creados/modificados y los 3 commits de tareas verificados en disco/`git log`.
