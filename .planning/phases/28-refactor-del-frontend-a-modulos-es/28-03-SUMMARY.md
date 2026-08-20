---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 03
subsystem: frontend
tags: [es-modules, ptz, observability, health, refactor]

# Dependency graph
requires:
  - phase: 28-refactor-del-frontend-a-modulos-es
    plan: "01"
    provides: "tests/test_frontend_modules.py (contrato pytest) + frontend/css/{base,layout,components}.css"
provides:
  - "frontend/js/views/dashboard-ptz.js: PTZ completo (steps, move, stop, atajos de teclado, presets)"
  - "frontend/js/views/dashboard-observability.js: salud del pipeline (Fase 16) + metricas de observabilidad (Fase 21)"
affects: [28-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "loadPresets() exportada y ademas invocada dentro de bindPtzControls() (no a nivel de modulo) — app.js (28-08) solo llama bindPtzControls() una vez"
    - "El listener input del slider de pasos PTZ queda a nivel de modulo (efecto de import), no dentro de bindPtzControls — ejecuta al importar, igual que hoy ejecuta al parsear el script"
    - "dashboard-observability.js no importa nada de otros modulos (unico modulo de la fase sin import) — loadHealth/loadObservability no llaman showToast/updateStat"
    - "loadHealth/loadObservability exportadas sin su propio setInterval — app.js (28-08) sera responsable de setInterval(loadHealth,30000)/setInterval(loadObservability,5000)"

key-files:
  created:
    - frontend/js/views/dashboard-ptz.js
    - frontend/js/views/dashboard-observability.js
  modified: []

key-decisions:
  - "Ninguna decision arquitectonica nueva — extraccion 1:1 verificada linea a linea contra frontend/index.html:874-985 y :1955-2023 antes de escribir, tal como fija 28-CONTEXT.md/28-PATTERNS.md"

requirements-completed: [OPS-01, OPS-02]

duration: ~10min
completed: 2026-08-18
---

# Phase 28 Plan 03: PTZ y salud/observabilidad Summary

**Extraccion 1:1 de `index.html:874-985` a `dashboard-ptz.js` (116 lineas) y `index.html:1955-2023` a `dashboard-observability.js` (65 lineas), ambos muy por debajo del limite de 300 lineas.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 completadas
- **Files created:** 2 (0 modificados)

## Accomplishments
- `frontend/js/views/dashboard-ptz.js` existe: 116 lineas, exporta `bindPtzControls`/`loadPresets`. Toda la logica PTZ (mover/parar/atajos de teclado/presets/guardar preset) es identica a la original, verificada linea a linea contra `frontend/index.html:874-985` antes de escribir el fichero.
- `frontend/js/views/dashboard-observability.js` existe: 65 lineas, exporta `loadHealth`/`loadObservability`, sin ningun `import` (unico modulo de la fase que no depende de `dashboard.js`, confirmado por lectura directa: ninguna de las 2 funciones llama `showToast`/`updateStat`).
- `loadPresets()` se exporta Y se invoca dentro de `bindPtzControls()`, no a nivel de modulo — evita doble carga cuando `app.js` (28-08) llame `bindPtzControls()`.
- El listener `input` del slider de pasos PTZ queda fuera de `bindPtzControls`, a nivel de modulo (efecto de import), igual que hoy ejecuta al parsear el script inline.
- `loadHealth`/`loadObservability` no registran su propio `setInterval` — queda para que `app.js` (28-08) lo registre (`setInterval(loadHealth, 30000)`/`setInterval(loadObservability, 5000)`), tal como exige el plan.

## Task Commits

1. **Task 1: frontend/js/views/dashboard-ptz.js** - `fcdbc3a` (feat)
2. **Task 2: frontend/js/views/dashboard-observability.js** - `d6e72eb` (feat)

_Nota: no se genera un commit de metadata separado con STATE/ROADMAP/REQUIREMENTS en este entorno (los actualiza el orquestador centralmente); el commit final de este plan es unicamente este SUMMARY.md, tal como se hizo en `28-02`._

## Files Created/Modified
- `frontend/js/views/dashboard-ptz.js` - steps slider, move, stop, atajos de teclado, presets (cargar/activar/guardar). 116 lineas, 2 exports (`bindPtzControls`, `loadPresets`).
- `frontend/js/views/dashboard-observability.js` - salud del pipeline (`/api/health`, Fase 16) + metricas de observabilidad (`/api/v2/metrics`, Fase 21). 65 lineas, 2 exports (`loadHealth`, `loadObservability`).

## Decisions Made
Ver `key-decisions` en el frontmatter. Ninguna decision arquitectonica nueva — extraccion 1:1 tal como fija `28-CONTEXT.md`/`28-PATTERNS.md`. Antes de escribir cada fichero se releyo el rango exacto de `frontend/index.html` (874-985 y 1955-2023) y coincide byte a byte con el codigo del plan.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. Ambos ficheros creados verbatim segun el `<action>` de cada tarea, verificados linea a linea contra el codigo fuente real antes de escribir.

## Issues Encountered
- Mismo matiz de entorno que `28-01`/`28-02`: el worktree no tiene `.venv` propio; se invoco el interprete del repo principal por ruta absoluta (`/f/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe -m pytest ...`).
- `pytest tests/test_frontend_modules.py -q` → 4 passed, 4 failed. Los 4 fallos (`TEST_js_modules_exist`, `TEST_no_inline_logic`, `TEST_app_entry_point_is_real`, `TEST_static_js_mime_type`) son exactamente los esperados y ya documentados en `28-02-SUMMARY.md`: dependen de modulos que crean planes futuros (`app.js`, `api.js`, `websocket.js`, los 5 componentes) y de la reescritura de `index.html` en 28-08. Se confirmo explicitamente con `pytest -k modules_exist -v` que `dashboard-ptz.js`/`dashboard-observability.js` **no** aparecen en la lista de modulos faltantes (`missing`) — este plan no introduce ninguna regresion sobre el estado esperado.

## User Setup Required
None - no se requiere configuracion de servicios externos.

## Next Phase Readiness
- `bindPtzControls`/`loadPresets` y `loadHealth`/`loadObservability` listos para que `app.js` (28-08) los importe y los invoque dentro de `DOMContentLoaded`, registrando ahi los `setInterval` de `loadHealth`/`loadObservability` tal como documenta `28-PATTERNS.md`.
- Ningun bloqueante para continuar con `28-04`..`28-08` (componentes y modulos restantes, sin solape de ficheros con este plan).

## Self-Check: PASSED

Ficheros verificados:
- FOUND: frontend/js/views/dashboard-ptz.js
- FOUND: frontend/js/views/dashboard-observability.js

Commits verificados:
- FOUND: fcdbc3a
- FOUND: d6e72eb

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*
