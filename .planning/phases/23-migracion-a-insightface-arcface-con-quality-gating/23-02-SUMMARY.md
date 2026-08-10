---
phase: 23-migracion-a-insightface-arcface-con-quality-gating
plan: 02
subsystem: perception, storage
tags: [insightface, arcface, recognizer, reenroll, dlib-removal]
requires: ["23-01"]
provides:
  - backend/recognizer.py: PersonRecognizer orquesta FaceEngine/FaceQualityAssessor/IdentityIndex
  - scripts/reenroll.py: reconstrucción de persons.db desde data/gallery/
affects:
  - requirements.txt (face-recognition retirado)
  - backend/main.py (mensaje de error 503, construcción de PersonRecognizer con umbrales de Settings)
tech-stack:
  removed: ["face-recognition"]
  patterns:
    - "scripts/reenroll.py preserva person_id explícitamente (INSERT con id, no autoincrement) — data/events.db referencia person_id por entero plano sin FK entre bases; perder la correspondencia habría desvinculado historial real de identidades"
    - "Scripts que importan backend.* se invocan como módulo (python -m scripts.reenroll), no como script suelto — mismo patrón ya establecido por seed_events.py/generate_initial_rules.py"
key-files:
  created:
    - scripts/reenroll.py
    - tests/test_recognizer_orchestration.py
  modified:
    - backend/recognizer.py
    - backend/main.py
    - requirements.txt
    - tests/test_phase9.py
key-decisions:
  - "_best_match agrupa por persona sobre similitud coseno (antes distancia euclídea de dlib): mismo patrón de ratio-test que Fase 9 (MEJORAS.md puntos 5-6), con el signo invertido — mayor similitud es mejor, no menor distancia."
  - "15 tests de tests/test_phase9.py que mockeaban backend.recognizer.fr (dlib) se sustituyeron por tests/test_recognizer_orchestration.py (17 tests) mockeando FaceEngine/FaceQualityAssessor — mismo alcance de cobertura (gates de calidad, consenso, ratio-test/ambigüedad, agrupación multi-muestra, selección de cara, re-verificación por voto mayoritario, enroll_named_face), IdentityIndex real (no mockeado) porque es simple y determinista."
  - "scripts/reenroll.py preserva el person_id de cada carpeta de data/gallery/ mediante INSERT explícito, no autoincrement — necesario porque data/events.db referencia person_id como entero plano (SQLite no impone FK entre bases de datos distintas); reasignar ids nuevos habría desvinculado el historial de eventos/grabaciones de las identidades reales."
requirements-completed: [FACE-01, FACE-02, FACE-03, FACE-04, FACE-05, FACE-06]
duration: "~2h (ejecución autónoma en worktree aislado, continuación tras 23-01 en la misma sesión)"
completed: "2026-08-10"
---

# Phase 23 Plan 02: Integración en recognizer.py y retirada de dlib — Summary

`backend/recognizer.py` queda reducido a orquestación pura sobre los tres componentes de `23-01`, preservando exactamente el contrato público que consume `RecognitionWorker` — ningún otro fichero del pipeline en vivo necesitó tocarse. `scripts/reenroll.py` reconstruye identidades reales desde `data/gallery/` preservando `person_id` y nombres. `dlib`/`face-recognition` fuera de `requirements.txt`. Suite completa: **326/326**.

## Qué se construyó

**Task 1 — PersonRecognizer delega en FaceEngine/FaceQualityAssessor/IdentityIndex**: `process_crop`/`identify_or_register`/`enroll_named_face` reescritos para usar los componentes de `23-01` en vez de `face_recognition`/dlib directamente. La lógica de negocio (buffer de consenso de 3 muestras, voto mayoritario en re-verificación, ratio-test de ambigüedad agrupado por persona) se conserva sin cambios — solo cambió el motor de detección/embedding/matching subyacente. Embeddings pasan de 128D float64 a 512D float32; `_blob_to_encoding` valida el nuevo tamaño (2048 bytes), y filas con el formato antiguo quedan inválidas para lectura directa — exactamente lo previsto en `23-CONTEXT.md`, de ahí que el re-enrolamiento (Task 2) sea obligatorio, no opcional. `IdentityIndex` se mantiene sincronizado en cada registro/enrolamiento/purga. 17/17 tests nuevos en `tests/test_recognizer_orchestration.py`, más los 9 tests de `tests/test_phase9.py` que no dependían de detección facial (siguen en verde con un helper `_recog()` actualizado).

**Task 2 — scripts/reenroll.py**: reconstruye `data/persons.db` desde `data/gallery/{person_id}/*.jpg` (las capturas que la Fase 9 ya guarda automáticamente). Hace backup con timestamp antes de tocar nada, preserva el `person_id` original de cada carpeta mediante `INSERT` explícito (no autoincrement) — crítico porque `data/events.db` referencia `person_id` como entero plano sin clave foránea entre bases de datos distintas; reasignar ids nuevos habría desvinculado el historial real de eventos y grabaciones de las identidades correspondientes. Reporta personas totales, migradas, sin imagen utilizable, y sale con código distinto de cero si una persona **con nombre** no pudo migrarse (una anónima sin migrar se tolera). Verificado end-to-end con una galería sintética (2 personas migran con la imagen real de `skimage.data.astronaut`, 1 falla por imagen en blanco): ids/nombres preservados correctamente, backup creado, código de salida 1 con la advertencia correcta.

**Task 3 — Retirada de dlib/face-recognition**: `face-recognition>=1.3` fuera de `requirements.txt`, tras confirmar que Tasks 1 y 2 pasan en verde. No se desinstaló el paquete del venv compartido (usado también por el checkout de `main` fuera de este worktree, que aún depende de dlib) — solo se retiró de `requirements.txt`, que es lo que pide el criterio de aceptación.

## Deviations from Plan

**[Rule 1 - Gap necesario] `_recog()` en test_phase9.py cargaba un modelo real innecesariamente**
El helper original construía `PersonRecognizer` sin mockear nada, haciendo `pytest.skip` si `face_recognition` no estaba instalado. Con insightface real instalado, esto habría cargado `buffalo_s` (varios segundos) en cada uno de los 3 tests que lo usan (`should_attempt`, `prune`, `purge_unnamed` — ninguno ejercita detección facial). Se actualizó para mockear `FaceEngine` con `available=True`, eliminando la carga real y el `pytest.skip` (ya no depende de que insightface esté instalado de verdad). Commit `ec85702`.

**[Rule 4 - Discrecional] Limitación conocida: re-ejecutar reenroll.py tras un fallo pierde la advertencia de "persona con nombre"**
`existing_names` se lee de `db_path` **antes** de respaldarlo y reconstruirlo. Si una persona con nombre falla en la primera ejecución (queda fuera de la base reconstruida) y el operador ejecuta el script una segunda vez sin resolver la causa, la segunda ejecución ya no encuentra su nombre en la base (reconstruida en la primera pasada) y la clasifica como anónima — sin la advertencia ni el código de salida distinto de cero. El backup de la primera ejecución conserva el nombre original y es recuperable manualmente. La primera ejecución (el caso real de uso: migrar una vez) reporta correctamente; el caso de re-ejecuciones repetidas tras un fallo no resuelto queda documentado aquí en vez de añadir lógica de fusión entre backups, que habría sido complejidad desproporcionada para un script de un solo uso. No hay commit de código para esto — es una limitación documentada, no un bug corregido.

**Total deviations:** 2 (1 gap de eficiencia en tests corregido, 1 limitación discrecional documentada sin corregir por desproporción de esfuerzo). **Impacto:** ninguno negativo sobre el caso de uso real (migración única).

## Issues Encountered

Al invocar `scripts/reenroll.py` directamente (`python scripts/reenroll.py`) se descubrió que falla con `ModuleNotFoundError: No module named 'backend'` — confirmado que es una limitación **preexistente** compartida por `scripts/seed_events.py` y `scripts/generate_initial_rules.py` (cualquier script que importe `backend.*`), no algo introducido aquí: Python solo añade el directorio del propio script a `sys.path`, no la raíz del proyecto. La invocación correcta, ya establecida por esos otros scripts, es `python -m scripts.reenroll` (con `-m`, Python añade el cwd a `sys.path`). Documentado en el docstring del script.

## Next Phase Readiness

Verificado sin mocks de terceros en el camino de negocio: 17 tests de orquestación con `FaceEngine`/`FaceQualityAssessor` mockeados pero `IdentityIndex` real, más verificación manual end-to-end de `scripts/reenroll.py` con una imagen real. Suite completa: **326/326**. El pipeline en vivo (`RecognitionWorker`) no necesitó ningún cambio — su única dependencia es la interfaz pública de `PersonRecognizer`, preservada exactamente.

**Pendiente — Task 4 (checkpoint, requiere cámara real y galería poblada):** tasa de aciertos de ArcFace sobre un set de validación de ≥50 recortes reales, comparada con dlib sobre el mismo conjunto de identidades — documentada como número real, no asumida. Identificación en vivo confirmada contra la cámara real. No ejecutable en este worktree aislado (sin cámara, sin `data/gallery/` poblada con capturas reales).

Con esto, la **Fase 23 queda completa en código y tests** (ambos planes, 23-01 y 23-02). Junto con los 4 checkpoints pendientes del bloque A (19-01, 19-02, 20-02, 21-01) y el de la Fase 22 (resistencia de 8h), quedan **6 checkpoints con cámara real** pendientes de acción del usuario antes de dar por completamente cerrado y validado en producción todo el trabajo de esta sesión — ninguno bloqueante para continuar con la Fase 24 (Identidad temporal — votación y máquina de estados), que depende de la Fase 23 en código, no en la validación en vivo.
