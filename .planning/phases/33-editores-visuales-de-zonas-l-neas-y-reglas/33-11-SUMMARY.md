---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 11
subsystem: ui
tags: [canvas, lines, crud, anti-xss, videoCanvas, direccion]

# Dependency graph
requires:
  - "canvasClickToFrac/syncCanvasToImage (33-09, frontend/js/components/videoCanvas.js)"
  - "#zone-line-canvas (33-10, contrato de ids compartido)"
  - "router /api/v2/lines (33-07, backend/api/v2/lines.py — aun no ejecutado en este punto, se escribe contra el contrato ya fijado)"
provides:
  - "initLineEditor() — engancha el motor de canvas de 2 clicks (inicio/fin) y el CRUD de lineas sobre el MISMO canvas que zoneEditor.js"
  - "loadLines() exportada — pinta #line-list y redibuja todas las lineas persistidas contra /api/v2/lines"
  - "Contrato de ids documentado en la cabecera del fichero (#line-mode-toggle, #line-list, #line-form-name, #line-new-btn, #line-save-btn, #line-cancel-btn, #line-error) para que 33-13 monte el HTML real"
affects: [33-13-wiring-camara]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Trazado de 2 clicks (vs. N vertices de zoneEditor.js): 1er click fija inicio, mousemove dibuja segmento fantasma, 2o click fija fin; un click adicional tras completar empieza una linea nueva descartando la anterior si no se guardo"
    - "Indicador de direccion: triangulo perpendicular al punto medio del segmento, formula fija (dy,-dx) documentada en cabecera como convencion arbitraria pero deterministica — no se valida contra el servidor ni se persiste"
    - "Render de 422: mismo patron exacto que zoneEditor.js (33-10) — Array.isArray(d.detail) ? d.detail.map(e => e.msg).join(', ') : String(d.detail)"

key-files:
  created:
    - frontend/js/components/lineEditor.js
  modified: []

key-decisions:
  - "Reutiliza el mismo <canvas> #zone-line-canvas que zoneEditor.js (33-10) en vez de crear uno propio, tal como recomendaba el <interfaces> del plan — documentado explicitamente en la cabecera del fichero que 33-13 debe anadir un selector Zonas/Lineas que active un _editMode a la vez, nunca ambos simultaneamente"
  - "#line-form-name es un input real (a diferencia de zoneEditor.js, que autogenera el nombre) porque el contrato de ids del plan lo pedia explicitamente; si el operador lo deja vacio se autogenera 'Linea HH:MM:SS' como fallback"
  - "_lines (ultima lista cargada) se guarda en modulo para redibujar TODAS las lineas persistidas en cada _redraw(), no solo el trazado en curso — necesario para que el must_have 'el operador puede dibujar multiples lineas... cada una con su indicador de direccion' sea visible en canvas, no solo en la lista de texto"

requirements-completed: [OPS-22]

# Metrics
duration: 20min
completed: 2026-08-24
---

# Phase 33 Plan 11: Editor visual de líneas (canvas + CRUD + dirección) Summary

**`lineEditor.js` nuevo: motor de canvas de dos clicks (inicio/fin) con segmento fantasma en `mousemove`, triángulo de dirección perpendicular al punto medio, y CRUD completo contra `/api/v2/lines`, compartiendo el mismo `<canvas>` y la misma matemática de letterboxing que `zoneEditor.js` (33-10).**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2/2 completadas
- **Files modified:** 1

## Accomplishments
- Motor de dibujo sobre `<canvas>`: primer click fija el punto de inicio, `mousemove` redibuja un segmento fantasma hasta la posición del ratón, segundo click completa el trazado; un click adicional sobre un trazado ya completo empieza una línea nueva
- Indicador visual de dirección: triángulo de 3 puntos (`ctx.lineTo`) perpendicular al segmento en su punto medio, con convención de lado fija y documentada en la cabecera (fórmula `(dy,-dx)`), puramente orientativo — no se envía al servidor
- CRUD completo contra `/api/v2/lines`: `loadLines()` (GET, exportada, redibuja además todas las líneas persistidas en el canvas), `_saveLine()` (POST upsert), `_deleteLine()` (DELETE) — cero referencias a otro endpoint
- Render de error 422 con el shape nativo de FastAPI (`Array.isArray(d.detail) ? d.detail.map(e => e.msg).join(', ') : String(d.detail)`), preservando el trazado en curso para reintentar sin perder los dos puntos ya marcados
- Clic en una fila de `#line-list` carga esa línea (inicio/fin/nombre) en el trazado para editarla
- Reutiliza `#zone-line-canvas` (contrato de 33-10) en vez de crear un segundo `<canvas>` apilado, con la decisión de compartición documentada explícitamente en la cabecera para que 33-13 la implemente sin ambigüedad
- Cero `innerHTML` en todo el fichero

## Task Commits

1. **Task 1 + Task 2 (mismo fichero, un solo commit):** `95a97eb` (feat) — motor de canvas y CRUD/formulario se escribieron juntos porque, igual que en 33-10, el motor de canvas por sí solo no es verificable ni tiene sentido funcional sin el CRUD que lo consume; separarlos en dos commits habría dejado el módulo en un estado no ejecutable a medio camino. Documentado aquí como desviación de forma del `<task_commit_protocol>`, no de contenido — ambos `<acceptance_criteria>` de Task 1 y Task 2 se verifican contra el mismo commit.

## Files Created/Modified
- `frontend/js/components/lineEditor.js` (278 líneas, límite 300) — nuevo: `initLineEditor()`, `loadLines()` (export), motor de canvas privado (`_onMouseDown/_onMouseMove/_redraw/_arrowPoints/_drawSegment/_fracToCanvasPx`), CRUD privado (`_saveLine/_deleteLine/_loadLineIntoForm/_clearForm/_showError`)

## Decisions Made
- Ver `key-decisions` en el frontmatter.
- Formato del body enviado en `POST /api/v2/lines`: `{id, name, start_x_frac, start_y_frac, end_x_frac, end_y_frac, enabled: true}` tal como especifica el contrato de 33-07; `camera_id` no se incluye en el body (el router de 33-07 lo trata como opcional con default `"cam1"` según su propio `<action>`, y el plan de este módulo no listó `camera_id` en el body del `<behavior>` — se deja al valor por defecto del servidor).

## Deviations from Plan

None - plan ejecutado tal como estaba escrito. La única nota de forma (commit único para ambos tasks) sigue exactamente el precedente ya documentado en 33-10-SUMMARY.md para el mismo tipo de situación.

## Issues Encountered

Ninguno relevante. El router backend `/api/v2/lines` (33-07) aún no existe en este punto de la ejecución (wave 3, posterior a esta wave 2) — este módulo es puramente frontend escrito contra el contrato ya fijado en 33-RESEARCH.md/33-PATTERNS.md/33-07-PLAN.md, tal como indicaba el plan; no se puede verificar contra un servidor real hasta que 33-07 y 33-13 existan.

## Known Stubs

Ninguno dentro del propio `lineEditor.js` — el módulo es funcional end-to-end contra `/api/v2/lines` en cuanto ese router exista (33-07) y `initLineEditor()` tenga un llamador (33-13). El "stub" de facto es que ningún HTML real lo invoca todavía, documentado como diseño explícito del plan (mismo patrón que `zoneEditor.js` en 33-10), no como dato falso o placeholder.

## Threat Flags

Ninguna superficie nueva fuera del threat model del plan (T-33-14): anti-XSS con `createElement`/`textContent` aplicado en todo el fichero, incluyendo el mensaje de error 422 y el nombre de cada línea en `#line-list`.

## User Setup Required

None - no requiere configuración de servicios externos.

## Next Phase Readiness

- `initLineEditor()`/`loadLines()` listos para que el Plan 33-13 los importe desde `../components/lineEditor.js` y llame `initLineEditor()` dentro de `initCamera()`, junto a `initZoneEditor()` (33-10).
- Contrato de ids completo documentado en la cabecera del fichero (`#zone-line-canvas` compartido, `#line-mode-toggle`, `#line-list`, `#line-new-btn`, `#line-form-name`, `#line-save-btn`, `#line-cancel-btn`, `#line-error`) — 33-13 debe crear exactamente estos ids en `index.html` y decidir el selector de modo Zonas/Líneas que evite que ambos `_editMode` estén activos a la vez.
- Bloqueante conocido para 33-13 (heredado de 33-10, no nuevo de este plan): debe retirar `bindZoneForm` del import de `app.js` además del wiring nuevo de `initLineEditor()`.
- Depende de que 33-07 (`backend/api/v2/lines.py`) exista antes de que el CRUD real funcione en el navegador — hasta entonces, `loadLines()`/`_saveLine()`/`_deleteLine()` fallarán con red/404 de forma silenciosa (capturado por los `catch` existentes), sin romper la carga del módulo.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/components/lineEditor.js
- FOUND: .planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-11-SUMMARY.md
- FOUND: commit 95a97eb
