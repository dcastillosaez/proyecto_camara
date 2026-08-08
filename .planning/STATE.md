---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Fase 17 y 18 completas. Task 6 de 18-02 dada por suficiente: CPU/ritmo/aislamiento de crash verificados con camara real; 1h de latencia inconcluso por corte externo de RTSP en la camara (ver 18-02-CHECKPOINT.md). Siguiente: Fase 19."
last_updated: "2026-08-07"
last_activity: 2026-08-07
progress:
  total_phases: 22
  completed_phases: 2
  total_plans: 4
  completed_plans: 4
  percent: 9
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
Phase: 17 COMPLETA. Phase 18 (Workers desacoplados) — EN CURSO
Status: Fase 17: comparativa A/B + soak de 30 min contra la camara real
  (192.168.1.132) sin crecimiento de latencia, 0 reconnects, FPS estable
  ~15. pipeline_v2=True por defecto desde 2026-08-07. Grabacion de clips
  verificada end-to-end (upload a Drive pendiente de renovar token OAuth —
  no relacionado con v2.0).
  Fase 18-01 completa: AdaptiveRate (escalones + histeresis por rachas),
  TrackRegistry (estado compartido thread-safe, historial acotado) y
  DetectionWorker (deteccion desacoplada con ritmo adaptativo, zonas y
  heatmap portados). PersonTracker gano set_frame_rate() para sincronizar
  ByteTrack sin perder tracks. 155/155 tests.
  DetectionWorker todavia NO esta cableado en main.py — el dashboard en
  produccion sigue usando RTSPStream (pipeline v2 de la Fase 17) sin
  cambios visibles. Eso ocurre en 18-02 Task 5.
Last activity: 2026-08-07

Progress v2.0: [░░░░░░░░░░] ~7% (Fase 17 completa + 18-01/2 de la Fase 18)
Progress v1.2: [██████████] 100% (16/16 fases) — completado 2026-05-01

## Siguiente paso

```
/gsd:execute-phase 18 --wave 2
```

18-02-PLAN.md construye StreamingWorker, RecordingWorker,
RecognitionWorker y WorkerSupervisor, y en su Task 5 retira RTSPStream
sustituyendolo en backend/main.py — es el cambio de mayor riesgo del
milestone hasta ahora (toca el camino de ejecucion en produccion). Su
Task 6 es un checkpoint con camara real (medicion de CPU antes/despues,
prueba de crash de worker en vivo, 1h sin crecimiento de latencia) y
requiere confirmacion del usuario antes de arrancar dado el alcance.

## Pendiente sin relacion con v2.0

- Token OAuth de Google Drive caducado (`data/token.json`, `invalid_grant`).
  Requiere rehacer el flujo de autorizacion manualmente.

## Documentos del milestone v2.0

| Documento | Contenido |
|-----------|-----------|
| `propuesta_mejora/SPEC_v2.md` | Especificación técnica: arquitectura objetivo, 10 ADRs, contratos de módulo, modelo de datos, catálogo de eventos, detalle ejecutable de las 22 fases, trazabilidad de los 25 puntos, riesgos y criterios de aceptación |
| `.planning/ROADMAP.md` § v2.0 | Fases 17-38 con goal, dependencias, requisitos y criterios de éxito |
| `.planning/REQUIREMENTS.md` § v2 | 107 requisitos (PIPE, DET, EVT, RULE, DB, CLIP, OBS, SEC, FACE, REID, BEH, OPS, SET, TEST, SCALE) |
| `propuesta_mejora/mejoras_inmediatas.md` | Propuesta original (25 puntos) |
| `propuesta_mejora/vulnerabilidades.md` | Análisis de seguridad (12/14 ya corregidas en v1.2) |

## Planes listos para ejecutar

El bloque A (fases 17-22) ya tiene CONTEXT y PLAN escritos. **No hace falta `/gsd:plan-phase`** para estas fases: se puede ir directo a `/gsd:execute-phase`.

| Fase | Planes | Checkpoints manuales |
|------|--------|----------------------|
| 17 — Frame Broker y Capture Worker | 17-01, 17-02 | Comparativa A/B del MJPEG con cámara real |
| 18 — Workers desacoplados | 18-01, 18-02 | Medición CPU antes/después + crash de worker en vivo |
| 19 — Event Engine y esquema v2 | 19-01, 19-02 | Migración de la BD real + validación de reglas en vivo |
| 20 — Pre/post-buffer | 20-01, 20-02 | Verificación visual del pre-buffer + prueba sin red |
| 21 — Observabilidad | 21-01 | Coste de instrumentación + línea base de 30 min |
| 22 — Seguridad y memoria | 22-01 | Prueba de resistencia de 8 h |

## Siguiente paso

```
/gsd:execute-phase 17
```

Fase 17 no tiene dependencias y su criterio principal es "no cambiar nada visible": el stream MJPEG debe comportarse igual que en v1.2 mientras la captura pasa a ejecutarse tras el FrameBroker.

Las fases 23-38 (bloques B, C y D) tienen su detalle ejecutable en `SPEC_v2.md` §9 pero aún no tienen PLAN. Generarlos con `/gsd:plan-phase 23` cuando llegue el momento, o pedirlos en Cowork como se hizo con el bloque A.

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

| Módulo | Tests | Estado |
|--------|-------|--------|
| tests/test_detector.py | — | passing |
| tests/test_tracker.py | — | passing |
| tests/test_phase9.py | 15 | passing |
| tests/test_phase10.py | 14 | passing |
| **Total** | **38** | **38/38 ✓** |

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

### Pendiente manual (no es código)

- Descargar `credentials.json` de Google Cloud Console (OAuth 2.0 → Desktop app)
  y colocarlo en la raíz del proyecto para habilitar upload a Google Drive
- Carpeta Drive destino: «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`)

### Blockers/Concerns

Ninguno — proyecto finalizado. Drive upload requiere credenciales manuales por diseño de seguridad de Google.

## Session Continuity

Last session: 2026-05-01
Stopped at: Phase 16 complete, 38/38 tests passing, commit bd12055
Resume file: None
