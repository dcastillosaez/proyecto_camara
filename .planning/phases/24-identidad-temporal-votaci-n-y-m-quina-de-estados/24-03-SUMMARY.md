---
phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados
plan: 03
subsystem: perception
tags: [recognizer, arcface, refactor, memory-bounds]

# Dependency graph
requires:
  - phase: 24-01
    provides: "TemporalVoter en backend/perception/face/identity.py"
  - phase: 24-02
    provides: "IdentityStateMachine en backend/perception/face/identity.py"
provides:
  - "FaceResult(person_id, name, is_new, score, ambiguous) y process_crop_scored() en backend/recognizer.py"
  - "process_crop() como wrapper de compatibilidad (misma firma de 3 elementos)"
  - "Cota de memoria demostrada (10.000 tracks) para TemporalVoter._votes e IdentityStateMachine._states"
affects: [24-04, 24-05, 24-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wrapper de compatibilidad: process_crop_scored() concentra la logica, process_crop() la envuelve descartando score/ambiguous — preserva la firma congelada por introspeccion sin duplicar codigo"
    - "El match por frame vive en PersonRecognizer; la agregacion temporal (voto por mayoria, confirmacion/perdida de identidad) vive fuera, en TemporalVoter/IdentityStateMachine — ninguna doble votacion encadenada"

key-files:
  created: []
  modified:
    - backend/recognizer.py
    - tests/test_recognizer_orchestration.py
    - tests/test_memory_bounds.py
    - tests/test_architecture.py
    - tests/test_phase9.py

key-decisions:
  - "_best_match ahora devuelve (person_id, name, ambiguous, score) en vez de descartar el score calculado — necesario para que IdentityStateMachine.on_face_result(track_id, person_id, score) tenga con que votar"
  - "Se retiro por completo la votacion interna por mayoria (_votes/VOTE_WINDOW=5) de PersonRecognizer: mantenerla habria encadenado dos votaciones delante de TemporalVoter, invalidando sus parametros configurados (window/min_votes/min_ratio) y haciendo pasar el criterio 3 de la fase por accidente (Pitfall 1 del RESEARCH)"
  - "TEST_identity_state_machine_bounded se dejo con el limite generoso <=500 sugerido por el plan aunque el valor medido real es 1 (con un solo person_id en juego, _claim_lost reclama la identidad TEMPORARILY_LOST del track anterior en cuanto llega el siguiente track_id) — el margen amplio protege el invariante de orden de magnitud sin acoplar el test a la combinacion exacta de parametros usada"

requirements-completed: [FACE-07]

# Metrics
duration: 20min
completed: 2026-08-13
---

# Phase 24 Plan 03: Recognizer expone score y retira votación interna Summary

**`backend/recognizer.py` expone `FaceResult`/`process_crop_scored()` con el score de similitud real, retira la doble votación por mayoría interna (`_votes`/`VOTE_WINDOW`) que quedaba delante de `TemporalVoter`, y dos tests nuevos demuestran que `TemporalVoter`/`IdentityStateMachine` no crecen sin cota tras 10.000 tracks.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-13T07:18:00Z (aprox., continuación de sesión 24-02)
- **Completed:** 2026-08-13T07:38:01Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- `FaceResult` dataclass y `process_crop_scored()` exponen el score de similitud coseno del mejor match, que antes se calculaba en `_best_match` y se descartaba en cada uno de los tres `return`.
- Retirada completa de la votación por mayoría interna (`_votes: dict[int, deque[int]]`, `VOTE_WINDOW = 5`) — el match ahora es por frame; la evidencia temporal la acumula `TemporalVoter`/`IdentityStateMachine` fuera de la clase.
- `process_crop()` se conserva intacta como wrapper de compatibilidad: misma firma `(crop_bgr, tracker_id)`, mismo retorno de 3 elementos — verificado por introspección (`TEST_public_contract_unchanged`).
- `INFERENCE_CALLS` (test de arquitectura) protege ahora también la ruta `process_crop_scored`.
- Dos tests nuevos de cota de memoria con 10.000 tracks: `TEST_temporal_voter_bounded` (`_votes` ≤ 6 tras podar) y `TEST_identity_state_machine_bounded` (`_states` ≤ 500, medido en la práctica 1).
- Suite completa: **361/361** (antes 358, +3 tests netos de esta fase).

## Task Commits

Each task was committed atomically:

1. **Task 1: Exponer el score y retirar la votación interna** - `ad84003` (feat)
2. **Task 2: Reparar los tests que dependían de _votes y del voto interno** - `659fa28` (test)

**Plan metadata:** (pendiente — commit final de este SUMMARY/STATE/ROADMAP)

## Files Created/Modified
- `backend/recognizer.py` - `FaceResult` dataclass, `_best_match` devuelve el score, `process_crop_scored()` (lógica completa sin voto interno), `process_crop()` como wrapper de compatibilidad, `prune()` sin `_votes`
- `tests/test_recognizer_orchestration.py` - `TEST_reverify_majority_vote_corrects_identity` sustituido por `TEST_match_is_per_frame_without_internal_vote`; nuevo `TEST_process_crop_scored_returns_similarity`
- `tests/test_memory_bounds.py` - `TEST_recognizer_cache_bounded` sin `_votes`; tracemalloc test sin `_votes`; nuevos `TEST_temporal_voter_bounded` y `TEST_identity_state_machine_bounded`
- `tests/test_architecture.py` - `INFERENCE_CALLS` incluye `process_crop_scored`
- `tests/test_phase9.py` - `TEST_107_prune_drops_inactive_track_state` sin `_votes`/`VOTE_WINDOW` (regresión directa no listada en el plan, ver Deviations)

## Decisions Made
Ver `key-decisions` en el frontmatter. Resumen: el score sube hasta el retorno de `_best_match`, la votación interna desaparece por completo (no se relaja, se retira), y el límite del test de cota de la FSM se deja generoso a propósito.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `TEST_107_prune_drops_inactive_track_state` en `tests/test_phase9.py` rompía tras retirar `_votes`/`VOTE_WINDOW`**
- **Found during:** Task 2, verificación completa (`pytest tests/test_recognizer_orchestration.py tests/test_memory_bounds.py tests/test_architecture.py tests/test_phase9.py tests/test_temporal_voting.py tests/test_identity_state_machine.py -q`)
- **Issue:** El test asignaba `r._votes[2] = deque([2], maxlen=r.VOTE_WINDOW)` y afirmaba `r._votes == {}` tras `prune()` — ninguno de los dos atributos existe ya en `PersonRecognizer`. No estaba en la tabla `<known_breakages>` del plan (que cubría `test_memory_bounds.py` y `test_recognizer_orchestration.py`, pero no `test_phase9.py`), pero es una regresión directa causada por el mismo cambio de Task 1.
- **Fix:** Se eliminaron la línea de setup de `_votes`, el import local de `deque` (ya sin uso) y la aserción `assert r._votes == {}`; se actualizó el comentario de cabecera del bloque para no mencionar `_votes`.
- **Files modified:** `tests/test_phase9.py`
- **Commit:** `659fa28` (incluido en el commit de Task 2)

---

**Total deviations:** 1 auto-fixed (1 bug — regresión de test fuera de la lista de rotura conocida del plan pero causada por el mismo cambio)
**Impact on plan:** Necesario para que la suite completa pasara en verde tras retirar `_votes`. Sin scope creep — mismo cambio de raíz que el resto de los puntos de rotura documentados.

## Issues Encountered
Ninguno bloqueante.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `process_crop_scored()` listo para que `24-05` (RecognitionWorker) lo conecte a `IdentityStateMachine.on_face_result(track_id, person_id, score, now)`.
- `process_crop()` sigue funcionando igual para cualquier llamador que no necesite el score.
- Cota de memoria de `TemporalVoter`/`IdentityStateMachine` demostrada con evidencia real (10.000 tracks), cerrando el invariante de la Fase 22 para las estructuras nuevas de la Fase 24.
- Sin bloqueos para continuar con `24-04`/`24-05`.

---
*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Completed: 2026-08-13*

## Self-Check: PASSED
