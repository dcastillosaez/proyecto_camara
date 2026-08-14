---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Ejecutado 25-04-PLAN.md (wave 3, cuarto plan de la Fase 25): via ReID cableada dentro de RecognitionWorker — _face_pass/_reid_pass extraidos de _loop corren cada tick sin bloquearse mutuamente, _next_reid_candidate con gate propio (TrackGallery.needs_embedding(), no needs_recognition()) y filtrado a tracks visibles en frame_ids(), flag reid_inherit en el worker (resolve() siempre calcula, on_reid_result() solo se aplica si el flag esta activo), 4 contadores reid_* en stats, TrackGallery.prune() en _sync_identity. Bug real encontrado y corregido durante el test end-to-end del criterio 3: sin el filtro frame_ids(), un track TEMPORARILY_LOST aun no podado se re-embebia y gallery.update() le escribia identity_of()==None, borrando la identidad que ReID necesita conservar. 5 tests nuevos (presupuesto criterio 5, modo solo-observacion criterio 4, contadores en stats, compatibilidad sin ReID, y el end-to-end del criterio 3 verificado 3/3 sin flaky). Suite 407/407. Quedan 25-05..25-06. Quedan 6 checkpoints con camara real de fases anteriores, sin relacion con esta fase (19-01 Task 5, 19-02 Task 5, 20-02 Task 4, 21-01 Task 5, 22-01 Task 4, 23-02 Task 4)."
last_updated: "2026-08-15"
last_activity: 2026-08-15
progress:
  total_phases: 22
  completed_phases: 8
  total_plans: 25
  completed_plans: 23
  percent: 36
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
Phase: **Bloque A (17-22) + Fase 23 + Fase 24 COMPLETOS** en código y tests. **Fase 25 en ejecución** (4/6 planes completos, 25-01..25-04).
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
  Quedan **6 checkpoints con cámara real** sin ejecutar, ninguno
  bloqueante para seguir programando: 19-01 Task 5 (migrar BD real),
  19-02 Task 5 (validación de reglas en vivo), 20-02 Task 4 (validación
  visual del pre-buffer), 21-01 Task 5 (coste de instrumentación y
  línea base de 30 min), 22-01 Task 4 (resistencia de 8 h), y
  23-02 Task 4 (tasa de aciertos ArcFace vs dlib con datos reales).
Last activity: 2026-08-15

Progress v2.0: [███░░░░░░░] ~36% (8/22 fases completas)
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
/gsd:execute-phase 25
```

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
(ya completa) — está **en ejecución**: `.planning/phases/25-re-identificaci-n-de-personas-reid/`
tiene CONTEXT, RESEARCH, PATTERNS, VALIDATION y 6 PLAN.md (25-01..25-06,
5 waves), verificados por `gsd-plan-checker` sin blockers. `25-01` ya
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
extremo — ver `25-04-SUMMARY.md`. Queda por ejecutar `25-05`..`25-06`:
`25-05` añade los parámetros `reid_*` a `config.py` y los cablea en
`manager.py`/`main.py`.

Nota histórica — la Fase 23 (ya cerrada) abrió con una **puerta
bloqueante** (verificar que `insightface` + `onnxruntime` instalan y
ejecutan una inferencia real en Windows, con plan B en `SPEC_v2.md`
ADR-02 si no instalaban) que se resolvió con evidencia real antes de
planificar el resto de la fase — ver `23-CONTEXT.md`.

Los 6 checkpoints pendientes (bloque A + Fase 23) pueden ejecutarse en
cualquier momento que haya acceso a la cámara real; ninguno bloquea el
avance a la Fase 24, pero sí deberían cerrarse antes de dar el bloque A
y la Fase 23 por completamente validados en producción.

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
| 25 — Re-identificación (ReID) | B | ⧗ En ejecución (4/6 planes) | — | `25-01`..`25-04` completos (modelo OSNet + `ReIDEngine` REID-01; `on_reid_result()` REID-02/REID-03; `TrackGallery` REID-04; vía ReID cableada en `RecognitionWorker`); quedan `25-05`..`25-06` |
| 26 — Análisis de comportamiento | B | — Sin planificar | — | Depende de 25 |
| 27 — Multi-clase y contexto de escena | B | — Sin planificar | — | Depende de 26 |
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

Suite completa (43 ficheros en `tests/`): **407/407 passing** (última ejecución 2026-08-15, tras `25-04`: +5 tests `TEST_*` en `tests/test_recognition_worker.py` — presupuesto de inferencias criterio 5, modo solo-observación criterio 4, contadores en `stats`, compatibilidad sin ReID, y el end-to-end del criterio 3). Cifra anterior 402/402 tras `25-03` (+12 tests `TEST_*` en `tests/test_track_gallery.py` (nuevo fichero, `TrackGallery` con vectores 512D de coseno exacto) + 2 tests de cota en `tests/test_memory_bounds.py`. Cifra anterior 388/388 tras `25-02` (+7 tests `TEST_reid*` en `tests/test_identity_state_machine.py` — herencia, no-voto, no-secuestro, no-interferencia, ausencia de identidad perdida, `IDENTITY_LOST` espurio y barrido de rancios). 381/381 tras `25-01` (+4 tests en `tests/test_reid_engine.py`); 377/377 verificada en `24-06`).
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

### Pendiente manual (no es código)

- Descargar `credentials.json` de Google Cloud Console (OAuth 2.0 → Desktop app)
  y colocarlo en la raíz del proyecto para habilitar upload a Google Drive
- Carpeta Drive destino: «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`)

### Blockers/Concerns

Ninguno bloqueante para el desarrollo de v2.0. Ver "Pendiente sin relacion
con v2.0" arriba (token OAuth de Google Drive caducado) y los 6 checkpoints
manuales con cámara real listados en la tabla del bloque A — ninguno bloquea
avanzar a la Fase 24, pero deben cerrarse antes de dar el bloque A y la
Fase 23 por completamente validados en producción.

## Session Continuity

Last session: 2026-08-15
Stopped at: Ejecutado 25-04-PLAN.md (wave 3, cuarto plan de la Fase 25).
  Los 3 tasks completos: vía ReID cableada dentro de `RecognitionWorker`
  (`backend/pipeline/recognition.py`) — `_loop` extrae `_face_pass`/
  `_reid_pass`, ambas corren cada tick sin bloquearse mutuamente;
  `_next_reid_candidate` gatea sobre `TrackGallery.needs_embedding()`
  (criterio 5) y exige `track_id in frame_ids()`; flag `reid_inherit` en
  el worker (`resolve()` siempre calcula, `on_reid_result()` solo se
  aplica si el flag está activo — modo solo-observación del criterio 4);
  4 contadores `reid_*` en `stats`; `TrackGallery.prune()` en
  `_sync_identity`; instrumentación `stage="reid"` separada de
  `AdaptiveRate`. Bug real encontrado y corregido durante el test
  end-to-end del criterio 3: sin el filtro `frame_ids()`, un track
  `TEMPORARILY_LOST` aún no podado se re-embebía y `gallery.update()` le
  escribía `identity_of()==None`, borrando la identidad que ReID
  necesita conservar. 5 tests `TEST_*` nuevos en
  `tests/test_recognition_worker.py` (presupuesto criterio 5, modo
  solo-observación criterio 4, contadores en `stats`, compatibilidad sin
  ReID, y el end-to-end del criterio 3 verificado 3/3 sin flaky). Suite
  completa 407/407 (402 previos + 5 nuevos). REID-01..REID-04 cableados
  de extremo a extremo. **Fase 25: 4/6 planes completos.** Siguiente:
  `/gsd:execute-phase 25` continúa con `25-05` (parámetros `reid_*` en
  `config.py` + cableado en `manager.py`/`main.py`).
Resume file: `.planning/phases/25-re-identificaci-n-de-personas-reid/25-05-PLAN.md`
