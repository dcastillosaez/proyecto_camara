---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Bloque A (fases 17-22) completo en codigo y tests: 310/310 pasan. Quedan 4 checkpoints con camara real pendientes de accion del usuario (19-01 Task 5, 19-02 Task 5, 20-02 Task 4, 21-01 Task 5, 22-01 Task 4). Siguiente: Fase 23, con la puerta bloqueante de insightface/onnxruntime en Windows."
last_updated: "2026-08-09"
last_activity: 2026-08-09
progress:
  total_phases: 22
  completed_phases: 6
  total_plans: 10
  completed_plans: 10
  percent: 27
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
Phase: **Bloque A (17-22) COMPLETO** en código y tests. Siguiente: Fase 23 (bloque B).
Status: Las seis fases del bloque A tienen código y suite en verde
  (310/310). Fase 22 cierra la deuda de seguridad pendiente (pickle
  erradicado, yolo_model_path validado contra {.pt, .onnx} y contención
  de path) y añade cotas de memoria verificadas por test en las 10
  estructuras acumulativas del pipeline, más un `_housekeeping_loop`
  centralizado (60 s) como purga periódica de respaldo.
  Quedan **4 checkpoints con cámara real** sin ejecutar, ninguno
  bloqueante para seguir programando: 19-01 Task 5 (migrar BD real),
  19-02 Task 5 (validación de reglas en vivo), 20-02 Task 4 (validación
  visual del pre-buffer), 21-01 Task 5 (coste de instrumentación y
  línea base de 30 min), y el nuevo 22-01 Task 4 (resistencia de 8 h).
Last activity: 2026-08-09

Progress v2.0: [███░░░░░░░] ~27% (6/22 fases completas — bloque A cerrado)
Progress v1.2: [██████████] 100% (16/16 fases) — completado 2026-05-01

## Mediciones acumuladas del bloque A

| Medición | Resultado | Fuente |
|----------|-----------|--------|
| CPU antes/después de desacoplar el pipeline (Fase 18) | 587.3% → 568.8% (normalizado, 8 cores) — mejora leve, sin regresión de RAM; YOLO sigue siendo el coste dominante | `18-02-CHECKPOINT.md` |
| Soak de 30 min, cámara real (Fase 17) | FPS estable ~15, 0 reconnects, sin crecimiento de latencia | `17-02-SUMMARY.md` |
| Línea base operativa de métricas (Fase 21, 30 min) | **Pendiente** — mecánica de `/api/v2/metrics` y `/metrics` verificada end-to-end (eventos reales incrementan `events_total`, `e2e_latency_seconds` registra observaciones reales), pero sin cámara real no hay FPS/latencia de producción que promediar | `21-01-SUMMARY.md`, checkpoint 21-01 Task 5 |
| Coste de instrumentación (<2% CPU objetivo) | **Pendiente** — requiere comparar `metrics_enabled=true/false` con carga real | checkpoint 21-01 Task 5 |
| Resistencia de 8 h (RSS, colas, `active_tracks`) | **Pendiente** — `scripts/soak_test.py` escrito y verificado con servidor real (6 s, 3 muestras), ejecución completa de 8 h aún no realizada | `22-01-SUMMARY.md`, checkpoint 22-01 Task 4 |

## Siguiente paso

```
/gsd:plan-phase 23
```

La Fase 23 (Migración a InsightFace/ArcFace) abre el bloque B y tiene
una **puerta bloqueante**: verificar que `insightface` + `onnxruntime`
instalan y ejecutan una inferencia real en el entorno Windows del
proyecto antes de comprometer el resto del bloque (plan B documentado
en `SPEC_v2.md` ADR-02 si no instalan). No tiene CONTEXT/PLAN escritos
todavía — a diferencia del bloque A, necesita `/gsd:plan-phase`.

Alternativamente, los 4 checkpoints pendientes del bloque A pueden
ejecutarse en cualquier momento que haya acceso a la cámara real; no
bloquean el arranque de la Fase 23, pero sí deberían cerrarse antes de
dar el bloque A por completamente validado en producción.

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

## Planes listos para ejecutar — bloque A (COMPLETO)

El bloque A (fases 17-22) tiene CONTEXT, PLAN y SUMMARY escritos, código
implementado y tests en verde. Solo quedan los checkpoints manuales con
cámara real.

| Fase | Planes | Checkpoints manuales |
|------|--------|----------------------|
| 17 — Frame Broker y Capture Worker | 17-01 ✓, 17-02 ✓ | ✓ Comparativa A/B del MJPEG con cámara real |
| 18 — Workers desacoplados | 18-01 ✓, 18-02 ✓ | ✓ Medición CPU antes/después + crash de worker en vivo |
| 19 — Event Engine y esquema v2 | 19-01 ✓, 19-02 ✓ | ⧗ Migración de la BD real + validación de reglas en vivo |
| 20 — Pre/post-buffer | 20-01 ✓, 20-02 ✓ | ⧗ Verificación visual del pre-buffer + prueba sin red |
| 21 — Observabilidad | 21-01 ✓ | ⧗ Coste de instrumentación + línea base de 30 min |
| 22 — Seguridad y memoria | 22-01 ✓ | ⧗ Prueba de resistencia de 8 h |

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
