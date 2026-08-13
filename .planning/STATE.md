---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Fase 24 (Identidad temporal) COMPLETA: 6/6 planes (24-01..24-06) ejecutados, FACE-07..FACE-11 cerrados, suite 377/377, los 6 criterios de exito del ROADMAP verificados con comando pytest -k en 24-06-SUMMARY.md. Siguiente: planificar Fase 25 (ReID) con /gsd:plan-phase 25. Quedan 6 checkpoints con camara real de fases anteriores, sin relacion con esta fase (19-01 Task 5, 19-02 Task 5, 20-02 Task 4, 21-01 Task 5, 22-01 Task 4, 23-02 Task 4)."
last_updated: "2026-08-13"
last_activity: 2026-08-13
progress:
  total_phases: 22
  completed_phases: 8
  total_plans: 19
  completed_plans: 19
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
Phase: **Bloque A (17-22) + Fase 23 + Fase 24 COMPLETOS** en código y tests (6/6 planes de la Fase 24 — `24-01`..`24-06`).
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
Last activity: 2026-08-13

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
/gsd:plan-phase 25
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

La Fase 25 (Re-identificación de personas, ReID) depende de la Fase 24
(ya completa) y aún no está planificada — generar su plan con
`/gsd:plan-phase 25`.

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
| 25 — Re-identificación (ReID) | B | — Sin planificar | — | Depende de 24 |
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

Suite completa (41 ficheros en `tests/`): **377/377 passing** (última ejecución 2026-08-13, verificada en `24-06` — puerta de fase de la Fase 24, sin cambios de código, misma cifra que tras `24-05`: cableado de `RecognitionWorker` a la FSM, `frame_ids()`/`set_frame_ids()`, recuperación de track por ruta real, reinicio del worker sin perder la FSM, y el criterio 6).
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

Last session: 2026-08-13
Stopped at: Ejecutado 24-06-PLAN.md (wave 5, puerta de fase — última de
  la Fase 24). La suite completa ya estaba verde (377/377) y
  FACE-07..FACE-11 ya estaban marcados `[x]` desde el cierre de `24-05`,
  así que la puerta no requirió ningún fix de código: solo verificación
  y trazabilidad. Los 6 criterios de éxito de ROADMAP § Phase 24 tienen
  cada uno un comando `pytest -k` que los selecciona y pasa (código 0,
  ninguno "no tests collected"), documentado en `24-06-SUMMARY.md` con
  el escenario exacto del criterio 6 (D-01: track NO confirmado, 16
  inferencias/s sin FSM -> 2 con FSM, 87.5% de reducción, umbral ≥70%),
  el contador usado (`stats["face_inferences"]`, no `face_fps`) y las
  consecuencias abiertas (regla `persona_desconocida` de
  `config/rules.yaml`, columna `identity_state` sin persistir, código
  muerto de `recognizer.py`, desajuste del CI Linux con
  `python_functions = TEST_*`). **Fase 24 completa: 6/6 planes,
  FACE-07..FACE-11 cerrados, suite 377/377.** Siguiente: planificar la
  Fase 25 (Re-identificación de personas, ReID) con `/gsd:plan-phase 25`.
Resume file: ninguno — Fase 24 cerrada, sin plan en ejecución.
