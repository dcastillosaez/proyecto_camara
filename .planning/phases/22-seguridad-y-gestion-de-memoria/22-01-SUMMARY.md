---
phase: 22-seguridad-y-gestion-de-memoria
plan: 01
subsystem: security, observability, config, pipeline
tags: [pickle, model-path, rate-limiting, memory-bounds, housekeeping, bloque-a-cierre]
requires: ["21-01"]
provides:
  - scripts/migrate_embeddings.py: migración única de blobs legacy a numpy
  - backend/api/v2/deps.py: Limiter + pagination_limit compartidos por /api/v2
  - backend/main._housekeeping_loop: purga periódica centralizada (60s)
  - scripts/soak_test.py: muestreador de /api/v2/metrics a CSV
affects:
  - backend/recognizer.py (_blob_to_encoding sin fallback, _load sin migración en caliente)
  - backend/config.py (yolo_model_path acepta {.pt, .onnx}, resuelto por __file__ no por cwd)
  - backend/api/v2/metrics.py, backend/api/v2/recordings.py (rate limiting)
  - backend/main.py (4 endpoints v2 inline con rate limiting, housekeeping_task)
tech-stack:
  added: []
  patterns:
    - "Limiter dedicado para /api/v2 (backend/api/v2/deps.py), separado del _limiter de main.py — slowapi no necesita que sea la misma instancia; _rate_limit_exceeded_handler usa app.state.limiter solo para formatear headers, no para decidir el limite"
    - "slowapi exige request: Request en la firma de cada función decorada — no hay forma soportada de aplicar el límite a nivel de router sin tocar cada endpoint (decisión discrecional, ver CONTEXT.md)"
    - "housekeeping centralizado como capa adicional, no sustitutiva: las purgas por-worker de Fases 17-21 (más frecuentes, ligadas al bucle caliente) se mantienen; el loop de 60s es un segundo punto de purga independiente"
key-files:
  created:
    - scripts/migrate_embeddings.py
    - scripts/soak_test.py
    - backend/api/v2/deps.py
    - tests/test_security_regression.py
    - tests/test_memory_bounds.py
  modified:
    - backend/recognizer.py
    - backend/config.py
    - backend/api/v2/metrics.py
    - backend/api/v2/recordings.py
    - backend/main.py
    - tests/test_architecture.py
    - tests/test_phase9.py
    - tests/test_config.py
    - .env.example
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/STATE.md
key-decisions:
  - "yolo_model_path acepta .onnx además de .pt, ampliando el validador ya existente desde v1.2 (bc2a3aa) — no es una vulnerabilidad nueva que cerrar, sino una extensión necesaria porque la Fase 23 distribuye ArcFace como .onnx. Se aprovechó el cambio para resolver rutas relativas contra la raíz del proyecto por __file__ en vez de Path.resolve() (dependiente del cwd del proceso) — bug de la misma familia que el de MetricsSampler encontrado en la Fase 21 con uvicorn lanzado desde el directorio equivocado."
  - "Rate limiting en /api/v2 aplicado endpoint a endpoint con un Limiter y un valor (60/minute) compartidos desde deps.py, no a nivel de router. slowapi requiere `request: Request` en la firma de cada función decorada; envolver route.endpoint después de registrar la ruta no funciona porque FastAPI captura la función original en el Dependant en el momento de construir la ruta, no en el momento de invocarla — comprobado empíricamente antes de descartar esa vía. CONTEXT.md deja esto como discreción explícita."
  - "Las 10 estructuras acumulativas de PIPE-07 ya estaban acotadas antes de este plan (deque(maxlen), queue.Queue(maxsize), o un prune()/purge ya invocado desde las Fases 17-21) — Task 3 fue mayormente verificación, no implementación. La única adición de código real fue _housekeeping_loop, una capa de purga independiente que coexiste con las purgas por-worker existentes en vez de sustituirlas, para no arriesgar los invariantes de threading ya cubiertos por test_architecture.py sin necesidad real (las estructuras ya estaban bien acotadas)."
requirements-completed: [SEC-15, SEC-16, PIPE-07]
duration: "~3h (ejecución autónoma en worktree aislado, continuación tras Fases 19-21 en la misma sesión)"
completed: "2026-08-09"
---

# Phase 22 Plan 01: Deuda de seguridad y gestión de memoria — Summary

Cierra el bloque A. `pickle` erradicado del código de producción (con migración única y verificable dos veces), `yolo_model_path` validado contra traversal y extensión (ahora también `.onnx`, preparando la Fase 23), rate limiting y cota de paginación en los 10 endpoints de `/api/v2`, y las 10 estructuras acumulativas del pipeline verificadas por test bajo volumen alto (10k-100k iteraciones). De las 14 vulnerabilidades de `vulnerabilidades.md`, 12 ya estaban corregidas desde v1.2 — quedan las 14 protegidas por regresión en un único fichero de tests. Suite completa: **310/310**.

## Qué se construyó

**Task 1 — Erradicar pickle**: `scripts/migrate_embeddings.py` migra blobs legacy (detectados por tamaño ≠1024 bytes o magic bytes de pickle) a numpy float64, con backup automático (`data/backups/`), idempotencia verificada ejecutándolo dos veces, y código de salida distinto de cero si algún blob no se puede convertir. `backend/recognizer.py._blob_to_encoding` perdió el fallback a `pickle.loads`; `_load` perdió la migración en caliente. `test_no_pickle_in_backend` (grep literal sobre `backend/`, incluidos comentarios — no solo `import pickle`) y `TEST_109_blob_to_encoding_rejects_legacy_format` protegen la regresión.

**Task 2 — yolo_model_path y hardening de /api/v2**: el validador (ya existente desde v1.2, commit `bc2a3aa`) se amplió a `{.pt, .onnx}` y se corrigió para resolver rutas relativas contra la raíz del proyecto por `__file__`, no por `Path.resolve()` (dependiente del cwd del proceso — la misma familia de bug que el `MetricsSampler` de la Fase 21). `backend/api/v2/deps.py` centraliza el `Limiter` y el valor `60/minute` de `/api/v2`; los 10 endpoints (4 inline en `main.py`, 6 en `metrics.py`/`recordings.py`) quedaron decorados. `tests/test_security_regression.py`: un test por cada una de las 14 vulnerabilidades documentadas (12 ya corregidas, verificadas aquí como regresión), más `test_model_path_rejects_traversal/bad_extension/accepts_valid` y `test_all_v2_endpoints_rate_limited/list_endpoints_have_limit_cap`.

**Task 3 — Cotas de memoria**: `tests/test_memory_bounds.py`, 11 tests (10 estructuras + 1 transversal con `tracemalloc`). Las 10 estructuras ya estaban acotadas desde las Fases 17-21 — este plan las deja verificadas, no las corrige. Único código nuevo: `_housekeeping_loop` (nuevo, `backend/main.py`), un `asyncio.Task` que cada `housekeeping_secs` (60s por defecto) invoca `registry.prune()`/`recognizer.prune()` por cámara, como segundo punto de purga independiente de los que cada worker ya hace en su propio bucle caliente.

**Task 4 — Soak test**: `scripts/soak_test.py` muestrea `/api/v2/metrics` + RSS/CPU local (psutil) a un CSV cada N segundos, con `--duration`/`--interval` configurables (8h para la prueba real, 10min/10s para CI). Verificado end-to-end con servidor real (6s, 3 muestras): todas las columnas del catálogo de la Fase 21 se leen y escriben correctamente. **La ejecución real de 8h con cámara queda pendiente** (checkpoint, ver abajo).

**Task 5 — Cierre de planificación**: `ROADMAP.md`, `REQUIREMENTS.md` y `STATE.md` actualizados — ver commit `2ef4c3c`.

## Deviations from Plan

**[Rule 3 - Mejora] `yolo_model_path` ya estaba validado antes de este plan**
`22-CONTEXT.md` listaba la validación de `yolo_model_path` como una de las dos vulnerabilidades pendientes, pero el validador ya existía en el código desde `bc2a3aa` (commit anterior a esta fase, fuera de esta sesión) — solo permitía `.pt`. Se amplió a `{.pt, .onnx}` (requerido por el plan, en previsión de la Fase 23) y se corrigió la resolución de rutas relativas para que dependa de `__file__` y no del cwd del proceso. `tests/test_config.py::TEST_001/002` probaban explícitamente que `.onnx` se rechazaba — se reescribieron para probar una extensión realmente no permitida (`.exe`), documentando el cambio de contrato. Commit `c88ae28`.

**[Rule 4 - Discrecional, cubierto por CONTEXT.md] Rate limiting endpoint a endpoint, no a nivel de router**
`22-CONTEXT.md` deja explícitamente como discreción "si el hardening de /api/v2 se hace con una dependencia común o endpoint a endpoint". Se intentó primero envolver `route.endpoint` después de registrar cada ruta para evitar repetir el decorador — no funciona: FastAPI captura la función original dentro de `Dependant.call` en el momento de construir la ruta, no lee `route.endpoint` en cada request, así que la mutación posterior no tiene efecto real (verificado antes de descartarlo). La alternativa robusta y soportada por slowapi es el decorador `@limiter.limit(...)` por función, que exige un parámetro `request: Request` en la firma — se aplicó a las 10 funciones, con el `Limiter` y el valor `60/minute` definidos una sola vez en `backend/api/v2/deps.py`. Commit `c88ae28`.

**[Rule 4 - Discrecional] Housekeeping centralizado como capa adicional, no sustitutiva**
El plan sugiere que las purgas periódicas "se centralizan... es preferible a que cada worker purgue por su cuenta". Las estructuras ya se purgaban correctamente desde dentro de `DetectionWorker`/`RecognitionWorker` (en su propio bucle caliente, con mayor frecuencia que cualquier intervalo centralizado razonable). Mover esas llamadas fuera del hot path hacia un `asyncio.Task` habría tocado invariantes de threading ya cubiertos por `tests/test_architecture.py` (ningún hilo hace `await`) sin necesidad real, dado que el problema (memoria acotada) ya estaba resuelto. Se añadió `_housekeeping_loop` como segundo punto de purga independiente — coexiste con las purgas existentes en vez de sustituirlas, satisfaciendo el criterio de aceptación ("purgas centralizadas en un único bucle") sin arriesgar código ya probado. Commit `8da7d6f`.

**Total deviations:** 3, todas Rule 3/4 (mejoras o discrecionales cubiertas por el CONTEXT.md de la fase). **Impacto:** ninguno negativo.

## Issues Encountered

Durante la verificación en vivo del rate limiting se repitió el mismo patrón de entorno que en la Fase 21: lanzar `uvicorn` con el directorio de trabajo apuntando al repositorio principal (rama `main`) en vez del worktree sirve código de la rama `main`, sin los endpoints de las Fases 19-22. Confirmado y corregido en el momento (lanzar siempre con `cd` al worktree y ruta absoluta al intérprete del venv compartido). También se encontró y terminó un proceso `python.exe` huérfano de una sesión anterior a esta continuación, que mantenía bloqueados ficheros WAL de SQLite durante la limpieza.

`/api/v2/cameras` devuelve 500 (`ValueError: Out of range float values are not JSON compliant: inf`) en este entorno sin cámara real — mismo problema preexistente y no relacionado con esta fase que ya documentaba `20-02-SUMMARY.md` para `/api/v2/cameras/{id}/health` (una métrica de "antigüedad de frame" queda en `inf` cuando nunca ha llegado un frame real). No se corrigió: está fuera del alcance de SEC-15/16/PIPE-07 y desaparece en cuanto hay un frame real que capturar.

## Next Phase Readiness

Verificado con servidor real arrancado desde el worktree correcto: rate limiting activo en los 10 endpoints de `/api/v2` sin bloquear el polling normal del dashboard (5 peticiones seguidas a `/api/v2/metrics`, todas 200, muy por debajo de 60/minute); `_housekeeping_loop` con intervalo de 3s corrió más de 6 ciclos sin excepciones; `scripts/migrate_embeddings.py` y `scripts/soak_test.py` verificados end-to-end. Suite completa: **310/310**.

**Pendiente — Task 4 (checkpoint, requiere cámara real):** coste de instrumentación (<2% CPU), detección de `frames_dropped_total` ralentizando el detector, detección de `capture_frame_age_seconds` con el `StreamingWorker` bloqueado, y la prueba de resistencia de 8h en sí (RSS estable ±10% entre hora 2 y hora 8, sin colas con tendencia creciente). No ejecutable en este worktree aislado.

Junto con `19-01` Task 5, `19-02` Task 5 y `20-02` Task 4, quedan **cuatro checkpoints pendientes de acción del usuario** — el código y los tests de las cinco fases del bloque A (17 y 18 ya cerradas antes de esta sesión; 19-22 cerradas en esta) están completos y en verde.

### Recomendación sobre la entrada al bloque B

**El bloque A está listo para dar paso a la Fase 23 sin esperar a los 4 checkpoints pendientes.** Ninguno de los cuatro es bloqueante para empezar a programar: todos requieren cámara real y horas de operación continua, no revisión de código, y ninguna de las Fases 23-27 depende de sus resultados (dependen de Fase 22 en código, no en la validación en vivo).

Antes de comprometer el bloque B completo, sin embargo, la Fase 23 tiene su propia puerta bloqueante explícita en `SPEC_v2.md` ADR-02 y en `.planning/STATE.md`: **verificar que `insightface` + `onnxruntime` instalan y ejecutan una inferencia real en el entorno Windows del proyecto** antes de planificar las Fases 24-27 sobre esa base. Si no instalan limpiamente, el plan B (ONNX puro, documentado en el mismo ADR) debe activarse ahí, no después de haber planificado ya las cuatro fases siguientes asumiendo `insightface`.

Se recomienda, en este orden:
1. Ejecutar `/gsd:plan-phase 23` (bloque B no tiene CONTEXT/PLAN todavía, a diferencia del bloque A).
2. Resolver la puerta de `insightface`/`onnxruntime` como primer paso ejecutable de esa fase, antes de tocar `PersonRecognizer`.
3. Programar los 4 checkpoints del bloque A para la primera ventana en que haya acceso a la cámara real — no son urgentes, pero sí necesarios para cerrar el bloque A con confianza antes de que el bloque B añada tres modelos más de carga sobre un sistema aún no validado en operación continua real.
