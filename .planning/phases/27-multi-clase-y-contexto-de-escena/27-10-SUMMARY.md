---
phase: 27-multi-clase-y-contexto-de-escena
plan: 10
subsystem: frontend
tags: [dashboard, index-html, detection-classes, vanilla-js]

# Dependency graph
requires:
  - phase: 27-07
    provides: "GET/PUT /api/v2/detection/classes — contrato LOCKED (active, available, locked)"
provides:
  - "Panel 'Clases detectadas' en frontend/index.html con checkboxes por clase"
  - "loadDetectionClasses/renderDetectionClasses/saveDetectionClasses inline en el <script> de index.html"
affects: ["27-11"]

tech-stack:
  added: []
  patterns:
    - "Molde literal del panel de zonas: fetch + Content-Type application/json, d.detail en el 400, recarga desde servidor tras fallo"
    - "Todo inline en index.html, sin modulos ES ni cambios en frontend/app.js (app.js sigue stub hasta Fase 28)"

key-files:
  created: []
  modified:
    - frontend/index.html

key-decisions:
  - "Sin formulario de alta como en zonas: las 6 clases son un catalogo fijo devuelto por GET, el guardado es inmediato al marcar/desmarcar (ajuste, no CRUD abierto)"
  - "El checkbox de persona sale disabled porque el servidor lo manda en 'locked', la UI nunca decide por su cuenta que clase bloquear (T-27-40 aceptado: el backend ya rechaza con 400 cualquier PUT sin la clase 0)"
  - "Tras un 400 o fallo de red se recarga desde el servidor (loadDetectionClasses) en vez de dejar el checkbox en el estado que el usuario marco (T-27-41 mitigado)"

requirements-completed: [BEH-06]

duration: ~15min
completed: 2026-08-17
---

# Phase 27 Plan 10: Panel de clases detectadas en el dashboard Summary

**Checkbox por clase del catalogo COCO (persona/bicicleta/coche/moto/mochila/maleta) en `frontend/index.html`, con "persona" siempre marcada y deshabilitada, consumiendo `GET`/`PUT /api/v2/detection/classes` de 27-07 sin tocar `frontend/app.js`.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-08-17
- **Tasks:** 2/2
- **Files modified:** 1

## Accomplishments
- Card "Clases detectadas" insertado en `index.html` justo despues del card de zonas, mismo molde visual (`detection-classes-list`, `detection-classes-msg`)
- `renderDetectionClasses`, `loadDetectionClasses` y `saveDetectionClasses` añadidas al `<script>` inline existente, junto a `loadZones()`
- Guardado inmediato al marcar/desmarcar un checkbox (evento `change`), sin boton de guardar separado
- 400 del backend muestra `d.detail` (mensaje en lenguaje llano de 27-07) y recarga el estado real del servidor; igual en fallo de red

## Task Commits

Each task was committed atomically:

1. **Task 1: Markup — panel "Clases detectadas"** - `0f608d1` (feat)
2. **Task 2: JS — cargar, pintar y guardar las clases activas** - `f235b22` (feat)

## Files Created/Modified
- `frontend/index.html` - card nuevo (17 líneas) tras el card de zonas; bloque JS nuevo (67 líneas) con `DETECTION_CLASS_LABELS`, `renderDetectionClasses`, `loadDetectionClasses`, `saveDetectionClasses` y la llamada inicial `loadDetectionClasses()`, insertado antes del bloque de Fase 15

## Decisions Made
Ver `key-decisions` en el frontmatter. Sin decisiones arquitectonicas nuevas: ambas ya cerradas por el usuario (persona indesactivable, backend fuente de verdad para `locked`).

## Deviations from Plan
None — plan ejecutado exactamente como estaba escrito. El markup y el JS coinciden con los snippets literales del plan; los `<read_first>` (card de zonas en `index.html:658-700`, bloque de guardado/carga de zonas en `1705-1789`) confirmaron el molde antes de insertar.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Verification
- `grep -n 'id="detection-classes-list"'` y `id="detection-classes-msg"'` aciertan (líneas 715-716)
- `grep -c "api/v2/detection/classes"` = 2 (GET y PUT)
- `d.detail` presente dentro de `saveDetectionClasses` (línea 1843)
- `grep -c "loadDetectionClasses()"` = 4 (definicion, llamada inicial, dos recargas en error)
- `git diff --stat frontend/app.js` vacio
- Sintaxis del bloque `<script>` inline validada con `node --check` sobre el rango extraido (787-2024) - OK
- Suite completa: **519/519 passed** (`pytest tests/`), incluye `tests/test_security_regression.py` (21/21, sin regresion en el chequeo de SRI del CDN de Chart.js que tambien lee `frontend/index.html`)

## Requirements traceability

`BEH-06` queda **contribuido** por este plan (mitad frontend del criterio 1 del ROADMAP). El cierre formal se marca en la puerta de fase `27-11`, siguiendo la misma convencion que `27-07-SUMMARY.md` y `27-06-SUMMARY.md`: el checkpoint manual de `27-11` (marcar una clase y verla reflejada en el overlay MJPEG cableado en `27-08`) es el que valida el criterio de punta a punta.

## Next Phase Readiness
- Panel funcional listo para el checkpoint manual de `27-11`: marcar/desmarcar clases desde el dashboard y verificar que el backend persiste y el overlay MJPEG (27-08) refleja el cambio
- No hay tests automatizados de frontend en el repo (sin framework JS, `27-RESEARCH.md § Environment Availability`) — la verificacion funcional completa queda para el checkpoint manual de `27-11`, como preveia el plan
- Sin bloqueos para continuar con `27-11`

---
*Phase: 27-multi-clase-y-contexto-de-escena*
*Completed: 2026-08-17*

## Self-Check: PASSED

- FOUND: frontend/index.html (detection-classes-list, detection-classes-msg presentes)
- FOUND: 0f608d1 (Task 1 commit)
- FOUND: f235b22 (Task 2 commit)
