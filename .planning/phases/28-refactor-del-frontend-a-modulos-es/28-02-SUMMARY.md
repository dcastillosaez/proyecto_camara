---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 02
subsystem: frontend
tags: [es-modules, dashboard, chart, refactor]

# Dependency graph
requires:
  - phase: 28-refactor-del-frontend-a-modulos-es
    plan: "01"
    provides: "tests/test_frontend_modules.py (contrato pytest) + frontend/css/{base,layout,components}.css"
provides:
  - "frontend/js/views/dashboard.js: nucleo del dashboard (showToast, updateStat, setCamStatus, loadInitialData, loadCamStatus)"
  - "frontend/js/views/dashboard-events.js: chart de actividad + lista de eventos + filtros, sustituye window.dashboardAPI"
affects: [28-07, 28-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ciclo de import de 2 modulos resuelto en el mismo plan (dashboard.js <-> dashboard-events.js) — ES modules soporta bindings en vivo, no requiere reordenar"
    - "loadInitialData/loadCamStatus exportados sin auto-invocarse a nivel de modulo — la invocacion la hace app.js (28-08), igual que el resto de loadX() de la fase"
    - "bumpHourBar nueva funcion exportada que sustituye el acceso directo de websocket.js a actChart (privado al modulo dashboard-events.js)"

key-files:
  created:
    - frontend/js/views/dashboard.js
    - frontend/js/views/dashboard-events.js
  modified: []

key-decisions:
  - "tickClock/fetchCounts/fetchDetections y los listeners de .cam-toggle/cam-settings-refresh/btn-reboot se quedan como efectos de nivel de modulo en dashboard.js (no se mueven a app.js) porque no tienen dependencia de orden con otros modulos, tal como fija 28-PATTERNS.md"
  - "El bloque de borrado de eventos por rango (btn-delete-events/-cancel/-confirm) se queda como efecto de nivel de modulo en dashboard-events.js, mismo criterio"

requirements-completed: [OPS-01, OPS-02]

duration: ~15min
completed: 2026-08-18
---

# Phase 28 Plan 02: Nucleo del dashboard y chart/eventos Summary

**Extraccion 1:1 de `index.html:787-873,1203-1301` a `dashboard.js` (188 lineas) y `index.html:987-1119,1896-1953` a `dashboard-events.js` (204 lineas), resolviendo el ciclo de import real entre ambos y sustituyendo `window.dashboardAPI` por exports nombrados.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2 completadas
- **Files created:** 2 (0 modificados)

## Accomplishments
- `frontend/js/views/dashboard.js` existe: 188 lineas, exporta `showToast`, `updateStat`, `setCamStatus`, `loadInitialData`, `loadCamStatus`. Ninguna se auto-invoca a nivel de modulo (las invoca `app.js` en 28-08).
- `frontend/js/views/dashboard-events.js` existe: 204 lineas, exporta `updateChart`, `bumpHourBar`, `hourlyToArray`, `addEvent`, `applyFilters`, `bindEventFilters`.
- El ciclo de import entre ambos ficheros esta resuelto exactamente como documenta `28-PATTERNS.md`: `dashboard-events.js` importa `loadInitialData` de `dashboard.js`; `dashboard.js` importa `updateChart`/`addEvent`/`hourlyToArray` de `dashboard-events.js`.
- `window.dashboardAPI` no existe en ningun fichero nuevo — sustituido por exports nombrados normales.
- El patron XSS-safe de `addEvent` (estructura estatica via `innerHTML`, datos del backend via `.textContent`) se conserva identico al original (comentario explicito preservado).
- `bumpHourBar` (funcion nueva, no existia como funcion separada en el codigo original) documentada como el acoplamiento no trivial que `28-PATTERNS.md` encontro al leer `index.html:1174-1177` contra la definicion de `actChart` en la linea 1040 — sustituye el acceso directo que `websocket.js` (28-07) tendria que hacer a `actChart`, que es privado a `dashboard-events.js`.

## Task Commits

1. **Task 1: frontend/js/views/dashboard.js (nucleo)** - `906d3a0` (feat)
2. **Task 2: frontend/js/views/dashboard-events.js (chart + eventos)** - `5c524c8` (feat)

_Nota: no se genera un commit de metadata separado en este entorno (STATE/ROADMAP/REQUIREMENTS los actualiza el orquestador centralmente); el commit final de este plan es unicamente este SUMMARY.md._

## Files Created/Modified
- `frontend/js/views/dashboard.js` - clock, toast, cam-status, stat counter, polling de `/counts` y `/detections`, `loadInitialData`, toggles de camara + reboot. 188 lineas, 5 exports.
- `frontend/js/views/dashboard-events.js` - borrado de eventos por rango, Chart.js de actividad, `addEvent` (XSS-safe), filtros de eventos, export CSV. 204 lineas, 6 exports.

## Decisions Made
Ver `key-decisions` en el frontmatter. Ninguna decision arquitectonica nueva — extraccion 1:1 tal como fija `28-CONTEXT.md`/`28-PATTERNS.md`; el ciclo de import ya estaba anticipado y resuelto por diseno (ambos ficheros se crean en el mismo plan, tal como explica el `<objective>` del plan).

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. El unico punto a documentar no es una desviacion de codigo sino una imprecision del propio `<verify>` del plan:

**Nota sobre el `<verify>` de Task 1 (no bloqueante, no requiere fix):** el acceptance criteria pide `grep -c "loadInitialData()\|loadCamStatus()" frontend/js/views/dashboard.js` == 0. El comando literal devuelve `2`, porque el patron tambien matchea las propias declaraciones `export async function loadInitialData() {` y `export async function loadCamStatus() {` (cualquier fichero que exporte estas funciones con esa sintaxis contendra ese substring). Se verifico con un patron mas preciso (excluyendo `function `) que **no hay ninguna invocacion real a nivel de modulo** — el requisito de comportamiento real (`loadInitialData`/`loadCamStatus` no se auto-invocan, las llama `app.js` en 28-08) se cumple. Es el mismo tipo de falso positivo en un `grep` de verificacion que ya se documento en `28-01-SUMMARY.md` con el string `@media` en `layout.css`.

## Issues Encountered
- Mismo matiz de entorno que `28-01`: el worktree no tiene `.venv` propio; se invoco el interprete del repo principal por ruta absoluta (`/f/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe -m pytest ...`).
- `pytest tests/test_frontend_modules.py -q` → 4 passed, 4 failed. Los 4 fallos (`TEST_js_modules_exist`, `TEST_no_inline_logic`, `TEST_app_entry_point_is_real`, `TEST_static_js_mime_type`) son exactamente los esperados: dependen de modulos que crean planes futuros (`app.js`, `api.js`, `websocket.js`, `views/dashboard-ptz.js`, `views/dashboard-observability.js`, los 5 componentes) y de la reescritura de `index.html` en 28-08. Se confirmo explicitamente que `dashboard.js`/`dashboard-events.js` **no** aparecen en la lista de módulos faltantes de `TEST_js_modules_exist` — este plan no introduce ninguna regresion sobre el estado esperado documentado en `28-01-SUMMARY.md`.

## User Setup Required
None - no se requiere configuracion de servicios externos.

## Next Phase Readiness
- El ciclo de import `dashboard.js` <-> `dashboard-events.js` esta resuelto y listo para que `websocket.js` (28-07) importe `updateStat`/`setCamStatus`/`showToast` de `dashboard.js` y `updateChart`/`addEvent`/`hourlyToArray`/`bumpHourBar` de `dashboard-events.js`.
- `bumpHourBar` queda documentada como la funcion que `websocket.js` debe usar en la rama `detection` del dispatch en vez de tocar `actChart` directamente.
- Ningun bloqueante para continuar con `28-03`..`28-06` (modulos JS restantes, sin solape de ficheros con este plan).

## Self-Check: PASSED

Ficheros verificados:
- FOUND: frontend/js/views/dashboard.js
- FOUND: frontend/js/views/dashboard-events.js

Commits verificados:
- FOUND: 906d3a0
- FOUND: 5c524c8

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*
