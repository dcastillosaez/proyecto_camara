---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Fase 17: 17-01 completo, 17-02 Tasks 1-4 completas — Task 5 (checkpoint A/B con camara real) bloqueada, camara no accesible desde este entorno"
last_updated: "2026-08-07"
last_activity: 2026-08-07
progress:
  total_phases: 22
  completed_phases: 0
  total_plans: 2
  completed_plans: 1
  percent: 2
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
Phase: 17 (Frame Broker y Capture Worker) — EN CURSO
Status: 17-01 completo (FrameBroker, 10/10 tests). 17-02 Tasks 1-4 completas
  (CaptureWorker, CameraManager, flag PIPELINE_V2, RTSPStream como
  despachador del broker, endpoints /api/v2/cameras). Task 5 (checkpoint
  A/B de 30 min con la camara real) BLOQUEADA: la camara Tapo
  (192.168.1.132:554) no respondio desde este entorno al intentarlo.
Last activity: 2026-08-07

Progress v2.0: [░░░░░░░░░░] ~2% (17-01 de 2 planes de la Fase 17 completo)
Progress v1.2: [██████████] 100% (16/16 fases) — completado 2026-05-01

## Accion requerida del usuario

Fase 17 no puede darse por completa hasta ejecutar la Task 5 de
17-02-PLAN.md con la camara real accesible:

```bash
PIPELINE_V2=false .venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# observar 5 min, luego:
PIPELINE_V2=true .venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# observar 5 min + dejar corriendo 30 min sin crecimiento de latencia
```

Ver `.planning/phases/17-frame-broker-y-capture-worker/17-02-SUMMARY.md`
§"Task 5 — PENDIENTE" para el detalle completo de que verificar y como
invertir el flag `pipeline_v2` a `True` por defecto si todo sale bien.

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
