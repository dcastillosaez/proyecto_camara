---
phase: 25-re-identificaci-n-de-personas-reid
plan: 05
subsystem: perception
tags: [reid, config, pydantic-settings, pipeline-wiring, worker-supervisor]

requires:
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 01
    provides: "ReIDEngine — embeddings de apariencia 512D L2-normalizados"
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 03
    provides: "TrackGallery — memoria de apariencia con inherit_window/similarity_threshold/interval/max_entries"
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 04
    provides: "RecognitionWorker con via ReID cableada (reid_engine/reid_gallery/reid_inherit)"

provides:
  - "7 parametros reid_* en backend/config.py con defaults locked de SPEC_v2.md §5.6 y reid_inherit_identity=False como fail-safe"
  - "validate_reid_model_path: extension permitida + contencion en _PROJECT_ROOT (SEC-16, T-25-16)"
  - "validate_reid_params: rangos que protegen los criterios 2 y 5 (T-25-18)"
  - "CameraPipeline construye ReIDEngine/TrackGallery fuera de la factoria del supervisor: sobreviven a un reinicio del worker"
  - "backend/main.py propaga los 7 settings al pipeline con mapeo explicito kwarg <- setting"

affects: [25-06]

tech-stack:
  added: []
  patterns:
    - "Motor + galeria construidos junto a la FSM, fuera de _make_recognition, mismo patron que Fase 24 establecio para IdentityStateMachine — un reinicio del worker por WorkerSupervisor no vacia estado de dominio"
    - "reid_enabled=False deja self.reid_engine/self.reid_gallery en None y el worker recibe None en esos kwargs: la via ReID queda no-op sin ramas nuevas en RecognitionWorker"

key-files:
  created: []
  modified:
    - backend/config.py
    - tests/test_config.py
    - backend/pipeline/manager.py
    - tests/test_recognition_worker.py
    - backend/main.py

key-decisions:
  - "reid_inherit_window_secs (15s) deliberadamente mas corta que identity_lost_ttl_secs (30s, Fase 24): la apariencia es menos fiable que la votacion facial y debe caducar antes"
  - "reid_inherit_identity=False por defecto: ReID calcula y registra la decision de herencia sin aplicarla, para auditar falsos positivos con datos reales antes de activarla en produccion (T-25-17, ASVS V14)"
  - "validate_reid_model_path NO comprueba que el fichero exista: la ausencia del modelo es un caso soportado (ReIDEngine.available=False), no un error de configuracion — verificado renombrando el modelo y comprobando que backend.main importa igual"

patterns-established: []

requirements-completed: [REID-01, REID-02, REID-03, REID-04]

duration: ~10min
completed: 2026-08-15
---

# Phase 25 Plan 05: Configuracion y cableado de produccion de ReID Summary

**7 parametros `reid_*` en `Settings` con validadores de rango/ruta (SEC-16), y `CameraPipeline` construyendo `ReIDEngine`/`TrackGallery` fuera de la factoria del supervisor para que sobrevivan a un reinicio del worker — la via ReID de 25-04 queda bajo configuracion real y arrancada desde `main.py`**

## Performance

- **Duration:** ~10 min
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- `backend/config.py`: bloque `# --- Re-identificacion por apariencia (Fase 25 — REID-01..REID-04) ---` con los 7 parametros y sus defaults locked (`reid_inherit_identity=False` como fail-safe), `validate_reid_model_path` (extension + `is_relative_to(_PROJECT_ROOT)`) y `validate_reid_params` (rangos independientes del bloque de identidad de la Fase 24).
- `CameraPipeline.__init__` acepta los 7 kwargs `reid_*`; `self.reid_engine`/`self.reid_gallery` se construyen junto a `self.identity_fsm`, fuera de `_make_recognition`, e inyectados en cada reconstruccion del worker via `reid_engine=`/`reid_gallery=`/`reid_inherit=`.
- `backend/main.py` propaga los 7 settings a `camera_manager.add()` con el mapeo explicito (`reid_inherit_window=settings.reid_inherit_window_secs`, `reid_inherit=settings.reid_inherit_identity`, etc.) — nombres de kwarg y de setting no siempre coinciden, igual que ya pasaba con `identity_lost_ttl`.
- Verificado que la app importa igual con y sin `models/reid/osnet_x0_25_msmt17_dyn.onnx` presente (degradacion graciosa, T-25-19).
- 4 tests nuevos en `test_config.py` (defaults, umbral fuera de rango, parametros temporales/cota, extension+traversal del modelo) y 2 en `test_recognition_worker.py` (supervivencia de motor/galeria a reinicio de worker, `reid_enabled=False` deja el worker sin galeria).
- Suite completa: **413/413**.

## Task Commits

Cada tarea se comprometio atomicamente:

1. **Task 1: 7 parametros reid_* + validadores en backend/config.py** - `38c197d` (feat)
2. **Task 2: CameraPipeline construye ReIDEngine y TrackGallery fuera de la factoria** - `c71220f` (feat)
3. **Task 3: backend/main.py pasa settings.reid_* al pipeline** - `6382dd2` (feat)

## Files Created/Modified

- `backend/config.py` - 7 parametros `reid_*`, `validate_reid_model_path`, `validate_reid_params`
- `tests/test_config.py` - 4 tests `TEST_reid_*`
- `backend/pipeline/manager.py` - imports de `ReIDEngine`/`TrackGallery`, kwargs `reid_*` en `CameraPipeline.__init__`, construccion fuera de `_make_recognition`, inyeccion en la factoria
- `tests/test_recognition_worker.py` - `TEST_reid_engine_and_gallery_survive_worker_restart`, `TEST_reid_disabled_leaves_worker_without_gallery`
- `backend/main.py` - 7 kwargs `reid_*` en `camera_manager.add()` con mapeo explicito

## Decisions Made

Ver `key-decisions` en el frontmatter. Todas ya estaban fijadas por el plan (adversarialmente revisado); no hubo decisiones nuevas durante la ejecucion.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. Los kwargs de `RecognitionWorker` (`reid_engine`/`reid_gallery`/`reid_inherit`) y los constructores de `ReIDEngine`/`TrackGallery` ya existian tal cual desde 25-01/25-03/25-04, sin necesidad de ajuste.

## Issues Encountered

None.

## User Setup Required

None - no hay configuracion de servicio externo. Los defaults ya son operativos; activar `REID_INHERIT_IDENTITY=true` en `.env` es una decision de producto pendiente para cuando se audite la tasa de falsos positivos con datos reales (fuera de alcance de este plan).

## Next Phase Readiness

La via ReID esta completa end-to-end: motor + galeria + parametros + arranque real. `reid_enabled=True` y `reid_inherit_identity=False` por defecto significa que en produccion ReID ya calcula, cuenta y expone `reid_inferences`/`reid_matches`/`reid_inherited`/`reid_conflicts` via `/api/v2/cameras/{id}/health`, pero no altera identidades hasta que el operador active `reid_inherit_identity` explicitamente. Sin deuda pendiente de este plan.

---
*Phase: 25-re-identificaci-n-de-personas-reid*
*Completed: 2026-08-15*

## Self-Check: PASSED

Ficheros modificados (`backend/config.py`, `tests/test_config.py`, `backend/pipeline/manager.py`, `tests/test_recognition_worker.py`, `backend/main.py`) verificados presentes en disco; los 3 hashes de commit (`38c197d`, `c71220f`, `6382dd2`) verificados presentes en el repositorio con `git log --oneline`.
