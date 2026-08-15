---
phase: 25-re-identificaci-n-de-personas-reid
plan: 03
subsystem: perception
tags: [reid, appearance-memory, cosine-similarity, temporal-identity]

requires:
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 01
    provides: "ReIDEngine — embeddings de apariencia 512D L2-normalizados (aun no consumido por este plan)"
  - phase: 25-re-identificaci-n-de-personas-reid
    plan: 02
    provides: "IdentityStateMachine.on_reid_result() — consumidor futuro del candidato que resolve() calcula"

provides:
  - "backend.perception.reid.gallery.TrackGallery — memoria de embeddings de tracks recientes y resolucion de candidato a heredar identidad por apariencia (REID-02/REID-04)"

affects: [25-04, 25-05, 25-06]

tech-stack:
  added: []
  patterns:
    - "Vectores 512D sinteticos con coseno exacto construidos a mano (cos*e_base + sqrt(1-cos^2)*e_other) para testear umbrales de similitud, en vez de np.random (el research de la Fase 25 midio 0,991 de coseno entre dos ruidos independientes con OSNet real — un colapso fuera de distribucion que invalidaria cualquier test de umbral)"
    - "Doble guarda de expiracion (TTL por ventana + cota dura LRU aplicada tambien en el path de escritura, no solo en el mantenimiento) replicada de IdentityStateMachine a una segunda estructura de dominio puro"

key-files:
  created:
    - backend/perception/reid/gallery.py
    - tests/test_track_gallery.py
  modified:
    - tests/test_memory_bounds.py

key-decisions:
  - "resolve() calcula SIEMPRE el candidato real (person_id, similitud), incluso cuando no se hereda por umbral no superado o conflicto: la politica de si aplicar la herencia (modo solo-observacion vs aplicar) vive fuera de TrackGallery, en el flag de RecognitionWorker (25-04) — si resolve() devolviera None en modo observacion se perderia el dato de auditoria del criterio 4"
  - "El umbral de similitud es estricto (sim > threshold, no >=): coherente con la redaccion del criterio 2 del ROADMAP ('similitud > 0.7'), verificado con un test dedicado al caso exacto 0.70"
  - "_enforce_cap() se invoca tanto desde update() como desde prune(): la cota dura de 256 entradas es un 'seguro de vida' (patron de la Fase 22) que actua aunque el mantenimiento periodico no se ejecute a tiempo — verificado con un test especifico que nunca llama a prune()"
  - "Los docstrings de gallery.py y test_track_gallery.py evitan las cadenas literales 'reid_inherit_identity' y 'np.random' (aunque el plan las proponia en su bloque de codigo) para no auto-invalidar los grep de aceptacion del propio plan, que exigen que esas cadenas NO aparezcan en el fichero final — se preservo el significado de cada docstring con una redaccion equivalente"

patterns-established:
  - "Test de cota de memoria duplicado (con y sin prune()) para cualquier estructura con cota dura aplicada en dos puntos de codigo: demuestra que ninguno de los dos caminos depende del otro"

requirements-completed: [REID-02, REID-04]

duration: 20min
completed: 2026-08-13
---

# Phase 25 Plan 03: TrackGallery — memoria de apariencia y resolucion de candidato Summary

**`TrackGallery` (dominio puro, reloj inyectado) implementa las 4 reglas de `resolve()` de REID-02 con producto escalar directo sobre embeddings 512D, mas el gate de intervalo del criterio 5 y una doble guarda de expiracion (TTL de 15 s + cota dura de 256 entradas aplicada tambien desde `update()`)**

## Accomplishments

- `backend/perception/reid/gallery.py`: `TrackGallery` con `needs_embedding()` (gate del criterio 5, espejo de `needs_recognition` de la Fase 24), `update()` (fuerza `float32`, 2 KB/entrada), `resolve()` (las 4 reglas en orden: candidatos con identidad y de otro track, frescura dentro de la ventana de 15 s, similitud maxima por coseno directo `emb @ e.emb`, umbral estricto + comprobacion de conflicto contra `active_identities`) y `prune()`/`_enforce_cap()` (doble guarda TTL + cota dura LRU, calcada de `IdentityStateMachine.on_tick`).
- `resolve()` devuelve siempre `(candidato, similitud)` reales — nunca gatea internamente sobre si la herencia se aplica o solo se audita; esa decision de producto queda para el cableado del worker en `25-04`.
- `tests/test_track_gallery.py`: 12 tests `TEST_*` con vectores 512D construidos a mano (`_vec_at_cosine`) con coseno exacto y controlado — cubren umbral por encima/exacto/por debajo, ventana, conflicto con `active_identities`, no-fusion de dos apariencias distintas (criterio 4), entradas sin identidad, auto-resolucion, intervalo del criterio 5 y las dos ramas de `prune()`. Cero `np.random`, cero imagenes, cero ONNX.
- `tests/test_memory_bounds.py`: 2 tests nuevos (`TEST_track_gallery_bounded`, `TEST_track_gallery_bounded_without_prune`) que verifican la cota de 256 entradas con 10.000 `update()`, con y sin llamada a `prune()`.
- Suite completa verificada: 402/402 (388 previos + 14 nuevos).

## Task Commits

Cada tarea se comprometio atomicamente:

1. **Task 1: `backend/perception/reid/gallery.py` — `TrackGallery`** - `e175420` (feat)
2. **Task 2: `tests/test_track_gallery.py` — criterios 2 y 4 con vectores sinteticos** - `8c971d0` (test)
3. **Task 3: cota de memoria de `TrackGallery` en `tests/test_memory_bounds.py`** - `4b604fd` (test)

## Files Created/Modified

- `backend/perception/reid/gallery.py` - `TrackGallery`: `_GalleryEntry`, `needs_embedding()`, `update()`, `resolve()`, `prune()`, `_enforce_cap()` (158 lineas)
- `tests/test_track_gallery.py` - 12 tests `TEST_*` con vectores 512D de coseno exacto (184 lineas)
- `tests/test_memory_bounds.py` - import de `TrackGallery` + 2 tests de cota (30 lineas insertadas, ningun test previo tocado)

## Decisions Made

Ver `key-decisions` en el frontmatter. La unica decision no anticipada por el plan fue de redaccion, no de arquitectura: el bloque de codigo que el propio plan proponia para los docstrings incluia literalmente las cadenas `reid_inherit_identity` y `np.random`, pero los `acceptance_criteria` del mismo plan (y el `<success_criteria>` de este executor) exigen que esas cadenas NO aparezcan en los ficheros finales. Se reformulo cada docstring para preservar el mensaje sin usar el token literal — sin cambio de comportamiento ni de contrato.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug de coherencia interna del plan] Docstrings con cadenas prohibidas por su propio grep de aceptacion**
- **Encontrado durante:** Task 1 y Task 2, al ejecutar los `grep` de `acceptance_criteria`.
- **Problema:** El bloque de codigo del plan para el docstring de modulo de `gallery.py` incluia literalmente `reid_inherit_identity`, y el docstring de cabecera de `test_track_gallery.py` incluia literalmente `np.random` — ambas cadenas estan explicitamente prohibidas por los `grep` de `acceptance_criteria` del mismo plan (`grep -n "reid_inherit_identity\|inherit_identity"` y `grep -n "np.random"`, ambos deben "no devolver nada").
- **Fix:** Reescritura de los pasajes afectados sin el token literal, conservando el significado (`gallery.py`: "esa politica de producto vive en RecognitionWorker" / "un flag de politica que vive en el worker"; `test_track_gallery.py`: "el generador aleatorio de numpy").
- **Ficheros modificados:** `backend/perception/reid/gallery.py`, `tests/test_track_gallery.py`.
- **Commits:** incluido en `e175420` y `8c971d0` (se corrigio antes del commit, no como commit separado).

## Issues Encountered

Ninguno mas. El resto del plan se ejecuto literalmente segun el bloque de codigo y las 4 reglas de `resolve()` en el orden exacto especificado.

## User Setup Required

None.

## Next Phase Readiness

`TrackGallery` esta lista y verificada en aislamiento (dominio puro, sin ONNX, sin pipeline). `25-04` puede cablear `ReIDEngine` (25-01) + `TrackGallery` (este plan) + `IdentityStateMachine.on_reid_result()` (25-02) dentro de `RecognitionWorker`, incluyendo el flag de politica `reid_inherit_identity` que decide si la herencia calculada por `resolve()` se aplica o solo se audita. Sin deuda pendiente de este plan.

---
*Phase: 25-re-identificaci-n-de-personas-reid*
*Completed: 2026-08-13*

## Self-Check: PASSED

Ficheros creados (`backend/perception/reid/gallery.py`, `tests/test_track_gallery.py`) y los 3 hashes de commit (`e175420`, `8c971d0`, `4b604fd`) verificados presentes en el repositorio.
