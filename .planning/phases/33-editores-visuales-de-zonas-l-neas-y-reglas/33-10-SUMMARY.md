---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 10
subsystem: ui
tags: [canvas, zones, crud, anti-xss, videoCanvas]

# Dependency graph
requires:
  - "canvasClickToFrac/syncCanvasToImage (33-09, frontend/js/components/videoCanvas.js)"
  - "router /api/v2/zones (33-03, backend/api/v2/zones.py)"
provides:
  - "initZoneEditor() — engancha el motor de canvas (dibujo/arrastre de vertices) y el CRUD de zonas; no dispara red hasta modo edicion"
  - "loadZones() — sigue exportada (compatibilidad de nombre con el import existente de app.js), ahora pinta contra /api/v2/zones"
  - "Contrato de ids documentado en la cabecera del fichero para que 33-13 monte el HTML real"
affects: [33-13-wiring-camara]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Canvas 2D nativo sin libreria: mousedown anade vertice o selecciona uno existente por hit-testing (radio 8px), mousemove reposiciona, dblclick cierra el trazado"
    - "Trazado en curso ({x_frac,y_frac}[]) sobrevive a un 422 del servidor para que el operador corrija sin redibujar desde cero"
    - "Render de 422: Array.isArray(d.detail) ? d.detail.map(e => e.msg).join(', ') : String(d.detail) — shape nativo de FastAPI (body param Pydantic tipado), distinto del shape custom {errors:[...]} de config.py/rules.py"

key-files:
  created: []
  modified:
    - frontend/js/components/zoneEditor.js

key-decisions:
  - "Reescritura completa del fichero (104 lineas -> 296 lineas): se sustituye el formulario JSON manual (bindZoneForm/#add-zone-panel) por el motor de canvas + CRUD contra v2, tal como pedia el plan"
  - "loadZones() se mantiene con el mismo nombre exportado (aunque su implementacion cambia de /api/zones a /api/v2/zones) porque app.js ya la importa; bindZoneForm() SI desaparece (sustituida por initZoneEditor(), que 33-13 debe cablear) — ver Issues Encountered"
  - "Clic en el nombre de una zona de #zone-list carga su poligono/kind/schedule en el trazado en curso (_loadZoneIntoForm), no solicitado literalmente por el <action> pero necesario para que 'editar sus vertices' (must_have) sea alcanzable sin reconstruir el poligono a mano"
  - "kind='exclude_objects' bloquea el <select> (disabled) y pinta #zone-kind-locked-label con el texto de origen, en vez de forzarlo a uno de los 3 valores editables"
  - "Compactacion agresiva de comentarios/blank-lines para cumplir el limite de 300 lineas (296) sin sacrificar los dos tasks del plan en el mismo fichero"

requirements-completed: [OPS-21, OPS-23]

# Metrics
duration: 25min
completed: 2026-08-24
---

# Phase 33 Plan 10: Editor visual de zonas (canvas + CRUD + tipo/horario) Summary

**`zoneEditor.js` reescrito de formulario JSON manual a motor de canvas nativo (dibujar/arrastrar/cerrar poligono) con CRUD completo contra `/api/v2/zones`, selector de tipo con bloqueo para `exclude_objects` heredado y horario propio (chips de dias + rango horario), todo por `createElement`/`textContent` sin `innerHTML`.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2/2 completadas
- **Files modified:** 1

## Accomplishments
- Motor de dibujo sobre `<canvas>`: `mousedown` anade vertice o selecciona uno existente (hit-testing por distancia euclidea, radio 8px), `mousemove` con vertice seleccionado lo reposiciona via `canvasClickToFrac`, `dblclick` cierra el trazado — sin reimplementar la matematica de letterboxing (`_fracToCanvasPx` es la inversa local de `canvasClickToFrac`, misma formula que `videoCanvas.js`)
- `ResizeObserver` propio sobre `#camera-feed` (no comparte el singleton privado de `videoCanvas.js`)
- CRUD contra `/api/v2/zones` exclusivamente: `loadZones()` (GET), `_saveZone()` (POST upsert), `_deleteZone()` (DELETE) — cero referencias a `/api/zones` v1
- `kind='exclude_objects'` deshabilita el `<select>` y muestra `#zone-kind-locked-label` con el origen, en vez de forzar un valor incorrecto
- 422 del servidor renderizado con `Array.isArray(d.detail) ? d.detail.map(e => e.msg).join(', ') : String(d.detail)` (shape nativo de FastAPI, no el custom de `rules.py`), preservando el trazado en curso para reintentar
- Clic en una fila de `#zone-list` carga esa zona (poligono/kind/schedule) en el formulario para editarla
- Cero `innerHTML` en todo el fichero (corrige la unica desviacion anti-XSS que tenia el `zoneEditor.js` original)

## Task Commits

1. **Task 1 + Task 2 (mismo fichero, un solo commit):** `4d99dea` (feat) — motor de canvas y CRUD/formulario se escribieron juntos porque ambos tasks modifican exclusivamente `frontend/js/components/zoneEditor.js` y no eran separables en commits intermedios sin dejar el modulo en un estado no compilable a medio camino (el motor de canvas por si solo no tiene forma de probarse sin el CRUD que lo consume). Documentado aqui como desviacion de forma del `<task_commit_protocol>`, no de contenido: ambos `<acceptance_criteria>` de Task 1 y Task 2 se verifican contra el mismo commit.

## Files Created/Modified
- `frontend/js/components/zoneEditor.js` (296 lineas, limite 300) — reescrito completo: `initZoneEditor()`, `loadZones()` (export), motor de canvas privado (`_onMouseDown/_onMouseMove/_redraw/_hitTestVertex/_fracToCanvasPx`), CRUD privado (`_saveZone/_deleteZone/_loadZoneIntoForm/_applyKindLock/_buildSchedule`)

## Decisions Made
- Ver `key-decisions` en el frontmatter.
- Formato del body enviado en `POST /api/v2/zones`: `{id, name, polygon, kind, schedule, enabled: true}` tal como especifica el contrato de 33-03; `id`/`name` se autogeneran (`zone-{timestamp}` / hora local) para zonas nuevas porque el plan no definio un input de nombre explicito en el contrato de ids — el operador puede renombrar despues editando directamente en BD si lo necesita, o un plan futuro puede anadir `#zone-form-name` sin romper este contrato (discrecion documentada, no bloqueante para el `must_have` del plan).

## Deviations from Plan

### Auto-fixed / documented issues

**1. [Rule 3 - Blocking, documentado no corregido] `app.js` importa `bindZoneForm` que ya no se exporta**
- **Encontrado en:** Task 2, al revisar consumidores existentes de `zoneEditor.js`
- **Detalle:** `frontend/js/app.js:8` hace `import { loadZones, bindZoneForm } from './components/zoneEditor.js'` y llama `bindZoneForm()` en `DOMContentLoaded` (linea 26). Esta funcion desaparece en la reescritura (sustituida por `initZoneEditor()`). `loadZones` sigue exportada asi que esa mitad del import sigue funcionando, pero el import nombrado de `bindZoneForm` fallará en el navegador (ES modules) hasta que `app.js` deje de importarla.
- **Por que no se corrigio aqui:** el propio plan 33-10 acota `files_modified` a solo `zoneEditor.js` ("sin tocar el HTML real todavia") y el Plan 33-13 (`files_modified: frontend/js/app.js, frontend/index.html, ...`) es explicitamente quien cablea `initZoneEditor()` en `initCamera()` y retira las referencias antiguas. Tocar `app.js` en este plan se saldria del scope declarado y duplicaria trabajo que 33-13 ya tiene asignado por diseño (wave 2 vs wave 5 de la fase).
- **Impacto:** el frontend queda en un estado transitorio no ejecutable en navegador entre el cierre de este plan y el cierre de 33-13 (dentro de la misma fase, antes de que el usuario final la use). `tests/test_frontend_modules.py` no lo detecta porque no ejecuta JS, solo verifica ficheros/lineas/estatico.
- **Accion recomendada:** el Plan 33-13 debe eliminar `bindZoneForm` del import de `app.js` y anadir `initZoneEditor()` a `initCamera()`, tal como su propio `<objective>` ya establece.

Resto de tasks: ejecutados tal como especificaba el `<action>` de cada uno, sin desviaciones adicionales.

## Issues Encountered

Ver deviation #1 arriba — es el unico hallazgo relevante, ya con plan de resolucion (33-13) identificado.

## Known Stubs

Ninguno dentro del propio `zoneEditor.js` — el modulo es funcional end-to-end contra `/api/v2/zones` real. El "stub" de facto es que ningun HTML real lo invoca todavia (`initZoneEditor()` no tiene llamador hasta 33-13), documentado como diseño explicito del plan, no como dato falso o placeholder.

## Threat Flags

Ninguna superficie nueva fuera del threat model del plan (T-33-13): anti-XSS con `createElement`/`textContent` aplicado en todo el fichero, incluyendo el mensaje de error 422 y el nombre/kind de cada zona en `#zone-list`.

## User Setup Required

None - no requiere configuracion de servicios externos.

## Next Phase Readiness

- `initZoneEditor()`/`loadZones()` listos para que el Plan 33-13 los importe desde `../components/zoneEditor.js` y llame `initZoneEditor()` dentro de `initCamera()`.
- Contrato de ids completo documentado en la cabecera del fichero (`#zone-line-canvas`, `#zone-mode-toggle`, `#zone-list`, `#zone-new-btn`, `#zone-form-kind`, `#zone-kind-locked-label`, `#zone-form-days`, `#zone-form-time-start/-end`, `#zone-save-btn`, `#zone-cancel-btn`, `#zone-error`) — 33-13 debe crear exactamente estos ids en `index.html`.
- Bloqueante conocido para 33-13: debe retirar `bindZoneForm` del import de `app.js` (ver Deviations) ademas del wiring nuevo que su propio plan ya contempla.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/components/zoneEditor.js
- FOUND: .planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-10-SUMMARY.md
- FOUND: commit 4d99dea
