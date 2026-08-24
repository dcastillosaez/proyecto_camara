---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 02
subsystem: api
tags: [fastapi, pydantic, config-api, audit-trail, sqlalchemy]

# Dependency graph
requires:
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 01
    provides: "config_schema.py: FieldDef/Group/Section/ALL_SECTIONS (112 campos), all_fields(), field_by_key(), resolve_origin(), build_candidate_settings(); ConfigRepo.delete()"
provides:
  - "backend/api/v2/config.py: GET/PUT /api/v2/config, POST /api/v2/config/{section}/restore, configure()"
  - "Router registrado en el lifespan de main.py — unico endpoint HTTP nuevo de la Fase 32"
affects: [32-03, 32-04, 32-05, 32-06, 32-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Validacion de lote en un solo pase (sin cortocircuitar en el primer error): per-field primero, invariantes cruzados de Settings despues, TODOS los errores 422 juntos (D-10)"
    - "Persistir-antes-de-propagar: ConfigRepo.set() se llama SIEMPRE antes de tocar CameraPipeline, mismo orden que detection.py de la Fase 27, verificado con attach_mock"
    - "App FastAPI local en el test file (no backend.main.app) para probar el router de forma aislada antes de que exista su wiring en main.py — mismo Limiter compartido de deps.py replicado con app.state.limiter"

key-files:
  created:
    - backend/api/v2/config.py
    - tests/test_config_api.py
  modified:
    - backend/main.py

key-decisions:
  - "El campo 'field' de los errores 422 de invariantes cruzados de Settings es el KEY DE SECCION (body.section), no el nombre del campo concreto: verificado empiricamente que pydantic v2 model_validator(mode='after') que hace 'raise ValueError(...)' produce err['loc'] == () (vacio), asi que el fallback del propio algoritmo del plan (fkey = body.section si loc esta vacio) es lo que realmente se ejecuta. El ejemplo jsonc de <interfaces> en la PLAN.md muestra field:'identity_min_votes', pero eso es ilustrativo del contrato de forma, no literal para errores cruzados — se siguio el algoritmo explicito del plan (que sí es normativo), no el ejemplo."
  - "Tests contra una app FastAPI local (fixture propia en tests/test_config_api.py) en vez de backend.main.app para las Tasks 1-2, replicando app.state.limiter + el exception handler de slowapi: permite TDD del router aislado del wiring de main.py, que llega en la Task 3 con su propio test dedicado (TEST_main_imports_with_config_router_registered)."
  - "_validate_range() cubre bool/int/float/enum/list_int/list_str/time/str con los rangos EXACTOS del esquema de 32-01 (min/max/enum_values/max_length) — sin inventar limites nuevos, discrecion explicita del CONTEXT para los campos sin min/max declarado en Settings."

patterns-established:
  - "Todo router HTTP nuevo que module cambios de configuracion debe: (1) persistir antes de propagar, (2) devolver TODOS los errores de un lote 422 juntos, (3) emitir exactamente un CONFIG_CHANGED por operacion con éxito, nunca uno por campo."

requirements-completed: [SET-01, SET-02, SET-03, SET-04]  # OPS-18/19/20 avanzan (el router ya soporta arbol/senalizacion/restaurar) pero no se cierran: su redaccion exige interfaz visible ("se edita desde la interfaz", "claramente senalizados", "permite restaurar"), que llega con 32-04..32-06 y se marca en la puerta de fase 32-08 — mismo patron que OPS-07/08/09 en la Fase 30

# Metrics
duration: ~35min
completed: 2026-08-23
---

# Phase 32 Plan 02: Router GET/PUT/restore de configuración Summary

**`backend/api/v2/config.py` (296 líneas) expone el único endpoint HTTP nuevo de la Fase 32 — GET resuelve origen/aplicación en caliente/secreto sobre los 112 campos de `Settings`, PUT valida el lote completo y persiste antes de propagar, y `restore` borra overrides por sección — con 22 tests nuevos y la suite completa en 711 passed.**

## Performance

- **Duration:** ~35 min (17 min de lectura/contexto, resto TDD de las 3 tasks)
- **Tasks:** 3 (con ciclo RED/GREEN por task, 6 commits de código + 1 de SUMMARY)
- **Files modified:** 3 (2 creados, 1 modificado)

## Accomplishments
- `GET /api/v2/config` devuelve las 8 secciones con `label`/`hint`/rango/`origin`/`applies`
  por campo; ningún campo `secret=True` lleva la clave `value` en ningún origen; `camera_url`
  siempre enmascarada vía `mask_rtsp_url()`.
- `PUT /api/v2/config` valida el lote completo en un solo pase — rango por campo primero,
  invariantes cruzados de `Settings` después (`build_candidate_settings`, que re-ejecuta los
  `model_validator`) — devolviendo TODOS los errores 422 juntos, nunca solo el primero.
- Persistir-antes-de-propagar verificado con `attach_mock`: `ConfigRepo.set()` se llama SIEMPRE
  antes que `CameraPipeline.set_detection_classes()`/`set_process_size()`, únicas 3 rutas
  reales de aplicación en caliente (`yolo_classes`, `process_width`, `process_height`).
- `yolo_classes` reutiliza literalmente las 4 comprobaciones de `detection.py:88-105` (vacía,
  rango COCO, duplicados, clase 0 obligatoria) — no una redacción paralela.
- `process_width` sin `process_height` en el mismo PUT aplica `set_process_size(nuevo_ancho,
  alto_efectivo_actual)`, nunca `set_process_size(w, 0)`.
- Exactamente un `CONFIG_CHANGED` por `PUT`/`restore` con éxito, con diff completo; ningún
  campo `secret` puede llegar nunca al diff (rechazo 422 antes de tocar `valid_changes`).
- `POST /{section}/restore` borra solo las filas `runtime` de esa sección — nunca escribe
  defaults encima — con `restored_count` y `CONFIG_CHANGED(restored=True)` solo si hubo algo
  que borrar.
- Router registrado en el lifespan de `main.py` (junto a `detection_v2_module`) e
  `include_router` (junto a `detection_v2_router`); `import backend.main` verificado sin error.

## Task Commits

1. **Task 1: GET /api/v2/config** - `6973668` (test) + `54137b6` (feat)
2. **Task 2: PUT /api/v2/config** - `de4fe7c` (test) + `468b1cf` (feat)
3. **Task 3: restore + wiring en main.py** - `5ada587` (test) + `b4199f6` (feat)

## Files Created/Modified
- `backend/api/v2/config.py` - GET/PUT/restore (296 líneas): `_field_payload`, `_validate_range`,
  `_validate_yolo_classes`, `configure()`, `_config_repo()` (mismo molde de `detection.py`)
- `tests/test_config_api.py` - 22 tests nuevos (5 GET, 13 PUT, 3 restore, 1 wiring de main.py)
- `backend/main.py` - `config_v2_module.configure(camera_manager, event_engine)` en el lifespan
  + `app.include_router(config_v2_router)`

## Decisions Made
- **`field` de errores cruzados = clave de sección, no nombre de campo**: verificado
  empíricamente (`.venv/Scripts/python.exe -c "..."`) que `model_validator(mode="after")` de
  `Settings` que hace `raise ValueError(...)` produce `err["loc"] == ()`, así que el algoritmo
  literal del plan (`fkey = str(err["loc"][0]) if err["loc"] else body.section`) resuelve
  siempre al `body.section` para estos casos — el ejemplo jsonc de `<interfaces>` en la
  PLAN.md (`"field": "identity_min_votes"`) es ilustrativo del contrato de forma, no literal
  para errores cruzados; se siguió el algoritmo explícito (normativo) en vez del ejemplo.
- **Tests contra una app FastAPI local, no `backend.main.app`**, para las Tasks 1-2: permite
  TDD del router aislado del wiring de `main.py`, que solo llega en la Task 3 con su propio
  test dedicado (`TEST_main_imports_with_config_router_registered`, que sí usa
  `backend.main.app`). Replica `app.state.limiter` + el exception handler de `slowapi` para
  que `@limiter.limit()` funcione igual que en producción.
- **`_validate_range()` cubre bool/int/float/enum/list_int/list_str/time/str** con los rangos
  exactos del esquema de 32-01 (`min`/`max`/`enum_values`/`max_length`), sin inventar límites
  nuevos — discreción explícita del `32-CONTEXT.md` para los campos sin rango declarado en
  `Settings`.

## Deviations from Plan

None de comportamiento — el algoritmo de PUT/GET/restore se implementó tal como lo
especificaba el `<action>` de cada task, prácticamente literal. La única aclaración
documentada arriba (campo de errores cruzados = sección, no nombre de campo) es una
consecuencia mecánica de seguir el propio pseudocódigo del plan contra el comportamiento
real de `pydantic` v2, no una desviación de lo pedido.

## Issues Encountered

Ninguno bloqueante. Un ajuste de test: `TEST_get_config_secret_field_never_leaks_value`
inicialmente asumía `rtsp_pass` vacío, pero el `.env` real del proyecto tiene credenciales
RTSP configuradas — se corrigió mockeando `get_settings()` con `model_copy(update={...})`
para hacer el test determinista sin depender del `.env` real de la máquina de desarrollo.

## Next Phase Readiness

- `GET/PUT/restore /api/v2/config` está listo para que las vistas de frontend (32-04
  "Cámara" con la barra de ajustes rápidos OPS-17, 32-05/32-06 "Ajustes") sean clientes puros
  sin lógica de validación propia (D-04) — consumen el contrato JSON documentado en
  `<interfaces>` de `32-02-PLAN.md` literalmente.
- SET-01 (edición en caliente vía HTTP), SET-02 (precedencia documentada y testeada),
  SET-03 (422 legible por HTTP) y SET-04 (auditoría con diff) quedan cerrados — SET-01 y
  SET-03 que 32-01 había dejado avanzando sin cerrar, se cierran aquí. OPS-18, OPS-19 y
  OPS-20 avanzan (el router ya soporta árbol/señalización/restaurar) pero no se cierran:
  su redacción exige interfaz visible, que llega con 32-04..32-06 y se marca en la puerta
  de fase 32-08 — mismo patrón que OPS-07/08/09 en la Fase 30.
- Suite completa verde: **711 passed, 2 skipped** (+22 sobre el cierre de 32-01).

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-23*

## Self-Check: PASSED

- FOUND: backend/api/v2/config.py
- FOUND: tests/test_config_api.py
- FOUND: .planning/phases/32-vista-de-c-mara-y-configuraci-n-visual/32-02-SUMMARY.md
- FOUND commit: 6973668
- FOUND commit: 54137b6
- FOUND commit: de4fe7c
- FOUND commit: 468b1cf
- FOUND commit: 5ada587
- FOUND commit: b4199f6
