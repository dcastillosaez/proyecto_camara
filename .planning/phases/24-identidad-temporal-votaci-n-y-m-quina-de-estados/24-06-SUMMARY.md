---
phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados
plan: 06
subsystem: testing
tags: [phase-gate, regression, measurement, ci-coverage]

# Dependency graph
requires:
  - phase: 24-01
    provides: "TemporalVoter, IdentityState, IdentityTransition, 5 parámetros de Settings"
  - phase: 24-02
    provides: "IdentityStateMachine — 4 estados, 6 transiciones, revalidación, needs_recognition"
  - phase: 24-03
    provides: "PersonRecognizer.process_crop_scored() con score real, sin votación interna"
  - phase: 24-04
    provides: "TrackRegistry.identity_state, EventEngine.emit_identity"
  - phase: 24-05
    provides: "RecognitionWorker cableado a la FSM, TrackRegistry.frame_ids (D-05), criterio 6 medido"
provides:
  - "Evidencia de que los 6 criterios de éxito de ROADMAP § Phase 24 tienen un comando automatizado que los demuestra"
  - "Verificación de que ningún test nuevo de la fase usa `def test_*` (se perdería en el CI Linux, python_functions = TEST_*)"
  - "Fase 24 cerrada: FACE-07..FACE-11 completos, suite 377/377"
affects: [25]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: []

key-decisions:
  - "No hizo falta ningún cambio de código: la suite ya estaba verde (377/377) y FACE-07..FACE-11 ya estaban marcados [x] en REQUIREMENTS.md desde los planes 24-01/24-02, marcados incrementalmente vía requirements.mark-complete tras cada SUMMARY. Este plan es puramente de verificación y documentación de trazabilidad."

patterns-established: []

requirements-completed: [FACE-07, FACE-08, FACE-09, FACE-10, FACE-11]

# Metrics
duration: 20min
completed: 2026-08-13
---

# Phase 24 Plan 06: Puerta de fase — trazabilidad de los 6 criterios de éxito Summary

**Suite completa verde (377/377, sin skipped/xfailed nuevos) y los 6 criterios de éxito de ROADMAP § Phase 24 verificados uno a uno con el comando `pytest -k` que los selecciona y pasa; FACE-07..FACE-11 confirmados como completos.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-13T07:50:00Z
- **Completed:** 2026-08-13T08:13:03Z
- **Tasks:** 2
- **Files modified:** 0 (plan de verificación pura, sin cambios de código)

## Accomplishments
- `pytest tests/ -q` sale con código 0: **377 passed** (línea base pre-fase: 326; +51 tests netos de la Fase 24 completa, 24-01..24-06).
- Verificado que ninguna función de test nueva de `test_temporal_voting.py`/`test_identity_state_machine.py` usa `def test_*` (se perdería en el CI Linux por `python_functions = TEST_*` sensible a mayúsculas).
- Los 6 criterios de éxito de ROADMAP § Phase 24 tienen cada uno un comando `pytest -k` que los selecciona y pasa con código 0 (ninguno con código 5 = "no tests collected").
- `FACE-07`, `FACE-08`, `FACE-09`, `FACE-10`, `FACE-11` confirmados `- [x]` en `.planning/REQUIREMENTS.md` (ya marcados incrementalmente por los planes 24-01/24-02 al completarse cada uno).
- Fase 24 cerrada: no se detectó ninguna regresión que arreglar, ningún checkpoint manual pendiente (`24-VALIDATION.md` § "Manual-Only Verifications" vacío).

## Tabla de trazabilidad — criterio → comando → test → resultado

| # | Criterio (verbatim de ROADMAP § Phase 24) | Comando | Test(s) que lo cubren | Resultado |
|---|---|---|---|---|
| 1 | Los 4 estados (UNKNOWN, CANDIDATE, CONFIRMED, TEMPORARILY_LOST) y sus transiciones están testeados uno a uno | `pytest tests/test_identity_state_machine.py -q` | Las 21 funciones `TEST_*` del fichero, una por transición/escenario del contrato de SPEC_v2.md §5.5 | **21 passed** |
| 2 | Una secuencia de 200 frames de una persona conocida emite exactamente un PERSON_RECOGNIZED | `pytest tests/test_identity_state_machine.py -k single_recognition -q` | `TEST_single_recognition_over_200_frames` | **1 passed** |
| 3 | Con embeddings ruidosos alternando dos identidades, el track permanece en CANDIDATE y no confirma ninguna | `pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py -k alternating -q` | `TEST_alternating_identities_have_no_winner` (temporal_voting) + `TEST_alternating_identities_stay_candidate` (identity_state_machine, con 3 identidades en rotación — ver Deviations de 24-02, no de este plan) | **2 passed** |
| 4 | Cero identidades duplicadas tras pérdida y recuperación de track | `pytest tests/test_identity_state_machine.py -k track_recovery -q` | `TEST_track_recovery_keeps_same_identity` | **1 passed** |
| 5 | La revalidación tras 120 s funciona y tres fallos consecutivos emiten IDENTITY_LOST | `pytest tests/test_identity_state_machine.py -k revalidat -q` | `TEST_revalidate_after_expires_triggers_recheck`, `TEST_three_failed_revalidations_emit_identity_lost`, `TEST_failed_revalidation_only_counts_once_per_cycle`, `TEST_successful_revalidation_resets_failures` | **4 passed** |
| 6 | Las inferencias faciales por minuto con una persona estática bajan al menos un 70% respecto a la Phase 23 | `pytest tests/test_recognition_worker.py -k inference_budget -q` | `TEST_inference_budget_drops_on_unconfirmed_track` | **1 passed** (87.5% de reducción medido; ver escenario abajo) |

Ninguno de los 6 comandos salió con código 5 ("no tests collected"). Los 21 tests de la fila 1 incluyen, sin duplicar el conteo, los tests de las filas 2, 4 y 5 (son subconjuntos del mismo fichero).

## Criterio 6 — escenario medido (D-01)

**Qué escenario se midió:** un track **NO confirmado**, estático, que nunca llega a identificarse — cara no detectable, calidad insuficiente o match ambiguo. Es el caso patológico exacto de la Fase 23: `_next_candidate` devolvía ese track en cada ciclo de reconocimiento indefinidamente, gastando inferencias sin ningún resultado útil (~120 inferencias/min a un `target_fps` de reconocimiento de 2). Es el escenario donde la FSM tiene margen real para ahorrar: sin identidad confirmada, `needs_recognition()` mete backoff entre reintentos en vez del reintento ciego de la Fase 23.

**Qué escenario NO se midió y por qué:** un track ya **confirmado**. El filtro `person_id is None` de la Fase 23 ya hacía 0 inferencias ahí — medir la reducción sobre un track confirmado daría 0% o negativo, porque esta fase **añade** la revalidación periódica cada 120 s, que antes no existía. Comparar contra ese escenario habría sido una medición sin sentido (partiendo ya de cero).

**Coste nuevo aceptado:** en régimen permanente, un track `CONFIRMED` consume 0,5 inferencias/min (una cada `revalidate_after_secs=120`) donde antes de esta fase consumía 0. Es el precio de poder detectar que la identidad dejó de ser correcta (revalidación) — una capacidad que la Fase 23 no tenía.

**Cifras reales de la ejecución** (`TEST_inference_budget_drops_on_unconfirmed_track`, `tests/test_recognition_worker.py`, mismo `RecognitionWorker` sobre la misma carga: 1 track estático, `min_track_age=0`, `target_fps=20`, `recognizer.process_crop_scored` sin match nunca, durante 1 segundo real):

| Escenario | Inferencias en 1 s |
|---|---|
| Baseline (Fase 23, `identity_fsm=None`) | 16 |
| Con FSM (Fase 24, `needs_recognition()`) | 2 |
| Reducción | **87.5%** (umbral exigido ROADMAP: ≥70%) |

**Con qué se midió:** el contador `RecognitionWorker.stats["face_inferences"]` (equivalente a `process_crop_scored.call_count` sobre el mock del recognizer en el test), que cuenta inferencias reales ejecutadas. **No** la métrica `face_fps` del sampler — esa cifra viene de `AdaptiveRate.stats` y refleja el FPS *objetivo* configurado para el reconocimiento, no cuántas inferencias se ejecutaron de verdad; con la FSM aplicando backoff, `face_fps` seguiría marcando el mismo objetivo aunque `needs_recognition()` devuelva `False` y no se ejecute ninguna inferencia real (Mismatch 5 de `24-RESEARCH.md`).

## Consecuencias abiertas

- **`config/rules.yaml`** tiene la regla `persona_desconocida` basada en `event: LINE_CROSSED` + `person: unknown`. Ahora que `UNKNOWN_PERSON` se emite de verdad (desde 24-04), añadir una regla nueva para ese tipo de evento sin retirar la existente duplicaría notificaciones. No se toca en esta fase — anotado ya en 24-04-SUMMARY.md, se repite aquí porque sigue sin resolverse al cierre de la fase.
- **`tracks.identity_state`** (columna de `backend/storage/models.py:78`) sigue sin escribirse en base de datos: la fase produce el valor en `TrackRegistry` (memoria, en vivo), pero persistirlo en SQLite quedó explícitamente fuera de alcance de la Fase 24.
- **`should_attempt`, `identify_or_register`, `REVERIFY_INTERVAL`, `get_cached`** de `backend/recognizer.py` siguen sin ninguna llamada en producción — solo los usan `tests/test_phase9.py` y `tests/test_recognizer_orchestration.py`. Su retirada quedó fuera del alcance de esta fase.
- **CI Linux:** `.github/workflows/tests.yml` tiene `continue-on-error: true` y `pytest.ini` fija `python_functions = TEST_*`. Los ~69 tests preexistentes del repo escritos en minúscula (`def test_*`, ver tabla de grep en Task 1) no se ejecutan en el CI Linux, y un fallo de la suite tampoco bloquea el check del PR mientras `continue-on-error` siga activo. Arreglar ese desajuste es trabajo aparte, no de esta fase — los tests nuevos de la Fase 24 sí siguen la convención `TEST_*` y sí se recogerían.
- **Checkpoints de cámara real:** ninguno pendiente de esta fase. `24-VALIDATION.md` § "Manual-Only Verifications" está vacío porque los 6 criterios de éxito son verificables con tests sintéticos. Los 6 checkpoints de cámara real de fases anteriores (19-01, 19-02, 20-02, 21-01, 22-01, 23-02) siguen abiertos pero no tienen relación con la Fase 24.

## Task Commits

Este plan no modificó ningún fichero de código ni de configuración — la suite ya estaba verde y `REQUIREMENTS.md` ya tenía FACE-07..FACE-11 marcados desde los planes 24-01/24-02. No hay commits de tarea; solo el commit final de metadatos (SUMMARY/STATE/ROADMAP).

## Files Created/Modified
- `.planning/phases/24-identidad-temporal-votaci-n-y-m-quina-de-estados/24-06-SUMMARY.md` - este documento

## Decisions Made
Ver `key-decisions` en el frontmatter: no hizo falta ningún fix, la puerta de fase pasó a la primera ejecución de la suite completa.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. No se encontró ninguna regresión que arreglar en el fichero causante (Rule 1/2/3) porque la suite ya estaba verde desde el cierre de 24-05.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Fase 24 (Identidad temporal — votación y máquina de estados) completa: 6/6 planes, FACE-07..FACE-11 cerrados, suite 377/377.
- Fase 25 (Re-identificación, ReID) puede planificarse: depende de la Fase 24, ya completa.
- Consecuencias abiertas documentadas arriba no bloquean la Fase 25, pero conviene revisarlas antes de dar por definitivamente cerrado el subsistema de identidad (en particular la regla `persona_desconocida` de `config/rules.yaml`, que sí interactúa con el catálogo de eventos que Fase 25 también usará).

---
*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Completed: 2026-08-13*

## Self-Check: PASSED

Verificado: `pytest tests/ -q` → 377 passed (código 0). Los 6 comandos de la tabla de trazabilidad ejecutados de nuevo, todos código 0. `grep -n "^def test_\|^async def test_" tests/test_temporal_voting.py tests/test_identity_state_machine.py` sin resultados. `grep -n "FACE-07\|FACE-08\|FACE-09\|FACE-10\|FACE-11" .planning/REQUIREMENTS.md` muestra los 5 con `- [x]`.
