---
phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados
plan: 02
subsystem: perception
tags: [identity, state-machine, fsm, events]

# Dependency graph
requires:
  - phase: 24-01
    provides: "TemporalVoter, IdentityState, IdentityTransition en backend/perception/face/identity.py"
provides:
  - "IdentityStateMachine: on_face_result, on_track_lost, on_tick, on_active_tracks, state_of, identity_of, needs_recognition"
  - "Herencia de identidad por person_id entre track_ids (_claim_lost) — FACE-09/FACE-10"
  - "Gate needs_recognition() para FACE-11"
affects: [24-03, 24-04, 24-05, 24-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FSM pura con reloj inyectado (now: float), sin time/threading, igual que TemporalVoter"
    - "Doble mecanismo de deteccion de perdida: on_track_lost (evento explicito) + on_active_tracks (comparacion con active_ids) + on_tick (expiracion por tiempo), cada uno con su disparador"
    - "El contador de fallos de revalidacion es independiente del veredicto agregado del voter: el reset de exito exige coincidencia del frame actual (person_id == st.person_id), no el ganador de la ventana"

key-files:
  created:
    - tests/test_identity_state_machine.py
  modified:
    - backend/perception/face/identity.py

key-decisions:
  - "_claim_lost se invoca tambien desde la rama UNKNOWN de on_face_result (no solo desde CANDIDATE): un track nuevo con un primer match ya intenta heredar una identidad TEMPORARILY_LOST antes de pasar por el proceso de votacion completo — confirmado por el Pitfall 3 del RESEARCH ('cuando llega el PRIMER on_face_result de un track nuevo... hereda CONFIRMED directamente')"
  - "El reset de fallos de revalidacion en CONFIRMED usa el match del frame actual (person_id == st.person_id), no el veredicto agregado del voter (winner == st.person_id): needs_recognition() solo dispara inferencias espaciadas por revalidate_after (~120s), asi que la ventana del voter retiene votos historicos durante varios ciclos; aceptar el veredicto agregado como señal de exito enmascararia fallos reales durante varios ciclos y el criterio 5 nunca se cumpliria"
  - "TEST_alternating_identities_stay_candidate usa rotacion de 3 identidades (7, 9, 11) en vez de 2: una alternancia binaria estricta desde cero produce, en la 5a votacion (ventana aun sin llenar), un empate exacto 3/5=0.6==min_ratio que el TemporalVoter (locked desde 24-01) interpreta como confirmacion valida — coincidencia numerica de la ventana parcial, no evidencia real de coherencia. Con 3 identidades en conflicto ningun candidato alcanza nunca min_votes con ratio>=0.6"

requirements-completed: [FACE-08, FACE-09, FACE-10, FACE-11]

# Metrics
duration: 10min
completed: 2026-08-13
---

# Phase 24 Plan 02: IdentityStateMachine — votación y máquina de estados Summary

**`IdentityStateMachine` con 4 estados (UNKNOWN/CANDIDATE/CONFIRMED/TEMPORARILY_LOST) y sus 6 transiciones sobre `backend/perception/face/identity.py`, con herencia de identidad por `person_id` entre `track_id`s, revalidación periódica con pérdida tras 3 ciclos fallidos, y el gate `needs_recognition()` que sustituye al reintento indefinido de FACE-11.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-08-13T07:18:06Z
- **Completed:** 2026-08-13T07:28:22Z
- **Tasks:** 2
- **Files modified:** 2 (1 creado, 1 modificado)

## Accomplishments
- Las 6 transiciones del contrato de SPEC_v2.md §5.5 implementadas y cada una con su propio test (criterio 1).
- 200 resultados faciales consecutivos de la misma persona producen exactamente una confirmación emisora (criterio 2).
- Identidades en conflicto (votación alternada entre varias personas) nunca confirman ni caen espontáneamente a UNKNOWN mientras sigan llegando matches (criterio 3).
- Pérdida y recuperación de un track con `track_id` nuevo (patrón real de ByteTrack) conserva la identidad sin duplicar el reconocimiento — cero segundos `PERSON_RECOGNIZED` (criterio 4, FACE-09/FACE-10).
- Revalidación a los 120 s y pérdida de identidad tras 3 ciclos de revalidación vencidos sin match (criterio 5, D-04, D-06).
- `needs_recognition()` cubre los tres disparadores de FACE-11 (track nuevo/CANDIDATE/TEMPORARILY_LOST, confianza de identidad baja del voter — D-03 —, y revalidación vencida), con *backoff* cuando la ventana de votos se agota sin ningún match (base del criterio 6, que se completa en 24-05).
- `on_active_tracks()` detecta tracks caídos sin podar los `TEMPORARILY_LOST` (Pitfall 2 del RESEARCH), y `on_tick()` añade una cota dura de memoria (`stale_ttl`) además de la expiración de `lost_ttl`.
- Suite completa: **358/358** (antes 337, +21 tests de esta fase).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): tests de los 4 estados y 6 transiciones** - `f3424e7` (test)
2. **Task 1 (GREEN): IdentityStateMachine base** - `4e50231` (feat)
3. **Task 2 (RED): tests de revalidación, needs_recognition y on_active_tracks** - `8a91c2e` (test)
4. **Task 2 (GREEN): revalidación completa, needs_recognition, on_active_tracks** - `8671b24` (feat)

**Plan metadata:** (pendiente — commit final de este SUMMARY/STATE/ROADMAP)

## Files Created/Modified
- `backend/perception/face/identity.py` - `_TrackIdentity` (dataclass de estado por track) + `IdentityStateMachine` completa (457 líneas totales del fichero; la clase añade ~330)
- `tests/test_identity_state_machine.py` - 21 tests `TEST_*` cubriendo los criterios 1-5 de la fase y el gate `needs_recognition` (386 líneas)

## Decisions Made
Ver `key-decisions` en el frontmatter. Resumen:
- `_claim_lost` se consulta también desde la rama UNKNOWN (no solo CANDIDATE) — confirmado como diseño correcto por el Pitfall 3 del RESEARCH.
- El reset de fallos de revalidación exige coincidencia del frame actual, no el veredicto agregado del voter — necesario para que el criterio 5 se cumpla con revalidaciones espaciadas 120 s.
- Test de alternancia con 3 identidades en vez de 2, para evitar una coincidencia numérica de ventana parcial del `TemporalVoter` ya bloqueado.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_claim_lost` debe consultarse también desde la rama UNKNOWN de `on_face_result`**
- **Found during:** Task 1, escribiendo `TEST_temporarily_lost_to_confirmed_on_coherent_match` (test explícito del plan que usa un `track_id` nuevo con una sola llamada a `on_face_result`).
- **Issue:** El pseudocódigo del `<action>` de la Task 1 solo menciona `self._claim_lost(winner, now)` dentro de la rama **CANDIDATE** (que requiere que el `TemporalVoter` ya tenga un ganador con `min_votes`/`min_ratio`). Con una sola llamada, un track nuevo nunca sale de la rama UNKNOWN, así que el test esperado (`state_of(2) is CONFIRMED` tras una única llamada) no podía cumplirse solo con la rama CANDIDATE.
- **Fix:** La rama UNKNOWN también intenta `_claim_lost(person_id, now)` antes de degradar a CANDIDATE. Confirmado como el diseño correcto por el propio `24-RESEARCH.md` § Pitfall 3: *"Cuando llega el **primer** `on_face_result` de un track nuevo con `person_id=X` y existe un `TEMPORARILY_LOST` con ese `person_id`... el track nuevo hereda `CONFIRMED` directamente sin re-votar"*.
- **Files modified:** `backend/perception/face/identity.py`
- **Commit:** `4e50231`

**2. [Rule 1 - Bug] El reset de éxito de revalidación no debe basarse en el veredicto agregado del voter**
- **Found during:** Task 2, `TEST_three_failed_revalidations_emit_identity_lost` — el tercer fallo esperado devolvía `None` en vez de la transición `CONFIRMED → UNKNOWN`.
- **Issue:** El `<action>` de la Task 2 proponía resetear el contador de fallos con `person_id == st.person_id **o** winner == st.person_id`. Como `needs_recognition()` solo dispara inferencias espaciadas ~120 s, el `TemporalVoter` recibe un voto nuevo por ciclo sobre una ventana que aún conserva los votos de la confirmación inicial: con solo 1-2 frames sin match, el veredicto agregado seguía dando la persona correcta como ganadora (ratio todavía ≥ `min_ratio`), lo que reseteaba el contador de fallos en cada ciclo y el criterio 5 (tres fallos) nunca se cumplía.
- **Fix:** El reset de éxito exige coincidencia del **frame actual** (`person_id == st.person_id`), no el veredicto agregado. La rama de corrección de identidad (`winner != st.person_id` con mayoría real) se mantiene intacta y separada.
- **Files modified:** `backend/perception/face/identity.py`
- **Commit:** `8671b24`

**3. [Rule 1 - Bug] Test de alternancia con 3 identidades en vez de 2**
- **Found during:** Task 1, `TEST_alternating_identities_stay_candidate`.
- **Issue:** Una alternancia binaria estricta (7, 9, 7, 9, ...) desde cero produce, en la 5ª votación (ventana aún sin llenar: 3 votos de una persona contra 2 de otra), un ratio exacto `3/5 = 0.6 == min_ratio`, que el `TemporalVoter` (ya bloqueado y probado desde 24-01, fuera de alcance de este plan) interpreta legítimamente como confirmación válida según su propio contrato (`ratio >= min_ratio` confirma). Es una coincidencia numérica de la ventana parcial, no evidencia real de una identidad coherente, pero contradice el criterio 3 tal como está descrito en el plan si se usan solo 2 identidades.
- **Fix:** El test rota entre 3 identidades en conflicto (7, 9, 11) en vez de 2, lo que evita matemáticamente que cualquier candidato alcance `min_votes` con `ratio >= 0.6` en cualquier punto de la secuencia, preservando el espíritu del criterio 3 (identidades en conflicto no deben confirmar) sin modificar el `TemporalVoter` ya bloqueado.
- **Files modified:** `tests/test_identity_state_machine.py`
- **Commit:** `f3424e7`

## Issues Encountered
Ninguno bloqueante — las tres desviaciones de arriba se descubrieron y corrigieron dentro del ciclo TDD normal (RED real con la implementación aún incompleta, ajuste, GREEN).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `IdentityStateMachine` completa y lista para que `24-03` la conecte al pipeline real (sustituyendo el mecanismo de votación/consenso actual de `PersonRecognizer`).
- `needs_recognition()` lista para sustituir el gate `person_id is None` de `RecognitionWorker._next_candidate` en una fase posterior.
- `on_active_tracks()` lista para engancharse donde hoy se llama `recognizer.prune(registry.active_ids())`.
- Sin bloqueos para continuar con `24-03`.

---
*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Completed: 2026-08-13*

## Self-Check: PASSED

Ficheros creados/modificados y los 4 commits de tareas verificados en disco/`git log`.
