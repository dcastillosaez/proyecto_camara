---
phase: 27-multi-clase-y-contexto-de-escena
plan: 01
subsystem: perception
tags: [python, dataclasses, domain-model, object-detection, tdd]

# Dependency graph
requires:
  - phase: 26-comportamiento
    provides: "BehaviorAnalyzer como molde de patron (dominio puro, reloj inyectado, latch por episodio, doble guarda TTL+LRU)"
provides:
  - "ObjectAnalyzer (backend/perception/objects.py): dominio puro que decide OBJECT_LEFT/OBJECT_REMOVED"
  - "Contratos LOCKED: ObjectKind, ObjectObservation, PersonObservation, ObjectFinding — consumidos por 27-05 (emit_object) y 27-06 (cableado)"
affects: ["27-05", "27-06"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Doble guarda de warmup (nace en escena al arranque) + zona de exclusion, ambas en memoria, antes de crear el agregado de un track"
    - "stable derivado de gone_secs sin parametro nuevo: el minimo tiempo quieto para poder declararse 'establecido' es la misma ventana de gracia con la que se declara la desaparicion"
    - "Asimetria LEFT (radio negativo, pasarse de grande suprime) vs REMOVED (radio positivo, pasarse de grande es peligroso)"

key-files:
  created:
    - backend/perception/objects.py
    - tests/test_object_analyzer.py
  modified:
    - tests/test_memory_bounds.py

key-decisions:
  - "ObjectObservation/PersonObservation en vez de dicts paralelos (behavior.py): cada objeto arrastra 6 atributos y varios dicts paralelos serian un criadero de bugs de desincronizacion"
  - "prune() devuelve list[ObjectFinding] (a diferencia de BehaviorAnalyzer.prune que devuelve None): OBJECT_REMOVED se decide en prune(), no en analyze(), para exigir gone_secs de gracia contra oclusiones de un frame"
  - "_ignored es dict[int, float], no set: necesita last_seen para su propio TTL y LRU"

patterns-established:
  - "Pattern 3 del research: radio de persona = max(person_radius_px, person_radius_ratio * height_px) — corrige la escala segun distancia a camara"

requirements-completed: [BEH-07]

duration: ~35min
completed: 2026-08-17
---

# Phase 27 Plan 01: ObjectAnalyzer Summary

**`ObjectAnalyzer` (dominio puro, reloj inyectado) decide `OBJECT_LEFT`/`OBJECT_REMOVED` a partir de posiciones de objetos y personas, con guarda de warmup, zona de exclusion y gracia de oclusion, siguiendo el molde de `BehaviorAnalyzer` de la Fase 26.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3/3 completados
- **Files modified:** 3 (1 creado en produccion, 2 de test)

## Accomplishments
- `backend/perception/objects.py` (320 lineas): `ObjectKind`, `ObjectObservation`, `PersonObservation`, `ObjectFinding` (con `magnitudes()` que omite `None`) y `ObjectAnalyzer` con `analyze()`/`prune()`/`_enforce_cap()`
- `tests/test_object_analyzer.py`: 11 tests `TEST_*` deterministas cubriendo los 9 comportamientos de BEH-07 (LEFT tras umbral, latch por episodio, igualdad de conjunto, supresion por persona cercana, guardas de warmup y zona de exclusion, REMOVED con/sin persona, gracia de oclusion, payload sin `None`)
- `tests/test_memory_bounds.py`: 3 tests nuevos que prueban la doble guarda de memoria (TTL + cota dura LRU) con y sin `prune()`, incluida la estructura `_ignored` (nueva de esta fase)

## Task Commits

1. **Task 1: backend/perception/objects.py — dominio puro** - `45fbca8` (feat)
2. **Task 2: tests/test_object_analyzer.py — 9 comportamientos de BEH-07** - `e6ff192` (test)
3. **Task 3: tests/test_memory_bounds.py — par de cota de memoria** - `3e627e7` (test)

## Files Created/Modified
- `backend/perception/objects.py` - `ObjectAnalyzer` y tipos de dominio (nuevo)
- `tests/test_object_analyzer.py` - 11 tests `TEST_*` de BEH-07 (nuevo)
- `tests/test_memory_bounds.py` - +3 tests `TEST_object_analyzer_*` (modificado)

## Decisions Made
- Ver `key-decisions` en frontmatter. Ninguna decision arquitectural nueva fuera de las ya fijadas por el contrato LOCKED del plan (interfaces de `27-01-PLAN.md`).

## Deviations from Plan

None - plan ejecutado tal como estaba escrito. El unico ajuste fue en el diseno de los tests (no en el codigo de produccion): el helper `_still_run` de `tests/test_object_analyzer.py` necesitaba "primar" el analizador con un frame vacio en `t=0.0` antes de que naciera el objeto de la trayectoria, para que la guarda de warmup (que se fija en la PRIMERA llamada que recibe el analizador, no en el primer frame de cada test) no confundiera un objeto genuinamente nuevo con mobiliario del arranque. Esto es una consecuencia directa y esperada del contrato de warmup del propio plan, no un cambio de comportamiento del `ObjectAnalyzer`.

## Issues Encountered
Al escribir los tests, la primera version fallaba 6/11 porque todas las trayectorias arrancaban en `t=0.0` (el warmup del analizador siempre se activa en su primerisima llamada). Se resolvio con el patron `prime=True` descrito arriba: solo `TEST_warmup_furniture` usa `prime=False` a proposito, porque es exactamente el caso que prueba.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
`ObjectAnalyzer` y sus 4 tipos LOCKED (`ObjectKind`, `ObjectObservation`, `PersonObservation`, `ObjectFinding`) quedan listos para que `27-05` construya `EventEngine.emit_object()` y `27-06` cablee el analizador en `DetectionWorker`/`manager.py`. Sin bloqueos.

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED
