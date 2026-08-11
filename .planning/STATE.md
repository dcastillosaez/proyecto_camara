---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Plataforma de Video Analytics
status: in_progress
stopped_at: "Fase 23 (Migracion a InsightFace/ArcFace) completa en codigo y tests: 326/326 pasan. Puerta bloqueante superada con evidencia real. Quedan 6 checkpoints con camara real pendientes de accion del usuario (19-01 Task 5, 19-02 Task 5, 20-02 Task 4, 21-01 Task 5, 22-01 Task 4, 23-02 Task 4). Siguiente: Fase 24 (Identidad temporal), sin CONTEXT/PLAN escritos todavia."
last_updated: "2026-08-10"
last_activity: 2026-08-10
progress:
  total_phases: 22
  completed_phases: 7
  total_plans: 12
  completed_plans: 12
  percent: 32
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
Phase: **Bloque A (17-22) + Fase 23 COMPLETOS** en código y tests. Siguiente: Fase 24 (bloque B, sin CONTEXT/PLAN).
Status: Bloque A cerrado (310/310) y Fase 23 (Migración a InsightFace/
  ArcFace) completa encima (326/326). La puerta bloqueante de la Fase 23
  se superó con evidencia real: `insightface`+`onnxruntime` instalan sin
  compilar en Windows, `buffalo_s` descarga y ejecuta una inferencia
  real (5 submodelos ONNX, embedding 512D confirmado). `FaceEngine`,
  `FaceQualityAssessor` e `IdentityIndex` construidos y verificados
  (23-01); `backend/recognizer.py` reducido a orquestación sobre ellos,
  `scripts/reenroll.py` para re-enrolamiento real, `dlib`/
  `face-recognition` fuera de requirements.txt (23-02).
  Quedan **6 checkpoints con cámara real** sin ejecutar, ninguno
  bloqueante para seguir programando: 19-01 Task 5 (migrar BD real),
  19-02 Task 5 (validación de reglas en vivo), 20-02 Task 4 (validación
  visual del pre-buffer), 21-01 Task 5 (coste de instrumentación y
  línea base de 30 min), 22-01 Task 4 (resistencia de 8 h), y el nuevo
  23-02 Task 4 (tasa de aciertos ArcFace vs dlib con datos reales).
Last activity: 2026-08-10

Progress v2.0: [███░░░░░░░] ~32% (7/22 fases completas)
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
/gsd:plan-phase 24
```

La Fase 24 (Identidad temporal — votación y máquina de estados) abre
con `IdentityStateMachine`/`TemporalVoter` (4 estados: UNKNOWN →
CANDIDATE → CONFIRMED → TEMPORARILY_LOST) y depende de la Fase 23 en
código (ya completa), no de su checkpoint de validación en vivo. No
tiene CONTEXT/PLAN escritos todavía — a diferencia del bloque A y la
Fase 23, necesita `/gsd:plan-phase` o una sesión de planificación
dedicada antes de ejecutarse.

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
| 23 — InsightFace/ArcFace | 23-01 ✓, 23-02 ✓ | ⧗ Tasa de aciertos ArcFace vs dlib con datos reales |

Las fases 24-38 (resto de bloques B, C y D) tienen su detalle ejecutable en `SPEC_v2.md` §9 pero aún no tienen PLAN. Generarlos con `/gsd:plan-phase 24` cuando llegue el momento, o pedirlos en Cowork como se hizo con el bloque A y la Fase 23.

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

Suite completa (39 ficheros en `tests/`): **326/326 passing** (última ejecución 2026-08-11).
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

Last session: 2026-08-11
Stopped at: Fix de env_file independiente del cwd (backend/config.py),
  limpieza de .env.example/README y corrección del modelo de cámara a
  C212 (era C220), fusionado en main (PR #1, commit 3e8cafc). Sin
  relación con el avance de fases de v2.0.
Resume file: None
