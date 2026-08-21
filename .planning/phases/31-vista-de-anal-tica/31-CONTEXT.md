# Phase 31: Vista de analítica - Context

**Gathered:** 2026-08-22
**Status:** Ready for planning
**Source:** Generado directamente por el orquestador a partir de ROADMAP.md, REQUIREMENTS.md, 31-UI-SPEC.md (ya aprobado 6/6) y del estado real del código tras cerrar la Fase 30 — sin sesión interactiva de `/gsd:discuss-phase` (mismo criterio que las Fases 29 y 30, contexto ya suficiente).

<domain>
## Phase Boundary

Convertir el histórico acumulado en información operativa: una segunda vista, conmutada por pestañas desde la misma página, con personas por hora, ocupación por zona, mapa de calor, ranking de personas más vistas y tarjetas de tendencia con porcentaje de variación frente al periodo anterior; un selector de rango (hoy / 7 días / 30 días / personalizado); y exportación CSV/JSON del rango visible. Todas las agregaciones se resuelven en SQL, nunca en el navegador.

**Fuera de alcance:** la vista de cámara y el árbol de configuración visual (Fase 32), los editores visuales de zonas/líneas/reglas (Fase 33), los tests E2E (Fase 34) y cualquier infraestructura multi-cámara (bloque D). Tampoco entra `js/store.js` ni un router declarativo: la conmutación de pestañas es el mecanismo mínimo que exige tener una segunda vista, y así queda fijado en el UI-SPEC.

</domain>

<decisions>
## Implementation Decisions

### Diseño visual e interacción (ya fijado por 31-UI-SPEC.md — aprobado 6/6, no volver a preguntar)
- **D-01:** Sin dependencias nuevas de ningún tipo. Se reutilizan Tailwind CDN, `components.css` y Chart.js 4.5.1 (ya cargado con SRI en `frontend/index.html`). El sistema de diseño se hereda literalmente de `29-UI-SPEC.md`/`30-UI-SPEC.md`: spacing 4/8/16/24/32/48/64, exactamente 4 tamaños tipográficos (12/16/14/30px) y 2 pesos (600/700), superficies slate-950/900 y un único acento azul con lista cerrada de usos.
- **D-02 (decisión estructural de la fase):** La analítica vive en una **segunda vista conmutada por pestañas**, no en un router ni como sección apilada de la página actual. Mecanismo mínimo y explícito: `<nav role="tablist">` con dos botones, `hidden` para conmutar, hash sincronizado con `history.replaceState` (nunca asignando `location.hash`), cabecera común siempre visible. **El MJPEG y el WebSocket nunca se desmontan al cambiar de pestaña.**
- **D-03:** Las instancias de Chart.js se crean **en la primera activación de la pestaña**, no al cargar la página: un `<canvas>` dentro de un contenedor `display:none` mide 0×0 y Chart.js calcularía mal el tamaño. Es la trampa concreta que documenta el UI-SPEC.
- **D-04:** El texto que Chart.js dibuja dentro del lienzo **también cumple el contrato tipográfico** (12px). La densidad se resuelve con `maxTicksLimit`, jamás bajando el tamaño de letra. Los 9-11px del histograma heredado de la Fase 5 son legado no replicable.
- **D-05:** Dos subsistemas de color nuevos que el sistema heredado no tenía, ambos acotados: **paleta de series** (azul sólido vs. slate discontinuo, máximo 4 series, legítima porque dentro de un `<canvas>` no hay afordancias que confundir con el acento) y **rampa secuencial del heatmap** (JET → INFERNO). Las tendencias van **deliberadamente sin verde/rojo**: más gente no es "bueno" ni "malo", depende del negocio.
- **D-06:** Ancla visual de la vista = panel "Personas por hora" (8 de 12 columnas, único con área rellena). Los demás paneles son lectura secundaria.

### Agregación en servidor (OPS-14 — el requisito con más filo de la fase)
- **D-07:** **Prohibición explícita y auditable:** en los módulos de analítica del navegador no puede aparecer ni un `.reduce()`, ni un `.sort()`, ni un `.filter()`, ni un `Math.max()` sobre datos del servidor. La única aritmética permitida en cliente es de **formato** (separador de millares, símbolo de porcentaje, `padStart` de horas). El porcentaje de variación, la hora pico, el orden del ranking y el orden de las zonas llegan ya resueltos desde SQL. Es el mismo criterio que se aplicó a `alertCenter.js` en la Fase 30 y es verificable con `grep`.
- **D-08:** Un cambio de rango dispara las cuatro peticiones **en paralelo** (`summary`, `hourly`, `occupancy`, `persons`) más la recarga del `<img>` del heatmap, y **cada panel resuelve su estado por separado**: un endpoint que falle pinta su error dentro de su panel sin dejar la vista en blanco. Nada de `Promise.all` que aborte todo al primer rechazo.
- **D-09:** Cada tanda de peticiones usa un `AbortController`; al cambiar de rango con peticiones en vuelo se abortan y se ignoran las respuestas rezagadas. Los `input[type=date]` no disparan nada al teclear: solo el botón "Aplicar rango".
- **D-10:** El CSV/JSON los genera el **servidor**, siguiendo el patrón ya existente de `bindEventExport()` en `dashboard-events.js` — el navegador no serializa un dataset que ya tiene el backend.

### Alcance honesto del mapa de calor
- **D-11:** El heatmap es un **`<img>` contra `/api/v2/analytics/heatmap`**, no un lienzo de Chart.js: lo compone OpenCV en servidor sobre el último frame (`compose_heatmap`, ya existente en `backend/pipeline/detection.py`) y se versiona tal cual, como fija `SPEC_v2.md` §8.1.
- **D-12:** El heatmap **acumula desde el arranque de la cámara y no sigue el rango seleccionado**, y el panel lo dice con un chip visible ("acumulado desde el arranque") en lugar de fingir que responde al selector. Esto es deliberado: reconstruirlo en SQL desde `events.bbox` produciría un mapa de la línea de conteo (los eventos se disparan en cruces y transiciones de zona, no de forma continua), es decir, un heatmap sesgado con apariencia de autoridad. Un dato honesto con su alcance escrito al lado es mejor que uno falsamente preciso.
- **D-13:** Al versionar el heatmap a v2, cambiar `cv2.COLORMAP_JET` por `cv2.COLORMAP_INFERNO` en `compose_heatmap` (cambio de una línea) por la razón perceptual documentada en el UI-SPEC. El heatmap no lleva botón de exportar: es una imagen, no una tabla.

### Reparto en módulos
- **D-14:** Seis módulos nuevos bajo `frontend/js/`, todos por debajo del tope duro de 300 líneas que impone `tests/test_frontend_modules.py::TEST_line_limit` (la Fase 30 ya tuvo que partir la línea temporal en cuatro por esto): `nav.js` (~70), `views/analytics.js` (~220), `views/analytics-charts.js` (~200), `views/analytics-range.js` (~130), `views/analytics-ranking.js` (~150), `views/analytics-export.js` (~90). Los seis se añaden a `LOCKED_JS`.
- **D-15:** Convención anti-XSS heredada e innegociable: las plantillas `innerHTML` llevan solo nodos vacíos y constantes del módulo; todo dato del backend entra por `textContent`/`dataset`/propiedades del DOM. Aplica en particular a los **nombres de persona** del ranking y a los **nombres de zona**.

### Claude's Discretion
- Forma exacta de la respuesta de cada endpoint de analítica (nombres de campo, envelope) — debe ser coherente con las convenciones que ya fijaron `backend/api/v2/events.py` y `alerts.py` en la Fase 30 (router con `configure()`, rate limit desde `deps.py`).
- Estrategia SQL concreta de cada agregación y qué índices hacen falta para cumplir el criterio 4 (<500 ms sobre 100.000 eventos). `DetectionStatRepo` ya agrega por minuto y tiene `hourly_baseline()` de la Fase 27 — decidir en RESEARCH si las agregaciones se apoyan en `detection_stats` (barato, ya agregado) o en `events` (más preciso, más caro), o en una combinación por panel.
- Si el criterio 3 (payload de 30 días < 100 KB) obliga a agrupar por día en vez de por hora cuando el rango supera cierto umbral, y dónde está ese umbral.
- Formato exacto del cursor/parámetros de rango (`from`/`to` ISO vs. presets nombrados) y cómo se validan los rangos inválidos o excesivos.
- Mecanismo concreto de la descarga CSV/JSON (`Content-Disposition` + enlace directo vs. `blob`), respetando D-10.

</decisions>

<specifics>
## Specific Ideas

- Los criterios 3 (<100 KB) y 4 (<500 ms sobre 100.000 eventos) son los más exigentes de la fase y deben medirse con datos reales sembrados, igual que hizo `30-12` con `scripts/seed_events.py` para los 10.000 eventos de la línea temporal. No basta con estimarlos.
- La Fase 30 dejó un precedente directo de paginación por cursor e índices medidos con `EXPLAIN QUERY PLAN`; el research de esta fase debería reutilizar esa metodología en vez de improvisar.
- `GET /api/v2/analytics/context` (Fase 27) ya devuelve nivel de actividad contra la media móvil de 7 días: revisar si la tendencia de esta fase puede reutilizar esa lógica en vez de duplicarla.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato visual (fuente de verdad para UI)
- `.planning/phases/31-vista-de-anal-tica/31-UI-SPEC.md` — contrato de diseño completo, aprobado 6/6, sustituye cualquier decisión visual no explícita en este CONTEXT.md

### Alcance funcional y criterios de éxito
- `.planning/ROADMAP.md` § Phase 31 — goal, dependencias (Fase 30), requisitos OPS-12..OPS-15, 5 criterios de éxito
- `.planning/REQUIREMENTS.md` líneas 254-257 — descripción completa de OPS-12..OPS-15

### Especificación técnica
- `propuesta_mejora/SPEC_v2.md` §8.1 — contrato de los endpoints `/api/v2/analytics/{summary,hourly,occupancy,persons,heatmap}`
- `propuesta_mejora/SPEC_v2.md` §8.2 — estructura de frontend objetivo (`js/views/analytics.js`)

### Precedentes de código de la fase anterior
- `backend/api/v2/events.py` y `backend/api/v2/alerts.py` — convenciones reales de router v2 (Fase 30)
- `frontend/js/views/timeline.js`, `timeline-row.js` — convención anti-XSS y reparto en módulos bajo el tope de 300 líneas
- `backend/pipeline/detection.py::compose_heatmap` — el heatmap existente que se versiona

### Convenciones del proyecto
- `CLAUDE.md` — stack cerrado, invariantes, Regla final ("cambio mínimo")

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Chart.js ya cargado** con SRI en `frontend/index.html` y ya instanciado por el dashboard para el histograma de actividad por hora — reutilizar ese molde de instanciación, no inventar otro.
- `bindEventExport()` en `frontend/js/views/dashboard-events.js` — patrón de exportación ya resuelto (el servidor genera el fichero), directamente aplicable a D-10.
- `backend/api/v2/context.py` (Fase 27) — `GET /api/v2/analytics/context` ya vive bajo el prefijo de analítica y es el molde más cercano para los routers nuevos.
- `DetectionStatRepo` (`backend/storage/repositories.py`) — agregación por minuto ya existente, más `hourly_baseline()` (media móvil por franja horaria, Fase 27).
- `backend/pipeline/detection.py::compose_heatmap` — composición del heatmap sobre el último frame; el cambio a INFERNO es de una línea (D-13).
- `scripts/seed_events.py` — siembra determinista usada por `30-12` para medir el criterio de 10.000 eventos; reutilizable para los 100.000 de esta fase.

### Established Patterns
- Router v2: `APIRouter` + `configure()` inyectado desde el `lifespan`, rate limit desde `backend/api/v2/deps.py` (`V2_RATE_LIMIT`, `limiter`), nunca estado global oculto.
- Frontend: ES modules bajo `frontend/js/views/` y `components/`, tope de 300 líneas por módulo verificado por `tests/test_frontend_modules.py::TEST_line_limit` y lista `LOCKED_JS`, validación de sintaxis con `node --check`.
- Seguridad de URLs: `isSafeMediaUrl()` en `timeline-row.js` (añadido al cerrar la Fase 30 tras 3 alertas de CodeQL) — cualquier URL que llegue del backend y acabe en `img.src`/`window.open`/`fetch` debe validarse antes. **Aplica directamente al `<img>` del heatmap y a las URLs de descarga.**
- Medición de rendimiento: `EXPLAIN QUERY PLAN` + tiempos reales con datos sembrados, no estimaciones (precedente de `30-02` y `30-12`).

### Integration Points
- `frontend/index.html` — hoy es una sola página de ~804 líneas con once paneles apilados; esta fase le añade el `tablist` de la cabecera y el contenedor de la segunda vista.
- `frontend/js/app.js` — bootstrap donde se registran los arranques; la activación diferida de los gráficos (D-03) se engancha aquí.
- `backend/main.py` — `include_router` y `configure()` de los routers nuevos, junto al resto de la superficie v2.

</code_context>

<deferred>
## Deferred Ideas

- Vista de cámara y árbol de configuración visual — Fase 32.
- Editores visuales de zonas, líneas y reglas — Fase 33.
- Tests E2E — Fase 34.
- `js/store.js` y un router declarativo — siguen diferidos: la conmutación por pestañas de D-02 es el mecanismo mínimo suficiente y no justifica introducir una capa de estado global.
- Heatmap que respete el rango temporal seleccionado — requeriría una fuente de datos continua (muestreo periódico de posiciones), que no existe hoy; ver D-12 para por qué no se resuelve con `events.bbox`.

</deferred>

---

*Phase: 31-vista-de-anal-tica*
*Context gathered: 2026-08-22*
