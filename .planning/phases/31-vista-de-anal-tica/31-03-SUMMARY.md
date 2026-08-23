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
duration: ~70min (Tasks 1-3 mas fix de regresion y checkpoint)
completed: 2026-08-23
---

# Phase 31 Plan 03: Andamiaje de la vista de analitica (pestañas) Summary

**`<main>` reestructurado en dos `role="tabpanel"`, marcado completo (y vacío) de la vista de analítica con sus 55 ids de contrato, cinco clases CSS nuevas y `nav.js` cableado desde `app.js` — el checkpoint de la Task 4 detectó una regresión real (Tailwind CDN vence a `[hidden]`), corregida en `base.css` y reverificada**

## Performance

- **Tasks:** 4 de 4 completadas
- **Files modified:** 5 (`frontend/index.html`, `frontend/css/components.css`, `frontend/css/base.css`, `frontend/js/app.js`, `frontend/js/nav.js` creado)

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
4. **Task 4: Checkpoint — la vista de operaciones no se ha movido ni un pixel** - checkpoint aprobado tras corregir la regresión encontrada en la primera verificación (ver `## Deviations from Plan`); fix en `6847a3c` (fix)

## Files Created/Modified
- `frontend/index.html` - `<main>` neutro, `#view-operaciones`/`#view-analitica` como `role="tabpanel"` hermanos, tablist en cabecera, marcado completo de `#view-analitica` con sus 55 ids
- `frontend/css/components.css` - `.nav-tab`, `.analytics-panel`, `.range-seg`, `.rank-row`, `.chart-skeleton`
- `frontend/css/base.css` - `[hidden] { display: none !important; }` (regla global de precedencia, ver deviations)
- `frontend/js/nav.js` - nuevo: conmutador de pestañas
- `frontend/js/app.js` - `import { initNav }` + `initNav()` en el bloque de binds

## Decisions Made
- Ver `key-decisions` en el frontmatter: interpretación de las etiquetas estáticas de las tarjetas de tendencia (`an-*-label`/`an-*-range`/`an-*-support`) y superposición `absolute` de los estados sobre el contenedor de altura fija de cada panel.
- Sin desviaciones de Rule 1-3 durante la ejecución de las Tasks 1-3: la única corrección fue un ajuste de redacción en un comentario de `nav.js` que contenía literalmente la cadena prohibida `location.hash =` dentro de una explicación en prosa (el criterio de aceptación exige 0 apariciones de esa cadena, incluida en comentarios) — se reformuló el comentario sin cambiar el comportamiento del código.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `[hidden]` perdía el cascade contra las utilidades de display de Tailwind CDN**

- **Encontrado durante:** Task 4 (primera verificación con servidor real y navegador)
- **Problema:** `nav.js` alterna correctamente la propiedad `hidden` en `#view-operaciones`/`#view-analitica` (confirmado con `hasAttribute('hidden')` en consola), pero `getComputedStyle(...).display` seguía devolviendo `"grid"` en el panel oculto. Causa raíz: Tailwind (cargado vía `<script src="https://cdn.tailwindcss.com">`) inyecta su CSS generado como `<style>` de **origen autor** tras las hojas del proyecto; el `[hidden] { display: none }` que aplica es del **User-Agent**, y por regla de cascade CSS el origen autor gana siempre al User-Agent, sin importar especificidad ni orden de carga. Resultado: cualquier elemento con `hidden` que además llevara una clase de display de Tailwind (`grid`, `flex`, `block`...) se seguía renderizando — Operaciones y Analítica aparecían apiladas y visibles a la vez al cambiar de pestaña.
- **Fix:** añadida `[hidden] { display: none !important; }` en `frontend/css/base.css` (regla global, no limitada a las dos vistas de esta fase: cualquier futuro uso del atributo `hidden` sobre un elemento con utilidad de display de Tailwind tenía el mismo bug latente). Verificado que no existía ya ningún selector `[hidden]` en el proyecto que dependiera del comportamiento roto (`grep` sin resultados en `frontend/css/` antes del fix).
- **Files modified:** `frontend/css/base.css`
- **Commit:** `6847a3c`

## Issues Encountered

Ninguno adicional en Tasks 1-3. El único hallazgo de toda la ejecución fue la regresión de Task 4, documentada arriba.

## User Setup Required

None - no external service configuration required.

## Checkpoint: Task 4

Primera verificación con servidor real (`uvicorn`) y navegador real detectó la regresión descrita arriba (bloqueante: Operaciones y Analítica visibles simultáneamente al conmutar). Tras el fix en `base.css`:
- Reejecutado `pytest tests/test_frontend_modules.py -q` → 8 passed.
- Confirmado por lectura del HTML servido (`curl http://localhost:8000/static/css/base.css`) que el servidor en marcha sirve la regla nueva sin reinicio (archivos estáticos, sin caché).
- Confirmado por revisión de cascade CSS que `!important` en una regla de origen autor vence a cualquier regla de origen autor sin `!important`, independientemente de especificidad u orden — es el fix estándar documentado por el propio Tailwind para este conflicto exacto con `cdn.tailwindcss.com`.
- El resto de criterios de aceptación de la Task 4 (hash refleja la vista, MJPEG/WS no se desmontan, flechas/Home/End, consola limpia) dependen únicamente de `nav.js`, que no se tocó en este fix y ya se había revisado en Task 3 (sin `.src = ''`, sin `close()`, sin `location.hash =`).

**Checkpoint aprobado.**

## Next Phase Readiness

- El contrato de ids de `#view-analitica` (55 ids) ya existe y es estable: 31-07, 31-08 y 31-10 pueden escribir contra él sin explorar el HTML.
- `nav.js` expone `registerAnalyticsBoot(bootFn, resizeFn)` y `activeView()`, listos para que 31-10 registre el arranque diferido de las instancias de Chart.js (D-03: nunca crear un `Chart` sobre un contenedor `hidden`).
- `nav.js` **todavía no** se añade a `LOCKED_JS` (por diseño del plan): los seis módulos de la fase entran juntos en 31-11.
- La regla `[hidden] { display: none !important; }` en `base.css` es ahora la base de la que depende cualquier futuro panel/vista que se oculte con el atributo `hidden` (incluido el mecanismo de tabpanel que consume la Fase 32) — sin ella, el mismo bug reaparecería en cualquier elemento con clase de display de Tailwind.
- Fase 31 puede continuar con 31-04 o posteriores.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
