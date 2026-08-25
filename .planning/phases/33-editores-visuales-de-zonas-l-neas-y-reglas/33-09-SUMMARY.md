---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 09
subsystem: ui
tags: [canvas, videoCanvas, object-fit-cover, cursor, tailwind]

# Dependency graph
requires: []
provides:
  - "canvasClickToFrac(clickX, clickY, img, canvas) exportada en videoCanvas.js — inversa de normalizedBoxToCanvasRect, convierte un click en px de canvas a fraccion [0,1] del frame fuente"
  - "syncCanvasToImage(canvas, img) exportada (antes privada) para que 33-10/33-11 monten su propio ResizeObserver sobre #camera-feed"
  - ".zone-editor-canvas en components.css (cursor: crosshair; touch-action: none;)"
affects: [33-10-editor-zonas, 33-11-editor-lineas]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Matematica de canvas/letterboxing centralizada en videoCanvas.js: cualquier editor que dibuje sobre #camera-feed debe importar canvasClickToFrac/syncCanvasToImage, nunca reimplementar scale=max()+offset"

key-files:
  created: []
  modified:
    - frontend/js/components/videoCanvas.js
    - frontend/css/components.css

key-decisions:
  - "syncCanvasToImage se exporta tal cual, sin tocar el singleton privado _tracksResizeObserver/initTracksOverlay (siguen ligados solo a #tracks-overlay)"
  - "Solo se anadio .zone-editor-canvas a components.css (cursor crosshair + touch-action none); no se crearon clases anticipando necesidades de 33-10/33-11 no confirmadas"

patterns-established:
  - "canvasClickToFrac como inversa formal de normalizedBoxToCanvasRect, mismo fichero, mismas variables (naturalWidth/naturalHeight, nunca width/height)"

requirements-completed: [OPS-21, OPS-22]

# Metrics
duration: 8min
completed: 2026-08-24
---

# Phase 33 Plan 09: Canvas math compartido (canvasClickToFrac) Summary

**canvasClickToFrac exportada en videoCanvas.js como inversa exacta de normalizedBoxToCanvasRect, deshaciendo el letterboxing de object-fit:cover para que 33-10 (zonas) y 33-11 (lineas) no reimplementen la matematica de canvas cada uno por su lado.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-24T15:32:00Z
- **Completed:** 2026-08-24T15:40:32Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- `canvasClickToFrac(clickX, clickY, img, canvas)` exportada junto a `normalizedBoxToCanvasRect`, con guard `!iw || !ih || !cw || !ch` igual que su par directa
- `syncCanvasToImage` pasa de privada a exportada, reutilizable por el `ResizeObserver` propio que 33-10/33-11 montaran sobre `#camera-feed`
- `.zone-editor-canvas` (cursor: crosshair; touch-action: none;) anadida a `components.css` sin gastar mas presupuesto del necesario

## Task Commits

Each task was committed atomically:

1. **Task 1: canvasClickToFrac exportada + syncCanvasToImage reutilizable + cursor de edicion** - `f5cf7b2` (feat)

**Plan metadata:** (siguiente commit, este SUMMARY)

## Files Created/Modified
- `frontend/js/components/videoCanvas.js` - +canvasClickToFrac (export), syncCanvasToImage ahora exportada (150 lineas, limite 300)
- `frontend/css/components.css` - +.zone-editor-canvas (242 lineas, limite 300)

## Decisions Made
- No se tocó `initTracksOverlay`/`_tracksResizeObserver`: siguen privados y ligados a `#tracks-overlay`/`#video-feed` (Operaciones), sin compartir singleton con el futuro canvas de edicion sobre `#camera-feed` (Camara).
- CSS minimo: solo la clase que Tailwind no cubre como utilidad de una palabra (cursor de precision + bloqueo de scroll tactil). Margen de 58 lineas libres queda intacto para 33-10/33-11/33-12.

## Deviations from Plan

None - plan ejecutado exactamente como estaba escrito.

## Issues Encountered
None.

## User Setup Required

None - no requiere configuracion de servicios externos.

## Next Phase Readiness
`canvasClickToFrac` y `syncCanvasToImage` listas para que 33-10 (editor de zonas) y 33-11 (editor de lineas) las importen desde `../components/videoCanvas.js` sin reimplementar matematica de canvas. `.zone-editor-canvas` disponible para el contenedor del canvas de edicion.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/components/videoCanvas.js
- FOUND: frontend/css/components.css
- FOUND: .planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-09-SUMMARY.md
- FOUND commit: f5cf7b2
