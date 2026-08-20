---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Ejecutado 27-06-PLAN.md (cableado de ObjectAnalyzer en DetectionWorker, wave 3, depende de 27-01+27-03+27-04+27-05). backend/pipeline/detection.py: _analyze_objects(obj_tracked, tracked, captured_at, processed_at) — mismo patron de aislamiento de fallos que _analyze_behavior (try envolviendo analyze+prune, except con self._exceptions += 1, emision fuera del try), anclas BOTTOM_CENTER para objetos y personas, findings += self._objects.prune(...) recogido explicitamente (el retorno NO se ignora); _excluded_object_ids/_object_zone_ids reutilizan sv.PolygonZone.trigger() sobre los mismos _zone_states (kind propagado en _rebuild_zone_states). backend/pipeline/manager.py: self.objects/self.object_tracker construidos en CameraPipeline.__init__ ANTES de _make_detection, gateados por objects_enabled — cuarto precedente (tras FSM Fase 24, ReID Fase 25, BehaviorAnalyzer Fase 26) de estado que sobrevive a un reinicio del DetectionWorker; set_detection_classes/get_object_stats/get_object_boxes en la fachada. backend/main.py propaga los 10 parametros object_*/objects_enabled desde Settings. 8 tests nuevos TEST_* en tests/test_detection_worker.py (emision real de OBJECT_LEFT, aislamiento de fallos, retorno de prune no ignorado, exclusion por zona, supervivencia de analizador y tracker a reinicio, objects_enabled=False, set_detection_classes sin reiniciar worker). Suite completa 500/500. Dos discrepancias de conteo en los <verify> automatizados del plan (no funcionales, documentadas en 27-06-SUMMARY.md): grep -c \"object_\" backend/main.py da 9 no >=10 (objects_enabled no matchea el patron por la 's' de plural, nombre fijado por el contrato LOCKED) y pytest -k object recoge 12 no >=13 (el plan asumia que los 7 tests de 27-03 matcheaban todos 'object', solo 4 lo hacen). BEH-06/07 NO se marcan en REQUIREMENTS.md: el ROADMAP sigue asignando esa puerta a 27-11. Fase 27: 6/11 planes. Ejecutado 27-07-PLAN.md (wave 4, depende de 27-02+27-04+27-06): backend/api/v2/detection.py — GET/PUT /api/v2/detection/classes con configure(camera_manager, event_engine) (molde metrics.py, nunca el global rtsp_stream), catalogo AVAILABLE_CLASSES de 6 clases COCO, LOCKED_CLASS_IDS={0}; el PUT valida en orden vacia/rango 0..79/duplicados/person-obligatoria (400 con detail en lenguaje llano) y solo entonces persiste en app_config (ConfigRepo, key=yolo_classes) ANTES de propagar via pipeline.set_detection_classes y emitir EventEngine.config_changed. backend/main.py: _resolve_active_classes(persisted, settings_value) extraida como funcion modulo-privada (app_config gana sobre YOLO_CLASSES, fila [] persistida se trata como ausente) llamada antes de construir PersonDetector; detection_v2_module.configure() cableado tras crear camera_manager; pipeline.set_detection_classes(active_classes) tras camera_manager.add() para que el reparto persona/objeto arranque coherente con la BD; include_router junto a recordings/metrics. 8 tests nuevos TEST_* en tests/test_detection_config_api.py (GET catalogo, 4 rechazos 400 con aserciones sobre detail, camino feliz con mocks de camera_manager/event_engine, orden persistir-antes-de-propagar, precedencia de arranque). Suite completa 508/508 (500 previos + 8). BEH-06 contribuido pero NO marcado en REQUIREMENTS.md (mismo criterio que 27-06: el ROADMAP cierra BEH-06/07 en la puerta de fase 27-11, que tambien exige el panel visual de 27-10). Fase 27: 7/11 planes. Quedan 27-08..27-11 (overlay MJPEG, endpoint de contexto, control de clases en el dashboard, puerta de fase). Ejecutado 27-08-PLAN.md (wave 4, depende de 27-03+27-06): backend/pipeline/streaming.py — StreamingWorker.__init__ acepta object_boxes: Callable[[], list[dict]] | None = None (via pull, mismo patron que registry/tracker; set_zone_overlay descartado por no tener llamadores), _annotate dibuja cada caja en magenta (255, 0, 255) con etiqueta class_name #track_id tras el bloque de zonas. backend/pipeline/manager.py: _make_streaming pasa object_boxes=self.get_object_boxes (metodo bound de CameraPipeline, 27-06), sin logica nueva ni segundo registry — sobrevive a un reinicio del supervisor porque el metodo bound resuelve self.detection en cada llamada. 4 tests nuevos TEST_* (3 en tests/test_streaming_worker.py sobre _annotate en aislamiento, 1 en tests/test_detection_worker.py de identidad de referencia del Callable cableado por la factoria). Suite completa 512/512 (508 previos + 4). Sin desviaciones de codigo. BEH-06 contribuido pero NO marcado en REQUIREMENTS.md: el ROADMAP cierra BEH-06/07 en la puerta de fase 27-11. Fase 27: 8/11 planes. Quedan 27-09..27-11 (endpoint de contexto, control de clases en el dashboard, puerta de fase). Ejecutado 27-09-PLAN.md (wave 5, depende de 27-04+27-06+27-07): backend/api/v2/context.py — GET /api/v2/analytics/context, molde configure()/APIRouter de metrics.py; _person_counts(registry) puro (frame_ids() nunca active_ids(), known solo identity_state is CONFIRMED, nunca person_id is not None que set_identity() escribe antes de confirmar la votacion) y _classify_activity(baseline_entry, now_entry, minutes_elapsed, settings) puro (tasa por minuto en los dos lados para no sesgar por hora parcial, unknown explicito con sample_days<context_min_sample_days o minutos_elapsed<5). hourly_baseline() (27-04) se llama dos veces: until=inicio de hora para el baseline, since=inicio de hora para el ahora. backend/main.py: context_v2_module.configure(camera_manager) justo tras crear CameraManager (antes de camera_manager.add), include_router junto al resto de la superficie v2. Desviacion Rule 3 (bloqueante, sin cambio de comportamiento): el fichero ya existia sin comprometer de un intento previo cortado por limite de API; su docstring de modulo y el de _person_counts citaban literalmente \"person_id\"/\"person_name\" para explicar la decision de diseno, lo que hacia fallar el propio <verify> automatizado del plan (que exige la ausencia literal de esas subcadenas en todo el fichero) — reescritas sin la subcadena literal, mismo significado. 7 tests nuevos TEST_* en tests/test_scene_context.py (5 sobre las funciones puras sin BD/HTTP: known vs pending vs unknown, frame_ids() vs active_ids(), historial insuficiente, sesgo de hora parcial, umbrales low/normal/high con Settings() real; 2 de integracion ASGI parcheando context_module._stat_repo en vez de get_session_factory, patron ya usado en test_detection_config_api.py: forma del JSON con los 6 bloques y ausencia de person_id/person_name en el cuerpo crudo de la respuesta). Suite completa 519/519 (512 previos + 7). BEH-08/BEH-09 contribuidos pero NO marcados en REQUIREMENTS.md, mismo criterio que BEH-06/07: el ROADMAP cierra BEH-06..09 en la puerta de fase 27-11. Fase 27: 9/11 planes. Quedan 27-10..27-11 (control de clases en el dashboard, puerta de fase). Ejecutado 27-10-PLAN.md (wave 5, depende de 27-07): frontend/index.html — card \"Clases detectadas\" insertado tras el card de zonas (molde identico: header con icono, contenedor con scroll), checkboxes por cada una de las 6 clases del catalogo devuelto por GET /api/v2/detection/classes, persona (id 0) siempre disabled porque el backend la manda en locked (la UI nunca decide por su cuenta que clase bloquear); guardado inmediato al marcar/desmarcar (evento change dispara saveDetectionClasses, sin boton separado, a diferencia del CRUD abierto de zonas); un 400 muestra d.detail (mensaje en lenguaje llano de 27-07) y recarga desde el servidor con loadDetectionClasses(), igual en fallo de red, para que la UI nunca mienta sobre el estado real. Todo inline en el <script> existente junto a loadZones(), cero cambios en frontend/app.js (sigue stub hasta la Fase 28), cero dependencias nuevas. Sin tests automatizados (no hay framework JS en el repo, verificacion funcional diferida al checkpoint manual de 27-11). Suite completa 519/519 sin cambios (plan solo toca frontend). BEH-06 contribuido pero NO marcado en REQUIREMENTS.md, mismo criterio que 27-06/27-07/27-08/27-09: el ROADMAP cierra BEH-06..09 en la puerta de fase 27-11. Fase 27: 10/11 planes. Queda 27-11 (puerta de fase). Ejecutado 27-11-PLAN.md (puerta de fase, wave 6, depende de 27-08+27-09+27-10): suite completa reejecutada verde 519/519 sin cambios de codigo, los 6 criterios de exito del ROADMAP trazados a comandos pytest -k que pasan (ver 27-11-SUMMARY.md), mas la regresion ByteTrack (TEST_object_class_does_not_reach_line_zone/TEST_objects_not_in_registry/TEST_bytetrack_ids_do_not_migrate) verde. BEH-06/BEH-08/BEH-09 marcados [x] en REQUIREMENTS.md (BEH-07 ya lo estaba desde 27-01); ROADMAP.md y STATE.md cierran la Fase 27 (11/11 planes). El checkpoint de calibracion de object_person_radius_px y de la tasa de falsos positivos de OBJECT_LEFT con camara real se DIFIERE explicitamente (9no checkpoint manual, mismo patron que los 8 anteriores: 19-01, 19-02, 20-02, 21-01, 22-01, 23-02, 25-06, 26-05) — no bloquea el cierre de la Fase 27 en codigo/tests ni el avance a la Fase 28; 150px (1,9x loiter_radius_px) ya esta cubierto por tests deterministas con trayectorias sinteticas. Fase 27 completa: 11/11 planes. Planificada la Fase 28 (Refactor del frontend a modulos ES): 28-CONTEXT.md fija el alcance (extraccion 1:1 de frontend/index.html a css/{base,layout,components}.css + js/{app,api,websocket}.js + js/views/dashboard*.js + js/components/{videoCanvas,zoneEditor,eventCard,detectionClasses,personGallery}.js, sin construir aun las vistas Timeline/Analytics/Camera/Settings de las Fases 29-32 ni js/store.js, diferido a la Fase 29); 28-RESEARCH.md midio con precision que el <body> actual sin <style>/<script> ya mide 667 lineas, lo que hizo el criterio original de ROADMAP ('index.html < 300 lineas') inalcanzable sin introducir fragmentacion de marcado — se opto por redefinir el criterio (cero <script>/<style> inline, no un recuento de lineas) en vez de anadir arquitectura nueva no pedida, decision del usuario reflejada en ROADMAP.md Success Criteria #1 de la Fase 28; 28-PATTERNS.md verifico contra el fichero real 3 correcciones sobre el mapeo inicial (bindPtzControls a dashboard-ptz.js no al core, loadResolutions a videoCanvas.js no al core, #clip-modal vive fuera del rango de marcado 121-784 y debe preservarse) y un ciclo de import real entre dashboard.js/dashboard-events.js resuelto creando ambos en el mismo plan (28-02); 9 PLAN.md en 5 waves (28-01 tests de contrato + 3 CSS; 28-02..28-06 en paralelo, 5 modulos JS sin solape de ficheros; 28-07 websocket.js depende de 02/04/05; 28-08 app.js real + index.html shell + suite completa; 28-09 checkpoint no autonomo de paridad funcional + medicion de carga en LAN), plan-checker paso sin bloqueantes (519/519 sin tocar, ningun modulo nuevo supera 300 lineas, dashboard-events.js el mayor con ~204). Ejecutados 28-01..28-08 (8/9 planes, ejecucion secuencial sin worktrees por falta de gsd-sdk en este entorno): frontend/index.html reescrito a shell puro (2038 -> 695 lineas), frontend/js/app.js como bootstrap real, stub frontend/app.js borrado, suite completa en verde (525 passed, 2 skipped = 519 previos + 8 de tests/test_frontend_modules.py nuevo). PR abierto: https://github.com/dcastillosaez/proyecto_camara/pull/12. Queda 28-09 (checkpoint no autonomo: checklist de paridad funcional de 13 areas + medicion de carga en LAN), servidor real arrancado en http://192.168.1.199:8000/ para la verificacion, respuesta del usuario pendiente. Siguiente: cerrar 28-09, luego /gsd:plan-phase 29."
last_updated: "2026-08-18"
last_activity: 2026-08-18
progress:
  total_phases: 22
  completed_phases: 11
  total_plans: 33
  completed_plans: 33
  percent: 50
previous_milestone:
  name: v1.2
  status: complete
  phases: 16/16
  completed: 2026-05-01
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-01)

**Core value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo, reconocimiento facial, grabación automática y métricas de sistema integrados en el mismo panel.
**Current focus:** v2.0 — PLANIFICADA. Desacoplar el pipeline, motor de eventos, percepción avanzada (ArcFace + ReID + comportamiento), centro de operaciones y preparación multi-cámara.

## Current Position

Milestone: v2.0 — Plataforma de Video Analytics
Phase: **Bloque A (17-22) + Fase 23 + Fase 24 + Fase 25 + Fase 26 + Fase 27 COMPLETOS** en código y tests (11/11 planes de la Fase 27, 27-01..27-11, ver `27-11-SUMMARY.md`). BEH-01..BEH-09 cerrados.
Status: Bloque A cerrado (310/310), Fase 23 (Migración a InsightFace/
  ArcFace) completa encima (326/326). La puerta bloqueante de la Fase 23
  se superó con evidencia real: `insightface`+`onnxruntime` instalan sin
  compilar en Windows, `buffalo_s` descarga y ejecuta una inferencia
  real (5 submodelos ONNX, embedding 512D confirmado). `FaceEngine`,
  `FaceQualityAssessor` e `IdentityIndex` construidos y verificados
  (23-01); `backend/recognizer.py` reducido a orquestación sobre ellos,
  `scripts/reenroll.py` para re-enrolamiento real, `dlib`/
  `face-recognition` fuera de requirements.txt (23-02); y **Fase 24
  (Identidad temporal — votación y máquina de estados) completa
  encima (377/377)**: `TemporalVoter`+`IdentityStateMachine` (4 estados,
  6 transiciones), `RecognitionWorker` cableado a la FSM sustituyendo
  el gate ciego de la Fase 23, `EventEngine.emit_identity` (3 eventos
  de identidad), y los 6 criterios de éxito del ROADMAP verificados
  uno a uno con comando `pytest -k` en `24-06-SUMMARY.md` (criterio 6:
  87.5% de reducción de inferencias faciales sobre un track no
  confirmado, umbral exigido ≥70%). FACE-07..FACE-11 cerrados.
  Quedan **9 checkpoints con cámara real** sin ejecutar, ninguno
  bloqueante para seguir programando: 19-01 Task 5 (migrar BD real),
  19-02 Task 5 (validación de reglas en vivo), 20-02 Task 4 (validación
  visual del pre-buffer), 21-01 Task 5 (coste de instrumentación y
  línea base de 30 min), 22-01 Task 4 (resistencia de 8 h),
  23-02 Task 4 (tasa de aciertos ArcFace vs dlib con datos reales),
  25-06 Task 2 (tasa de falsos positivos de ReID con dos personas
  reales — la parte determinista ya está verde, `reid_inherit_identity`
  sigue en `False`), 26-05 Task 3 (calibración de
  `run_speed_px_s`/`loiter_radius_px`/`immobile_radius_px` contra
  cámara real — los defaults de SPEC_v2.md §5.7 ya están cubiertos por
  tests deterministas con trayectorias sintéticas), y 27-11 Task 2
  (calibración de `object_person_radius_px` y tasa de falsos positivos
  de `OBJECT_LEFT` — 150 px ya cubierto por tests deterministas con
  trayectorias sintéticas, `OBJECT_LEFT` sigue en `Severity.WARNING`).
  **Fase 28 (Refactor del frontend a módulos ES) planificada** encima:
  9 planes en 5 waves, plan-checker verde — ver `## Siguiente paso` para
  el detalle. Ningún cambio de código todavía, solo planificación.
Last activity: 2026-08-18

Progress v2.0: [█████░░░░░] ~50% (11/22 fases completas)
Progress v1.2: [██████████] 100% (16/16 fases) — completado 2026-05-01

## Mediciones acumuladas del bloque A y Fase 23

| Medición | Resultado | Fuente |
|----------|-----------|--------|
| CPU antes/después de desacoplar el pipeline (Fase 18) | 587.3% → 568.8% (normalizado, 8 cores) — mejora leve, sin regresión de RAM; YOLO sigue siendo el coste dominante | `18-02-CHECKPOINT.md` |
| Soak de 30 min, cámara real (Fase 17) | FPS estable ~15, 0 reconnects, sin crecimiento de latencia | `17-02-SUMMARY.md` |
| Línea base operativa de métricas (Fase 21, 30 min) | **Pendiente** — mecánica de `/api/v2/metrics` y `/metrics` verificada end-to-end (eventos reales incrementan `events_total`, `e2e_latency_seconds` registra observaciones reales), pero sin cámara real no hay FPS/latencia de producción que promediar | `21-01-SUMMARY.md`, checkpoint 21-01 Task 5 |
| Coste de instrumentación (<2% CPU objetivo) | **Pendiente** — requiere comparar `metrics_enabled=true/false` con carga real | checkpoint 21-01 Task 5 |
| Resistencia de 8 h (RSS, colas, `active_tracks`) | **Pendiente** — `scripts/soak_test.py` escrito y verificado con servidor real (6 s, 3 muestras), ejecución completa de 8 h aún no realizada | `22-01-SUMMARY.md`, checkpoint 22-01 Task 4 |
| Latencia FaceEngine (detect+embed) tras optimizar `allowed_modules` | ~15-40ms/llamada (antes ~250-370ms con los 5 submodelos por defecto de buffalo_s) — medido con imagen real, 10-20x de mejora | `23-01-SUMMARY.md` |
| Tasa de aciertos ArcFace vs dlib (≥50 recortes reales) | **Pendiente** — requiere `data/gallery/` poblada con capturas reales | `23-02-SUMMARY.md`, checkpoint 23-02 Task 4 |

## Siguiente paso

```
/gsd:execute-phase 28
```

La Fase 28 (Refactor del frontend a módulos ES) está **planificada**: 9
planes en 5 waves (`28-01`..`28-09`), plan-checker verde sin bloqueantes.
`frontend/index.html` (2038 líneas, `<script>` único de ~1240) se extrae
1:1 a `css/{base,layout,components}.css` + `js/{app,api,websocket}.js` +
`js/views/dashboard{,-ptz,-events,-observability}.js` +
`js/components/{videoCanvas,zoneEditor,eventCard,detectionClasses,personGallery}.js`,
sin construir todavía las vistas de operaciones/timeline/analytics/cámara/
configuración (Fases 29-32) ni `js/store.js` (diferido a la Fase 29) — así
lo cerró el usuario en `28-CONTEXT.md`. La investigación (`28-RESEARCH.md`)
midió con precisión que el `<body>` actual sin `<style>`/`<script>` ya
ocupa 667 líneas, lo que hacía inalcanzable el criterio original del
ROADMAP ("`index.html` < 300 líneas") sin fragmentar el marcado con
`fetch()+innerHTML` — arquitectura nueva no pedida. El usuario optó por
redefinir el criterio en vez de añadir esa complejidad: `ROADMAP.md`
Success Criteria #1 de la Fase 28 ahora mide "cero `<script>`/`<style>`
inline", no un recuento de líneas. `28-PATTERNS.md` verificó contra el
fichero real 3 correcciones al mapeo inicial de RESEARCH (`bindPtzControls`
→ `dashboard-ptz.js`, `loadResolutions` → `videoCanvas.js`, `#clip-modal`
vive fuera del rango de marcado 121-784 y debe preservarse) y un ciclo de
import real entre `dashboard.js`/`dashboard-events.js` resuelto creando
ambos en el mismo plan (28-02). `frontend/app.js` (stub v1.2 de 2 líneas)
se borra en 28-08 al crear el entry point real. Ningún módulo nuevo supera
300 líneas (el mayor, `dashboard-events.js`, ~204). Wave 5 (28-09) es un
checkpoint no autónomo: checklist manual de paridad funcional (13 áreas) +
medición de carga inicial desde un segundo dispositivo de la LAN.

La Fase 27 (Multi-clase y contexto de escena) está **completa**: 11/11
planes (`27-01`..`27-11`), BEH-06..BEH-09 cerrados, suite 519/519.
`ObjectAnalyzer` (dominio puro), `ObjectTracker` con partición por clase
antes de `sv.ByteTrack` (class-agnostic — cierra el riesgo de que un
`tracker_id` migre entre persona y objeto), `DetectionStatRepo.hourly_baseline()`
(media móvil por franja horaria), `EventEngine.emit_object()`/`config_changed()`,
cableado completo en `DetectionWorker`/`manager.py` (construcción fuera de la
factoría, cuarto precedente tras FSM/ReID/BehaviorAnalyzer), router
`GET/PUT /api/v2/detection/classes` con persistencia en `app_config` (gana
sobre `YOLO_CLASSES`), overlay de objetos en magenta en el feed MJPEG,
`GET /api/v2/analytics/context` (hora, zona, personas totales/conocidas/
desconocidas, nivel de actividad contra la media móvil de 7 días) y el
panel "Clases detectadas" en el dashboard. `27-11` (puerta de fase) trazó
los 6 criterios del ROADMAP a comandos `pytest -k` que pasan sin tocar
código (ver `27-11-SUMMARY.md`); el checkpoint de calibración de
`object_person_radius_px` y de la tasa de falsos positivos de `OBJECT_LEFT`
con cámara real se **difiere** explícitamente (9º checkpoint manual, mismo
patrón que los 8 anteriores) — no bloquea el avance a la Fase 28.

La Fase 24 (Identidad temporal — votación y máquina de estados) está
**completa**: 6/6 planes (`24-01`..`24-06`), FACE-07..FACE-11 cerrados,
suite 377/377. `IdentityStateMachine`/`TemporalVoter` (4 estados: UNKNOWN →
CANDIDATE → CONFIRMED → TEMPORARILY_LOST) cableados de extremo a extremo
en `RecognitionWorker`, con los 6 criterios de éxito del ROADMAP
verificados uno a uno (`24-06-SUMMARY.md`). El research corrigió
la lista de ficheros de `SPEC_v2.md` §9 (el fichero real no es
`perception/face/engine.py` sino `pipeline/recognition.py` +
`pipeline/manager.py`), y el plan-checker encontró y se corrigió un bug
real: `_sync_identity` dependía del TTL de 30 s de `TrackRegistry.active_ids()`
para detectar tracks perdidos, lo que habría producido un segundo
`PERSON_RECOGNIZED` al recuperar una identidad con un `track_id` nuevo
dentro de ese TTL — corregido con `TrackRegistry.frame_ids()`, publicado
por `DetectionWorker` en cada frame.

La Fase 25 (Re-identificación de personas, ReID) — depende de la Fase 24
(ya completa) — está **completa** (6/6 planes, 25-01..25-06):
`.planning/phases/25-re-identificaci-n-de-personas-reid/` tiene CONTEXT,
RESEARCH, PATTERNS, VALIDATION y 6 PLAN.md (5 waves), verificados por
`gsd-plan-checker` sin blockers. `25-01` ya
está completo: `scripts/fetch_models.py` descargó el ONNX de OSNet
(`kornia/osnet`, sha256 `e78604f4...` verificado) y reescribió el eje de
batch fijo (16) a dinámico (grafo bit-idéntico, idempotente), y
`ReIDEngine` produce embeddings 512D L2-normalizados en ~5-12 ms p50 en
CPU (criterio 1 del ROADMAP cumplido), degradando con `available=False`
sin modelo o con batch fijo != 1. REID-01 cerrado — ver `25-01-SUMMARY.md`.
`25-02` también está completo: `IdentityStateMachine.on_reid_result()`
(método aditivo, justo después de `on_face_result`) reutiliza
`_claim_lost()` para heredar una identidad `TEMPORARILY_LOST` por
apariencia, sin votar en `TemporalVoter` y con `emits=False` (misma
visita, sin segundo `PERSON_RECOGNIZED`); fija `last_face_at = now` al
heredar para que el barrido de rancios de `on_tick` no purgue el estado
recién heredado (Pitfall 5) y evita el `IDENTITY_LOST` espurio que
producía resolver la herencia fuera de la FSM (Pitfall 4). 7 tests
`TEST_reid*` verdes, suite completa 388/388. REID-02 y REID-03 cerrados
— ver `25-02-SUMMARY.md`. `25-03` también está completo: `TrackGallery`
(`backend/perception/reid/gallery.py`) implementa las 4 reglas de
`resolve()` (candidatos con identidad de otro track, frescura dentro de
la ventana de 15 s, similitud máxima por coseno directo, umbral
estricto + comprobación de conflicto contra `active_identities`),
devolviendo siempre `(candidato, similitud)` reales — la política de si
aplicar la herencia queda para `25-04`. `needs_embedding()` implementa
el gate del criterio 5 y `prune()`/`_enforce_cap()` replican la doble
guarda TTL + cota dura de `IdentityStateMachine`. 12 tests con vectores
512D de coseno exacto construidos a mano (nunca `np.random`: el research
midió coseno 0,991 entre dos ruidos independientes con OSNet real) más
2 tests de cota de memoria (con y sin `prune()`). Suite completa
402/402. REID-04 cerrado (REID-02 ya cerrado en 25-02) — ver
`25-03-SUMMARY.md`. `25-04` también está completo: la vía ReID queda
cableada dentro de `RecognitionWorker` — `_loop` extrae `_face_pass`/
`_reid_pass`, ambas corren cada tick sin bloquearse mutuamente (persona
de espaldas: `needs_recognition()` dice que no, `_next_reid_candidate`
dice que sí); `_next_reid_candidate` gatea sobre
`TrackGallery.needs_embedding()` (criterio 5), nunca sobre
`needs_recognition()`; el flag `reid_inherit` vive en el worker, no en
`TrackGallery` (`resolve()` siempre calcula el candidato real, el flag
decide si se aplica vía `on_reid_result()` o solo se audita — criterio
4); 4 contadores `reid_*` en `stats`, canal de auditoría sin endpoints
nuevos; `self._rate.observe()` nunca se llama desde la vía ReID
(instrumentación separada con `stage="reid"`). Durante el test
end-to-end del criterio 3 se encontró y corrigió un bug real:
`_next_reid_candidate` re-seleccionaba tracks fuera de `frame_ids()`
(`TEMPORARILY_LOST` aún no podados por `DetectionWorker`), y
`gallery.update()` les escribía `identity_of()==None`, borrando en la
galería la identidad que ReID necesita conservar para que otro track la
reclame después — corregido con un filtro `track_id in frame_ids()`.
Suite completa 407/407 (402 previos + 5 nuevos, incluido el end-to-end
del criterio 3 verificado 3/3 sin flaky). REID-01..REID-04 ya estaban
cerrados por los planes previos; `25-04` los cablea de extremo a
extremo — ver `25-04-SUMMARY.md`. `25-05` también está completo: 7
parámetros `reid_*` en `backend/config.py` (defaults locked de
SPEC_v2.md §5.6, `reid_inherit_identity=False` como fail-safe) con
`validate_reid_model_path` (extensión + contención en `_PROJECT_ROOT`,
SEC-16) y `validate_reid_params` (rangos, T-25-18); `CameraPipeline`
construye `ReIDEngine`/`TrackGallery` FUERA de `_make_recognition`,
junto a la FSM, para que un reinicio del worker no vacíe la galería ni
recargue el ONNX; `backend/main.py` propaga los 7 settings con mapeo
explícito (`reid_inherit_window <- reid_inherit_window_secs`,
`reid_inherit <- reid_inherit_identity`, etc.), verificado que la app
importa igual con y sin el modelo ONNX presente (degradación graciosa,
T-25-19). 6 tests nuevos (4 en `test_config.py`, 2 en
`test_recognition_worker.py`). Suite completa 413/413 — ver
`25-05-SUMMARY.md`. `25-06` (puerta de fase) también está completo: la
suite completa se reejecutó verde (413/413, sin skips en
`test_reid_engine.py`, sin cambios de código) y los 5 criterios de éxito
del ROADMAP quedaron trazados a comandos `pytest -k` que pasan
(`25-06-SUMMARY.md`), con la latencia p50 de `embed()` remedida en esta
máquina (~11,9 ms, criterio 1). REID-01..REID-04 ya estaban cerrados
desde `25-01`/`25-02`/`25-03`. El checkpoint manual del criterio 4 (tasa
de falsos positivos con dos personas reales) se **difiere**: sin acceso
a cámara en esta sesión, la parte determinista ya está verde y
`reid_inherit_identity=False` sigue siendo el default seguro — no
bloquea avanzar a la Fase 26. **Fase 25 completa: 6/6 planes.**

La Fase 26 (Análisis de comportamiento) — depende de la Fase 25 (ya
completa) — está **completa** (5/5 planes, 26-01..26-05):
`BehaviorAnalyzer` (dominio puro, `26-01`) emite `BehaviorFinding` para
LOITERING, RUNNING, IMMOBILE y CROWD_DETECTED con agregados O(1) y
latch por episodio en los cuatro comportamientos; 10 umbrales
configurables en `config.py` (`26-02`); `EventEngine.emit_behavior()` +
`duration_s` en `ZONE_EXITED` (`26-03`); cableado completo en
`DetectionWorker`/`manager.py`/`main.py` (`26-04`). `26-05` (puerta de
fase) cerró el criterio 5: 3 tests nuevos en `tests/test_rule_engine.py`
prueban el camino real (YAML en `tmp_path` + `load_rules` + `evaluate`)
para los cuatro eventos de comportamiento como `when.event`, incluida
la prueba de regresión explícita del pitfall de naming (`duration`
en vez de `duration_s` no dispara la regla) — sin tocar
`backend/events/rules.py` ni `config/rules.yaml`. Suite completa
454/454. Los 5 criterios de éxito del ROADMAP quedaron trazados a
comandos `pytest -k` que pasan (`26-05-SUMMARY.md`); el criterio 2 (seis
trayectorias) se reparte entre los 4 tests de comportamiento de `26-01`
y los tests ya existentes de `EventEngine.process_zone` (2 trayectorias
de zona, propiedad de la Fase 19) — no es un hueco. BEH-01..BEH-05 ya
estaban `[x]` desde planes anteriores, confirmado. El checkpoint de
calibración de umbrales con cámara real (`run_speed_px_s`,
`loiter_radius_px`, `immobile_radius_px`) se **difiere** explícitamente
(8º checkpoint manual, sin cámara en esta sesión) — no bloquea avanzar
a la Fase 27 porque los defaults de SPEC_v2.md §5.7 ya están cubiertos
por tests deterministas con trayectorias sintéticas. **Fase 26 completa:
5/5 planes.**

La Fase 27 (Multi-clase y contexto de escena) — depende de la Fase 26
(ya completa) — está **completa** (11/11 planes, 27-01..27-11): ver el
detalle completo de cada plan en "Siguiente paso" arriba y en
`27-11-SUMMARY.md`. `27-11` (puerta de fase) reejecutó la suite completa
verde (519/519, sin cambios de código) y trazó los 6 criterios de éxito
del ROADMAP a comandos `pytest -k` que pasan, más la regresión ByteTrack
(`TEST_object_class_does_not_reach_line_zone`, `TEST_objects_not_in_registry`,
`TEST_bytetrack_ids_do_not_migrate_between_classes`). BEH-06, BEH-08 y
BEH-09 se marcan `[x]` en `REQUIREMENTS.md` (BEH-07 ya lo estaba desde
`27-01`). El checkpoint de calibración de `object_person_radius_px` y de
la tasa de falsos positivos de `OBJECT_LEFT` con cámara real se **difiere**
explícitamente (9º checkpoint manual, sin cámara en esta sesión) — no
bloquea avanzar a la Fase 28 porque los criterios deterministas ya están
verdes con trayectorias sintéticas y `objects_enabled=False`/
`UPLOAD_MIN_SEVERITY=critical` quedan como válvulas de escape sin tocar
código. **Fase 27 completa: 11/11 planes.**

Nota histórica — la Fase 23 (ya cerrada) abrió con una **puerta
bloqueante** (verificar que `insightface` + `onnxruntime` instalan y
ejecutan una inferencia real en Windows, con plan B en `SPEC_v2.md`
ADR-02 si no instalaban) que se resolvió con evidencia real antes de
planificar el resto de la fase — ver `23-CONTEXT.md`.

Los 9 checkpoints pendientes (bloque A + Fase 23 + Fase 25 + Fase 26 +
Fase 27) pueden ejecutarse en cualquier momento que haya acceso a la
cámara real; ninguno bloquea el avance a la Fase 28, pero sí deberían
cerrarse antes de dar el bloque A, la Fase 23, la Fase 25, la Fase 26 y
la Fase 27 por completamente validados en producción.

## Pendiente sin relacion con v2.0

- Token OAuth de Google Drive caducado (`data/token.json`, `invalid_grant`).
  Requiere rehacer el flujo de autorizacion manualmente.

## Documentos del milestone v2.0

| Documento | Contenido |
|-----------|-----------|
| `propuesta_mejora/SPEC_v2.md` | Referencia técnica: arquitectura objetivo, 10 ADRs, contratos de módulo, modelo de datos, catálogo de eventos, ficheros/riesgo por fase, trazabilidad de los 25 puntos, riesgos y criterios de aceptación del milestone |
| `.planning/ROADMAP.md` § v2.0 | Fases 17-38 con goal, dependencias, requisitos y criterios de éxito |
| `.planning/STATE.md` (este) | Estado real de las 22 fases — qué está completo, qué falta y por qué |
| `.planning/REQUIREMENTS.md` § v2 | 107 requisitos (PIPE, DET, EVT, RULE, DB, CLIP, OBS, SEC, FACE, REID, BEH, OPS, SET, TEST, SCALE) |
| `propuesta_mejora/mejoras_inmediatas.md` | Propuesta original (25 puntos) |
| `propuesta_mejora/vulnerabilidades.md` | Análisis de seguridad (12/14 ya corregidas en v1.2) |

## Estado de las 22 fases de v2.0

Fuente única de verdad sobre qué queda por hacer — sustituye a la extinta
tabla "Progress Tracking v2.0" de `ROADMAP.md` (quedaba desactualizada por
duplicación). Para el detalle de cada fase (goal, dependencias, requisitos,
criterios de éxito) ver `ROADMAP.md` § Phase Details v2.0; para ficheros y
riesgos de las fases aún no planificadas, `SPEC_v2.md` §9.

| Fase | Bloque | Estado | Cerrada | Pendiente |
|------|--------|--------|---------|-----------|
| 17 — Frame Broker y Capture Worker | A | ✓ Completa | 2026-08-07 | — (checkpoint superado) |
| 18 — Workers desacoplados | A | ✓ Completa | 2026-08-08 | — (checkpoint superado) |
| 19 — Event Engine y esquema v2 | A | ✓ Completa (código) | 2026-08-09 | ⧗ Migración BD real + validación de reglas en vivo |
| 20 — Pre/post-buffer | A | ✓ Completa (código) | 2026-08-09 | ⧗ Verificación visual del pre-buffer + prueba sin red |
| 21 — Observabilidad | A | ✓ Completa (código) | 2026-08-09 | ⧗ Coste de instrumentación + línea base de 30 min |
| 22 — Seguridad y memoria | A | ✓ Completa (código) | 2026-08-09 | ⧗ Prueba de resistencia de 8 h |
| 23 — InsightFace/ArcFace | B | ✓ Completa (código) | 2026-08-10 | ⧗ Tasa de aciertos ArcFace vs dlib con datos reales |
| 24 — Identidad temporal | B | ✓ Completa | 2026-08-13 | — (sin checkpoints manuales; 6 checkpoints de cámara real de fases anteriores siguen abiertos, sin relación con esta fase) |
| 25 — Re-identificación (ReID) | B | ✓ Completa (código) | 2026-08-15 | ⧗ Tasa de falsos positivos con dos personas reales (checkpoint 25-06 Task 2) |
| 26 — Análisis de comportamiento | B | ✓ Completa (código) | 2026-08-16 | ⧗ Calibración de umbrales con cámara real (checkpoint 26-05 Task 3) |
| 27 — Multi-clase y contexto de escena | B | ✓ Completa (código) | 2026-08-17 | ⧗ Calibración de `object_person_radius_px` y tasa de falsos positivos (checkpoint 27-11 Task 2) |
| 28 — Frontend a módulos ES | C | — Sin planificar | — | Depende de 21 (ya completa) — puede solaparse con B |
| 29 — Vista de operaciones | C | — Sin planificar | — | Depende de 28 |
| 30 — Event Timeline y alertas | C | — Sin planificar | — | Depende de 29 |
| 31 — Vista de analítica | C | — Sin planificar | — | Depende de 30 |
| 32 — Vista de cámara y config visual | C | — Sin planificar | — | Depende de 31 |
| 33 — Editores visuales | C | — Sin planificar | — | Depende de 32 |
| 34 — Tests E2E | C | — Sin planificar | — | Depende de 33 |
| 35 — CameraManager | D | — Sin planificar | — | Depende de 34 |
| 36 — Multi-cámara en runtime | D | — Sin planificar | — | Depende de 35 |
| 37 — PostgreSQL y Redis | D | — Sin planificar | — | Depende de 36 |
| 38 — Worker GPU (opcional) | D | — Sin planificar | — | Depende de 37 |

Las fases sin planificar (24-38) no tienen PLAN todavía. Generarlos con
`/gsd:plan-phase <N>` cuando llegue el momento, o pedirlos en Cowork como
se hizo con el bloque A y la Fase 23.

## Notas de ejecución

- **Puerta bloqueante en la Fase 23:** verificar que `insightface` + `onnxruntime` instalan en el entorno Windows del proyecto antes de comprometer el bloque B. Plan B documentado en `SPEC_v2.md` ADR-02.
- **Migración de embeddings:** ArcFace 512D no es compatible con dlib 128D. La Fase 23 exige re-enrolamiento desde `data/gallery/`.
- **Fase 28 (frontend) solo depende de la 21**, así que el bloque C puede solaparse con el B si interesa.

## Phases Summary

| Phase | Descripción | Estado | Fecha |
|-------|-------------|--------|-------|
| 1 | Scaffolding y entorno | ✓ Complete | 2026-04-16 |
| 2 | Captura RTSP y stream MJPEG | ✓ Complete | 2026-04-17 |
| 3 | Detección de personas YOLO26n | ✓ Complete | 2026-04-17 |
| 4 | Tracking y conteo por línea virtual | ✓ Complete | 2026-04-17 |
| 5 | Persistencia en SQLite | ✓ Complete | 2026-04-18 |
| 6 | API REST y WebSocket | ✓ Complete | 2026-04-18 |
| 7 | Dashboard web | ✓ Complete | 2026-04-18 |
| 8 | Configuración centralizada | ✓ Complete | 2026-04-16 |
| 9 | Reconocimiento facial y enrolamiento | ✓ Complete | 2026-04-19 |
| 10 | Grabación de video y upload Google Drive | ✓ Complete | 2026-04-19 |
| 11 | Rendimiento y estabilidad | ✓ Complete | 2026-04-23 |
| 12 | Alertas y notificaciones | ✓ Complete | 2026-04-26 |
| 13 | Detección avanzada e historial | ✓ Complete | 2026-04-25 |
| 14 | Seguridad | ✓ Complete | 2026-04-23 |
| 15 | UI y exportación | ✓ Complete | 2026-04-26 |
| 16 | Operaciones | ✓ Complete | 2026-05-01 |

## Test Coverage

Suite completa: **519/519 passing** (última ejecución 2026-08-17, tras `27-09`: +7 tests
`TEST_*` en `tests/test_scene_context.py` — 5 sobre `_person_counts`/`_classify_activity`
puras (`TEST_known_requires_confirmed`, `TEST_person_counts_uses_frame_ids_not_active_ids`,
`TEST_insufficient_history`, `TEST_partial_hour_normalised`, `TEST_activity_ratio_thresholds`)
y 2 de integracion ASGI (`TEST_context_shape`, `TEST_context_never_leaks_person_identity`) —
ver `27-09-SUMMARY.md`). Cifra anterior 512/512 (tras `27-08`: +4 tests
`TEST_*` — 3 en `tests/test_streaming_worker.py` (`TEST_object_overlay_drawn_when_boxes_present`,
`TEST_no_object_overlay_when_provider_returns_empty`, `TEST_streaming_worker_without_object_boxes_provider`,
todos sobre `_annotate` en aislamiento, sin hilo ni broker) y 1 en `tests/test_detection_worker.py`
(`TEST_streaming_factory_wires_object_boxes_provider`, identidad de referencia del `Callable`
cableado por `_make_streaming`) — ver `27-08-SUMMARY.md`). Cifra anterior 508/508 (tras `27-07`: +8 tests
`TEST_*` en `tests/test_detection_config_api.py` — `TEST_get_classes_returns_active_and_catalog`,
los 4 rechazos `TEST_rejects_*` con aserciones sobre `detail` (no solo el codigo 400),
`TEST_put_persists_propagates_and_emits`, `TEST_put_persists_before_propagating` (orden via
`MagicMock.attach_mock`) y `TEST_empty_persisted_row_is_treated_as_absent` (prueba directa de
`main._resolve_active_classes`) — ver `27-07-SUMMARY.md`). Cifra anterior 500/500 (tras `27-06`: +8 tests
`TEST_*` en `tests/test_detection_worker.py` — `TEST_object_left_emitted_from_worker`
(emision real de `OBJECT_LEFT` con reloj inyectado), `TEST_object_analysis_failure_does_not_kill_thread`,
`TEST_object_prune_findings_are_emitted` (protege el retorno de `prune()`),
`TEST_excluded_zone_suppresses_object_candidate`, `TEST_object_analyzer_survives_worker_restart`,
`TEST_object_tracker_survives_worker_restart`, `TEST_objects_disabled_leaves_pipeline_without_analyzer`
y `TEST_set_object_detection_classes_does_not_restart_worker` — ver `27-06-SUMMARY.md`). Cifra anterior
492/492 (última ejecución 2026-08-17, tras `27-05`: +5 tests
`TEST_*` en `tests/test_event_engine.py` — `TEST_emit_object_translates_both_kinds`,
`TEST_emit_object_payload_carries_magnitudes` (`duration_s`/`class_name` presentes,
`person_distance_px` ausente al ser `None`), `TEST_emit_object_severity_comes_from_catalog`
(`OBJECT_LEFT` en `Severity.WARNING`, `OBJECT_REMOVED` en `Severity.INFO`, sin que
`emit_object` pase `severity=`), `TEST_emit_object_carries_bbox_as_first_class_field` y
`TEST_config_changed_is_emitted_with_detail` — ver `27-05-SUMMARY.md`). Cifra anterior
487/487 (última ejecución 2026-08-17, tras `27-04`: +7 tests
`TEST_*` en `tests/test_repositories.py`/`tests/test_database.py` — 5 de
`DetectionStatRepo.hourly_baseline()` (orden de agregacion con datos repartidos en varios
minutos, `sample_days` con un solo dia, `until` excluyendo la hora en curso, aislamiento por
`camera_id`, ventana vacia sin excepcion), `TEST_config_repo_roundtrip_list` (roundtrip de
`list[int]` en la columna JSON de `app_config`, overwrite y default) y
`TEST_get_zones_returns_kind` (zona con `kind="exclude_objects"` y zona con `kind=None`,
ambas expuestas por `get_zones()` del ORM legacy) — ver `27-04-SUMMARY.md`. Cifra anterior
480/480 (última ejecución 2026-08-17, tras `27-03`: +7 tests
`TEST_*` en `tests/test_detection_worker.py` — regresion del riesgo ByteTrack
class-agnostic: `TEST_bytetrack_ids_do_not_migrate_between_classes` reproduce
literalmente el hallazgo del research con un `sv.ByteTrack` compartido y demuestra
que con la particion por clase (`ObjectTracker` + `PersonTracker` separados) no
ocurre; mas `TEST_object_class_does_not_reach_line_zone` (igualdad de `get_counts()`
con/sin coche), `TEST_objects_not_in_registry`, `TEST_split_by_class_preserves_class_name`,
`TEST_sync_frame_rate_reaches_both_trackers`, `TEST_no_object_classes_behaves_like_today`
y `TEST_object_boxes_snapshot_is_a_copy` — ver `27-03-SUMMARY.md`). Cifra anterior
473/473 (última ejecución 2026-08-17, tras `27-02`: +5 tests
`TEST_*` — 3 en `tests/test_config.py` (`TEST_yolo_model_default_is_yolo26n`,
`TEST_object_defaults_match_research` con un assert por cada uno de los 10 `object_*` y
4 `context_*`, `TEST_object_params_reject_impossible_values` con caso propio para
`object_class_ids=[0, 24]`) + 2 en `tests/test_detector.py`
(`TEST_set_classes_changes_next_inference`, y `TEST_multiclass_latency_under_15_percent`
que mide con pesos reales de `yolo26n.pt` sobre `bus.jpg` a 1280x720: p50 con 1 clase vs
6 clases, criterio 6 del ROADMAP con margen — sin skip, `bus.jpg` presente en
`ultralytics/assets`). Cifra anterior 468/468 (tras `27-01`: +11 tests
`TEST_*` en `tests/test_object_analyzer.py` (nuevo fichero: los 9 comportamientos de BEH-07
— `OBJECT_LEFT` tras umbral, latch por episodio, igualdad de conjunto, supresion por
persona cercana, guardas de warmup y zona de exclusion, `OBJECT_REMOVED` con/sin persona,
gracia de oclusion, payload sin `None`) + 3 tests `TEST_object_analyzer_*` en
`tests/test_memory_bounds.py` (doble guarda TTL+LRU con y sin `prune()`, incluida `_ignored`)
— ver `27-01-SUMMARY.md`). Cifra anterior 454/454 (última ejecución 2026-08-16, tras `26-05`: +3 tests `TEST_behavior_*` en `tests/test_rule_engine.py` — carga de las 4 reglas de comportamiento desde YAML real vía `load_rules`, `duration_gte` leyendo `duration_s` con prueba negativa explícita del nombre equivocado, y filtro `zone` sobre `zone_id` de primer nivel — sin cambios en `backend/events/rules.py` ni `config/rules.yaml`, ver `26-05-SUMMARY.md`). Cifra anterior 451/451 (tras `26-04`: +11 tests `TEST_behavior_*` en `tests/test_detection_worker.py` — 4 de cableado de `_analyze_behavior`/`_zone_membership_snapshot` (CROWD_DETECTED real, ausencia de `behavior`, fallo aislado, reutilización de `st["inside"]`) + 3 de supervivencia/desactivación/umbrales vía `CameraPipeline` (mismo molde que `TEST_fsm_survives_worker_restart` de la Fase 24) — sin cambios en `backend/perception/behavior.py` ni `backend/events/engine.py`, ver `26-04-SUMMARY.md`). Cifra anterior 444/444 (tras `26-03`: +7 tests — 3 `TEST_emit_behavior_*` y 3 `TEST_zone_dwell_*` en `tests/test_event_engine.py` (traducción de los 4 `BehaviorKind`, magnitudes en payload, severidad INFO por defecto, `duration_s` en `ZONE_EXITED` con/sin reloj monotónico) + 1 `TEST_zone_entry_at_bounded` en `tests/test_memory_bounds.py` (10.000 entradas/salidas efímeras en dos zonas, ambos dicts quedan vacíos)). Cifra anterior 437/437 (tras `26-02`: +3 tests `TEST_behavior_*` en `tests/test_config.py` — defaults de los 10 parámetros `behavior_*`, positividad de umbrales, y cota de `run_window_secs <= 12.0`). Cifra anterior 434/434 (tras `26-01`: +21 tests — 19 `TEST_*` nuevos en `tests/test_behavior_analyzer.py` (las 4 reglas de `BehaviorAnalyzer`, sus latches, el payload de magnitudes y 4 tests de trayectoria con igualdad de conjunto para el criterio 2 del ROADMAP) + 2 tests de cota en `tests/test_memory_bounds.py` (`TEST_behavior_state_bounded`/`..._without_prune`)). Cifra anterior 413/413 (última ejecución 2026-08-15, tras `25-06`: sin cambios de código, puerta de fase pura — misma cifra que tras `25-05`: +6 tests — 4 `TEST_reid_*` en `tests/test_config.py` (defaults, umbral fuera de rango, parámetros temporales/cota, extensión+traversal del modelo) y 2 en `tests/test_recognition_worker.py` (supervivencia de motor/galería a reinicio de worker, `reid_enabled=False`)). Cifra anterior 407/407 tras `25-04` (+5 tests `TEST_*` en `tests/test_recognition_worker.py` — presupuesto de inferencias criterio 5, modo solo-observación criterio 4, contadores en `stats`, compatibilidad sin ReID, y el end-to-end del criterio 3). Cifra anterior 402/402 tras `25-03` (+12 tests `TEST_*` en `tests/test_track_gallery.py` (nuevo fichero, `TrackGallery` con vectores 512D de coseno exacto) + 2 tests de cota en `tests/test_memory_bounds.py`. Cifra anterior 388/388 tras `25-02` (+7 tests `TEST_reid*` en `tests/test_identity_state_machine.py` — herencia, no-voto, no-secuestro, no-interferencia, ausencia de identidad perdida, `IDENTITY_LOST` espurio y barrido de rancios). 381/381 tras `25-01` (+4 tests en `tests/test_reid_engine.py`); 377/377 verificada en `24-06`).
La tabla por módulo de v1.2 (38 tests) quedó obsoleta al crecer la suite en v2.0 —
ver `pytest tests/ -v` para el desglose actual por fichero.

## Accumulated Context

### Decisions

- YOLO26n en lugar de YOLOv8n (31% más rápido en CPU, misma API)
- supervision (ByteTrack + LineZone) para tracking y conteo
- aiosqlite + SQLAlchemy 2.0 async para persistencia
- pydantic-settings para configuración centralizada
- face-recognition/dlib HOG para reconocimiento facial (sin GPU)
- mp4v fourcc para VideoWriter en Windows (más fiable que H.264)
- asyncio.run_coroutine_threadsafe para bridge thread→async en recorder/uploader
- Degradación elegante sin credentials.json (Drive upload deshabilitado, resto funciona)
- psutil para métricas de salud (CPU/RAM) sin dependencias extra
- Rotación diaria con tarea async (`_purge_loop`) usando `asyncio.sleep(24*3600)`
- Docker Compose con volúmenes para `data/`, `certs/` y `.env`
- TemporalVoter (Fase 24): confianza agregada = media de scores del ganador (no el máximo) y el ratio de veredicto se calcula sobre el total de votos de la ventana (incluidos los `None`), para que identidades alternadas no confirmen ninguna
- IdentityStateMachine (Fase 24, 24-02): `_claim_lost` (herencia de identidad por `person_id`) se consulta también desde la rama UNKNOWN, no solo CANDIDATE — un track nuevo con un primer match ya intenta heredar una identidad `TEMPORARILY_LOST` antes de pasar por votación completa (Pitfall 3 del RESEARCH, FACE-09/FACE-10)
- IdentityStateMachine (Fase 24, 24-02): el reset del contador de fallos de revalidación exige coincidencia del frame actual (`person_id == st.person_id`), no el veredicto agregado del voter — necesario porque `needs_recognition()` espacia las inferencias ~120 s y el voter retiene votos históricos varios ciclos
- PersonRecognizer (Fase 24, 24-03): retirada por completo la votación interna por mayoría (`_votes`/`VOTE_WINDOW=5`) — mantenerla habría encadenado dos votaciones delante de `TemporalVoter`, invalidando sus parámetros configurados; el match ahora es por frame y `process_crop_scored()` expone el score real para que la agregación temporal viva solo en `TemporalVoter`/`IdentityStateMachine`
- EventEngine.emit_identity (Fase 24, 24-04): nunca pasa `severity=` explícita, para que `UNKNOWN_PERSON` conserve el `WARNING` por defecto del catálogo (`_apply_default_severity` solo actúa si `severity` no está en `model_fields_set`); las transiciones intermedias (destino `CANDIDATE`/`TEMPORARILY_LOST`) no generan evento — la UI las lee directamente del `TrackRegistry`
- RecognitionWorker/TrackRegistry (Fase 24, 24-05, D-05 bloqueante): `_sync_identity` detecta tracks perdidos con `TrackRegistry.frame_ids()` (el set exacto de tracks del frame actual, escrito por `DetectionWorker`), nunca con `active_ids()` (TTL de 30s de `prune()`) — con `active_ids()`, un track recuperado con un `track_id` nuevo dentro del TTL habría confirmado como visita nueva en vez de heredar la identidad (segundo `PERSON_RECOGNIZED`, rompe FACE-10). `set_frame_ids()` se publica ANTES de la guarda `if event_engine is None` en `_emit_track_lifecycle`, porque la construcción por defecto de `DetectionWorker` no lleva `event_engine`
- IdentityStateMachine en manager.py (Fase 24, 24-05): se construye FUERA de la factoría `_make_recognition` que registra el `WorkerSupervisor`, para que un reinicio del worker no pierda la identidad ya confirmada — mismo motivo por el que `_make_streaming` rescata `clients`
- Criterio 6 (Fase 24, 24-05, D-01): medido sobre un track NO confirmado (persona estática cuyo reconocimiento nunca tiene éxito), no sobre uno ya identificado — con baseline real medido en la misma ejecución del test (16 inferencias/s sin FSM → 2 con FSM, 87.5% de reducción, umbral exigido ≥70%)
- Puerta de fase (Fase 24, 24-06): la suite ya estaba verde (377/377) y FACE-07..FACE-11 ya marcados desde 24-01/24-02 al cierre de `24-05` — `24-06` no requirió ningún fix de código, solo trazabilidad criterio→comando→test en `24-06-SUMMARY.md`
- ReIDEngine (Fase 25, 25-01): la salida cruda del modelo OSNet NO está L2-normalizada (norma ~52,4 medida) — `embed()` normaliza explícitamente antes de devolver, porque SPEC_v2.md §5.6 y el futuro coseno de `TrackGallery` dan por hecho un vector unitario
- scripts/fetch_models.py (Fase 25, 25-01): el export público de OSNet trae el eje de batch fijo a 16 (una inferencia suelta costaría 84,5 ms en vez de 4,97 ms, criterio 1 fallado por 4x) — el script reescribe ese eje a simbólico antes de guardar el fichero en `models/` (gitignored), verificando sha256 y tamaño exacto antes de escribir; `ReIDEngine` además se autodeshabilita si detecta batch fijo != 1, por si el script no se ejecutó
- IdentityStateMachine.on_reid_result (Fase 25, 25-02): la herencia de identidad por apariencia entra por la FSM, nunca por el worker — resolver la herencia fuera de la FSM deja huérfana la entrada `TEMPORARILY_LOST` en `_states`, y 30 s después `on_tick()` emitiría un `IDENTITY_LOST` espurio de una persona ya reetiquetada delante de la cámara (Pitfall 4); el método fija `last_face_at = now` al heredar porque sin eso el barrido de rancios de `on_tick` (`stale_ttl = lost_ttl + revalidate_after * MAX_FAILED_REVALIDATIONS`) purgaría el estado recién heredado (Pitfall 5); nunca vota en `TemporalVoter` para no contaminar los parámetros medidos de FACE-07
- TrackGallery.resolve (Fase 25, 25-03): calcula SIEMPRE el candidato real `(person_id, similitud)`, incluso cuando no se hereda por umbral no superado o conflicto — la política de si aplicar la herencia (modo solo-observación vs aplicar) vive en el flag del worker, cableado en `25-04`; el umbral es estricto (`sim > 0.7`, no `>=`), coherente con la redacción del criterio 2 del ROADMAP
- TrackGallery._enforce_cap (Fase 25, 25-03): la cota dura de 256 entradas se invoca tanto desde `update()` como desde `prune()` — mismo patrón "seguro de vida" de la Fase 22, verificado con un test que nunca llama a `prune()`
- tests/test_track_gallery.py (Fase 25, 25-03): vectores 512D construidos a mano con coseno exacto (`cos*e_base + sqrt(1-cos^2)*e_other`), nunca ruido aleatorio — el research midió coseno 0,991 entre dos embeddings de OSNet alimentados con ruido independiente (colapso fuera de distribución) que invalidaría cualquier test de umbral
- RecognitionWorker._reid_pass (Fase 25, 25-04): `reid_inherit` es un flag del worker, no de `TrackGallery` — `resolve()` siempre calcula el candidato real y el worker decide si lo aplica (`on_reid_result()`) o solo lo audita (contadores + log INFO, modo solo-observación del criterio 4); `self._rate.observe()` nunca se llama desde la vía ReID para no contaminar `avg_latency` de `/api/v2/cameras/{id}/health` (instrumentación propia con `stage="reid"`)
- RecognitionWorker._next_reid_candidate (Fase 25, 25-04, bug encontrado en el test del criterio 3): exige `track_id in registry.frame_ids()`, no solo `TrackGallery.needs_embedding()` — sin este filtro, un track `TEMPORARILY_LOST` que aún no ha sido podado por `DetectionWorker` (TTL 30 s por defecto) se re-embebía con `identity_of()==None` (identity.py solo devuelve `person_id` si el track está `CONFIRMED`), borrando en la galería la identidad que ReID necesita conservar para que otro track la reclame después — justo lo contrario del criterio 3
- backend/config.py (Fase 25, 25-05): `reid_inherit_window_secs` (15 s) es deliberadamente MÁS CORTA que `identity_lost_ttl_secs` (30 s, Fase 24) — la apariencia es menos fiable que la votación facial y debe caducar antes; `reid_inherit_identity=False` por defecto (fail-safe, T-25-17): ReID calcula y registra la herencia sin aplicarla hasta que el operador la active explícitamente
- CameraPipeline (Fase 25, 25-05): `self.reid_engine`/`self.reid_gallery` se construyen junto a `self.identity_fsm`, FUERA de `_make_recognition` — mismo motivo que la FSM de la Fase 24: el `WorkerSupervisor` re-ejecuta la factoría en cada reinicio del worker, y construirlos dentro vaciaría la galería de apariencia y recargaría el ONNX en cada reinicio
- Puerta de fase (Fase 25, 25-06): no hizo falta ningún fix de código — la suite ya estaba verde (413/413) y REID-01..REID-04 ya estaban marcados `[x]` desde 25-01/25-02/25-03; el checkpoint del criterio 4 (tasa de falsos positivos con personas reales) se difiere explícitamente por falta de acceso a cámara en la sesión, sin bloquear el avance a la Fase 26 porque `reid_inherit_identity=False` sigue siendo el default y la mitad determinista del criterio ya está probada
- BehaviorAnalyzer (Fase 26, 26-01): `BehaviorFinding` es dominio puro (no `Event`), mismo patrón que `IdentityTransition` — corrige la firma `analyze(...) -> list[Event]` de SPEC_v2.md §5.7 (26-RESEARCH.md D-3); IMMOBILE usa la caja envolvente (`span`) del recorrido y no la distancia al ancla, porque la distancia permitiría un diámetro real de 2R; LOITERING usa una ancla independiente por `(track, zona)` — sin zonas configuradas cae a `zone_id=None` (escena implícita, D-02) salvo `loiter_require_zone=True`, y con zonas solapadas emite un finding por zona (D-04); los 4 comportamientos (no solo CROWD) llevan latch por episodio con re-armado por histéresis (`REARM_RATIO=0.8` en RUNNING/CROWD) — sin latch, una persona parada 10 min generaría miles de eventos IMMOBILE; `_enforce_cap()` se invoca también desde `analyze()` además de `prune()`, mismo "seguro de vida" de la Fase 22/25
- EventEngine.emit_behavior (Fase 26, 26-03): nunca pasa `severity=` explícita, para que `@model_validator` de `Event` aplique el default `INFO` del catálogo (D-01) y los comportamientos no crucen `upload_min_severity="warning"`; `process_zone()` añade `now_monotonic` AL FINAL de la firma (aditivo, compatible con el único llamador posicional) porque `captured_at`/`processed_at` son conceptos privados de latencia OBS-03, no un reloj semántico — restar dos `datetime.datetime.now()` sería sensible a saltos de reloj por NTP; `duration_s` es la clave literal del payload porque `rules.py:88-91` la lee tal cual para `duration_gte`; `_zone_entry_at` se acota con `pop()` en el mismo bucle que emite `ZONE_EXITED` (mismo "seguro de vida" que `TrackGallery`/`BehaviorAnalyzer` de las Fases 25/26)
- DetectionWorker/manager.py (Fase 26, 26-04): `_analyze_behavior` toma los ids del frame de `tracked.tracker_id` directamente, nunca de `self._registry.frame_ids()` — `set_frame_ids()` se llama dentro de `_emit_track_lifecycle`, que corre DESPUÉS en `_loop`, así que leer `frame_ids()` en `_analyze_behavior` vería el frame anterior; `self.behavior` se construye en `CameraPipeline.__init__` ANTES del bloque `if detector is not None and tracker is not None`, gateado solo por `behavior_enabled`, y se pasa como último kwarg dentro de `_make_detection` — mismo motivo que `identity_fsm`/`reid_gallery`: el `WorkerSupervisor` re-ejecuta la factoría en cada reinicio y construir el analizador dentro borraría las anclas y latches, produciendo una ráfaga de eventos duplicados
- backend/config.py (Fase 26, 26-02): `validate_behavior_params` acota `run_window_secs <= 12.0` — es la misma clase de guarda que `validate_identity_params` (impide una configuración que nunca podría cumplirse), aquí contra el límite real de `centroid_history` (`tracking.py:47`, `deque(maxlen=150)`) al peor caso de FPS (`rate.py:26`, `AdaptiveRate.STEPS[0]=12.0`) — sin esta cota, un operador podría configurar una ventana de RUNNING que jamás se calcularía; `loiter_require_zone=False` por defecto (fallback D-02) para que una instalación limpia sin zonas configuradas siga pudiendo emitir LOITERING
- backend/config.py (Fase 27, 27-02, D-03): `yolo_model_path` por defecto pasa de `yolov8n.pt` a `yolo26n.pt` — corrige la deriva respecto a CLAUDE.md; se aplica en este plan y no antes porque el criterio 6 (latencia con 6 clases) se mide despues, sobre la ruta de post-proceso NMS-free de `yolo26n.pt`. `validate_object_params` sigue el molde de `validate_behavior_params` y rechaza explicitamente la clase 0 (person) en `object_class_ids` — desviarla ahi perderia el `LineZone`/identidad/comportamiento del `PersonTracker`
- PersonDetector.set_classes (Fase 27, 27-02): mutacion en caliente de `self._classes` (rebind atomico, sin lock) en vez de reconstruir el detector — mismo motivo que `PersonTracker.set_frame_rate`, pero con coste mayor si se reconstruyera: `WorkerSupervisor._check()` cuenta cualquier parada del worker como caida y tres reinicios en 60 s lo dejarian en `FAILED` permanente
- ObjectAnalyzer (Fase 27, 27-01): `ObjectObservation`/`PersonObservation` (dataclasses con 6 atributos) en vez de los `dict[int, tuple]` de `BehaviorAnalyzer` — varios dicts paralelos por objeto serían un criadero de bugs de desincronización; `prune()` devuelve `list[ObjectFinding]` (a diferencia de `BehaviorAnalyzer.prune` que devuelve `None`) porque `OBJECT_REMOVED` se decide ahí, no en `analyze()`, para exigir `gone_secs` de gracia contra oclusiones de un frame; `stable` se deriva de `object_gone_secs` sin parámetro nuevo (mínimo tiempo quieto para considerarse "establecido" = la misma ventana de gracia con la que se declara la desaparición); asimetría deliberada entre el radio de persona en `OBJECT_LEFT` (negativo: pasarse de grande suprime eventos, lado seguro) y en `OBJECT_REMOVED` (positivo: pasarse de grande es peligroso)
- ObjectTracker (Fase 27, 27-03): análogo por sustracción de `PersonTracker` — mismo `sv.ByteTrack`+`LOST_TRACK_BUFFER`+`set_frame_rate`, SIN `DetectionsSmoother` (congelaría `class_id` hasta 5 frames) y SIN `LineZone` (el conteo de la Fase 4, en producción, es solo de personas); `PersonTracker` queda intacto, verificado por `git diff` sin líneas `-`
- EventEngine.emit_object (Fase 27, 27-05): nunca pasa `severity=` explicita — a diferencia de los 4 comportamientos de la Fase 26 (que se quedaron en INFO a proposito), aqui `OBJECT_LEFT` hereda `WARNING` del catalogo y por tanto SUBE EL CLIP A GOOGLE DRIVE al cruzar `upload_min_severity`; decision cerrada con el usuario (T-27-19). `bbox` viaja como campo de primer nivel del `Event` (los eventos de objeto llevan caja, los de comportamiento no). `config_changed()` es el primer emisor de `CONFIG_CHANGED` desde que existe en el catalogo (Fase 19) — unica mitigacion de repudio disponible sin roles en el sistema (ASVS V4, T-27-20)
- DetectionWorker._split_by_class (Fase 27, 27-03): la partición por `class_id` (`np.isin` contra `PERSON_CLASS_IDS=(0,)`) ocurre DENTRO del `try` de inferencia ya existente, para que un `sv_dets` malformado siga cayendo en el mismo `except`; `PersonTracker.update` recibe siempre `person_dets`, nunca `sv_dets` completo — sin esto, un objeto (coche, mochila) sumaría al conteo de línea de la Fase 4 o entraría en `TrackRegistry`/reconocimiento facial. Los objetos NUNCA entran en `TrackRegistry`: su estado vive en `self._object_boxes` bajo `self._lock` (mismo patrón que `_zone_states`), con escritor único (hilo de detección) y lectores desde fuera (`get_object_boxes`/`get_object_stats`, copias defensivas). `self._rate.observe()` sigue midiendo solo la vía de personas — la vía de objetos nunca la llama, mismo patrón que ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26)
- Riesgo de primer orden verificado con test de reproducción (Fase 27, 27-03): `sv.ByteTrack` es class-agnostic (el tensor del matcher usa solo `xyxy`+`confidence`, `supervision/tracker/byte_tracker/core.py:104-110`) — `TEST_bytetrack_ids_do_not_migrate_between_classes` reproduce literalmente que un `sv.ByteTrack` COMPARTIDO transfiere el id de una mochila "perdida" a una persona casi en la misma caja, y demuestra que con `ObjectTracker`+`PersonTracker` separados no ocurre
- DetectionWorker._analyze_objects / CameraPipeline (Fase 27, 27-06): `findings += self._objects.prune(...)` se recoge explícitamente — a diferencia de `BehaviorAnalyzer.prune` (devuelve `None`), el `prune()` de `ObjectAnalyzer` decide `OBJECT_REMOVED` y su retorno no se puede ignorar sin perder la mitad del requisito BEH-07; `_excluded_object_ids`/`_object_zone_ids` reutilizan `sv.PolygonZone.trigger()` sobre los mismos `_zone_states` (con `kind` ya propagado desde `27-04`) en vez de escribir geometría punto-en-polígono propia. `self.objects`/`self.object_tracker` se construyen en `CameraPipeline.__init__` ANTES de `_make_detection` — cuarto precedente del mismo patrón que la FSM (Fase 24), la galería ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26): reconstruirlos en cada reinicio del `DetectionWorker` reabriría la ventana de warmup y reiniciaría los `track_id` de objeto, emitiendo una ráfaga de `OBJECT_LEFT` (`WARNING`) que subiría un clip a Google Drive por cada mueble fijo de la escena
- backend/api/v2/detection.py (Fase 27, 27-07): el PUT persiste en `app_config` (`ConfigRepo.set`) ANTES de propagar al pipeline y emitir `CONFIG_CHANGED` — si el proceso muriera entre ambos pasos, el arranque siguiente (precedencia BD > env var) aplicaria lo que el operador pidio en vez de perderlo; `LOCKED_CLASS_IDS={0}` rechaza con 400 cualquier PUT que no incluya "person" (decision cerrada con el usuario, el frontend de `27-10` ademas la muestra marcada y deshabilitada)
- backend/main.py `_resolve_active_classes` (Fase 27, 27-07): logica de precedencia extraida a funcion modulo-privada para poder testearla sin arrancar el lifespan completo — mejora prevista explicitamente por el plan; `if persisted` (no `is not None`) trata una fila `[]` guardada por error como ausente, nunca como "no detectes nada"
- StreamingWorker/manager.py (Fase 27, 27-08): `object_boxes` es un `Callable[[], list[dict]] | None` inyectado en el constructor (via pull), nunca un setter tipo `set_zone_overlay` (patron muerto, sin llamadores, 27-PATTERNS.md § No Analog Found); `manager.py` pasa `self.get_object_boxes` (metodo bound de `CameraPipeline`) directamente, sin envolverlo en una lambda — un metodo bound resuelve `self.detection` en cada llamada, asi que sobrevive a un reinicio del `DetectionWorker` sin volver a pasar la referencia. Color magenta `(255, 0, 255)` BGR, deliberadamente distinto del naranja de zonas `(0, 200, 255)` — decision cerrada con el usuario en 27-RESEARCH.md Open Question #1
- Puerta de fase (Fase 27, 27-11): no hizo falta ningún fix de código — la suite ya estaba verde (519/519) y BEH-07 ya estaba `[x]` desde `27-01`; `27-11` marca BEH-06/BEH-08/BEH-09 y traza los 6 criterios del ROADMAP a comandos `pytest -k`. Las decisiones clave de la fase quedan resumidas aquí: (1) `sv.ByteTrack` es class-agnostic (reproducido en `27-RESEARCH.md` Q4 y en `TEST_bytetrack_ids_do_not_migrate_between_classes`) — la partición por clase ANTES del tracker y un `ObjectTracker` dedicado son obligatorios, no una optimización, o un track de objeto puede transferir su id a una persona solapada y contaminar el `LineZone` de la Fase 4; (2) los objetos nunca entran en `TrackRegistry` — su estado vive en `self._object_boxes` bajo `self._lock`, mismo patrón que `_zone_states`; (3) `self.objects`/`self.object_tracker` (y el resto de estado de la fase) se construyen en `CameraPipeline.__init__` ANTES de `_make_detection`/`_make_recognition`, fuera de la factoría del `WorkerSupervisor` — cuarto precedente tras FSM (Fase 24), galería ReID (Fase 25) y `BehaviorAnalyzer` (Fase 26); (4) la BD (`app_config`) gana sobre `YOLO_CLASSES` al arrancar, y una fila `[]` persistida se trata como ausente para no dejar el sistema ciego en silencio; (5) `person` (clase 0) siempre viaja forzada/activa y bloqueada en el catálogo — ningún PUT puede desactivarla; (6) `OBJECT_LEFT` se mantiene en `Severity.WARNING` (decisión del usuario) y por tanto cruza `upload_min_severity="warning"` y sube clips a Drive desde el primer evento — exige calibrar `object_person_radius_px` con cámara real antes de operar desatendido (checkpoint diferido de este plan); (7) el nivel de actividad de BEH-09 se normaliza a tasa por minuto en baseline y "ahora" para no sesgar `"low"` al principio de cada hora, y cae a `"unknown"` con menos de `context_min_sample_days` de historial; (8) `yolo_model_path` por defecto corregido a `yolo26n.pt` (D-03), alineado con CLAUDE.md. El checkpoint de calibración de `object_person_radius_px` (150 px, 1,9× `loiter_radius_px`) y de la tasa de falsos positivos de `OBJECT_LEFT` se difiere explícitamente — 9º checkpoint manual pendiente, no bloquea avanzar a la Fase 28
- Puerta de fase (Fase 26, 26-05): no hizo falta ningún fix de código — `tests/test_rule_engine.py` ganó 3 tests que recorren el camino real (YAML en `tmp_path` + `load_rules` + `evaluate`) para demostrar el criterio 5 sin tocar `backend/events/rules.py` ni `config/rules.yaml`, y BEH-01..BEH-05 ya estaban `[x]` desde planes anteriores. Las seis decisiones clave de la fase quedan resumidas aquí: (1) el historial de 120 s se disuelve con agregados incrementales O(1) en vez de ampliar `history_len` (584 B/track medidos frente a 141,8 KB si se hubiera ampliado a 1000, `tracking.py` intacto); (2) los CUATRO comportamientos llevan latch por episodio, no solo CROWD — sin él, una persona parada 10 min generaría miles de eventos IMMOBILE, y `debounce_secs` de `rules.yaml` no sustituye al latch porque actúa después de persistir y difundir; (3) `analyze()` devuelve `list[BehaviorFinding]`, no `list[Event]` (D-3, corrige SPEC §5.7) — `perception/` no conoce `camera_id` ni el reloj de pared; (4) semántica de zonas: LOITERING cae a escena implícita (`zone_id=None`) sin zonas configuradas salvo `loiter_require_zone=True` (D-02), LOITERING e IMMOBILE coexisten (D-03), y con zonas solapadas se emite un finding por zona (D-04); (5) la clave del payload es `duration_s` literal porque `rules.py:88-91` la lee así para `duration_gte` — cualquier otro nombre rompe el criterio 5 en silencio; (6) los 4 comportamientos se quedan en `Severity.INFO` por defecto (D-01, cambio cero) — subirlos a WARNING habría activado la subida automática de clips a Google Drive. El checkpoint de calibración de umbrales con cámara real (Task 3) se difiere explícitamente — 8º checkpoint manual pendiente, no bloquea avanzar a la Fase 27

### Pendiente manual (no es código)

- Descargar `credentials.json` de Google Cloud Console (OAuth 2.0 → Desktop app)
  y colocarlo en la raíz del proyecto para habilitar upload a Google Drive
- Carpeta Drive destino: «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`)

### Blockers/Concerns

Ninguno bloqueante para el desarrollo de v2.0. Ver "Pendiente sin relacion
con v2.0" arriba (token OAuth de Google Drive caducado) y los 9 checkpoints
manuales con cámara real listados en la tabla de fases — ninguno bloquea
avanzar a la Fase 28, pero deben cerrarse antes de dar el bloque A, la
Fase 23, la Fase 25, la Fase 26 y la Fase 27 por completamente validados
en producción.

## Session Continuity

Last session: 2026-08-17
Stopped at: Ejecutado 27-11-PLAN.md (puerta de fase, wave 6, depende de
  27-08+27-09+27-10). Suite completa reejecutada verde: `pytest tests/ -q`
  → 519/519, sin cambios de código. Trazabilidad de los 6 criterios de
  éxito del ROADMAP a comandos `pytest -k` que pasan, más la regresión
  ByteTrack (`TEST_object_class_does_not_reach_line_zone`,
  `TEST_objects_not_in_registry`, `TEST_bytetrack_ids_do_not_migrate_between_classes`)
  — ver la tabla completa en `27-11-SUMMARY.md`. `REQUIREMENTS.md`:
  BEH-06/BEH-08/BEH-09 marcados `[x]` (BEH-07 ya lo estaba desde `27-01`).
  `ROADMAP.md`: Fase 27 marcada `[x]` en el bloque B y "11/11 plans
  complete (6 waves)" en el detalle. El checkpoint de calibración de
  `object_person_radius_px` y de la tasa de falsos positivos de
  `OBJECT_LEFT` con cámara real se **difiere** explícitamente (9º
  checkpoint manual, sin cámara en esta sesión, mismo patrón que los 8
  anteriores) — no bloquea el cierre de la Fase 27 en código/tests ni el
  avance a la Fase 28. Sin desviaciones de código. **Fase 27 completa:
  11/11 planes.** Siguiente: `/gsd:plan-phase 28`.
Resume file: ninguno — Fase 27 completa. Siguiente paso: planificar la
  Fase 28 con `/gsd:plan-phase 28`.

Sesión anterior (2026-08-17): Ejecutado 27-08-PLAN.md (wave 4, depende de 27-03+27-06). `StreamingWorker`
  (`backend/pipeline/streaming.py`) acepta `object_boxes: Callable[[], list[dict]] | None = None`
  en el constructor (via pull, mismo patron que `registry`/`tracker` — `set_zone_overlay` se
  descarto por no tener llamadores) y `_annotate` dibuja cada caja de objeto en magenta
  `(255, 0, 255)` con etiqueta `class_name #track_id`, tras el bloque de zonas. `manager.py`:
  `_make_streaming` pasa `object_boxes=self.get_object_boxes` (metodo bound de `CameraPipeline`,
  27-06) sin logica nueva. 4 tests nuevos `TEST_*` (3 en `test_streaming_worker.py` sobre
  `_annotate` en aislamiento, 1 en `test_detection_worker.py` de identidad de referencia del
  Callable cableado por la factoria del supervisor) — ver `27-08-SUMMARY.md`. Suite completa
  512/512 (508 previos + 4). Sin desviaciones de codigo (una nota sobre un detalle menor del
  propio criterio de aceptacion del plan, documentada en `27-08-SUMMARY.md` § Deviations).
  BEH-06 contribuido pero NO marcado en REQUIREMENTS.md (mismo criterio que 27-06/27-07: el
  ROADMAP cierra BEH-06/07 en la puerta de fase 27-11). Fase 27: 8/11 planes. Siguiente:
  `/gsd:execute-phase 27` para continuar con `27-09` (endpoint de contexto de escena).
Resume file: ninguno registrado todavía para `27-09` — generar/ejecutar con
  `/gsd:execute-phase 27`.

Sesión anterior (2026-08-17): Ejecutado 27-07-PLAN.md (wave 4, depende de 27-02+27-04+27-06). Router
  `GET/PUT /api/v2/detection/classes` en `backend/api/v2/detection.py` con persistencia en
  `app_config` (precedencia sobre `YOLO_CLASSES`), las 4 validaciones con 400 y `detail` en
  lenguaje llano, y `CONFIG_CHANGED` como rastro — ver detalle en `27-07-SUMMARY.md`. Suite
  completa 508/508. Fase 27: 7/11 planes. Siguiente: `/gsd:execute-phase 27` para continuar
  con `27-08` (overlay MJPEG).

Sesión anterior (2026-08-17): Ejecutado 27-06-PLAN.md (wave 3, depende de 27-01+27-03+27-04+27-05).
  `_analyze_objects` cableado en `DetectionWorker._loop` justo despues de `_analyze_behavior`:
  construye `ObjectObservation`/`PersonObservation` con anclas `BOTTOM_CENTER`, recoge
  `findings += self._objects.prune(...)` explicitamente (el retorno NO se ignora, a
  diferencia de `BehaviorAnalyzer.prune`), y emite via `EventEngine.emit_object` fuera del
  `try` de aislamiento de fallos. `_excluded_object_ids`/`_object_zone_ids` reutilizan
  `sv.PolygonZone.trigger()` sobre los mismos `_zone_states` (nueva clave `kind` propagada en
  `_rebuild_zone_states`), sin geometria propia. `CameraPipeline.__init__`: `self.objects`/
  `self.object_tracker` construidos ANTES de `_make_detection`, gateados por
  `objects_enabled` — cuarto precedente de estado que sobrevive a un reinicio del
  `DetectionWorker` (FSM Fase 24, ReID Fase 25, `BehaviorAnalyzer` Fase 26). Fachada
  `set_detection_classes`/`get_object_stats`/`get_object_boxes`; `set_detection_classes` muta
  detector+reparto sin reiniciar ningun worker (test explicito `stop.assert_not_called()`).
  `backend/main.py` propaga los 10 parametros `object_*`/`objects_enabled`. 8 tests nuevos
  `TEST_*` en `tests/test_detection_worker.py`. Suite completa 500/500 (492 previos + 8). Dos
  discrepancias de conteo en los `<verify>` automatizados del propio plan, documentadas y sin
  impacto funcional (ver `27-06-SUMMARY.md` § Deviations): `grep -c "object_" backend/main.py`
  da 9 no >=10 (`objects_enabled` no matchea por la "s" de plural; nombre fijado por el
  contrato LOCKED) y `pytest -k object` recoge 12 no >=13 (3 de los 7 tests de `27-03` no
  contienen la palabra "object" en su nombre). BEH-06/07 NO se marcan `[x]`: el ROADMAP
  asigna esa puerta a `27-11`. Quedan `27-07`..`27-11` (router de clases activas, overlay
  MJPEG, endpoint de contexto, control de clases en el dashboard y puerta de fase). Siguiente:
  `/gsd:execute-phase 27` para continuar con `27-07`.
Resume file: ninguno registrado todavía para `27-07` — generar/ejecutar con
  `/gsd:execute-phase 27`.

Sesión anterior (2026-08-17): Ejecutado 27-04-PLAN.md (media movil horaria + kind de zona,
  wave 1, sin dependencias de codigo). backend/storage/repositories.py:
  DetectionStatRepo.hourly_baseline() con doble GROUP BY (subquery por dia+hora, luego avg
  por hora) sobre unique_tracks, parametro until para excluir la hora en curso, todo
  parametros ligados. backend/database.py: kind en el Zone legacy (copiado caracter a
  caracter de storage/models.py) y en get_zones(), que main.py:468 usa para alimentar al
  DetectionWorker. Sin indice nuevo ni migracion (confirmado con git diff --stat vacio en
  models.py/migrations.py). tests: +7 tests TEST_* (5 de hourly_baseline: orden de
  agregacion, sample_days, until, filtro por camara, ventana vacia; 1 de ConfigRepo roundtrip
  de list[int]; 1 de get_zones_returns_kind). Suite completa 487/487. Sin desviaciones.

Sesión anterior (2026-08-17): Ejecutado 27-02-PLAN.md (wave 1, sin dependencias reales de
  código). D-03: `yolo_model_path` por defecto pasa de `yolov8n.pt` a `yolo26n.pt`
  (end2end=True, NMS-free). 10 parámetros `object_*` y 4 `context_*` en `backend/config.py`
  con los defaults del research, más `validate_object_params` (rechaza clase 0/person en
  `object_class_ids`, ratios fuera de rango, ids COCO inválidos,
  `context_low_ratio >= context_high_ratio`). `PersonDetector.set_classes()`
  (`backend/detector.py`): mutación en caliente de `self._classes` con rebind atómico (sin
  lock, mismo patrón que `PersonTracker.set_frame_rate`), verificado que no recarga el
  modelo (`id(self._model)` no cambia). 5 tests nuevos: 3 en `tests/test_config.py`
  (default `yolo26n.pt`, defaults de los 14 parámetros, rechazo de las 6 configuraciones
  imposibles) + 2 en `tests/test_detector.py` (`TEST_set_classes_changes_next_inference` y
  `TEST_multiclass_latency_under_15_percent`, el benchmark del criterio 6 del ROADMAP con
  pesos reales de `yolo26n.pt` sobre `bus.jpg`, sin skip). Suite completa 473/473 (468
  previos + 5). Sin desviaciones de código — ver `27-02-SUMMARY.md`.

Sesión anterior (2026-08-16): Ejecutado 26-05-PLAN.md (criterio 5 `when.event` desde YAML
  real + puerta de fase, wave 4, depende de `26-01`..`26-04`). Los 3
  tasks: (1) `tests/test_rule_engine.py` gana `BEHAVIOR_RULES_YAML`
  (4 reglas, una por evento de comportamiento) y 3 tests que recorren
  el camino real (`tmp_path` + `load_rules` + `evaluate`) —
  `TEST_behavior_events_usable_as_when_event` (`errors == []`, 4
  reglas), `TEST_behavior_duration_gte_reads_duration_s` (dispara con
  `duration_s=130.0`, no dispara con `90.0` ni con la clave equivocada
  `duration=130.0` — regresión explícita del pitfall de naming),
  `TEST_behavior_zone_filter_uses_first_class_zone_id` (`zone: "z1"`
  filtra sobre `zone_id` de primer nivel del `Event`) — sin tocar
  `backend/events/rules.py` ni `config/rules.yaml` (criterio 5 es cero
  código); (2) puerta de fase: suite completa **454/454** (451 previos
  + 3), los 5 criterios del ROADMAP trazados a comandos `pytest -k` que
  pasan (ver tabla en `26-05-SUMMARY.md`), con el criterio 2 repartido
  explícitamente entre los 4 tests de trayectoria de `26-01`
  (comportamiento) y los tests ya existentes de
  `EventEngine.process_zone` (2 trayectorias de zona, propiedad de la
  Fase 19); BEH-01..BEH-05 confirmados `[x]` en `REQUIREMENTS.md`
  (ya lo estaban desde planes anteriores); `ROADMAP.md`/`STATE.md`
  actualizados (Fase 26 completa, 5/5 planes); (3) checkpoint de
  calibración de umbrales con cámara real (`run_speed_px_s`,
  `loiter_radius_px`, `immobile_radius_px`) **diferido** explícitamente
  — sin acceso a cámara en esta sesión, mismo patrón que los 7
  checkpoints anteriores (25-06 Task 2 fue el último); los defaults de
  SPEC_v2.md §5.7 (350 px/s, 80 px, 20 px) ya están cubiertos por tests
  deterministas con trayectorias sintéticas y no bloquea avanzar a la
  Fase 27. Sin desviaciones de código, ver `26-05-SUMMARY.md`.
  **Fase 26 completa: 5/5 planes.** Siguiente: `/gsd:plan-phase 27`.
Resume file: ninguno — Fase 26 completa. Siguiente paso: planificar la
  Fase 27 con `/gsd:plan-phase 27`.
