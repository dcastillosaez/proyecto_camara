---
phase: 30-event-timeline-y-centro-de-alertas
plan: 07
subsystem: frontend
tags: [html, css, tailwind, markup, a11y, dom-contract, cleanup]

# Dependency graph
requires:
  - phase: 30-05
    provides: GET /api/v2/events con cursor, filtros y miniaturas — la API que consumirá timeline.js
  - phase: 30-06
    provides: GET /api/v2/alerts y mute/unmute — la API que consumirá alertCenter.js
provides:
  - "Contrato de ids del DOM de la línea temporal (#timeline-*, #tl-filter-*, #btn-tl-*)"
  - "Contrato de ids del centro de alertas (#btn-alert-center, #alert-badge, #alert-drawer y su popover de silenciado)"
  - "Contrato de ids del modal de marcar como persona (#mark-person-*)"
  - "Clases visuales de la Fase 30 en components.css: .timeline-row, .sev-bar, .sev-dot, .chip, .rule-chip, .row-action, .timeline-sep, .tl-skeleton, .tl-thumb, .filter-chip, .new-pill, .alert-group, #alert-drawer, #alert-badge, #alert-mute-popover"
  - "bindEventExport() en dashboard-events.js"
affects: [30-08 timeline.js, 30-09 alertCenter.js, 30-11 markPerson.js]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Contenedores de datos creados vacíos en el HTML: la estructura la pone el marcado estático y el contenido lo pondrá textContent desde JS (CodeQL js/xss)"
    - "El cajón lateral reutiliza el mecanismo display:none → .open de #clip-modal, sin librería de modales"
    - "Altura de fila fija (52px) declarada en CSS para que la virtualización de 30-08 pueda compensar scrollTop con aritmética, sin medir en JS"
    - "Borrado de marcado y de sus bindings en el mismo plan, para que no exista ningún commit intermedio con el arranque roto"

key-files:
  created: []
  modified:
    - frontend/css/components.css
    - frontend/index.html
    - frontend/js/views/dashboard-events.js
    - frontend/js/views/dashboard.js
    - frontend/js/websocket.js
    - frontend/js/app.js

key-decisions:
  - "Modal propio #mark-person-modal en vez de reutilizar #enroll-modal: el submit de enroll ya está enlazado por personGallery.js con otra semántica (fichero o frame actual) y reutilizarlo obligaría a meterle un modo condicional al handler"
  - ".rule-chip lleva solo gap:4px y se aplica junto a .chip: no se duplica la caja de 20px, se separa el prefijo ⚡ del nombre de la regla con el token xs"
  - "El export CSV se queda apuntando a /api/events/export sin parámetros: la barra de filtros v1 que los construía ha desaparecido y el endpoint v1 no forma parte de OPS-07..11"
  - "loadInitialData() deja de ser un Promise.all: al caer la carga de /api/events?limit=50 solo queda /api/stats, así que la espera paralela sobraba"

# Metrics
duration: 12min
completed: 2026-08-21
---

# Phase 30 Plan 07: Andamiaje de la línea temporal y el centro de alertas Summary

**El card "Eventos recientes" pasa a ser "Línea temporal" con los 35 ids que 30-08, 30-09 y 30-11 consumen como contrato, más la campana con badge, el cajón lateral de alertas y el modal de marcar como persona; y en el mismo movimiento desaparecen `addEvent`, `applyFilters` y `bindEventFilters`, que eran justo lo que habría reventado el arranque de `app.js` al borrar el marcado viejo.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files modified:** 6
- **Commits:** 3

## Accomplishments

### Task 1 — Estilos (`components.css`, 81 → 158 líneas)

Los 13 bloques del contrato visual con las medidas exactas del UI-SPEC: fila de 52px
fijos, barra de severidad de 3px y punto de 6px alimentados por la variable `--sev`,
miniatura de 64×36, chips de 20px con `line-height: 1`, acciones de fila de 32×32
(mínimo WCAG 2.2 AA 2.5.8 con holgura), separador sticky de 24px, esqueletos con
pulso de opacidad, chips de filtro, pill de eventos nuevos, cajón de 380px con
backdrop y badge circular de 20px. Ningún tamaño de fuente nuevo fuera de los 12px
de la escala; el 9px de `.intrusion-badge` sigue siendo legado y no se ha tocado.

### Task 2 — Marcado (`index.html`, +102 −31)

- Campana de 44×44 (`.ptz-btn`) a la izquierda del reloj, dentro de un contenedor
  `relative` para anclar `#alert-badge`, con `aria-label="Centro de alertas, 0 activas"`.
- "Ver todas" en la cabecera del panel "Alertas activas" de la Fase 29; el resto del
  panel intacto.
- Card de la línea temporal: título nuevo, `#timeline-count`, barra de filtros
  `tl-*` (chips de tipo vacíos, tres chips de severidad excluyentes, select de zona,
  persona con `datalist`, dos fechas, "Filtrar" y "Limpiar filtros"), fila de chips
  activos, y el contenedor con scroll con sus cuatro estados (vacío, vacío por
  filtros, error, cargando), el fin de lista, el centinela de 1px, la pill flotante
  y la barra ámbar de "sin tiempo real".
- Cajón `#alert-drawer` con contador héroe de 30px, lista de grupos, estado vacío,
  pie y popover de silenciado con las tres duraciones (`data-duration`).
- Modal `#mark-person-modal` con recorte a 96×96, autocompletado y hueco para el
  aviso de alcance retroactivo.
- Fuera `#events-list`, `#events-empty`, `#events-badge` y los siete controles de la
  barra de filtros v1. `#btn-export-csv`, `#btn-delete-events` y todo
  `#delete-events-panel` siguen donde estaban.

Los 21 literales del Copywriting Contract se han copiado tal cual, sin parafrasear.

### Task 3 — Limpieza del JS (−123 líneas)

`dashboard-events.js` baja de 204 a 116 líneas: se van `addEvent`,
`_eventsFilterParams`, `applyFilters` y `bindEventFilters`, y entra
`bindEventExport()`, que enlaza el CSV comprobando `null` antes de nada.
`dashboard.js` deja de escribir en `#events-badge` y `loadInitialData()` se queda
solo con `/api/stats`. En `websocket.js`, el caso `detection` conserva `updateStat`,
`bumpHourBar` y `showToast` — la gráfica horaria y el contador de la Fase 5 siguen
alimentándose de ahí — y pierde únicamente la inserción de fila. `app.js` llama a
`bindEventExport()`.

## Verification

- `tests/test_frontend_modules.py` → 8/8 en verde (módulos locked presentes, tope de
  300 líneas, sin `<script>` inline ni `<style>`).
- `tests/test_security_regression.py` → 21/21 en verde (es el otro fichero que mira
  el marcado).
- Barrido estático propio: ningún `document.getElementById('x').` de `frontend/js/`
  apunta ya a un id ausente de `index.html`. Cubre la clase de fallo
  `TypeError: Cannot read properties of null` para los accesos directos, que era el
  riesgo real de este plan.
- Todos los criterios de aceptación con `grep` del plan cuadran exactamente:
  10 ids de timeline, 9 de filtros, 10 de alertas, 6 del modal, 0 del card viejo,
  6 de export/borrado conservados, 3 `data-duration`.

**Pendiente de comprobación manual** (no automatizable sin navegador, anotado aquí
como pide el plan): arrancar el servidor y abrir `/` para confirmar que la consola
sale limpia. El card de la línea temporal aparecerá vacío hasta 30-08 — es el estado
esperado.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Accesibilidad] `role="dialog"` en `#mark-person-modal`**
- **Found during:** Task 2
- **Issue:** el bloque del plan para el modal no llevaba atributos ARIA, mientras que
  todos los demás modales de `index.html` (`#enroll-modal`, `#gallery-modal`,
  `#clip-modal`) sí, y la sección de accesibilidad del UI-SPEC los exige para el cajón.
- **Fix:** añadidos `role="dialog"`, `aria-modal="true"` y `aria-label="Marcar como persona"`.
- **Commit:** e9ef6d9

**2. [Rule 1 — CSS muerto] `.rule-chip` vacío**
- **Found during:** Task 1
- **Issue:** el plan proponía `.rule-chip { }` con solo un comentario dentro, es decir
  una regla sin efecto.
- **Fix:** `.rule-chip { gap: 4px; }` — separa el prefijo `⚡` del nombre de la regla
  con el token xs del UI-SPEC, sin duplicar la caja que ya aporta `.chip`.
- **Commit:** 6e631da

**3. [Rule 1 — Simplificación derivada] `Promise.all` de un solo elemento**
- **Found during:** Task 3
- **Issue:** al borrar la petición de `/api/events?limit=50`, el `Promise.all` de
  `loadInitialData()` se quedaba con una única promesa.
- **Fix:** sustituido por un `await fetch('/api/stats')` directo, con un comentario que
  dice dónde vive ahora la carga de eventos.
- **Commit:** 5131c54

### Desviación consciente respecto al UI-SPEC

El UI-SPEC dice que "Marcar como persona" reutiliza `#enroll-modal`. Se ha creado
`#mark-person-modal` aparte, con el mismo patrón visual y las tres diferencias que el
contrato exige (recorte precargado a 96×96, autocompletado de personas conocidas,
aviso de alcance retroactivo). Motivo: el `submit` de `#enroll-modal` ya está enlazado
por `personGallery.js` con otra semántica —subir fichero o usar el frame actual— y
reutilizar el mismo nodo obligaría a meterle un modo condicional a ese handler. Cero
pérdida de funcionalidad respecto al contrato; el coste es un bloque de marcado más.

## Known Stubs

| Stub | Fichero | Motivo |
|------|---------|--------|
| `#tl-filter-types` vacío | `frontend/index.html` | Los chips de tipo los puebla `timeline.js` desde el catálogo de eventos (30-08) |
| `#tl-filter-zone` con una sola opción | `frontend/index.html` | Las zonas se cargan de `/api/v2/zones` en 30-08 |
| `#tl-person-options` / `#mark-person-options` vacíos | `frontend/index.html` | Los rellena `/persons` en 30-08 y 30-11 |
| `#alert-groups` vacío | `frontend/index.html` | Lo puebla `alertCenter.js` (30-09) contra `/api/v2/alerts` |
| Sin listeners en campana, cajón, filtros ni modal | — | Es el andamiaje: el comportamiento llega en 30-08, 30-09 y 30-11 |

Son stubs intencionados y previstos por el plan: este plan entrega estructura y
estilos, no comportamiento. Ninguno impide alcanzar el objetivo declarado.

## Self-Check: PASSED

- `frontend/css/components.css` — FOUND (158 líneas)
- `frontend/index.html` — FOUND
- `frontend/js/views/dashboard-events.js` — FOUND (116 líneas)
- `frontend/js/views/dashboard.js` — FOUND
- `frontend/js/websocket.js` — FOUND
- `frontend/js/app.js` — FOUND
- Commit 6e631da — FOUND
- Commit e9ef6d9 — FOUND
- Commit 5131c54 — FOUND
