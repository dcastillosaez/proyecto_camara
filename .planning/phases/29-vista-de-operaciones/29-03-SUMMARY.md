---
phase: 29
plan: 03
subsystem: frontend (js/views/dashboard.js, js/websocket.js, js/app.js, index.html)
tags: [header, degraded-state, personas-ahora, alertas-activas, ops-04, ops-06]
dependency-graph:
  requires:
    - "backend: mensaje WS type:\"tracks\" (29-01-PLAN.md)"
    - "frontend: canvas#tracks-overlay (29-02-PLAN.md)"
  provides:
    - "computeHeaderState() / setCamStatus(state) de 3 estados en dashboard.js"
    - "renderPersonList() / loadActiveAlerts() (paneles Personas ahora / Alertas activas)"
  affects: []
tech-stack:
  added: []
  patterns:
    - "Header de 3 estados combina pipeline.degraded + health.connected + ciclos de reconexión WS, nunca dropped (invariante 4 de CLAUDE.md)"
    - "_statusRow() helper compartido para mantener dashboard.js dentro del límite de 300 líneas de TEST_line_limit"
key-files:
  created: []
  modified:
    - frontend/index.html
    - frontend/js/views/dashboard.js
    - frontend/js/websocket.js
    - frontend/js/app.js
decisions:
  - "Alertas activas reutiliza GET /api/v2/events existente (sin backend nuevo) en vez de abrir /api/v2/ws — consistente con la decisión de 29-RESEARCH.md de no duplicar conexiones WS"
metrics:
  duration: "~25 min (Tasks 1-2), checkpoint Task 3 sin completar"
  completed: null
---

# Phase 29 Plan 03: Header de 3 estados + paneles Summary

**Estado: PARCIAL — Tasks 1 y 2 completas y comiteadas, Task 3 (checkpoint humano) pendiente de aprobación.**

## Lo construido

**Task 1 — Header de 3 estados** (commit `f6d6c06`): `computeHeaderState()` en `frontend/js/views/dashboard.js` combina `pipeline.degraded` (poll a `/api/v2/cameras/cam1/health` cada 4s) + `health.connected` + un contador de ciclos de reconexión WS (`_wsCloseCount > 1` → degradado) para decidir entre `online`/`degraded`/`offline`. `setCamStatus(bool)` se sustituyó por `setCamStatus(state)` de 3 estados; todas las llamadas antiguas binarias se eliminaron.

**Task 2 — Paneles "Personas ahora" y "Alertas activas"** (commit `cc8aa31`): `renderPersonList(tracks)` reutiliza el mismo mensaje `type:"tracks"` que alimenta el overlay de canvas (29-02) para listar identidades activas con su etiqueta de confirmación. `loadActiveAlerts()` consulta `GET /api/v2/events` y muestra el top-3 por severidad. Ambas funciones comparten el helper `_statusRow()` extraído durante la ronda de revisión del plan-checker para mantener `dashboard.js` dentro del límite de 300 líneas (`tests/test_frontend_modules.py::TEST_line_limit`).

## Pendiente — Task 3: checkpoint humano (NO completado)

El plan tiene una tercera tarea `type="checkpoint:human-verify" gate="blocking"` que verifica los criterios de éxito 1, 4, 5 y 6 del ROADMAP (zero-scroll en 1366×768, overlay alineado sin re-render del MJPEG, reconexión WS visible sin recargar, reconocimiento de alerta activa en <3s). El servidor se arrancó y se compartieron los pasos de verificación con el usuario, pero la sesión se desvió a:

1. Diagnosticar y corregir un bug de entorno no relacionado con el código de esta fase (el worktree en el que se ejecutó no tenía `.env`/`.venv` propios, así que `camera_url` caía al valor por defecto y no había imagen real — ver commit `dec9191`, política nueva en `CLAUDE.md` de no usar worktrees).
2. Mover toda la rama a la raíz del repositorio.

**La Task 3 nunca recibió la señal de reanudación** ("aprobado" o descripción de fallo) — no se ha verificado en persona ninguno de los 4 criterios de éxito que dependen de esa tarea. Esto sigue el mismo patrón que los 9 checkpoints manuales previos del proyecto (19-01, 19-02, 20-02, 21-01, 22-01, 23-02, 25-06, 26-05, 27-11): se documenta como pendiente explícito, no se fuerza una aprobación falsa.

**Para retomar:** arrancar el backend desde la raíz del repo (`.venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`) y seguir los 5 pasos de verificación ya descritos (ver `29-03-PLAN.md` líneas 359-372 para el texto exacto del checkpoint).

## Verificación (Tasks 1-2 únicamente)

- `node --check frontend/js/views/dashboard.js frontend/js/websocket.js frontend/js/app.js` → sintaxis válida
- `pytest tests/test_frontend_modules.py -q` → verde (según reporte del ejecutor)
- `wc -l frontend/js/views/dashboard.js` → ≤300 líneas (criterio añadido en la ronda de revisión del plan-checker)

**No se ejecutó la suite completa de Python** tras esta wave — por instrucción explícita del usuario, la suite completa (`pytest tests/ -q`) se reserva para una única ejecución al cierre de toda la fase, no tras cada wave.

## Self-Check: PARTIAL

- FOUND commit f6d6c06: feat(29-03): header de 3 estados combinando pipeline health + WS
- FOUND commit cc8aa31: feat(29-03): paneles Personas ahora y Alertas activas (top-3)
- MISSING: aprobación del checkpoint de Task 3 — criterios de éxito 1, 4, 5, 6 del ROADMAP sin verificar en persona
