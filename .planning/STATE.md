---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: La v1.2 resolvió el pipeline funcional completo
status: executing
stopped_at: Plan de mejoras tras la v2.0 implementado (fases 1-7, 3 bis parcial) en claude/mejoras-post-v2-fe5ev8. Pendiente la validación con cámara real.
last_updated: "2026-11-03T12:00:00.000Z"
last_activity: 2026-11-03 -- Plan de mejoras tras la v2.0: CI recoge los test_*, seguridad, retención, grabación con garantías, dashboard sin CDN, sondeo con backoff, reinicio supervisado. Detalle por id al final de propuesta_mejora/mejoras_inmediatas.md.
progress:
  total_phases: 32
  completed_phases: 22
  total_plans: 104
  completed_plans: 99
  percent: 95
---

# Project State

Solo el estado actual. El historial completo (sesiones, decisiones por fase, cobertura y mediciones) está en `.planning/STATE-archive.md`: búscalo con Grep, no hace falta leerlo entero.

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-01)

**Core value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo, reconocimiento facial, grabación automática y métricas de sistema integrados en el mismo panel.
**Current focus:** Plan de mejoras tras la v2.0 implementado en código (estado por id al final de `propuesta_mejora/mejoras_inmediatas.md`). Quedan la puerta manual 28-09 y los checkpoints con cámara real.

## Current Position

Milestone: v2.0 — Plataforma de Video Analytics
Phase: 38 (Worker de inferencia en GPU) — COMPLETA, última del milestone
Plan: ninguno en curso
Status: Fases de código cerradas; verificación manual pendiente
Last activity: 2026-11-03

Progress v2.0: 22/22 fases con código completo; 99/104 planes marcados
Progress v1.2: 16/16 fases, completado 2026-05-01

## Siguiente paso

1. **Antes de arrancar el backend tras hacer pull, copia `data/`.** La retención (BUG-02) se aplica al arrancar y borra, con los valores por defecto:
   - eventos de cualquier tipo con más de 30 días (`EVENTS_RETENTION_DAYS`), salvo los que dispararon una grabación que sigue en `recordings`. Antes solo se borraban los `LINE_CROSSED`, así que los datos de agosto y septiembre de `data/events.db` desaparecerán;
   - filas de `recordings` con más de 30 días (`RECORDINGS_RETENTION_DAYS`) que no estén `pending`/`uploading`, y su fichero si quedaba;
   - recortes de la galería (tabla `captures` e imágenes de `data/gallery/`) con más de 30 días (`CAPTURES_RETENTION_DAYS`, nuevo);
   - clips locales más antiguos cuando el total supere 20 GB (`CLIPS_MAX_TOTAL_MB`, nuevo), nunca los pendientes de subir;
   - ficheros `*.part.mp4` de `data/clips/` (clips interrumpidos); además, las grabaciones pendientes cuyo fichero ya no existe pasan a `failed`;
   - siguen como antes: clips locales de más de 7 días, snapshots de más de 30 y personas anónimas de una visita sin ver en 30 días.
   Para no borrar nada en el primer arranque, pon a 0 los `*_RETENTION_DAYS` y `CLIPS_MAX_TOTAL_MB` en `.env`.
2. Instalar de nuevo las dependencias: `pip install -r requirements-dev.txt` (cambia `requirements.txt` y aparece `requirements-dev.txt`).
3. Volver a autorizar Drive con `scripts/gdrive_auth.py` (el token local estaba caducado; el backend ya no abre el navegador).
4. Validar con la cámara real lo marcado en la tabla siguiente y en la columna «Pendiente» del plan.
5. Grabar y anotar 10-15 clips para `scripts/eval_detection.py` (DET-03) antes de decidir DET-04 a DET-07 y la GPU.

## Pendiente de verificar

Ninguno bloquea el código, pero conviene cerrarlos antes de dar cada fase por validada en producción.

| Fase | Qué falta |
|------|-----------|
| 19 — Event Engine | Migración de BD real y validación de reglas en vivo |
| 20 — Pre/post-buffer | Verificación visual del pre-buffer y prueba sin red |
| 21 — Observabilidad | Coste de instrumentación (<2 % CPU) y línea base de 30 min |
| 22 — Seguridad y memoria | Prueba de resistencia de 8 h con `scripts/soak_test.py` |
| 23 — ArcFace | Tasa de aciertos frente a dlib con ≥50 recortes reales de `data/gallery/` |
| 25 — ReID | Tasa de falsos positivos con dos personas reales (25-06 Task 2) |
| 26 — Comportamiento | Calibración de umbrales con cámara real (26-05 Task 3) |
| 27 — Multi-clase | Calibración de `object_person_radius_px` y falsos positivos (27-11 Task 2) |
| 28 — Frontend ES | Paridad funcional y carga en LAN (28-09) |
| 29 — Operaciones | Checkpoint visual de 29-03 Task 3 (criterios 1/4/5/6) |
| 30 — Timeline y alertas | Cuatro puntos de 30-12 Task 2 que exigen cámara real |
| 31 — Analítica | Heatmap con datos genuinos y ranking con personas reconocidas |
| 32 — Cámara y config | Vídeo en directo con imagen real |
| 38 — GPU | Criterio 3 (≥3× FPS) con el stack GPU instalado (`38-GPU-NOTES.md`) |
| Mejoras post-v2 | Clip real de principio a fin (BUG-08/10/11, `probe_clip`), retención sobre `data/` real, `inference_threads=3` en el i7-9700K, vida de tracks y reentradas tras DET-02, FPS medido (DET-08), puerta de movimiento (DET-09, desactivada), contraseña RTSP con caracteres especiales (SEC-02), `icacls` (SEC-11), revisión visual de todas las vistas con Tailwind 4, carga en LAN con `poll()` (DIR-04), cambio de resolución en caliente (BUG-03) |

## Pendiente sin relacion con v2.0

- Token OAuth de Google Drive caducado (`data/token.json`, `invalid_grant`). Requiere rehacer el flujo de autorización a mano.
- Descargar `credentials.json` de Google Cloud Console (OAuth 2.0 → Desktop app) y colocarlo en la raíz para habilitar la subida a Drive. Carpeta destino: «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`).

## Documentos del milestone v2.0

| Documento | Contenido |
|-----------|-----------|
| `.planning/ROADMAP.md` § v2.0 | Fases 17-38: goal, dependencias, requisitos y criterios de éxito |
| `.planning/REQUIREMENTS.md` § v2 | Requisitos del milestone |
| `propuesta_mejora/SPEC_v2.md` | Arquitectura objetivo, ADRs, contratos de módulo y modelo de datos |
| `.planning/STATE-archive.md` | Historial de STATE.md hasta 2026-10-31 |

## Test Coverage

Última suite completa (2026-11-03, Linux, Python 3.12): las cifras exactas están en la descripción de la PR del plan de mejoras. Playwright 16/16 en local con Chromium. Los tests de PostgreSQL y Redis pasan contra servicios reales (PostgreSQL 16, Redis 7) y corren en CI.

## Accumulated Context

### Decisions

Las decisiones por fase están en `.planning/STATE-archive.md` y en cada `*-SUMMARY.md`.

- `reid_inherit_identity=False` por defecto: ReID calcula la herencia sin aplicarla hasta que el operador la active.
- `OBJECT_LEFT` se mantiene en `WARNING`, pero ninguna regla por defecto lo graba (DIR-01): solo graban intrusión y persona desconocida. Antes de añadir una regla `record` para `OBJECT_LEFT` hay que calibrar `object_person_radius_px`. (El texto anterior decía que ya subía clips a Drive; no era cierto: ninguna regla tenía `record`.)
- Decisiones del plan de mejoras aplicadas con la opción recomendada: retención de 30 días para todos los eventos salvo los que tienen clip; límite de 60/min mantenido con menos sondeo; Docker y `watchdog.py` retirados; GPU sin activar; DET-04 a DET-07 sin adoptar hasta tener el banco DET-03 con clips.
- Tailwind pasa del CDN v3 a `@tailwindcss/browser` 4.3.4 copiado en `frontend/vendor/` (el v3 no se distribuye fuera de su CDN).
- El estado que debe sobrevivir a un reinicio de worker (FSM, galería ReID, analizadores) se construye en `CameraPipeline.__init__`, fuera de las factorías del `WorkerSupervisor`.

### Blockers/Concerns

Ninguno bloqueante.

## Session Continuity

Last session: 2026-11-03
Stopped at: Plan de mejoras tras la v2.0 implementado; pendiente la validación con cámara real
Resume file: None
