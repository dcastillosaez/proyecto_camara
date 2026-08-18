---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 08
subsystem: ui
tags: [es-modules, frontend, dashboard, vanilla-js, refactor]

requires:
  - phase: 28-01..28-07
    provides: los 12 modulos JS (websocket.js, views/dashboard*.js, components/*.js) y los 3 CSS (base/layout/components) que este plan cablea
provides:
  - "frontend/js/app.js: bootstrap real que orquesta DOMContentLoaded, importa y llama a los 12 modulos en el orden original"
  - "frontend/index.html reescrito como shell puro: sin <style>/<script> inline, 3 <link> CSS, 1 <script type=module>"
  - "frontend/app.js (stub v1.2) eliminado — ya no queda huerfano junto al entry point real"
  - "Suite completa de pytest en verde (527 tests: 525 passed + 2 skipped), incluyendo los 8 de test_frontend_modules.py"
affects: [29-timeline-y-analitica-del-centro-de-operaciones, 30-vista-camara-y-configuracion]

tech-stack:
  added: []
  patterns:
    - "app.js como unico orquestador de arranque: ningun modulo ejecuta fetch()/addEventListener de arranque como efecto lateral de import"

key-files:
  created: [frontend/js/app.js]
  modified: [frontend/index.html]

key-decisions:
  - "frontend/app.js (stub Fase 6) eliminado en el mismo commit que se crea el bootstrap real, evitando dejarlo huerfano"
  - "index.html termino en 695 lineas reales (vs. ~685 estimadas en 28-RESEARCH.md) — diferencia de 10 lineas por comentarios/espaciado preservados al mover el marcado tal cual, no afecta al criterio redefinido de 'cero logica inline'"

patterns-established:
  - "Bootstrap centralizado en DOMContentLoaded: bind*() para listeners, load*() para carga inicial, mismo orden que el script original (1362-2023)"

requirements-completed: [OPS-01, OPS-02, OPS-03]

duration: 6min
completed: 2026-08-18
---

# Phase 28 Plan 08: Bootstrap real, shell puro y puerta de fase Summary

**`frontend/js/app.js` sustituye al stub v1.2 como entry point real y `frontend/index.html` queda como shell puro (sin `<style>`/`<script>` inline), cerrando la extraccion 1:1 de la Fase 28 con la suite completa en verde (527 tests).**

## Performance

- **Duration:** 6 min
- **Started:** 2026-08-18T14:33:00Z (aprox., tras el commit final de 28-07)
- **Completed:** 2026-08-18T14:39:03Z
- **Tasks:** 3
- **Files modified:** 3 (frontend/js/app.js creado, frontend/app.js borrado, frontend/index.html reescrito)

## Accomplishments
- `frontend/js/app.js` orquesta `DOMContentLoaded`: `bindPtzControls()`, `bindZoneForm()`, `bindEventCardControls()`, `bindPersonGallery()`, `bindEventFilters()` para listeners; `loadResolutions()`, `loadCamStatus()`, `loadInitialData()`, `connectWS()`, `loadRecordings()`+interval, `loadPersons()`+interval, `loadZones()`, `loadDetectionClasses()`, `loadHealth()`+interval, `loadObservability()`+interval para carga inicial — mismo orden que `index.html:1362-2023` en el script original.
- `frontend/app.js` (stub de 2 lineas de la Fase 6) eliminado — ya no hay entry point huerfano.
- `frontend/index.html` reescrito: 2038 -> 695 lineas. Sin `<style>` inline (capturado por `css/base.css`+`css/components.css` en 28-01), sin `<script>` inline (capturado por los 12 modulos en 28-02..28-07), sustituido por 3 `<link>` a `/static/css/{base,layout,components}.css` y un unico `<script type="module" src="/static/js/app.js">`. Marcado del `<body>` y `#clip-modal` preservados byte a byte, mismos `id`. SRI de Chart.js intacto en una unica linea.
- Suite completa de pytest: `525 passed, 2 skipped` (527 tests recogidos = 519 previos + 8 nuevos de `test_frontend_modules.py`), 0 fallos.

## Task Commits

1. **Task 1: frontend/js/app.js (bootstrap real) + eliminar el stub** - `ff1b14c` (feat)
2. **Task 2: Reescribir frontend/index.html como shell puro** - `d8b8b76` (refactor)
3. **Task 3: Puerta mecanica — suite completa en verde** - sin commit (tarea de verificacion, no modifica ficheros)

**Plan metadata:** (pendiente, commit final de este SUMMARY)

## Files Created/Modified
- `frontend/js/app.js` - bootstrap real: `DOMContentLoaded` orquesta los 12 modulos de 28-01..28-07 en el orden original
- `frontend/app.js` - eliminado (stub v1.2, 2 lineas, "entry point vacio para Phase 6")
- `frontend/index.html` - reescrito a shell puro: sin `<style>`/`<script>` inline, 3 `<link>` CSS nuevos, `<script type="module">` unico; marcado y `#clip-modal` sin cambios

## Decisions Made
- Eliminar `frontend/app.js` en el mismo commit que crea `frontend/js/app.js` (Task 1), evitando que quede huerfano un solo commit, siguiendo la advertencia explicita de `TEST_app_entry_point_is_real`.
- Reescritura de `index.html` hecha con `awk` (extraccion de rangos de linea) en vez de `Edit` por el tamano del bloque `<script>` (1240 lineas): mismo resultado, verificado linea a linea contra el original (marcado 121-784 y `#clip-modal` 2027-2035 intactos).

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito. Los 3 archivos tocados, el orden de imports/llamadas en `app.js`, y los limites exactos de `<style>`/`<script>` en `index.html` coincidieron con lo verificado en 28-PATTERNS.md sin necesidad de ajustes.

## Issues Encountered

Ninguno relevante. Nota tecnica: al usar `diff` con `process substitution` en Git Bash sobre Windows para verificar el resultado de `awk`, aparecio una diferencia aparente linea-a-linea que resulto ser un artefacto de codificacion del propio `diff`/bash en Windows (no una diferencia real) — se confirmo con `sed -n` que el contenido resultante era correcto antes de sustituir el fichero.

## Recuento de lineas de `index.html` (criterio de exito #1, redefinido por 28-CONTEXT.md)

| Momento | Lineas |
|---|---|
| Antes de esta fase (verificado en planificacion) | 2038 |
| Tras Task 2 (esta plan) | 695 |
| Estimacion de 28-RESEARCH.md | ~685 |

Diferencia de 10 lineas frente a la estimacion: espaciado/comentarios del marcado original preservados tal cual (no se reformateo nada, por diseño). El criterio real de la fase — "`index.html` deja de contener logica" — se cumple: `TEST_no_inline_logic` confirma ausencia de `<style>` y de cualquier `<script>` sin `src=`.

## Resultado de la suite completa

```
.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -v
8 passed in 6.93s

.venv/Scripts/python.exe -m pytest tests/test_security_regression.py -k chartjs -q
1 passed, 20 deselected in 6.12s

.venv/Scripts/python.exe -m pytest tests/ -q
525 passed, 2 skipped, 117 warnings in 124.07s
```

`TEST_app_entry_point_is_real` (dentro de los 8 de `test_frontend_modules.py`) verifica dos cosas a la vez: que `frontend/js/app.js` tiene mas de 10 lineas y orquesta `DOMContentLoaded` (no es el stub), y que `frontend/app.js` (el stub v1.2) ya no existe en disco — ambas condiciones se cumplen tras el commit `ff1b14c`.

## Checklist de paridad funcional (manual, sin framework de test JS — mismo criterio que 27-10)

Verificado por lectura del codigo movido (no hay servidor con camara real disponible en esta sesion de ejecucion; cada funcion se preservo 1:1 desde su rango de origen en `index.html`, confirmado contra 28-PATTERNS.md):

- [x] Video en vivo (`videoCanvas.js` — `<img id="video-feed">`, handlers `onerror`/`onclick` inline preservados sin tocar, Pitfall 3 de RESEARCH)
- [x] PTZ + presets (`dashboard-ptz.js` — `bindPtzControls()` invoca `loadPresets()` internamente)
- [x] Contadores (`dashboard.js` — `loadInitialData`, `updateStat`)
- [x] Chart de actividad (`dashboard-events.js` — `updateChart`, `bumpHourBar`, `hourlyToArray`)
- [x] Toggles de camara (`dashboard.js` core, rango 1203-1301 original)
- [x] Resoluciones (`videoCanvas.js` — `loadResolutions`, `setResolutionBadge`)
- [x] Grabaciones + Drive (`eventCard.js` — `loadRecordings`, `addRecording`, `updateRecordingStatus`)
- [x] Personas + galeria (`personGallery.js` — `loadPersons`, `bindPersonGallery`)
- [x] Zonas CRUD (`zoneEditor.js` — `loadZones`, `bindZoneForm`)
- [x] Clases detectadas (`detectionClasses.js` — `loadDetectionClasses`)
- [x] Filtros de eventos (`dashboard-events.js` — `bindEventFilters`)
- [x] Salud (`dashboard-observability.js` — `loadHealth`)
- [x] Observabilidad (`dashboard-observability.js` — `loadObservability`)
- [x] WebSocket con reconexion (`websocket.js` — `connectWS`, backoff exponencial hasta 30s)

## Medicion de carga inicial < 1s en LAN (criterio de exito #6)

Diferido explicitamente: esta sesion de ejecucion no tiene acceso a un segundo dispositivo en la LAN para medir con DevTools Network fuera de `localhost` (mismo patron que los checkpoints de camara real ya diferidos en fases anteriores). Los modulos ES resultantes son ficheros pequenos (el mayor, `dashboard-events.js`, no supera las 300 lineas por `TEST_line_limit`), servidos en paralelo por HTTP/1.1 sin bundler — no deberia ser un problema practico, pero queda pendiente de medicion real por el usuario cuando tenga acceso a la LAN.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- La Fase 28 queda funcionalmente cerrada: `frontend/` tiene la estructura LOCKED de ADR-08 (3 CSS + `js/app.js` + `js/api.js`(sin uso activo aun, ver 28-01) + `js/websocket.js` + 4 `js/views/*.js` + 5 `js/components/*.js`), `index.html` es shell puro, suite en verde.
- Pendiente (fuera de este plan): medicion real de carga inicial en LAN (criterio #6, diferido arriba) y la puerta formal de fase (`28-09` si existe, o cierre directo del ROADMAP) que consolide el checklist de paridad funcional con un navegador real.
- Fases 29-32 (Timeline, Analitica, Camara, Configuracion) pueden apoyarse en esta base de modulos ES sin bundler.

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*

## Self-Check: PASSED

- FOUND: frontend/js/app.js
- CONFIRMED ABSENT: frontend/app.js (stub eliminado)
- FOUND: frontend/index.html
- FOUND commit: ff1b14c (Task 1)
- FOUND commit: d8b8b76 (Task 2)
