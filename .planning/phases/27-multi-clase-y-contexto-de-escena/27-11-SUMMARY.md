---
phase: 27-multi-clase-y-contexto-de-escena
plan: 11
subsystem: events
tags: [pytest, phase-gate, requirements, bytetrack, object-detection, scene-context]

requires:
  - phase: 27-08
    provides: "Overlay de objetos trackeados en magenta sobre el feed MJPEG"
  - phase: 27-09
    provides: "GET /api/v2/analytics/context (BEH-08/BEH-09)"
  - phase: 27-10
    provides: "Panel 'Clases detectadas' en el dashboard, checkboxes contra GET/PUT /api/v2/detection/classes"
provides:
  - "Trazabilidad de los 6 criterios de exito del ROADMAP de la Fase 27 a comandos pytest -k que pasan"
  - "BEH-06, BEH-08 y BEH-09 marcados [x] en REQUIREMENTS.md (BEH-07 ya lo estaba desde 27-01)"
  - "ROADMAP.md y STATE.md reflejan la Fase 27 completa: 11/11 planes"
  - "Checkpoint de calibracion con camara real diferido explicitamente (9no checkpoint manual)"
affects: [28]

tech-stack:
  added: []
  patterns:
    - "Puerta de fase: reejecutar la suite completa, trazar cada criterio del ROADMAP a un comando pytest -k concreto, marcar requisitos [x] solo si la suite esta verde"

key-files:
  created: []
  modified:
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/STATE.md

key-decisions:
  - "El checkpoint de calibracion de object_person_radius_px y de la tasa de falsos positivos de OBJECT_LEFT se difiere explicitamente (9no checkpoint manual, sin camara en esta sesion) — no bloquea el cierre de la Fase 27 en codigo/tests ni el avance a la Fase 28"
  - "sv.ByteTrack es class-agnostic: la particion por clase antes del tracker y un ObjectTracker dedicado son obligatorios, no una optimizacion — verificado con TEST_bytetrack_ids_do_not_migrate_between_classes"
  - "Los objetos nunca entran en TrackRegistry: su estado vive en self._object_boxes bajo self._lock, mismo patron que _zone_states"

requirements-completed: [BEH-06, BEH-07, BEH-08, BEH-09]

duration: ~15min
completed: 2026-08-17
---

# Phase 27 Plan 11: Puerta de fase — trazabilidad de los 6 criterios + checkpoint de calibración Summary

**La suite completa de la Fase 27 se reejecuta verde (519/519, sin cambios de código) y los 6 criterios de éxito del ROADMAP quedan trazados a comandos `pytest -k` que pasan — Fase 27 completa (11/11 planes), BEH-06..BEH-09 cerrados.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2 (1 ejecutado, 1 checkpoint diferido)
- **Files modified:** 3 (.planning/ROADMAP.md, .planning/REQUIREMENTS.md, .planning/STATE.md)

## Accomplishments

- Suite completa reejecutada: `pytest tests/ -q` → **519/519 passed**, sin cambios de código, sin `skip` nuevos
- Los 6 criterios de éxito del ROADMAP de la Fase 27 trazados a comandos `pytest -k` que pasan (tabla abajo)
- Regresión ByteTrack (riesgo de primer orden de la fase, `27-03`) verde: partición por clase antes del tracker, objetos nunca en `TrackRegistry`
- `REQUIREMENTS.md`: BEH-06, BEH-08 y BEH-09 marcados `[x]` (BEH-07 ya lo estaba desde `27-01`)
- `ROADMAP.md`: Fase 27 marcada `[x]` en el bloque B, "11/11 plans complete (6 waves)" y los 11 planes marcados `[x]` en el detalle
- `STATE.md` actualizado: Current Position, tabla de fases (11/22 completas, ~50%), Accumulated Context (decisiones acumuladas de la Fase 27), Session Continuity
- Checkpoint de calibración con cámara real diferido explícitamente (9º checkpoint manual)

## Task Commits

1. **Task 1: Suite completa + trazabilidad de los 6 criterios de éxito** — commit de metadata (ROADMAP/REQUIREMENTS/STATE), ver commit final de este plan
2. **Task 2: checkpoint humano (calibración con cámara real)** — diferido, sin commit de código (ver sección Checkpoint abajo)

## Trazabilidad de los 6 criterios del ROADMAP

| # | Criterio | Comando | Resultado |
|---|---|---|---|
| 1 | Clases configurables desde la UI | `pytest tests/test_detection_config_api.py -q` | 8 passed |
| 2 | `OBJECT_LEFT` tras 60 s inmóvil sin persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_left -q` | 3 passed, 8 deselected |
| 3 | `OBJECT_REMOVED` al desaparecer con persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_removed -q` | 1 passed, 10 deselected |
| 4 | `/api/v2/analytics/context` con media móvil de 7 días | `pytest tests/test_scene_context.py -q` | 7 passed |
| 5 | Un único `OBJECT_LEFT`; con persona presente, ninguno | `pytest tests/test_object_analyzer.py -k "TEST_object_left_latched or TEST_no_left_with_person" -q` | 2 passed, 9 deselected |
| 6 | 6 clases no suben la latencia > 15 % | `pytest tests/test_detector.py -k TEST_multiclass_latency -q` | 1 passed, 11 deselected |
| — | Regresión ByteTrack (riesgo de primer orden, `27-03`) | `pytest tests/test_detection_worker.py -k "object_class_does_not_reach_line_zone or objects_not_in_registry or bytetrack_ids_do_not_migrate" -q` | 3 passed, 30 deselected |
| — | Sin regresión | `pytest tests/ -q` | **519 passed** |

Todos los nombres de test usados coinciden literalmente con los fijados por los planes
01-10 (`27-01-SUMMARY.md`..`27-10-SUMMARY.md`); no hizo falta ajustar ningún comando de
`27-VALIDATION.md`.

**Criterio 1:** cubierto por el backend (`test_detection_config_api.py`, GET catálogo +
4 rechazos 400 + PUT feliz + orden persistir-antes-de-propagar). La evidencia visual
(marcar una clase y verla en el MJPEG) está cableada end-to-end desde `27-08`/`27-10`
pero requiere el checkpoint manual del Task 2 para verificarse con cámara real.

## Files Created/Modified

- `.planning/ROADMAP.md` — Fase 27 marcada `[x]` en el bloque B ("Bloque B — Inteligencia
  artificial"), "11/11 plans complete (6 waves)" y los 11 planes `[x]` en el detalle
- `.planning/REQUIREMENTS.md` — BEH-06, BEH-08, BEH-09 marcados `[x]` (BEH-07 ya lo estaba)
- `.planning/STATE.md` — Current Position, progreso v2.0 (11/22, ~50%), tabla de las 22
  fases (fila 27), Accumulated Context (8 decisiones acumuladas de la fase resumidas),
  lista de checkpoints manuales (9º), Session Continuity, Siguiente paso

## Decisions Made

Ver `key-decisions` en el frontmatter y el detalle completo en `STATE.md` §
Accumulated Context. Las decisiones clave acumuladas de toda la Fase 27, resumidas aquí
para el cierre de fase:

1. `sv.ByteTrack` es class-agnostic (reproducido en `27-RESEARCH.md` Q4 y en
   `TEST_bytetrack_ids_do_not_migrate_between_classes`) — la partición por clase ANTES
   del tracker y un `ObjectTracker` dedicado son obligatorios, no una optimización, o un
   track de objeto puede transferir su id a una persona solapada y contaminar el
   `LineZone` de la Fase 4.
2. Los objetos nunca entran en `TrackRegistry` — su estado vive en `self._object_boxes`
   bajo `self._lock`, mismo patrón que `_zone_states` (escritor único: hilo de
   detección; lectores: `get_object_boxes`/`get_object_stats`, copias defensivas).
3. `self.objects`/`self.object_tracker` (y el resto del estado de la fase) se construyen
   en `CameraPipeline.__init__` ANTES de `_make_detection`, fuera de la factoría que
   registra el `WorkerSupervisor` — cuarto precedente tras la FSM (Fase 24), la galería
   ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26): reconstruir dentro de la factoría
   reabriría la ventana de warmup en cada reinicio del worker.
4. La BD (`app_config`) gana sobre `YOLO_CLASSES` al arrancar; una fila `[]` persistida
   se trata como ausente, no como "no detectes nada", para no dejar el sistema ciego en
   silencio.
5. `person` (clase 0) siempre viaja forzada/activa y bloqueada en el catálogo
   (`LOCKED_CLASS_IDS={0}`) — ningún PUT puede desactivarla, decisión cerrada con el
   usuario.
6. `OBJECT_LEFT` se mantiene en `Severity.WARNING` (decisión del usuario) — cruza
   `upload_min_severity="warning"` y sube clips a Drive desde el primer evento; exige
   calibrar `object_person_radius_px` con cámara real antes de operar desatendido
   (checkpoint de este plan).
7. El nivel de actividad de BEH-09 se normaliza a tasa por minuto en ambos lados
   (baseline y "ahora") para no sesgar `"low"` al principio de cada hora, y cae a
   `"unknown"` con menos de `context_min_sample_days` de historial.
8. `yolo_model_path` por defecto corregido a `yolo26n.pt` (D-03), alineado con
   CLAUDE.md — se aplicó en `27-02` porque el criterio 6 (latencia con 6 clases) se mide
   sobre la ruta de post-proceso NMS-free de `yolo26n.pt`.

## Deviations from Plan

None - plan executed exactly as written. La suite ya estaba verde antes de este plan
(519/519 heredado de `27-09`/`27-10`, sin cambios de código en ninguno de los dos). No
hizo falta ningún fix de código; el único trabajo de este plan es trazabilidad y cierre
de documentación de planificación.

## Checkpoint (Task 2): calibración con cámara real — DIFERIDO

**Estado:** DIFERIDO (9º checkpoint manual con cámara real pendiente, se suma a los 8
checkpoints anteriores: 19-01 Task 5, 19-02 Task 5, 20-02 Task 4, 21-01 Task 5,
22-01 Task 4, 23-02 Task 4, 25-06 Task 2, 26-05 Task 3).

**Motivo:** esta sesión no tiene acceso a la cámara Tapo C212 real.
`object_person_radius_px=150.0` (1,9× `loiter_radius_px`, ~media altura de persona a
media distancia en un frame de 1280×720 — `27-RESEARCH.md` Assumption A1/A7) es una
distancia razonada, no medida contra una escena real. Lo mismo aplica a
`object_warmup_secs=10.0` (A2) y `object_gone_secs=3.0` (A3). Los 6 criterios
deterministas ya están verdes con trayectorias sintéticas.

**Riesgo operativo concreto:** `OBJECT_LEFT` es `Severity.WARNING` (decisión del
usuario, T-27-19) y cruza `upload_min_severity="warning"` — cada falso positivo sube
automáticamente un clip a Google Drive y consume cuota (Pitfall 12 de
`27-RESEARCH.md`).

**No bloquea:**
- El cierre de la Fase 27 en código/tests (los 6 criterios de éxito ya están verdes).
- El avance a la Fase 28 (`/gsd:plan-phase 28`).
- Los umbrales son configurables en caliente por `.env`; `objects_enabled=False`
  desactiva la vía entera si molestara operativamente; `UPLOAD_MIN_SEVERITY=critical`
  es una válvula de escape sin tocar código si la tasa de falsos positivos es alta.

**Cuándo cerrarlo:** cuando haya acceso a la cámara real, seguir `how-to-verify` del
`27-11-PLAN.md` Task 2 — marcar una clase de objeto en el panel, comprobar el overlay
magenta, dejar un objeto quieto 60 s y verificar exactamente un `OBJECT_LEFT` + subida
del clip a Drive, medir la distancia real a la que deja de emitirse `OBJECT_LEFT` con
una persona cerca, y anotar ~15-20 min de tasa de falsos positivos. Ajustar
`OBJECT_PERSON_RADIUS_PX`/`OBJECT_WARMUP_SECS`/`OBJECT_GONE_SECS` en `.env` si procede.

## Issues Encountered

Ninguno. El venv del proyecto vive fuera del worktree
(`F:/Documentos/IA/Proyecto_Camara/.venv`); se usó la ruta absoluta indicada en el plan
para todos los comandos de test.

## User Setup Required

None - no external service configuration required en este plan. Pendiente (no
bloqueante): la calibración manual de umbrales con cámara real, documentada arriba.

## Next Phase Readiness

- Fase 27 completa: 11/11 planes (27-01..27-11). BEH-06..BEH-09 cerrados.
- Los 6 criterios de éxito del ROADMAP verificados uno a uno con comando `pytest -k`.
- Siguiente paso: `/gsd:plan-phase 28` (Refactor del frontend a módulos ES, depende de la
  Fase 21 ya completa — puede solaparse con el bloque B).

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*
