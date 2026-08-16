---
phase: 26-an-lisis-de-comportamiento
plan: 05
subsystem: events
tags: [rule-engine, behavior, yaml, phase-gate, requirements]

requires:
  - phase: 26-01
    provides: "BehaviorAnalyzer con los 4 BehaviorKind (LOITERING, RUNNING, IMMOBILE, CROWD_DETECTED)"
  - phase: 26-03
    provides: "EventEngine.emit_behavior() con duration_s literal en el payload"
  - phase: 26-04
    provides: "Cableado end-to-end en DetectionWorker/manager.py/main.py"
provides:
  - "tests/test_rule_engine.py: prueba end-to-end (YAML real + load_rules + evaluate) de que los 4 eventos de comportamiento son usables como when.event sin cambios en el RuleEngine (criterio 5)"
  - "Trazabilidad de los 5 criterios de exito del ROADMAP de la Fase 26 a comandos pytest -k que pasan"
  - "BEH-01..BEH-05 confirmados [x] en REQUIREMENTS.md"
affects: [27]

tech-stack:
  added: []
  patterns:
    - "Camino real para validar un YAML de reglas: escribir en tmp_path + load_rules(str(path)) + RuleEngine.evaluate(), nunca Rule.model_validate() a secas"
    - "Prueba negativa explicita del nombre de clave equivocado como regresion documentada (When.duration_gte lee event.payload['duration_s'] literal)"

key-files:
  created: []
  modified:
    - tests/test_rule_engine.py
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/STATE.md

key-decisions:
  - "BEHAVIOR_RULES_YAML vive SOLO en el test, nunca se anade a config/rules.yaml — que alertas quiere el usuario es decision suya (T-26-17), y scripts/generate_initial_rules.py sobrescribiria el fichero de todos modos"
  - "El criterio 2 (seis trayectorias) se reparte entre los 4 tests de trayectoria de 26-01 (comportamiento) y los tests ya existentes de EventEngine.process_zone (2 trayectorias de zona, propiedad de la Fase 19) — division intencional, no un hueco"
  - "El checkpoint de calibracion de umbrales con camara real (Task 3) se difiere explicitamente — 8o checkpoint manual, no bloquea avanzar a la Fase 27"

requirements-completed: [BEH-01, BEH-02, BEH-03, BEH-04, BEH-05]

duration: ~20min
completed: 2026-08-16
---

# Phase 26 Plan 05: Criterio 5 (YAML real) + puerta de fase Summary

**Tres tests end-to-end demuestran que los cuatro eventos de comportamiento cargan como `when.event` desde un YAML real sin tocar el `RuleEngine`, y los 5 criterios de éxito de la Fase 26 quedan trazados a comandos `pytest -k` verdes — Fase 26 completa (5/5 planes).**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 (2 ejecutados, 1 checkpoint diferido)
- **Files modified:** 4 (tests/test_rule_engine.py, .planning/ROADMAP.md, .planning/REQUIREMENTS.md, .planning/STATE.md)

## Accomplishments

- `BEHAVIOR_RULES_YAML` (4 reglas, una por `BehaviorKind`) + 3 tests nuevos en `tests/test_rule_engine.py` que recorren el camino real: `tmp_path` + `load_rules(str(path))` + `RuleEngine.evaluate()`
- `TEST_behavior_duration_gte_reads_duration_s` incluye la prueba de regresión explícita del pitfall de naming: `payload={"duration": 130.0}` (clave equivocada) NO dispara la regla
- `backend/events/rules.py` y `config/rules.yaml` sin cambios — el criterio 5 se cumple con cero código
- Suite completa 454/454 (451 previos + 3 nuevos)
- Los 5 criterios de éxito del ROADMAP de la Fase 26 trazados a comandos `pytest -k` que pasan (tabla abajo)
- BEH-01..BEH-05 confirmados `[x]` en `REQUIREMENTS.md` (ya lo estaban desde planes anteriores)
- `ROADMAP.md` y `STATE.md` actualizados: Fase 26 completa, 5/5 planes

## Task Commits

1. **Task 1: Criterio 5 — reglas de comportamiento cargadas desde YAML real** — `0112e5e` (test)
2. **Task 2: Puerta de fase — suite completa y trazabilidad** — commit de metadata (ROADMAP/REQUIREMENTS/STATE), ver commit final de este plan
3. **Task 3: checkpoint humano** — diferido, sin commit de código (ver sección Checkpoint abajo)

## Trazabilidad de los 5 criterios del ROADMAP

| # | Criterio | Comando | Resultado |
|---|---|---|---|
| 1 | Se emiten LOITERING, RUNNING, IMMOBILE, CROWD_DETECTED, ZONE_ENTERED y ZONE_EXITED con umbrales configurables | `pytest tests/test_behavior_analyzer.py tests/test_config.py tests/test_event_engine.py -k "behavior or loiter or crowd or immobile or running or zone" -q` | 29 passed |
| 2 | Seis trayectorias sintéticas producen exactamente el evento esperado y ninguno más | `pytest tests/test_behavior_analyzer.py -k trajectory -q` + `pytest tests/test_event_engine.py -k "zone_dwell or zone_transitions" -q` | 4 passed + 4 passed |
| 3 | Cada evento incluye en payload las magnitudes que lo justifican | `pytest tests/test_behavior_analyzer.py -k payload -q` + `pytest tests/test_event_engine.py -k emit_behavior -q` | 1 passed + 3 passed |
| 4 | El historial por track está acotado y no crece con el tiempo de sesión | `pytest tests/test_memory_bounds.py -k "behavior or zone_entry" -q` | 3 passed |
| 5 | Los eventos de comportamiento son usables como `when.event` en rules.yaml sin cambios en el RuleEngine | `pytest tests/test_rule_engine.py -k behavior -q` | 3 passed |
| — | Sin regresión | `pytest tests/ -q` | **454 passed** |

**Nota sobre el criterio 2:** se reparte a propósito en dos comandos. Cuatro de las seis
trayectorias (LOITERING, RUNNING, IMMOBILE, CROWD) viven en el dominio puro y están
cubiertas por los 4 tests `-k trajectory` de `26-01`. Las otras dos (ZONE_ENTERED,
ZONE_EXITED) son propiedad de `EventEngine.process_zone` desde la Fase 19 — el
`test_event_engine.py -k "zone_dwell or zone_transitions"` verifica esas dos vías,
no reimplementadas dentro de `BehaviorAnalyzer` para no duplicar cada evento de zona
(26-CONTEXT.md H-2). La división no es un hueco de cobertura, es la frontera de dominio
correcta.

## Files Created/Modified

- `tests/test_rule_engine.py` — `BEHAVIOR_RULES_YAML` + 3 tests `TEST_behavior_*`
- `.planning/ROADMAP.md` — Fase 26 marcada completa (checkbox + 5/5 planes), `26-05-PLAN.md` marcado `[x]`
- `.planning/REQUIREMENTS.md` — BEH-01..BEH-05 confirmados `[x]` (ya lo estaban)
- `.planning/STATE.md` — Current Position, tabla de fases, Test Coverage, Accumulated Context (6 decisiones), Session Continuity, Siguiente paso

## Decisions Made

Ver `key-decisions` en el frontmatter. Las seis decisiones clave acumuladas de toda la
Fase 26 (ya registradas por planes anteriores, resumidas aquí para el cierre de fase):

1. El problema del historial de 120 s se disuelve con agregados incrementales O(1) en vez
   de ampliar `history_len` (584 B/track medidos frente a 141,8 KB si se hubiera ampliado
   a 1000; `backend/pipeline/tracking.py` no se tocó en toda la fase).
2. Los CUATRO comportamientos llevan latch por episodio, no solo CROWD — sin él, una
   persona parada 10 min generaría miles de eventos IMMOBILE; `debounce_secs` de
   `rules.yaml` no sustituye al latch porque actúa después de persistir y difundir.
3. `analyze()` devuelve `list[BehaviorFinding]`, no `list[Event]` (D-3, corrige SPEC §5.7)
   — `perception/` no conoce `camera_id` ni el reloj de pared.
4. Semántica de zonas: LOITERING cae a escena implícita (`zone_id=None`) sin zonas
   configuradas salvo `loiter_require_zone=True` (D-02); LOITERING e IMMOBILE coexisten
   (D-03); con zonas solapadas se emite un finding por zona (D-04).
5. La clave del payload es `duration_s` literal porque `rules.py:88-91` la lee así para
   `duration_gte` — cualquier otro nombre rompe el criterio 5 en silencio (verificado con
   test de regresión explícito en este plan).
6. Los 4 comportamientos se quedan en `Severity.INFO` por defecto (D-01, cambio cero) —
   subirlos a WARNING habría activado la subida automática de clips a Google Drive.

## Deviations from Plan

None - plan executed exactly as written. `BEHAVIOR_RULES_YAML` y los 3 tests se
implementaron literalmente según la acción especificada. `REQUIREMENTS.md` ya tenía
BEH-01..BEH-05 marcados `[x]` desde planes anteriores (confirmado, no fue necesario
editar el fichero).

## Checkpoint (Task 3): calibración de umbrales — DIFERIDO

**Estado:** DIFERIDO (8º checkpoint manual con cámara real pendiente, se suma a los 7
checkpoints anteriores: 19-01 Task 5, 19-02 Task 5, 20-02 Task 4, 21-01 Task 5,
22-01 Task 4, 23-02 Task 4, 25-06 Task 2).

**Motivo:** esta sesión no tiene acceso a la cámara Tapo C212 real. Los umbrales
`run_speed_px_s=350`, `loiter_radius_px=80` e `immobile_radius_px=20` (SPEC_v2.md §5.7)
son los defaults por diseño y ya están cubiertos por tests deterministas con
trayectorias sintéticas (`tests/test_behavior_analyzer.py`). Su calibración fina
requiere ~15 min de footage real para ajustar por perspectiva y distancia de la escena.

**No bloquea:**
- El cierre de la Fase 26 en código/tests (los 5 criterios de éxito ya están verdes).
- El avance a la Fase 27 (`/gsd:plan-phase 27`).
- Los umbrales son configurables en caliente por `.env` y `behavior_enabled=False`
  desactiva la vía entera si molestara en producción.

**Cuándo cerrarlo:** cuando haya acceso a la cámara real, seguir `how-to-verify` del
`26-05-PLAN.md` Task 3 (arrancar el sistema, observar el WebSocket ~15 min, comprobar
RUNNING/IMMOBILE/LOITERING/CROWD_DETECTED uno a uno, anotar los valores finales en
`.env`).

## Issues Encountered

Ninguno. El venv del proyecto vive fuera del worktree
(`F:/Documentos/IA/Proyecto_Camara/.venv`); se usó la ruta absoluta indicada en el plan
para todos los comandos de test.

## User Setup Required

None - no external service configuration required en este plan. Pendiente (no
bloqueante): la calibración manual de umbrales con cámara real, documentada arriba.

## Next Phase Readiness

- Fase 26 completa: 5/5 planes (26-01..26-05). BEH-01..BEH-05 cerrados.
- Los 5 criterios de éxito del ROADMAP verificados uno a uno con comando `pytest -k`.
- Siguiente paso: `/gsd:plan-phase 27` (Multi-clase y contexto de escena, depende de la
  Fase 26 ya completa).

---
*Phase: 26-an-lisis-de-comportamiento*
*Completed: 2026-08-16*
