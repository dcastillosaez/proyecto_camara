---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: La v1.2 resolvió el pipeline funcional completo
status: executing
stopped_at: Fases 32 y 38 COMPLETAS (2026-10-04). Unica puerta abierta: 28-09 (verificacion manual del refactor del frontend). Pendiente de decision: rate limit v2 (60/min) agotable por el propio dashboard, ver 32-08-SUMMARY.md.
last_updated: "2026-10-04T23:30:00.000Z"
last_activity: 2026-10-04 -- Puerta 32-08 cerrada con checkpoint visual en navegador real. Corregidos: Ajustes sin barra de guardado (no se podia guardar), Ajustes reescribiendo el hash de otras vistas y BD de E2E que no se reiniciaba entre ejecuciones. Nuevo tests/e2e/settings.spec.js. pytest 883 passed / 16 skipped; Playwright 14/14.
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
**Current focus:** Todas las fases de v2.0 (17-38) tienen el código completo. Quedan la puerta manual 28-09, los checkpoints con cámara real y una decisión sobre el rate limit.

## Current Position

Milestone: v2.0 — Plataforma de Video Analytics
Phase: 38 (Worker de inferencia en GPU) — COMPLETA, última del milestone
Plan: ninguno en curso
Status: Fases de código cerradas; verificación manual pendiente
Last activity: 2026-10-04

Progress v2.0: 22/22 fases con código completo; 99/104 planes marcados
Progress v1.2: 16/16 fases, completado 2026-05-01

## Siguiente paso

1. Cerrar la puerta manual 28-09: checklist de paridad funcional y medición de carga en LAN.
2. Decidir qué hacer con el rate limit de la API v2 (60 peticiones/min por IP, `backend/api/v2/deps.py`), que el propio dashboard puede agotar. Detalle en `32-08-SUMMARY.md`.
3. Hacer los checkpoints de la tabla siguiente cuando haya acceso a la cámara real.

El plan de mejoras tras la v2.0 (2026-10-31) está al final de `propuesta_mejora/mejoras_inmediatas.md`, con fases, decisiones pendientes y evidencias.

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

Última suite completa (2026-10-04): pytest 883 passed, 16 skipped; Playwright 14/14.

## Accumulated Context

### Decisions

Las decisiones por fase están en `.planning/STATE-archive.md` y en cada `*-SUMMARY.md`.

- `reid_inherit_identity=False` por defecto: ReID calcula la herencia sin aplicarla hasta que el operador la active.
- `OBJECT_LEFT` se mantiene en `WARNING` y sube clips a Drive; hay que calibrar `object_person_radius_px` antes de operar desatendido.
- El estado que debe sobrevivir a un reinicio de worker (FSM, galería ReID, analizadores) se construye en `CameraPipeline.__init__`, fuera de las factorías del `WorkerSupervisor`.

### Blockers/Concerns

Ninguno bloqueante.

## Session Continuity

Last session: 2026-10-31
Stopped at: Fases 32 y 38 completas; pendiente la puerta manual 28-09 y la decisión del rate limit v2
Resume file: None
