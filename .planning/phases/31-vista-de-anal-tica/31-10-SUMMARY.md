---
phase: 31-vista-de-anal-tica
plan: 10
subsystem: ui
tags: [frontend, fetch, abortcontroller, xss-prevention, chartjs]

# Dependency graph
requires:
  - phase: 31-03
    provides: "Marcado de #view-analitica, registerAnalyticsBoot()/activeView() en nav.js, ids de estado por panel"
  - phase: 31-06
    provides: "GET /api/v2/analytics/heatmap y /heatmap/scale (peak/mean/unit, 404 vs 503)"
  - phase: 31-07
    provides: "analytics-charts.js: createCharts/renderHourly/renderOccupancy/setCompare/resizeCharts"
  - phase: 31-08
    provides: "analytics-range.js (initRange/currentRange) y analytics-ranking.js (renderCards/renderRanking)"
  - phase: 31-09
    provides: "GET /api/v2/analytics/export (CSV/JSON) con format/panel Literal"
provides:
  - "frontend/js/views/analytics.js: initAnalytics() — orquestador completo de la vista"
  - "frontend/js/views/analytics-export.js: initExport()/setExportEnabled() — los cuatro botones de descarga"
  - "frontend/js/app.js: initAnalytics() cableado antes de initNav()"
affects: [31-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Import por namespace (import * as nav) para que la unica cita literal de registerAnalyticsBoot en el fichero sea la llamada real, no el import — necesario para que el criterio de aceptacion grep -c == 1 sea satisfacible con codigo valido"
    - "Tabla PANEL_STATES + helper _show(id, on) que alterna las clases hidden/flex — el marcado de 31-03 declara los overlays como class=\"hidden flex-col ...\" (Tailwind), sin la clase flex que activa el display; mismo patron ya usado en timeline.js::_show"
    - "loadPanel() en abort no llama a settle(): un settle() de una tanda vieja decrementaria por error el contador pending de la tanda NUEVA, que ya se reinicio a 5 de forma sincrona en load()"
    - "fetch crudo (no apiFetch) en loadHeatmap(): apiFetch lanza y pierde el codigo de estado, y aqui el codigo ES el dato (404 sin actividad vs 503 sin senal)"

key-files:
  created:
    - frontend/js/views/analytics-export.js
  modified:
    - frontend/js/views/analytics.js
    - frontend/js/app.js

key-decisions:
  - "import * as nav en vez de import { registerAnalyticsBoot, activeView }: el criterio de aceptacion exige exactamente una linea con la cadena registerAnalyticsBoot en el fichero, imposible con import nombrado (la linea de import y la llamada suman dos coincidencias); el namespace import deja la unica cita literal en la llamada real"
  - "setPanelState() usa classList.toggle('hidden'/'flex'), nunca el atributo hidden ni style.display: el marcado de los overlays de 31-03 usa 'hidden' como clase Tailwind dentro de class=\"...\", igual que #an-custom/#an-range-error en 31-08 — no es la propiedad hidden de nav.js, que si es un atributo booleano real en las secciones de vista"
  - "okPanels cuenta solo summary/hourly/occupancy/persons (nunca el heatmap, que no tiene boton de exportar): #an-export-json se enciende cuando los cuatro llegan a 'ok', tanto en la tanda inicial como tras un reintento individual que complete el cuarto"
  - "paintHeatmap() extraída como funcion compartida entre applyHeatmap() (carga normal) y resizeAnalytics() (aplicacion diferida al volver a la pestana), para no duplicar la validacion isSafeMediaUrl ni el cambio de estado a 'ok'"

requirements-completed: [OPS-12, OPS-13, OPS-14, OPS-15]

# Metrics
duration: ~50min
completed: 2026-08-23
---

# Phase 31 Plan 10: Orquestador de analitica — analytics.js, analytics-export.js y arranque Summary

**El andamiaje de 31-03, las graficas de 31-07, el rango/ranking de 31-08 y los siete endpoints de 31-05/06/09 se convierten en una vista que funciona: cinco peticiones en paralelo por tanda (cuatro `/api/v2/analytics/*` + heatmap), un `AbortController` que cancela la tanda anterior, un estado por panel que nunca deja la vista en blanco, y cuatro descargas que van directas al servidor**

## Performance

- **Duration:** ~50 min
- **Tasks:** 3 de 3 completadas
- **Files modified:** 3 (1 nuevo, 2 modificados)

## Accomplishments

- `frontend/js/views/analytics.js` (211 líneas, nuevo): `initAnalytics()` registra el arranque diferido en `nav.js` sin pedir nada; `bootAnalytics()` crea las gráficas, inicializa rango/exportación/botones y dispara la primera tanda; `load(range)` cancela la tanda anterior con un único `AbortController`, dispara `summary`/`hourly`/`occupancy`/`persons` en paralelo (sin combinador que aborte todo por un fallo) y `loadHeatmap()` por separado; cada `loadPanel()` resuelve su propio estado (`loading`/`ok`/`empty`/`error`) y una respuesta rezagada de una tanda abortada no toca el DOM ni decrementa el contador de la tanda nueva.
- Panel del mapa de calor: `loadHeatmap()` pregunta primero a `/heatmap/scale` (404 = sin actividad, 503 = sin señal — un `<img>` solo no puede distinguirlos), `applyHeatmap()` pinta la leyenda relativa (`0`/`50 %`/`pico`) con el valor absoluto y su unidad en el `title`, y la recarga se difiere con `activeView()` cuando la pestaña está oculta, aplicándose al volver desde `resizeAnalytics()`. Cache-busting con `?t=${Date.now()}` en cada recarga.
- `frontend/js/views/analytics-export.js` (47 líneas, nuevo): `initExport(getRange)` engancha los cuatro botones (`hourly`/`occupancy`/`persons`/`json`), valida la URL con `isSafeMediaUrl()` antes de `window.location.href` y no serializa nada en cliente — el servidor de 31-09 genera el fichero. `setExportEnabled(panel, enabled)` apaga/enciende cada botón; `#an-export-json` se enciende solo cuando los cuatro paneles de datos (no el heatmap) han resuelto en `ok`.
- `frontend/js/app.js`: `initAnalytics()` importado y llamado **antes** de `initNav()`, así que abrir la página directamente en `#analitica` no deja la vista en esqueletos para siempre.
- Cero `.reduce()`/`.sort()`/`.filter()`/`Math.max()`, cero `Promise.all`, cero `style.display`, cero `setInterval`/`setTimeout` en los tres módulos — verificado por grep literal, incluidos comentarios (dos ajustes de redacción documentados abajo).
- Los dos ficheros de la vista quedan en 211 y 168 líneas: la válvula de escape del tope de 300 líneas (mover el heatmap a `analytics-charts.js`) **no hizo falta**.
- Suite dirigida verde (`tests/test_frontend_modules.py` 8 passed). Plan solo de frontend, sin tocar pipeline/API/config — no se relanzó la suite completa, consistente con el criterio del `CLAUDE.md` del proyecto.

## Task Commits

1. **Task 1: analytics.js — arranque diferido, tanda de peticiones y estados por panel** - `e3a75cb` (feat)
2. **Task 2: Panel del mapa de calor — 404 frente a 503, cache-busting y recarga diferida** - `1fd152a` (feat)
3. **Task 3: analytics-export.js y el arranque desde app.js** - `2eb820f` (feat)

## Files Created/Modified

- `frontend/js/views/analytics.js` (nuevo, 211 líneas) — orquestador completo: tanda de peticiones, estados por panel, panel del heatmap
- `frontend/js/views/analytics-export.js` (nuevo, 47 líneas) — `initExport`/`setExportEnabled`
- `frontend/js/app.js` — import y llamada de `initAnalytics()` antes de `initNav()`

## Decisions Made

Ver `key-decisions` en el frontmatter: import por namespace de `nav.js` para satisfacer el criterio de aceptación de una sola cita literal de `registerAnalyticsBoot`; `classList.toggle('hidden'/'flex')` en vez de la propiedad `hidden` porque el marcado de los overlays usa `hidden` como clase Tailwind, no como atributo; el contador `okPanels` que enciende la exportación JSON cuenta solo los cuatro paneles de datos; y `paintHeatmap()` compartida entre la carga normal y la aplicación diferida al volver a la pestaña.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] El comentario de cabecera citaba literalmente `Promise.all`, `AbortController` y `AbortError`, y el import de `nav.js` citaba `registerAnalyticsBoot`, disparando varios criterios de aceptación que exigen un conteo exacto (0 o 1) de esas cadenas en todo el fichero, comentarios incluidos**

- **Found during:** Verificación de criterios de aceptación de la Task 1 (primera pasada)
- **Issue:** `grep -c "Promise.all"` debía dar `0` y el comentario de cabecera citaba la expresión al explicar por qué no se usa; `grep -c "AbortController"` y `grep -c "registerAnalyticsBoot"` debían dar exactamente `1`, y con un `import { registerAnalyticsBoot } from '../nav.js'` nombrado más la llamada real, o con la mención en el comentario de cabecera de `AbortController`, el fichero sumaba dos coincidencias de cada una. Mismo patrón de hallazgo que 31-07 (comentarios que citan literalmente las cadenas prohibidas por los criterios) y 31-08 (`toISOString`), esta vez además con un criterio de conteo exacto en vez de solo prohibición.
- **Fix:** Reformulados los comentarios sin citar las cadenas literales exactas ("un combinador que descarte las tres buenas", "controlador de cancelación", "nombre de error de cancelación"), y sustituido el import nombrado de `nav.js` por un import de namespace (`import * as nav from '../nav.js'`), de modo que la única cita literal de `registerAnalyticsBoot` en todo el fichero sea la llamada real dentro de `initAnalytics()`. Sin cambio de comportamiento.
- **Files modified:** `frontend/js/views/analytics.js`
- **Commit:** `e3a75cb` (corregido antes de comitir, no llegó a comitearse en estado roto)

**2. [Rule 1 - Bug] El comentario de cabecera de `analytics-export.js` citaba literalmente `URL.createObjectURL`, disparando el criterio que exige cero coincidencias de esa cadena (y de `new Blob(`/`JSON.stringify(`) en todo el fichero**

- **Found during:** Verificación de criterios de aceptación de la Task 3
- **Issue:** El comentario explicaba el patrón anti-blob citando literalmente `URL.createObjectURL` como lo que el módulo NO hace, pero el criterio `grep -cE "createObjectURL|new Blob\(|JSON.stringify\("` exige `0` coincidencias sin excepción de comentarios, mismo criterio que ya afectó a 31-07/31-08/31-10 Task 1.
- **Fix:** Reformulado el comentario sin citar el nombre literal del método ("sin objeto de blob intermedio ni enlace sintético de descarga"), sin cambiar el código.
- **Files modified:** `frontend/js/views/analytics-export.js`
- **Commit:** `2eb820f` (corregido antes de comitir)

---

**Total deviations:** 2 auto-fixed (Rule 1, ambas de redacción de comentarios para cumplir los criterios de aceptación tal como están escritos por lectura literal — ningún commit quedó con un criterio incumplido, sin impacto en el comportamiento de la vista).

## Issues Encountered

Ninguno más allá de las dos desviaciones documentadas arriba, encontradas y corregidas antes de cada commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Los seis módulos de la fase (`analytics.js`, `analytics-export.js`, `analytics-charts.js`, `analytics-range.js`, `analytics-ranking.js` y el `nav.js` de 31-03) están completos y cableados de punta a punta: abrir `#analitica` crea las gráficas, pide las cinco fuentes en paralelo y pinta cada panel con su propio estado.
- OPS-12, OPS-13, OPS-14 y OPS-15 quedan **funcionalmente completos** por primera vez en la fase (los módulos anteriores existían pero nada los cableaba al DOM); la puerta de fase 31-11 es quien los marca formalmente, mismo patrón que las Fases 27/28/29/30.
- 31-11 puede añadir los seis módulos de la fase a `LOCKED_JS` — todos existen en disco y pasan `node --check`.
- Verificación visual pendiente para 31-11 (checkpoint): graficas pintadas con datos reales, cambio de rango real con abort de peticiones en vuelo, heatmap distinguiendo 404/503 con cámara real, y las cuatro descargas completándose desde el navegador.
- Peso de línea y presupuesto: `analytics.js` 211/300 líneas, `analytics-charts.js` sin tocar en 168/300 — margen amplio para cualquier ajuste que salga del checkpoint visual de 31-11.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
