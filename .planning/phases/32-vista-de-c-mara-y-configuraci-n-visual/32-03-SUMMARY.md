---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 03
subsystem: ui
tags: [css, design-system, wcag, tailwind]

# Dependency graph
requires:
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 02
    provides: "GET/PUT/restore /api/v2/config: contrato JSON (origin/applies/secret) que 32-04/32-05 consumen; sin dependencia de CSS"
provides:
  - "frontend/css/components.css: 8 clases nuevas (.metric-tile, .rtsp-card, .cfg-tree, .cfg-node, .cfg-row, .cfg-badge/--runtime/--env/--default, .cfg-applies/--hot/--restart, .cfg-savebar) con las medidas exactas del UI-SPEC"
  - ".cam-toggle::before de 44x44 (WCAG 2.2 AA 2.5.8) sobre los 4 interruptores heredados de la Fase 11 y cualquier interruptor nuevo"
affects: [32-04, 32-05, 32-06, 32-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Extension in situ de components.css con medicion real de margen antes de escribir (32-RESEARCH.md Pitfall 6): 172 lineas medidas en el momento de ejecutar, no las 163 estimadas en la investigacion — la Fase 31 ya habia anadido su bloque .nav-tab/.analytics-panel/.range-seg/.rank-row/.chart-skeleton antes de que este plan se ejecutara"
    - "Area de pulsacion ampliada via pseudo-elemento ::before con inset asimetrico (vertical -12px, horizontal -2px) para llevar una caja visual de 40x20 a un objetivo real de 44x44 sin tocar el tamano ni la posicion visual del control"
    - "Modificador de fila 'dirty' con box-shadow inset en vez de border-left, para no desplazar 2px el contenido interno de .cfg-row (que ya usa gap:16px entre columnas)"

key-files:
  created: []
  modified:
    - frontend/css/components.css

key-decisions:
  - "Extender components.css en el mismo fichero (172 -> 231 lineas) en vez de crear frontend/css/config.css: el margen real medido al ejecutar (172 lineas, no las 163 de la investigacion) dejaba sitio de sobra para las ~59 lineas anadidas sin acercarse al tope de 300 de TEST_line_limit — no hizo falta tocar LOCKED_CSS en tests/test_frontend_modules.py ni index.html"
  - "El error de validacion de .cfg-row (borde #ef4444) se ata a selectores nativos `input`/`select` dentro de `.cfg-row.error`, no a una novena clase `.cfg-control` inventada: el UI-SPEC y la propia PLAN.md solo listan 8 clases como contrato, y los controles reales ya son `.filter-input`/`.filter-input.filter-select`/`input[type=time]`/`.cam-toggle`, todos elementos `input`/`select` nativos"
  - "El punto de 6px de 'cambios sin guardar' del arbol (`.cfg-node-dot`) y las etiquetas/valores internos de `.metric-tile`/`.rtsp-status-dot` son sub-clases descendientes, no las 8 del contrato: el must_haves del plan solo exige que las 8 clases de nivel superior existan con classList, y estas son detalle de implementacion natural dentro de cada contrato padre"

patterns-established:
  - "Semaforo RTSP reutilizado literalmente via variable CSS `--rtsp-color` con 3 clases modificadoras (.connected/.reconnecting/.offline) sobre los mismos 3 colores del semaforo de cabecera de la Fase 29 (#4ade80/#f59e0b/#ef4444), sin cuarto estado"

requirements-completed: []  # OPS-16/17/18 avanzan (la capa CSS ya soporta metricas/RTSP/arbol/filas de config) pero no se cierran: exigen interfaz visible funcionando, que llega con 32-04/32-05 y se marca en la puerta de fase 32-08 — mismo patron que SET-01..04 en 32-01/32-02

# Metrics
duration: ~20min
completed: 2026-08-23
---

# Phase 32 Plan 03: Contrato visual CSS de Cámara y Ajustes Summary

**`frontend/css/components.css` gana las 8 clases (.metric-tile, .rtsp-card, .cfg-tree, .cfg-node, .cfg-row, .cfg-badge, .cfg-applies, .cfg-savebar) que 32-04 y 32-05 importarán como dado, más el área de pulsación real de 44×44 en `.cam-toggle` para los 4 interruptores heredados desde la Fase 11 — 172 a 231 líneas, dentro del tope de 300.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- `.metric-tile` (padding 12px/`p-3`, fondo `#1e293b`, sin color por métrica) y `.rtsp-card`
  (fondo `#0f172a`, borde `#1e293b`, `.rtsp-status-dot` de 8px con los 3 colores exactos del
  semáforo heredado de la Fase 29) listas para la vista Cámara.
- `.cfg-tree` (`sticky; top:112px`, 200-260px), `.cfg-node` (32px, mismo molde que `.nav-tab`
  de la Fase 31, ya presente en el fichero), `.cfg-row` (altura mínima 56px, única fila de
  altura variable del proyecto), `.cfg-badge` (3 variantes de origen) y `.cfg-applies` (2
  variantes de aplicación) listas para la vista Ajustes.
- `.cfg-savebar` (56px, `sticky; bottom:0`, `backdrop-filter: blur(6px)` sobre
  `rgba(15,23,42,0.92)`).
- `.cam-toggle::before` da un área de pulsación real de 44×44 (WCAG 2.2 AA 2.5.8) sobre la
  pista de 40×20, sin cambiar su tamaño visual — corrige de una vez los 4 interruptores de
  "Ajustes de cámara" ya existentes desde la Fase 11 (`toggle-privacy`, `toggle-led`,
  `toggle-motion`, `toggle-autotrack`) y cualquier interruptor nuevo que reutilice la clase.
- `TEST_line_limit` en verde: `components.css` mide 231 líneas, 69 de margen restante bajo
  el tope de 300.

## Task Commits

1. **Task 1: Medir margen real y añadir las 8 clases nuevas** - `e010cd2` (feat)

**Plan metadata:** (este commit, `docs(32-03)`)

## Files Created/Modified
- `frontend/css/components.css` - +59 líneas: bloque "Fase 32: vista Camara" (`.metric-tile`,
  `.rtsp-card`, `.rtsp-status-dot` + 3 modificadores, `.cam-toggle::before`) y bloque "Fase 32:
  vista Ajustes" (`.cfg-tree`, `.cfg-node` + `.sub`/`[aria-current]`/`.cfg-node-dot`,
  `.cfg-row` + `.dirty`/`.error`, `.cfg-badge` + 3 modificadores, `.cfg-applies` + 2
  modificadores, `.cfg-savebar`). 172 → 231 líneas totales.

## Decisions Made
- **Extender in situ, no fichero nuevo**: medido al ejecutar (no asumido de la investigación),
  `components.css` estaba en 172 líneas — la Fase 31 ya había dejado su bloque (`.nav-tab`,
  `.analytics-panel`, `.range-seg`, `.rank-row`, `.chart-skeleton`) antes de que este plan
  corriera. 172 + 59 = 231, muy por debajo de 300: no hizo falta crear
  `frontend/css/config.css` ni tocar `LOCKED_CSS` en `tests/test_frontend_modules.py` ni
  `index.html`.
- **Sin novena clase `.cfg-control`**: el estado de error de `.cfg-row` engancha directamente
  a los elementos nativos `input`/`select` dentro de `.cfg-row.error`, respetando que el
  contrato de la PLAN.md y del UI-SPEC declara exactamente 8 clases — los controles reales
  (`.filter-input`, `input[type=time]`, `.cam-toggle`) ya son elementos nativos.
- **Barra de fila modificada con `box-shadow: inset` en vez de `border-left`**: evita que un
  borde de 2px desplace el contenido interno de `.cfg-row` (que usa `gap: 16px` entre columna
  de etiqueta y columna de control), mismo resultado visual sin alterar el ancho útil de la
  fila.

## Deviations from Plan

None de comportamiento — el `<action>` de la Task 1 se siguió literalmente: medición real
primero (`wc -l` dio 172, no los 163 de la investigación), extensión in situ por caber
dentro del margen, las 8 clases con las medidas exactas citadas en el plan, y el `::before`
de `.cam-toggle` con el mismo criterio de inset asimétrico que el propio plan sugería como
ejemplo (ajustado a la caja real de 40×20 que ya tiene el proyecto, sin necesitar recalcular
nada distinto).

## Issues Encountered

Ninguno.

## Next Phase Readiness

- Las 8 clases del contrato visual están listas para que `32-04` (vista Cámara) y `32-05`
  (vista Ajustes) las consuman por `classList` sin negociar medidas ni colores — el
  `key_links` del plan (`camera.js`/`settings-field.js` → `components.css`) queda satisfecho
  del lado del proveedor.
- `.cam-toggle::before` no requiere ningún cambio en `dashboard.js` ni en el marcado
  existente de `index.html`: la clase Tailwind `relative` que ya llevan los 4 interruptores
  provee el contexto de posicionamiento que el pseudo-elemento necesita.
- OPS-16/17/18 avanzan (capa CSS lista) pero no se cierran: exigen interfaz visible
  funcionando con datos reales, que llega con 32-04/32-05 y se marca en la puerta de fase
  32-08.
- Suite dirigida verde: `tests/test_frontend_modules.py` 9 passed. Plan solo de CSS, sin
  tocar pipeline/API/config — no se relanzó la suite completa (mismo criterio que 31-04,
  31-07, 31-08, 31-10).

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-23*

## Self-Check: PASSED

- FOUND: frontend/css/components.css
- FOUND commit: e010cd2
- FOUND: .planning/phases/32-vista-de-c-mara-y-configuraci-n-visual/32-03-SUMMARY.md
