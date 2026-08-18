---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 07
subsystem: ui
tags: [websocket, es-modules, frontend, vanilla-js]

# Dependency graph
requires:
  - phase: 28-refactor-del-frontend-a-modulos-es
    provides: "dashboard.js (updateStat/setCamStatus/showToast), dashboard-events.js (updateChart/addEvent/hourlyToArray/bumpHourBar), eventCard.js (addRecording/updateRecordingStatus), videoCanvas.js (setRecBadge) — modulos ES creados en 28-02/28-04/28-05"
provides:
  - "frontend/js/websocket.js: connectWS() con reconexion por backoff exponencial (1s->30s) y dispatch de los 5 tipos de mensaje WS a las 10 funciones de UI importadas"
affects: [28-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "websocket.js no mantiene estado de UI propio (ni Chart ni DOM directo) — delega en funciones exportadas por los modulos de vista/componente (bumpHourBar en vez de tocar actChart, setRecBadge en vez de tocar #rec-badge)"

key-files:
  created: [frontend/js/websocket.js]
  modified: []

key-decisions:
  - "Codigo copiado 1:1 desde frontend/index.html:1121-1201, con solo dos sustituciones de acceso privado: dashboardAPI.updateChart/addEvent -> updateChart/addEvent importados directamente, y acceso directo a actChart/#rec-badge -> bumpHourBar()/setRecBadge()"

patterns-established:
  - "Modulo de infraestructura (WS) importa exclusivamente contratos publicos (export function) de las vistas/componentes, nunca variables privadas como actChart"

requirements-completed: [OPS-01, OPS-02]

# Metrics
duration: 6min
completed: 2026-08-18
---

# Phase 28 Plan 07: websocket.js Summary

**Conexion WebSocket /ws extraida a modulo ES con reconexion por backoff exponencial y dispatch de 5 tipos de mensaje a 10 funciones importadas de 4 modulos distintos**

## Performance

- **Duration:** 6 min
- **Tasks:** 2 (1 de creacion, 1 de verificacion)
- **Files modified:** 1

## Accomplishments
- `frontend/js/websocket.js` creado (78 lineas), exporta unicamente `connectWS`
- Los 10 simbolos importados (`updateStat`, `setCamStatus`, `showToast` de `dashboard.js`; `updateChart`, `addEvent`, `hourlyToArray`, `bumpHourBar` de `dashboard-events.js`; `addRecording`, `updateRecordingStatus` de `eventCard.js`; `setRecBadge` de `videoCanvas.js`) verificados como `export function` reales mediante grep contra el codigo fuente, no solo contra el contrato documentado en 28-PATTERNS.md
- Cero acceso directo a `actChart` (privado a `dashboard-events.js`) ni a `#rec-badge` por DOM — sustituidos por `bumpHourBar()` y `setRecBadge()`

## Task Commits

Each task was committed atomically:

1. **Task 1: frontend/js/websocket.js** - `50bb52c` (feat) — crea el modulo con `connectWS` y los 4 imports
2. **Task 2: Verificacion cruzada de los 4 imports** - sin commit (tarea de solo verificacion, cero ficheros modificados; comando de verify devolvio `OK: 10/10 exports resueltos`)

**Plan metadata:** (pendiente, commit final de este mensaje)

## Files Created/Modified
- `frontend/js/websocket.js` - `connectWS()`: token WS opcional (`/api/ws-token`), apertura/cierre con backoff 1s->30s, dispatch de `init`/`detection`/`recording_started`/`recording_uploaded`/`recording_failed`

## Decisions Made
None - plan ejecutado exactamente como estaba escrito. El codigo del plan ya venia verificado linea a linea contra `index.html:1121-1201` y contra los exports reales de los 4 modulos previos.

## Deviations from Plan

None - plan executed exactly as written. Los 10 exports esperados existian tal cual en los 4 ficheros de destino (mismos nombres, misma firma `export (async )?function`), sin necesidad de corregir ningun import.

## Issues Encountered
None

## Known Stubs

None. El modulo no introduce datos vacios/hardcodeados: todo el estado (contadores, chart, lista de eventos, badge de grabacion) llega de mensajes reales del backend via `/ws`.

## Threat Flags

Ninguno nuevo. La unica superficie es el dispatch de `JSON.parse(e.data)` sobre mensajes del backend ya identificada en el `<threat_model>` del plan (T-28-13, T-28-14) — sin cambios de comportamiento respecto al original.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`connectWS` esta listo para que `frontend/js/app.js` (28-08) lo importe y lo invoque como ultimo paso del arranque, igual que hoy `connectWS();` es la ultima linea del bloque inline. `frontend/index.html` aun conserva el bloque WebSocket original (1121-1201) sin tocar — su eliminacion corresponde a 28-08, cuando el `<script>` inline completo se sustituya por los modulos ES.

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*

## Self-Check: PASSED

- FOUND: frontend/js/websocket.js
- FOUND: 50bb52c (commit Task 1)
