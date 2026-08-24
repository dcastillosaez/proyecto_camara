---
phase: 31-vista-de-anal-tica
plan: 07
subsystem: ui
tags: [frontend, chartjs, analytics, accessibility]

# Dependency graph
requires:
  - phase: 31-03
    provides: "Contrato de ids de #view-analitica (#an-chart-hourly, #an-chart-occupancy, contenedores de 240px) y registerAnalyticsBoot() para activacion diferida"
  - phase: 31-05
    provides: "Router /api/v2/analytics/{hourly,occupancy} con peak_index, min_index, chart, has_previous, truncated ya resueltos en servidor"
provides:
  - "frontend/js/views/analytics-charts.js: createCharts, renderHourly, renderOccupancy, setCompare, resizeCharts"
affects: [31-10, 31-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Activacion diferida de Chart.js: instancias creadas solo en createCharts(), llamado por 31-10 en la primera activacion de la pestana (nunca en DOMContentLoaded)"
    - "Cero agregacion de cliente (OPS-14): peak_index/min_index/chart/has_previous consumidos por indice, .map() solo para colores de presentacion por posicion"
    - "Guarda de division por cero como ternario (paso = n > 1 ? i/(n-1) : 0) en vez de Math.max(1, n-1), para que el fichero no contenga la cadena Math.max( ni por lectura literal en un comentario"

key-files:
  created:
    - frontend/js/views/analytics-charts.js
  modified: []

key-decisions:
  - "El fichero se escribio completo en un solo Write y luego se dividio en dos commits retirando temporalmente el contenido de la Task 2 (creacion de occupancyChart dentro de createCharts(), renderOccupancy, resizeCharts), verificando los criterios de aceptacion de la Task 1 sobre ese estado intermedio antes de restaurar el contenido completo para el commit de la Task 2 — mismo patron que uso 31-05 para mantener un commit por tarea"
  - "Los criterios de aceptacion prohiben las cadenas .reduce(/.sort(/.filter(/Math.max(/Math.min( de forma literal, sin excepcion para comentarios: los tres comentarios que citaban 'Math.max()' o 'borderDash [4,4]' en prosa se reformularon sin esas cadenas exactas (mismo tipo de ajuste que 31-03 hizo con 'location.hash =' y 31-05 con 'datetime.now()')"
  - "titleFont/bodyFont del tooltip usan el literal `size: 12` en vez de la constante TICK_SIZE, para que el criterio de aceptacion 'grep -oE size: ?[0-9]+ solo contiene size: 12' tenga al menos una coincidencia real que verificar; los ticks de los ejes si usan TICK_SIZE (una referencia a la constante, no un literal, por eso no aparece en ese grep)"

requirements-completed: []  # OPS-12/OPS-14 se cierran formalmente en 31-11 (puerta de fase), como en 31-03/31-04/31-05

# Metrics
duration: ~35min
completed: 2026-08-23
---

# Phase 31 Plan 07: Graficas de analitica — analytics-charts.js Summary

**`frontend/js/views/analytics-charts.js` (168 lineas): las dos instancias de Chart.js de la vista de analitica creadas bajo demanda, con el tipo de grafica, el pico y la disponibilidad de comparacion resueltos enteramente por el servidor — cero `.reduce()`, `.sort()`, `.filter()`, `Math.max()` o `Math.min()` sobre datos del servidor, verificado por lectura literal del fichero incluidos los comentarios**

## Performance

- **Tasks:** 2 de 2 completadas
- **Files modified:** 1 (`frontend/js/views/analytics-charts.js`, nuevo)

## Accomplishments

- `createCharts()` idempotente: instancia `hourlyChart` (barras/linea, dos datasets desde el inicio) y `occupancyChart` (barras horizontales) sobre `#an-chart-hourly`/`#an-chart-occupancy`; no se anade `<script>` nuevo, Chart.js sigue siendo el global cargado por CDN en `index.html`
- `renderHourly(data)`: `hourlyChart.config.type = data.chart` — el servidor decide barras (`<=48` cubos) o linea (`>48`); realce del pico por comparacion de indice contra `data.peak_index` (sin `Math.max`); resumen accesible regenerado en cada carga sobre `aria-label`, construido solo con `data.total`, `peak_index`, `min_index`, `labels` y `values` ya resueltos
- `renderOccupancy(data)`: barras horizontales (`indexAxis: 'y'`) con opacidad decreciente por posicion (`paso = n > 1 ? i/(n-1) : 0`, sin `Math.max(1, n-1)` para cumplir el criterio de aceptacion por lectura literal); valor de cada zona pegado al final de la etiqueta de categoria (`"{zona} — {valor}"`, texto de dato via Chart.js, nunca `innerHTML`) para que sea visible sin raton
- `setCompare(enabled)`: alterna el dataset 1 (`_lastPrevious` guardado en el ultimo `renderHourly`) sin volver a pedir datos
- `resizeCharts()`: `chart.resize()` de las dos instancias para la trampa del contenedor `hidden` (D-03), lista para que 31-10 la llame al reactivar la pestana
- Paleta y tipografia del UI-SPEC respetadas letra a letra: `SERIE_ACTUAL`/`SERIE_RELLENO`/`SERIE_ANTERIOR` (discontinua `[4,4]`, sin relleno), `TICK_SIZE = 12` en todos los ejes, `y.min: 0` en las dos graficas (Pitfall 9), tooltip con `mode: 'index'`/`intersect: false` y los dos callbacks de etiqueta exactos

## Task Commits

1. **Task 1: createCharts() y renderHourly() con las dos series y el realce del pico** - `3ccd7e6` (feat)
2. **Task 2: renderOccupancy() y resizeCharts()** - `ecfb721` (feat)

## Files Created/Modified

- `frontend/js/views/analytics-charts.js` (nuevo, 168 lineas) — modulo completo con las cinco funciones del contrato de `<interfaces>`

## Decisions Made

Ver `key-decisions` en el frontmatter: division manual del fichero en dos commits (mismo patron que 31-05), reformulacion de comentarios que citaban literalmente las cadenas prohibidas por los criterios de aceptacion, y uso deliberado del literal `12` en el tooltip para que el criterio de tipografia tenga una coincidencia real que verificar.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Tres comentarios citaban literalmente `Math.max(`/`borderDash [4,4]`, disparando los criterios de aceptacion que exigen 0 coincidencias**
- **Found during:** Verificacion de criterios de aceptacion de la Task 1 (primera pasada)
- **Issue:** El comentario de cabecera, el comentario de `renderHourly` y el de `renderOccupancy` explicaban en prosa por que no se usa `Math.max()`, citando la llamada literal; y el comentario de la constante `SERIE_ANTERIOR` citaba `borderDash [4,4]` ademas del uso real en codigo, duplicando la coincidencia y rompiendo el criterio `grep -c "borderDash" == 1`. El plan es explicito en que estos criterios se leen literalmente, sin excepcion para comentarios ("la regla se cumple por lectura literal, sin excepciones argumentadas").
- **Fix:** Reformulados los cuatro comentarios sin citar las cadenas exactas prohibidas por los criterios (p. ej. "funcion de maximo" en vez de "Math.max()", "trazo discontinuo 4x4" en vez de "borderDash [4,4]"), sin cambiar ningun comportamiento de codigo.
- **Files modified:** `frontend/js/views/analytics-charts.js`
- **Commit:** `3ccd7e6` (parte del commit de Task 1, corregido antes de comitir)

**2. [Rule 1 - Bug] `titleFont`/`bodyFont` del tooltip con `TICK_SIZE` (variable) no dejaban ninguna coincidencia literal para el criterio de tipografia**
- **Found during:** Verificacion de criterios de aceptacion de la Task 1
- **Issue:** El criterio `grep -oE "size: ?[0-9]+" ... solo contiene "size: 12"` se cumplia vacuamente (sin ninguna coincidencia) si todos los tamanos de fuente se referenciaban via la constante `TICK_SIZE`, lo cual no demuestra que el fichero use realmente 12px. El propio texto de la Task 1 especificaba `titleFont:{size:12}` en literal para el tooltip.
- **Fix:** `titleFont`/`bodyFont` del tooltip pasan a usar el literal `12` directamente; los ticks de los ejes siguen usando `TICK_SIZE` (unica fuente de verdad para esos seis usos).
- **Files modified:** `frontend/js/views/analytics-charts.js`
- **Commit:** `3ccd7e6`

---

**Total deviations:** 2 auto-fixed (Rule 1, ambas cosmeticas — ajustes de comentarios/literal para cumplir los criterios de aceptacion tal como estan escritos, sin impacto en el comportamiento de las graficas).

## Issues Encountered

Ninguno mas alla de las dos desviaciones documentadas arriba, encontradas y corregidas antes de cada commit (no llegaron a comitirse en estado roto).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Las cinco funciones del contrato (`createCharts`, `renderHourly`, `renderOccupancy`, `setCompare`, `resizeCharts`) existen y estan verificadas contra los payloads reales de `/api/v2/analytics/hourly` y `/api/v2/analytics/occupancy` (31-05).
- El modulo **no** llama a `fetch()` ni escribe `innerHTML`: solo pinta lo que 31-10 le pase.
- `analytics-charts.js` **todavia no** entra en `LOCKED_JS`: los seis modulos de la fase entran juntos en 31-11, tal como especifica el plan.
- 31-10 puede registrar `createCharts`/`resizeCharts` en `registerAnalyticsBoot()` (31-03) y llamar a `renderHourly`/`renderOccupancy`/`setCompare` con las respuestas de 31-05 sin explorar este fichero.
- Suite de frontend dirigida verde: `tests/test_frontend_modules.py` 8 passed. No se toco pipeline, API ni configuracion, asi que no se relanzo la suite completa (criterio del CLAUDE.md del proyecto).

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
