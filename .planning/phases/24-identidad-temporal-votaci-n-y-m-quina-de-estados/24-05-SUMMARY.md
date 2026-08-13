---
phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados
plan: 05
subsystem: pipeline
tags: [recognition-worker, wiring, fsm, event-engine, inference-budget]

# Dependency graph
requires:
  - phase: 24-01
    provides: "TemporalVoter, IdentityState, IdentityTransition en backend/perception/face/identity.py"
  - phase: 24-02
    provides: "IdentityStateMachine — needs_recognition, on_face_result, on_active_tracks, on_tick"
  - phase: 24-03
    provides: "PersonRecognizer.process_crop_scored() con el score real"
  - phase: 24-04
    provides: "TrackRegistry.set_identity_state, EventEngine.emit_identity"
provides:
  - "RecognitionWorker cableado a la FSM: needs_recognition() sustituye al gate ciego (FACE-11)"
  - "TrackRegistry.set_frame_ids/frame_ids — set exacto del frame actual, publicado por DetectionWorker (D-05)"
  - "IdentityStateMachine construida fuera de la factoria del supervisor en manager.py, con event_engine cableado"
  - "Criterio 6 (>=70% menos inferencias) medido con baseline real en el mismo test"
affects: [24-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DetectionWorker separa 'publicar estado en el registry' de 'emitir eventos': set_frame_ids ocurre siempre, process_tracks/accumulate_detections solo si hay event_engine"
    - "Tests con EventBus real + hilo de worker: deben ser async def (asyncio_mode=auto) y ceder el control al loop explicitamente (await asyncio.sleep) tras cualquier espera cuyo predicado pueda cumplirse antes del primer await interno de wait_until, o el bus nunca drena la cola hacia el subscriptor de test"

key-files:
  created: []
  modified:
    - backend/pipeline/recognition.py
    - backend/pipeline/tracking.py
    - backend/pipeline/detection.py
    - backend/pipeline/manager.py
    - backend/main.py
    - tests/test_recognition_worker.py
    - tests/test_detection_worker.py

key-decisions:
  - "D-05 (bloqueante, verificado): _sync_identity usa TrackRegistry.frame_ids() (set exacto del frame actual, escrito por DetectionWorker), nunca active_ids() (TTL de 30s de prune()). set_frame_ids() se llama ANTES de la guarda `if event_engine is None: return` en _emit_track_lifecycle -- si quedara detras, la construccion por defecto de DetectionWorker (event_engine=None) dejaria frame_ids() vacio para siempre y cada track CONFIRMED se reportaria como perdido en cada ciclo. Verificado por TEST_frame_ids_published_without_event_engine y por el test end-to-end de recuperacion de track."
  - "D-01: el criterio 6 se mide sobre UNA persona estatica cuyo reconocimiento NUNCA tiene exito (track no confirmado), no sobre un track ya identificado -- ver seccion de mediciones abajo."
  - "D-03: el disparador de confianza baja usa la confianza agregada del TemporalVoter (st.confidence, expuesta via needs_recognition), no TrackState.confidence (la de deteccion de YOLO)."
  - "El test de recuperacion de track por la ruta real (D-05) usa un mock de reconocimiento que solo 've cara' del track fisicamente presente en cada fase (no un MagicMock plano que matchee cualquier track_id): sin esto, el track viejo (mas antiguo, TEMPORARILY_LOST) seguiria ganando el turno de _next_candidate sobre el track nuevo indefinidamente, o revertiria a CONFIRMED el solo antes de que el track nuevo tuviera ocasion de reclamar la identidad via _claim_lost -- ninguno de los dos casos ejercita realmente el camino que D-05 corrige."

requirements-completed: [FACE-08, FACE-09, FACE-10, FACE-11]

# Metrics
duration: 70min
completed: 2026-08-13
---

# Phase 24 Plan 05: Cableado del pipeline de identidad temporal Summary

**`RecognitionWorker` pasa a ser el dueño del ciclo de vida de la identidad: sustituye el gate ciego `person_id is None` por `needs_recognition()` de la FSM (FACE-11), escribe `identity_state` en el registry y publica los eventos de identidad vía `EventEngine`; `manager.py` construye la `IdentityStateMachine` fuera de la factoría del supervisor para que sobreviva a un reinicio del worker; y `DetectionWorker` publica el set exacto de tracks del frame actual (`TrackRegistry.frame_ids()`) para que la detección de tracks perdidos no dependa del TTL de 30 s de `active_ids()` (D-05).**

## Performance

- **Duration:** ~70 min
- **Started:** 2026-08-13
- **Completed:** 2026-08-13
- **Tasks:** 3
- **Files modified:** 7 (0 creados, 7 modificados)

## Accomplishments

- `RecognitionWorker._next_candidate` pregunta a `IdentityStateMachine.needs_recognition()` cuando hay FSM, sustituyendo el reintento indefinido de la Fase 23 sobre tracks que nunca se identifican (FACE-11). Sin `identity_fsm` (parámetro `None`, default) conserva el comportamiento anterior — es el baseline del criterio 6.
- `RecognitionWorker._sync_identity` mantiene la FSM (`on_active_tracks` + `on_tick`) en cada ciclo del bucle, usando `TrackRegistry.frame_ids()` — nunca `active_ids()` (D-05, ver más abajo).
- `stats["face_inferences"]` cuenta inferencias reales completadas (distinto de `face_fps`, que es el objetivo de `AdaptiveRate` aunque no se ejecute ninguna).
- Los eventos de identidad (`PERSON_RECOGNIZED`/`UNKNOWN_PERSON`/`IDENTITY_LOST`) se publican vía `EventEngine.emit_identity` desde el hilo del worker, sin `await`, con manejo de excepciones que nunca mata al hilo.
- `TrackRegistry.set_frame_ids()`/`frame_ids()`: el set exacto de tracks vistos en el frame actual, escrito por `DetectionWorker` en cada ciclo (antes de la guarda de `event_engine`, deliberadamente).
- `manager.py`: `IdentityStateMachine` construida fuera de `_make_recognition`, con 6 parámetros escalares inyectados desde `Settings` vía `main.py`; un reinicio del worker por el `WorkerSupervisor` conserva la instancia de la FSM (`TEST_fsm_survives_worker_restart`).
- Criterio 6 medido con baseline real en la misma ejecución del test (ver mediciones).
- Suite completa: **377/377** (antes 371, +6 tests netos de esta fase).

## Task Commits

Each task was committed atomically:

1. **Task 1: RecognitionWorker toma posesión de la FSM y del gate FACE-11** - `754d8c0` (feat)
2. **Task 2: Cableado en manager.py y main.py, con la FSM fuera de la factoría** - `6b5768c` (feat)
3. **Task 3: Medir el criterio 6 — presupuesto de inferencias con track no confirmado** - `cf773f7` (test)

**Plan metadata:** (pendiente — este commit)

## Escenario del criterio 6 (D-01) y cifras medidas

Decisión bloqueante del usuario: el criterio 6 (≥70 % menos inferencias) se mide sobre un
track **NO confirmado** — una persona estática cuyo reconocimiento nunca tiene éxito (cara
no detectable, calidad insuficiente o match ambiguo). Medir sobre un track ya identificado
no aporta nada: el filtro de la Fase 23 ya hacía 0 inferencias ahí, y esta fase *añade*
revalidación periódica encima.

`TEST_inference_budget_drops_on_unconfirmed_track` (`tests/test_recognition_worker.py`)
ejecuta el mismo `RecognitionWorker` sobre la misma carga (1 track estático, `min_track_age=0`,
`target_fps=20`, `recognizer.process_crop_scored` sin match nunca) durante 1 segundo real,
dos veces: sin FSM (`identity_fsm=None`, comportamiento Fase 23) y con FSM
(`TemporalVoter(window=2, min_votes=2)`, `revalidate_after=10.0`, la ventana de test escalada
manteniendo la proporción ventana/backoff de producción `window=8`/`revalidate_after=120.0`).

Cifras medidas (ejecución real, reproducible con
`pytest tests/test_recognition_worker.py -k inference_budget -q`):

| Escenario | Inferencias en 1 s |
|---|---|
| Baseline (Fase 23, sin FSM) | 16 |
| Con FSM (Fase 24, `needs_recognition`) | 2 |
| Reducción | **87.5 %** (umbral exigido: ≥70 %) |

El test aserta `with_fsm <= baseline * 0.30` con `baseline >= 8` (evita un baseline
degenerado que no mida nada), ejecutado en la misma sesión de test para que la comparación
sea honesta frente a variaciones de máquina.

## Files Created/Modified

- `backend/pipeline/recognition.py` - docstring reescrito, `identity_fsm`/`event_engine` en el constructor, `_next_candidate` con `needs_recognition()`, `_sync_identity`, `_emit_identity`, `_notify_identified`, `process_crop_scored` + `face_inferences`
- `backend/pipeline/tracking.py` - `TrackRegistry.set_frame_ids`/`frame_ids`, docstring de invariante de escritores ampliado
- `backend/pipeline/detection.py` - `_emit_track_lifecycle` publica `set_frame_ids` ANTES de la guarda de `event_engine` (D-05)
- `backend/pipeline/manager.py` - `self.identity_fsm` construida fuera de `_make_recognition`, `event_engine`/`identity_fsm` cableados al `RecognitionWorker`, 6 parámetros escalares en `CameraPipeline.__init__`
- `backend/main.py` - 6 parámetros `identity_*` inyectados desde `Settings` en `camera_manager.add(...)`
- `tests/test_recognition_worker.py` - 5 mocks migrados a `process_crop_scored`/`FaceResult`, `TEST_frame_ids...` (en `test_detection_worker.py`), `TEST_track_recovery_via_real_path_emits_person_recognized_once` (D-05 end-to-end), `TEST_fsm_survives_worker_restart`, `TEST_inference_budget_drops_on_unconfirmed_track` (criterio 6), `TEST_low_identity_confidence_retriggers_recognition` (D-03), `TEST_confirmed_track_emits_person_recognized_once` (FACE-09 end-to-end)
- `tests/test_detection_worker.py` - `TEST_frame_ids_published_without_event_engine`

## Decisions Made

Ver `key-decisions` en el frontmatter. Resumen:
- D-05 (bloqueante): `frame_ids()`, nunca `active_ids()`, y la publicación ocurre siempre, no solo con `event_engine` configurado.
- D-01: escenario del criterio 6 fijado sobre track no confirmado, con baseline real medido en el mismo test.
- D-03: el gate de confianza baja usa la confianza agregada del voter, no la de detección.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] El test de recuperación real (D-05) necesitaba un mock de reconocimiento "consciente del track", no uno plano**
- **Found during:** Task 1, implementando `TEST_track_recovery_via_real_path_emits_person_recognized_once`.
- **Issue:** El pseudocódigo del plan usa `recognizer.process_crop_scored.return_value = _face(7, "Juan", score=0.8)` fijo para todas las llamadas. Como `_next_candidate` elige siempre el track más antiguo entre los que necesitan reconocimiento, y el track viejo (`TEMPORARILY_LOST`) sigue siendo candidato válido (`needs_recognition` devuelve `True` para ese estado), con un mock que "reconoce" a cualquier track_id el track viejo o bien seguía ganando el turno de inferencia sobre el nuevo indefinidamente, o revertía a `CONFIRMED` él solo (mismo `track_id`, rama `TEMPORARILY_LOST` de `on_face_result`) antes de que el track nuevo tuviera ocasión de reclamar la identidad vía `_claim_lost` — en ningún caso se ejercitaba el camino que D-05 corrige.
- **Fix:** El mock solo "ve cara" del track físicamente presente en cada fase (`match_track["id"]`, cambiado explícitamente en cada fase del test) y el `TrackRegistry` suelta el track viejo (`registry.prune(...)`) antes de introducir el nuevo, simulando lo que `DetectionWorker.prune()` haría eventualmente en producción. El plan explícitamente autoriza este ajuste ("el objetivo es que la FSM tenga tiempo de procesar cada fase, no una duración exacta").
- **Files modified:** `tests/test_recognition_worker.py`
- **Commit:** `754d8c0`

**2. [Rule 1 - Bug] Los tests con `EventBus` real + hilo de worker necesitaban ceder el control al loop explícitamente**
- **Found during:** Task 1, el mismo test — `received` quedaba vacío pese a que la FSM sí confirmaba la identidad.
- **Issue:** El helper local `wait_until` (mismo patrón que `tests/test_event_engine.py`/`test_event_bus.py`) sale del bucle sin haber llamado nunca a `await asyncio.sleep(...)` si el predicado ya es cierto en la primera comprobación — habitual aquí porque `_publish_for` (bloqueante) ya deja tiempo de sobra para que el hilo del worker alcance el estado esperado antes de que `wait_until` lo compruebe. Sin ceder el control al loop ni una sola vez, `EventBus._enqueue` (programado vía `call_soon_threadsafe` desde el hilo del worker) nunca se ejecuta, y `received` queda vacío indefinidamente.
- **Fix:** `await asyncio.sleep(0.1)` explícito tras `worker.stop()`, antes de leer `received`, en los tres tests que combinan `EventBus` real con el hilo del worker.
- **Files modified:** `tests/test_recognition_worker.py`
- **Commit:** `754d8c0` (y `cf773f7` para `TEST_confirmed_track_emits_person_recognized_once`)

**3. [Rule 2 - Falta de dato necesario] `TEST_inference_budget_drops_on_unconfirmed_track` necesitaba `registry.set_frame_ids({1})`**
- **Found during:** Task 3.
- **Issue:** Sin publicar `frame_ids()`, el valor por defecto es un set vacío; `_sync_identity` (vía `on_active_tracks`) interpretaría en cada ciclo que el único track del test ha desaparecido, purgando su estado de la FSM y su voter constantemente — el "backoff" del criterio 6 nunca llegaría a activarse y el test mediría otra cosa.
- **Fix:** `registry.set_frame_ids({1})` justo después de crear el track, simulando que `DetectionWorker` lo sigue viendo en cada frame durante todo el test.
- **Files modified:** `tests/test_recognition_worker.py`
- **Commit:** `cf773f7`

---

**Total deviations:** 3 auto-fixed (todas Rule 1/2, correcciones de test necesarias para que los escenarios midieran realmente lo que el plan pedía; ningún cambio de diseño en el código de producción respecto al plan).

## Nota sobre un criterio de aceptación del plan más amplio de lo previsto

El acceptance criterion `grep -n "self._registry.active_ids()" backend/pipeline/recognition.py`
no devuelve nada" (y el mismo grep en `success_criteria` del prompt del ejecutor) es más
amplio de lo que el propio plan pide: `_maybe_prune` (paso 10 de la Task 1, explícitamente
"no tocar") sigue usando `registry.active_ids()` — con razón, para limpiar cachés del
`PersonRecognizer` de tracks que ya no existen en el registry, un propósito distinto al de
D-05 (que solo afecta a `_sync_identity`, la detección de tracks perdidos por la FSM). Se
mantiene `_maybe_prune` sin tocar, tal como el plan indica explícitamente, documentando aquí
la discrepancia textual en vez de romper una función que el propio plan protege.

## Issues Encountered

Ninguno bloqueante.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Pipeline de identidad temporal funcional de extremo a extremo: `RecognitionWorker` decide,
  vota, confirma, revalida y pierde identidad; `TrackRegistry` expone el estado; `EventEngine`
  publica los tres eventos de identidad; `manager.py`/`main.py` lo cablean todo desde
  `Settings`.
- Queda `24-06` (último plan de la fase) para cerrar la Fase 24.
- Sin bloqueos.

---
*Phase: 24-identidad-temporal-votaci-n-y-m-quina-de-estados*
*Completed: 2026-08-13*

## Self-Check: PASSED

Ficheros modificados y los 3 commits de tareas (`754d8c0`, `6b5768c`, `cf773f7`) verificados en disco/`git log`.
