---
phase: 31-vista-de-anal-tica
plan: 03
subsystem: ui
tags: [frontend, tabs, aria, chartjs-scaffold]

# Dependency graph
requires:
  - phase: 30-event-timeline-y-centro-de-alertas
    provides: "convenciones de components.css (.filter-chip, .chip, .row-action) y patron de estados vacio/error/cargando reutilizados en la vista de analitica"
provides:
  - "Contrato de ids de #view-analitica (55 ids) que consumen 31-07, 31-08 y 31-10 sin explorar el HTML"
  - "nav.js: conmutador de pestanas con hash, teclado y registerAnalyticsBoot() para la activacion diferida de Chart.js"
  - "<main> como contenedor neutro con dos role=tabpanel hermanos; la reticula de operaciones vive en #view-operaciones"
affects: [31-04, 31-05, 31-06, 31-07, 31-08, 31-09, 31-10, 31-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Conmutador de vistas: dos role=tabpanel + propiedad hidden, hash resuelto con lista blanca, history.replaceState (nunca location.hash=), activacion diferida de Chart.js via registerAnalyticsBoot()/resize()"

key-files:
  created:
    - frontend/js/nav.js
  modified:
    - frontend/index.html
    - frontend/css/components.css
    - frontend/js/app.js

key-decisions:
  - "Los ids an-total-label/an-delta-range/an-peak-support/an-unknown-support llevan directamente el texto fijo de la tabla de copy (son las etiquetas de cada tarjeta, no valores dinamicos); el numero/cifra vive en an-*-value. Interpretacion necesaria porque el contrato de <interfaces> no distinguia explicitamente cual de los dos elementos es la etiqueta estatica."
  - "Estados de carga/vacio/error de los paneles 1, 2 y 4 se superponen con position:absolute sobre el contenedor del grafico/lista (mismo contenedor que fija la altura de 240px), en vez de vivir fuera de el: mantiene el alto del panel estable durante las transiciones de estado sin flash de layout."

requirements-completed: []  # OPS-12/13/15 se completan en 31-11 (puerta de fase); este plan solo sienta el andamiaje visual

# Metrics
duration: ~45min (Tasks 1-3; Task 4 checkpoint pendiente de verificacion humana)
completed: pending (Task 4 sin resolver)
---

# Phase 31 Plan 03: Andamiaje de la vista de analitica (pestañas) Summary

**`<main>` reestructurado en dos `role="tabpanel"`, marcado completo (y vacío) de la vista de analítica con sus 55 ids de contrato, cinco clases CSS nuevas y `nav.js` cableado desde `app.js` — Task 4 (checkpoint visual) queda pendiente de verificación humana con servidor real**

## Performance

- **Tasks:** 3 de 4 completadas (Task 4 es un checkpoint bloqueante, no ejecutable por el agente)
- **Files modified:** 4 (`frontend/index.html`, `frontend/css/components.css`, `frontend/js/app.js`, `frontend/js/nav.js` creado)

## Accomplishments
- `<main>` es ahora un contenedor neutro (`class="flex-1 w-full"`); las clases de rejilla que antes vivían en `<main>` bajaron a `#view-operaciones`, que junto a `#view-analitica` forma el par de `role="tabpanel"` hermanos (Pitfall 8 evitado)
- Tablist en la cabecera (`#tab-operaciones` / `#tab-analitica`) entre el badge del modelo y `#cam-status`, sin reordenar nada existente
- `#view-analitica` completo: barra de rango (4 chips + personalizado + exportar JSON), cuatro tarjetas de tendencia, panel "Personas por hora" con leyenda de dos series y botón comparar, panel "Ocupación por zona", panel "Mapa de calor" (sin botón de exportar, con leyenda INFERNO) y panel "Personas más vistas" — los 55 ids del contrato de `<interfaces>` existen, cada panel con sus estados vacío/error/cargando y las cadenas exactas del UI-SPEC
- Cinco clases CSS nuevas (`.nav-tab`, `.analytics-panel`, `.range-seg`, `.rank-row`, `.chart-skeleton`) añadidas al final de `components.css` con las medidas del UI-SPEC
- `frontend/js/nav.js` (93 líneas): `activate()` alterna `hidden` (nunca `style.display` ni se desmonta nada), hash resuelto con lista blanca (`operaciones`/`analitica`), `history.replaceState` (nunca `location.hash =`), flechas/`Home`/`End` con activación automática y *roving tabindex*, y `registerAnalyticsBoot(bootFn, resizeFn)` listo para que 31-10 registre el arranque diferido de Chart.js
- `app.js` importa `initNav` y lo llama dentro del bloque de `bind*()` del `DOMContentLoaded`, antes de cualquier pintado

## Task Commits

1. **Task 1: Bajar la retícula de main a la sección de operaciones y añadir el tablist** - `301511d` (feat)
2. **Task 2: Marcado completo de la vista de analítica y clases CSS nuevas** - `c6e7555` (feat)
3. **Task 3: nav.js y su enganche desde app.js** - `b7c7d7d` (feat)
4. **Task 4: Checkpoint — la vista de operaciones no se ha movido ni un pixel** - **PENDIENTE**, requiere servidor real y navegador (ver `## Checkpoint pendiente`)

## Files Created/Modified
- `frontend/index.html` - `<main>` neutro, `#view-operaciones`/`#view-analitica` como `role="tabpanel"` hermanos, tablist en cabecera, marcado completo de `#view-analitica` con sus 55 ids
- `frontend/css/components.css` - `.nav-tab`, `.analytics-panel`, `.range-seg`, `.rank-row`, `.chart-skeleton`
- `frontend/js/nav.js` - nuevo: conmutador de pestañas
- `frontend/js/app.js` - `import { initNav }` + `initNav()` en el bloque de binds

## Decisions Made
- Ver `key-decisions` en el frontmatter: interpretación de las etiquetas estáticas de las tarjetas de tendencia (`an-*-label`/`an-*-range`/`an-*-support`) y superposición `absolute` de los estados sobre el contenedor de altura fija de cada panel.
- Sin desviaciones de Rule 1-3 durante la ejecución de las Tasks 1-3: la única corrección fue un ajuste de redacción en un comentario de `nav.js` que contenía literalmente la cadena prohibida `location.hash =` dentro de una explicación en prosa (el criterio de aceptación exige 0 apariciones de esa cadena, incluida en comentarios) — se reformuló el comentario sin cambiar el comportamiento del código.

## Deviations from Plan

None de las Rules 1-4 aplicadas al código: la única corrección fue de redacción de un comentario (ver arriba), sin impacto funcional.

## Issues Encountered

None en Tasks 1-3.

## User Setup Required

None - no external service configuration required.

## Checkpoint pendiente

**Task 4** es un `checkpoint:human-verify` bloqueante y no se ha ejecutado en esta sesión: requiere servidor real (`uvicorn`) y navegador para confirmar que la vista de operaciones no sufrió ninguna regresión visual/funcional tras la reestructuración de `<main>`, que conmutar pestañas no reconecta el MJPEG ni el WebSocket, que el hash refleja la vista activa, que las flechas/Home/End funcionan y que la consola queda limpia. Ver la sección `<how-to-verify>` de `31-03-PLAN.md` Task 4 para el procedimiento exacto. Este plan **no se considera cerrado** (ni se ha avanzado STATE.md/ROADMAP.md/REQUIREMENTS.md) hasta que ese checkpoint se resuelva.

## Next Phase Readiness

- El contrato de ids de `#view-analitica` (55 ids) ya existe y es estable: 31-07, 31-08 y 31-10 pueden escribir contra él sin explorar el HTML.
- `nav.js` expone `registerAnalyticsBoot(bootFn, resizeFn)` y `activeView()`, listos para que 31-10 registre el arranque diferido de las instancias de Chart.js (D-03: nunca crear un `Chart` sobre un contenedor `hidden`).
- `nav.js` **todavía no** se añade a `LOCKED_JS` (por diseño del plan): los seis módulos de la fase entran juntos en 31-11.
- Pendiente de aprobación humana del checkpoint antes de que la Fase 31 continúe con 31-04 o posteriores, según decida el orquestador.

---
*Phase: 31-vista-de-anal-tica*
*Completed: pending (Task 4 checkpoint)*

## Self-Check: PASSED
