---
phase: 25-re-identificaci-n-de-personas-reid
plan: 02
subsystem: perception
tags: [identity-fsm, reid, temporal-identity]

requires:
  - phase: 24-identidad-temporal
    provides: "IdentityStateMachine con 4 estados y _claim_lost() como unico punto de herencia por person_id"
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 01
    provides: "ReIDEngine (embeddings de apariencia) — no consumido aun por este plan, solo por el futuro cableado del pipeline"

provides:
  - "IdentityStateMachine.on_reid_result(track_id, person_id, similarity, now) — segunda via de recuperacion de identidad, por apariencia, aditiva y sin voto"

affects: [25-03, 25-04, 25-05, 25-06]

tech-stack:
  added: []
  patterns:
    - "Segunda via de entrada de evidencia a una FSM de dominio puro: reutiliza el metodo privado que ya resuelve la herencia (_claim_lost) en vez de duplicar logica o resolverla fuera de la FSM"

key-files:
  created: []
  modified:
    - backend/perception/face/identity.py
    - tests/test_identity_state_machine.py

key-decisions:
  - "on_reid_result() vive en identity.py, no en el worker: resolver la herencia fuera de la FSM deja huerfana la entrada TEMPORARILY_LOST en _states y on_tick() emitiria un IDENTITY_LOST espurio 30 s despues (Pitfall 4 del RESEARCH) — solo _claim_lost() limpia esa entrada y es privado"
  - "on_reid_result() fija st.last_face_at = now al heredar (Pitfall 5): sin esto, el barrido de rancios de on_tick (stale_ttl = lost_ttl + revalidate_after * MAX_FAILED_REVALIDATIONS) purgaria el estado recien heredado; consecuencia deliberada: el track heredado por apariencia no revalida con cara hasta revalidate_after (120 s)"
  - "on_reid_result() nunca llama a TemporalVoter.vote(): la votacion sigue siendo exclusivamente facial (FACE-07); un voto de apariencia contaminaria los parametros ya medidos de la votacion"
  - "Guarda de doble capa contra secuestro: state is not UNKNOWN (la cara ya establecio CANDIDATE/CONFIRMED) O matched_votes(track_id) > 0 (hay evidencia facial aunque el estado agregado siga UNKNOWN) — cualquiera de las dos basta para que ReID no interfiera"

patterns-established: []

requirements-completed: [REID-02, REID-03]

duration: 5min
completed: 2026-08-13
---

# Phase 25 Plan 02: on_reid_result — segunda via de recuperacion de identidad Summary

**Metodo aditivo en `IdentityStateMachine` que hereda una identidad `TEMPORARILY_LOST` por apariencia (sin cara visible), reutilizando `_claim_lost()` y sin votar en el `TemporalVoter`**

## Accomplishments

- `IdentityStateMachine.on_reid_result(track_id, person_id, similarity, now)` anadido justo despues de `on_face_result`, con la implementacion exacta validada por el RESEARCH y el plan-checker: reutiliza `_claim_lost()`, fija `last_face_at = now` para sobrevivir al barrido de rancios de `on_tick`, y devuelve `emits=False` (misma visita, sin segundo `PERSON_RECOGNIZED`).
- Guardas de no-interferencia: un track `CANDIDATE`/`CONFIRMED`, o un `UNKNOWN` con votos faciales coincidentes (`matched_votes > 0`), nunca es secuestrado por un resultado de ReID — la cara siempre manda.
- Docstring de modulo actualizado: la re-identificacion por apariencia deja de estar "fuera de alcance (Fase 25)" y pasa a documentarse como entrada por `on_reid_result()`.
- 7 tests `TEST_reid*` deterministas (reloj sintetico, sin pipeline ni ReID real) cubren herencia, ausencia de voto, no-secuestro de tracks en votacion o confirmados, no-interferencia con evidencia facial propia, ausencia de identidad perdida, y los dos pitfalls criticos del RESEARCH: `IDENTITY_LOST` espurio tras heredar (Pitfall 4) y barrido de rancios sobre el estado recien heredado (Pitfall 5).
- Suite completa verificada: 388/388 (381 previos + 7 nuevos).

## Task Commits

1. **Task 1: `IdentityStateMachine.on_reid_result()`** - `e7a2a43` (feat)
2. **Task 2: 7 tests `TEST_reid*` en `tests/test_identity_state_machine.py`** - `ad5c720` (test)

## Files Created/Modified

- `backend/perception/face/identity.py` - `on_reid_result()` (43 lineas insertadas, docstring de modulo actualizado)
- `tests/test_identity_state_machine.py` - 7 tests `TEST_reid*` (96 lineas insertadas) con seccion documentada de por que ReID entra por la FSM

## Decisions Made

Ver `key-decisions` en el frontmatter. Ninguna decision arquitectural nueva: el codigo se copio verbatim del RESEARCH §Q1, ya validado por trazado de codigo y por el plan-checker.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. El bloque de codigo de `on_reid_result` se copio literalmente del plan/RESEARCH, incluido el comentario de Pitfall 5 sobre `last_face_at`.

## Issues Encountered

Ninguno.

## User Setup Required

None.

## Next Phase Readiness

`on_reid_result()` esta listo para que `25-03`..`25-06` construyan `TrackGallery` y el cableado del pipeline que lo invoque con resultados reales de `ReIDEngine` (Fase 25-01). Sin deuda pendiente de este plan: `on_face_result`, `_claim_lost`, `on_tick`, `on_active_tracks` y `needs_recognition` quedan intactos (cambio puramente aditivo, D-8).

---
*Phase: 25-re-identificaci-n-de-personas-reid*
*Completed: 2026-08-13*

## Self-Check: PASSED

Ficheros y ambos hashes de commit (`e7a2a43`, `ad5c720`) verificados presentes en el repositorio.
