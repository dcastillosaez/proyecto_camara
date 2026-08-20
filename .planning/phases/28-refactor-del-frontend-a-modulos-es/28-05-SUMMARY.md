---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 05
subsystem: ui
tags: [es-modules, frontend, vanilla-js, xss-safe-dom]

# Dependency graph
requires:
  - phase: 28-01
    provides: "Contrato pytest OPS-01/02/03 + extraccion CSS locked (frontend/css/*.css)"
provides:
  - "frontend/js/components/eventCard.js: panel de grabaciones + borrado por rango + modal de reproduccion de clip"
  - "frontend/js/components/detectionClasses.js: panel de clases detectadas (Fase 27-10) contra GET/PUT /api/v2/detection/classes"
affects: [28-07-websocket, 28-08-app-bootstrap, 28-09-index-html-shell]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Componente ES sin efectos de import-time: exporta funciones, app.js (28-08) decide cuando se invocan (loadX, bindX)"
    - "XSS-safe DOM: innerHTML solo para estructura estatica, datos del backend siempre via .textContent/.dataset/.href tras montar el nodo"

key-files:
  created:
    - frontend/js/components/eventCard.js
    - frontend/js/components/detectionClasses.js
  modified: []

key-decisions:
  - "loadRecordings() no usa setRecBadge (videoCanvas.js, 28-04): el original solo actualiza el contador de #rec-badge, nunca su visibilidad, en este punto — preservar esa inconsistencia preexistente evita una regresion funcional real (el badge quedaria visible tras cada poll de 30s sin grabacion en curso)."
  - "eventCard.js no importa setRecBadge: la decision anterior hace que no exista ningun uso real de esa funcion en este fichero (websocket.js, 28-07, si la usara para sus 3 ramas de mensaje)."

patterns-established: []

requirements-completed: [OPS-01, OPS-02]

# Metrics
duration: ~15min
completed: 2026-08-18
---

# Phase 28 Plan 05: Extraccion de grabaciones + clases detectadas a modulos ES Summary

**Grabaciones (lista, borrado por rango, estado de subida a Drive) + modal de clip y panel de clases detectadas (Fase 27-10) extraidos 1:1 a `eventCard.js`/`detectionClasses.js`, sin cambios de comportamiento observable.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-08-18T14:29:20Z
- **Tasks:** 2
- **Files modified:** 2 (ambos ficheros nuevos)

## Accomplishments
- `frontend/js/components/eventCard.js` (189 lineas): grabaciones (`addRecording`, `updateRecordingStatus`, `loadRecordings`), borrado por rango de fechas, modal de reproduccion de clip (`openClipModal`) y `bindEventCardControls()` que agrupa todos los listeners de la seccion.
- `frontend/js/components/detectionClasses.js` (67 lineas): panel de clases detectadas de la Fase 27-10 (`loadDetectionClasses`, `renderDetectionClasses`, `saveDetectionClasses`) con el contrato GET/PUT `/api/v2/detection/classes` y el revert en error preservado sin cambios.
- El patron XSS-safe de `_recRow` (datos del backend asignados via `.textContent`/`.dataset`/`.href`, nunca interpolados en `innerHTML`) se conservo integro.

## Task Commits

Cada tarea se commiteo de forma atomica:

1. **Task 1: frontend/js/components/eventCard.js** - `68a1d37` (feat)
2. **Task 2: frontend/js/components/detectionClasses.js** - `8a3723f` (feat)

**Plan metadata:** (este commit, docs)

## Files Created/Modified
- `frontend/js/components/eventCard.js` - Grabaciones + borrado por rango + modal de clip (5 exports)
- `frontend/js/components/detectionClasses.js` - Panel de clases detectadas Fase 27-10 (3 exports)

## Decisions Made
- Ver `key-decisions` en el frontmatter: `loadRecordings()` preserva a proposito la inconsistencia preexistente de no alternar la visibilidad de `#rec-badge` (solo actualiza el contador), documentada ya en `28-PATTERNS.md` y en `read_first` del plan. No se importa `setRecBadge` en `eventCard.js` porque no tiene ningun uso real en este fichero con esa decision.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. `frontend/index.html` todavia contiene el `<script>` inline monolitico original (sin tocar en este plan, segun alcance de 28-05) — su reescritura para importar estos modulos corresponde a un plan posterior de la fase (28-09, shell de `index.html`).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `eventCard.js` expone `addRecording`/`updateRecordingStatus`, contrato ya documentado para que `websocket.js` (28-07) los consuma en las ramas `recording_started`/`recording_uploaded`/`recording_failed`.
- `detectionClasses.js` queda listo para que `app.js` (28-08) invoque `loadDetectionClasses()` en el bootstrap.
- Sin bloqueos para los planes 28-06 a 28-09.

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*

## Self-Check: PASSED

- FOUND: frontend/js/components/eventCard.js
- FOUND: frontend/js/components/detectionClasses.js
- FOUND: .planning/phases/28-refactor-del-frontend-a-modulos-es/28-05-SUMMARY.md
- FOUND commit: 68a1d37
- FOUND commit: 8a3723f
