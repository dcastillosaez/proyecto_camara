---
phase: 26-an-lisis-de-comportamiento
plan: 03
subsystem: events
tags: [event-engine, behavior, zones, dwell-time, sqlite, websocket]

requires:
  - phase: 26-01
    provides: "BehaviorKind/BehaviorFinding (dominio puro) con magnitudes() para el payload"
provides:
  - "EventEngine.emit_behavior(): traduce los 4 BehaviorKind al EventType del catalogo, con severidad INFO por defecto"
  - "EventEngine._zone_entry_at: memoria de entrada por (zona, track) para calcular duration_s"
  - "process_zone(now_monotonic=...): ZONE_EXITED lleva duration_s (clave literal, leida por rules.py)"
affects: [26-04, 26-05]

tech-stack:
  added: []
  patterns:
    - "Tabla estatica de traduccion dict[Enum, EventType] a nivel de modulo (mismo patron que _identity_event_type, pero total y 1:1)"
    - "Parametro aditivo al final de una firma existente para no romper el unico llamador posicional"
    - "pop() dentro del mismo bucle que emite el evento de salida como politica de cota de memoria"

key-files:
  created: []
  modified:
    - backend/events/engine.py
    - tests/test_event_engine.py
    - tests/test_memory_bounds.py

key-decisions:
  - "emit_behavior() nunca pasa severity= explicita, para que el @model_validator de Event aplique el default INFO del catalogo (D-01) y los comportamientos no crucen upload_min_severity=warning"
  - "now_monotonic va al final de la firma de process_zone (no reemplaza captured_at/processed_at, que son conceptos privados de latencia OBS-03) para no ser sensible a saltos de reloj de pared por NTP/cambio de hora"
  - "duration_s es la clave literal del payload (no duration/dwell_s/elapsed) porque rules.py:88-91 la lee tal cual para duration_gte"

requirements-completed: [BEH-04]

duration: ~20min
completed: 2026-08-16
---

# Phase 26 Plan 03: EventEngine.emit_behavior() + duration_s en ZONE_EXITED Summary

**`EventEngine.emit_behavior()` traduce los 4 `BehaviorKind` al catalogo de eventos con severidad INFO fija, y `process_zone()` calcula `duration_s` de permanencia en zona via un nuevo dict acotado `_zone_entry_at`.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-08-16
- **Tasks:** 3/3
- **Files modified:** 2 (`backend/events/engine.py`, `tests/test_event_engine.py`) + 1 test-only (`tests/test_memory_bounds.py`)

## Accomplishments
- `_BEHAVIOR_EVENT_TYPE` + `emit_behavior()`: los 4 `BehaviorKind` (LOITERING, RUNNING, IMMOBILE, CROWD) se traducen a su `EventType` del catalogo (Fase 19), con `payload=finding.magnitudes()` y sin `severity=` explicita (severidad INFO por defecto, D-01)
- `process_zone(now_monotonic=...)`: `ZONE_EXITED` lleva `duration_s` cuando se pasa el reloj monotonico; sin el, el comportamiento es identico al de antes de este plan
- `EventEngine._zone_entry_at` queda acotado por el `pop()` en el mismo bucle que emite `ZONE_EXITED` — verificado con 10.000 entradas/salidas efimeras en dos zonas solapadas
- `backend/pipeline/tracking.py` y `backend/events/types.py` sin cambios (verificado con `git diff --stat`)

## Task Commits

1. **Task 1: emit_behavior() y la tabla de traduccion al catalogo** - `658af26` (feat)
2. **Task 2: Tiempo de permanencia en ZONE_EXITED (BEH-04)** - `b5b40f0` (feat)
3. **Task 3: Cota de _zone_entry_at (criterio 4, segunda estructura)** - `f7406fe` (test)

**Plan metadata:** (este commit)

_Nota: los tests de cada task se escribieron y verificaron junto con la implementacion antes de cada commit; se optó por un commit atomico por task (test+feat combinados) en vez de commits RED/GREEN separados, porque las Tasks 1 y 2 modifican los mismos dos ficheros y separar por hunks no aportaba trazabilidad adicional._

## Files Created/Modified
- `backend/events/engine.py` - import de `BehaviorFinding`/`BehaviorKind`, `_BEHAVIOR_EVENT_TYPE`, `emit_behavior()`, `_zone_entry_at` y `now_monotonic` en `process_zone()`
- `tests/test_event_engine.py` - 3 tests `TEST_emit_behavior_*` + 3 tests `TEST_zone_dwell_*`
- `tests/test_memory_bounds.py` - `TEST_zone_entry_at_bounded` (import de `EventEngine`/`asyncio` añadidos)

## Decisions Made
Ver `key-decisions` en el frontmatter. Sin desviaciones respecto al plan: los 3 tasks se ejecutaron tal como estaban escritos, incluida la ubicacion exacta de `now_monotonic` al final de la firma y la clave literal `duration_s`.

## Deviations from Plan

None - plan ejecutado tal cual estaba escrito. El unico ajuste fue de forma (commits atomicos combinados test+feat por task en lugar de RED/GREEN separados), no de contenido — documentado arriba en "Task Commits".

## Issues Encountered

Ninguno. `EventBus.publish_threadsafe()` usa `loop.call_soon_threadsafe(...)`, que no requiere un loop en marcha para programar el callback — el test sincrono `TEST_zone_entry_at_bounded` construye `EventBus(loop=asyncio.new_event_loop())` sin arrancarlo, y como el `pop()` de `_zone_entry_at` ocurre dentro de `process_zone()` (antes de llegar a `_publish`/`_enqueue`), el test verifica la cota de memoria sin necesitar que el bus entregue el evento.

## Next Phase Readiness

`EventEngine.emit_behavior()` y `process_zone(now_monotonic=...)` son la API completa que necesita `26-04` (cableado en `DetectionWorker`/`manager.py`/`main.py`) para invocar el analizador de comportamiento y pasarle el reloj monotonico real. Sin bloqueos.

---
*Phase: 26-an-lisis-de-comportamiento*
*Completed: 2026-08-16*

## Self-Check: PASSED

Todos los ficheros modificados y los 3 hashes de commit (`658af26`, `b5b40f0`, `f7406fe`) verificados presentes en el repositorio.
