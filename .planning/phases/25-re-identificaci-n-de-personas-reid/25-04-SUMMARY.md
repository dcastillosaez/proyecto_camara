---
phase: 25-re-identificaci-n-de-personas-reid
plan: 04
subsystem: perception
tags: [reid, recognition-worker, appearance-memory, temporal-identity, event-loop]

requires:
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 01
    provides: "ReIDEngine — embeddings de apariencia 512D L2-normalizados"
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 02
    provides: "IdentityStateMachine.on_reid_result() — herencia de identidad por apariencia"
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 03
    provides: "TrackGallery.resolve()/needs_embedding()/prune() — memoria de apariencia y candidato real"

provides:
  - "RecognitionWorker con via ReID cableada en el mismo hilo/tick que la via facial: _face_pass + _reid_pass"
  - "_next_reid_candidate — seleccion propia de candidato ReID, gate TrackGallery.needs_embedding(), filtrado a tracks visibles en frame_ids()"
  - "Flag reid_inherit en el worker (no en TrackGallery): resolve() siempre calcula, on_reid_result() solo se invoca si el flag esta activo"
  - "Contadores reid_inferences/reid_matches/reid_inherited/reid_conflicts en RecognitionWorker.stats, expuestos via /api/v2/cameras/{id}/health"

affects: [25-05, 25-06]

tech-stack:
  added: []
  patterns:
    - "Extraccion de _face_pass/_reid_pass desde _loop: ambas vias corren en el mismo tick sin que la ausencia de candidato de una impida la otra (return en vez de continue)"
    - "Flag de politica (aplicar vs solo-auditar una decision ya calculada) vive en el consumidor (worker), no en el dominio puro (TrackGallery) — mismo patron que separa calculo de aplicacion en IdentityStateMachine.on_reid_result vs RecognitionWorker"

key-files:
  created: []
  modified:
    - backend/pipeline/recognition.py
    - tests/test_recognition_worker.py

key-decisions:
  - "_next_reid_candidate exige track_id in registry.frame_ids(), ademas del gate de TrackGallery.needs_embedding() ya previsto por el plan: un track fuera del frame actual no tiene bbox fiable, y si se re-embebiera igualmente, gallery.update() escribiria identity_of(tid)==None (identity.py solo devuelve person_id si el track esta CONFIRMED) sobre la entrada de ese track, borrando en la galeria la identidad que ReID necesita conservar para que otro track la reclame despues — justo lo contrario del criterio 3. Ver Deviations."
  - "REID_INHERIT_IDENTITY vive en RecognitionWorker (self._reid_inherit), no en TrackGallery: resolve() calcula siempre el candidato real, y el worker decide aplicar la herencia (on_reid_result) o solo contarla (modo solo-observacion, criterio 4) — decision ya fijada por 25-03, aqui solo se cablea"
  - "self._rate.observe() nunca se llama desde _reid_pass: la latencia ReID se instrumenta solo con _metrics.inference_latency_seconds.labels(stage='reid'), para no contaminar avg_latency de /api/v2/cameras/{id}/health (que significa latencia facial)"

patterns-established:
  - "Un metodo _pass por via de inferencia dentro de _loop, cada uno con su propio try/except que incrementa _exceptions y hace return (nunca mata el hilo del worker) — patron reutilizable para futuras vias de inferencia adicionales"

requirements-completed: [REID-01, REID-02, REID-03, REID-04]

duration: 12min
completed: 2026-08-15
---

# Phase 25 Plan 04: Via ReID dentro de RecognitionWorker Summary

**`RecognitionWorker` cablea `ReIDEngine` + `TrackGallery` + `on_reid_result()` en el mismo hilo/tick que la via facial, con seleccion propia de candidato, flag de herencia y 4 contadores de auditoria — criterios 3 y 5 del ROADMAP verdes end-to-end**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- `backend/pipeline/recognition.py`: `_loop` extrae `_face_pass`/`_reid_pass`, ambas corren cada tick sin que la ausencia de candidato de una bloquee la otra (persona de espaldas: `needs_recognition()` dice que no, `_next_reid_candidate` dice que si).
- `_next_reid_candidate` gatea sobre `TrackGallery.needs_embedding()` (criterio 5) y NO sobre `fsm.needs_recognition()` — deliberado, es el gate facial que precisamente rechazaria los casos que ReID cubre.
- `_reid_pass`: embed -> update de galeria -> `resolve()` (siempre calcula el candidato real) -> si `reid_inherit` esta activo, `on_reid_result()` -> propagacion a `TrackRegistry` + `_emit_identity`. Excepcion completa envuelta en `try/except` que incrementa `_exceptions` sin matar el hilo.
- 4 contadores `reid_inferences`/`reid_matches`/`reid_inherited`/`reid_conflicts` en `stats`, canal de auditoria del criterio 4 sin endpoints nuevos.
- `TrackGallery.prune()` cableado en `_sync_identity`, unico punto de mantenimiento periodico.
- 5 tests nuevos en `tests/test_recognition_worker.py`: presupuesto de inferencias (criterio 5), modo solo-observacion (criterio 4), contadores expuestos, compatibilidad sin ReID (Fase 24 intacta), y el end-to-end del criterio 3 (`TEST_reid_recovers_identity_without_face`, verificado 3 veces seguidas sin flaky).
- Suite completa: **407/407** (402 previos + 5 nuevos).

## Task Commits

Cada tarea se comprometio atomicamente:

1. **Task 1: via ReID dentro de RecognitionWorker** - `f220430` (feat)
2. **Task 2: tests de presupuesto (criterio 5) y modo solo-observacion** - `4fb505f` (test)
3. **Task 3: test end-to-end del criterio 3 + fix de `_next_reid_candidate`** - `6c31569` (test)

## Files Created/Modified

- `backend/pipeline/recognition.py` - `_face_pass`/`_reid_pass` extraidos de `_loop`, `_next_reid_candidate`, `_active_identities`, 4 contadores en `__init__`/`stats`, `gallery.prune()` en `_sync_identity`
- `tests/test_recognition_worker.py` - `_emb`/`_reid_mock` helpers + 5 tests `TEST_reid*`

## Decisions Made

Ver `key-decisions` en el frontmatter. La unica decision no anticipada por el plan es el filtro `frame_ids()` en `_next_reid_candidate` — ver Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_next_reid_candidate` re-embebia tracks fuera del frame actual, borrando su identidad en la galeria**
- **Found during:** Task 3, al escribir `TEST_reid_recovers_identity_without_face` (el test end-to-end del criterio 3) — fallaba de forma reproducible (3/3), no por flakiness.
- **Issue:** El codigo del plan para `_next_reid_candidate` (copiado literal del RESEARCH) solo filtra por `min_track_age` y `TrackGallery.needs_embedding()`, sobre `registry.snapshot()` completo. Un track que pasa a `TEMPORARILY_LOST` (ya no esta en `frame_ids()`) sigue en `snapshot()` hasta que `DetectionWorker.prune()` lo expulsa (TTL 30s por defecto en produccion). Si el gate de intervalo vuelve a cumplirse antes de esa poda, `_next_reid_candidate` lo re-selecciona, `_reid_pass` llama a `self._fsm.identity_of(tid)` — que devuelve `(None, 0.0)` para cualquier estado que no sea `CONFIRMED` (identity.py:155-159) — y `gallery.update(tid, emb, None, now)` sobrescribe la identidad de ese track en la galeria a `None`. Como el track perdido es precisamente la fuente de la identidad que un track nuevo (reaparecido de espaldas) necesita reclamar, esto borraba en segundos la memoria de apariencia que el criterio 3 exige conservar durante toda la ventana de herencia (15s) — el mecanismo de ReID quedaba inutilizado para su caso de uso principal.
- **Fix:** `_next_reid_candidate` anade `ts.track_id in self._registry.frame_ids()` a los filtros: solo se re-embebe un track actualmente visible (bbox fiable). Un track perdido conserva en la galeria la ultima identidad que tenia mientras estaba confirmado y visible, sin que nada la sobrescriba despues.
- **Files modified:** `backend/pipeline/recognition.py`.
- **Verification:** `TEST_reid_recovers_identity_without_face` pasa 3/3 tras el fix; suite completa de `test_recognition_worker.py` (16/16), `test_track_gallery.py`, `test_identity_state_machine.py` y `test_architecture.py` siguen verdes tras el cambio (61/61 en conjunto); suite global 407/407.
- **Committed in:** `6c31569` (Task 3 commit — el fix y el test que lo revela van juntos, no se podia commitear el test en rojo sin violar el criterio 3).

---

**Total deviations:** 1 auto-fixed (1 bug de correctitud)
**Impact on plan:** El fix es minimo (un filtro adicional en un list comprehension ya existente), no cambia ninguna firma ni contrato de las interfaces de 25-01/25-02/25-03, y es coherente con la propia justificacion del plan para `_next_reid_candidate` ("un track por tick... degradacion segura"). Sin este fix, el criterio 3 (razon de ser de esta fase) habria quedado roto en produccion pasado el primer `reid_interval_secs` tras perder un track.

## Issues Encountered

Ninguno mas. El resto del plan se ejecuto tal cual el bloque de codigo y la secuencia de los 3 tasks.

## User Setup Required

None.

## Next Phase Readiness

La via ReID esta completa y verificada end-to-end dentro de `RecognitionWorker`: criterios 3, 4 (modo solo-observacion) y 5 del ROADMAP demostrados con tests reales sobre el worker real (no mocks del propio worker). `reid_inherit=False` por defecto (fail-safe, T-25-12) — activar la herencia en produccion es una decision de configuracion pendiente para `25-05`/`25-06` (cableado en `manager.py`/`config.py` y validacion con camara real), fuera del alcance de este plan. Sin deuda pendiente de este plan; `backend/pipeline/tracking.py` y `backend/events/engine.py` sin tocar (D-5/D-6 verificados).

---
*Phase: 25-re-identificaci-n-de-personas-reid*
*Completed: 2026-08-15*

## Self-Check: PASSED

Ficheros modificados (`backend/pipeline/recognition.py`, `tests/test_recognition_worker.py`) y el fichero de este resumen verificados presentes en disco; los 3 hashes de commit (`f220430`, `4fb505f`, `6c31569`) verificados presentes en el repositorio.
