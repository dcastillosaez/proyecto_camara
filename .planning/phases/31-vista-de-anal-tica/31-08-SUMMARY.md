---
phase: 31-vista-de-anal-tica
plan: 08
subsystem: ui
tags: [frontend, forms, xss-prevention, localStorage]

# Dependency graph
requires:
  - phase: 31-03
    provides: "Contrato de ids de #view-analitica (#an-range-*, #an-custom, #an-from/#an-to, #an-apply, #an-range-error, #an-subtitle, #an-cards, #an-*-value/support/range, #an-rank-list) y .rank-row/.chip de components.css"
  - phase: 31-05
    provides: "Contrato HTTP de GET /api/v2/analytics/summary y /persons, y las dos cadenas literales de error del 422 de _resolve_range()"
provides:
  - "analytics-range.js: initRange(onChange)/currentRange() — presets, validacion de cliente, persistencia en localStorage y subtitulo de fechas efectivas"
  - "analytics-ranking.js: renderCards(summary)/renderRanking(data) — cuatro tarjetas de tendencia y filas del ranking de personas, sin agregacion ni XSS"
affects: [31-10, 31-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fechas locales sin toISOString(): helper ymd()/daysAgo() propio para evitar el bug de zona horaria al este de Greenwich"
    - "Validacion de cliente como cortesia, nunca autoridad: mismas dos cadenas literales del 422 del servidor, solo se evalua al pulsar Aplicar rango"
    - "Plantilla innerHTML de nodos vacios + textContent (mismo patron que timeline-row.js) para el nombre de persona, importando isSafeMediaUrl en vez de reimplementarla"

key-files:
  created:
    - frontend/js/views/analytics-range.js
    - frontend/js/views/analytics-ranking.js
  modified: []

key-decisions:
  - "Toggle de #an-custom y #an-range-error via classList.add/remove/toggle('hidden'), no el atributo hidden: en el marcado de 31-03 ambos elementos llevan 'hidden' como clase Tailwind (class=\"hidden ...\"), no como atributo booleano — mismo patron que dashboard-events.js:9/15/19."
  - "Selectores de clase en vez de indices numericos en renderRanking: el .rank-initial anidado dentro de .rank-avatar desplaza el indice plano de querySelectorAll('span') respecto a lo que describia el plan; se usan selectores de clase unicos (.w-5, .truncate, .text-base, .text-slate-500, .text-slate-400) para evitar ese acoplamiento fragil."

requirements-completed: []  # OPS-14 ya cerrado por 31-04/31-05; OPS-13 avanza pero se cierra en la puerta de fase 31-11, cuando 31-10 cablee estos modulos al DOM

# Metrics
duration: ~35min
completed: 2026-08-23
---

# Phase 31 Plan 08: Selector de rango y ranking de personas Summary

**Dos modulos de presentacion pura — `analytics-range.js` emite un rango con fechas locales inclusivas y validacion de cortesia, `analytics-ranking.js` pinta las cuatro tarjetas de tendencia y el ranking de personas sin agregar nada ni permitir que un nombre inyecte marcado**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 de 2 completadas
- **Files modified:** 2 (ambos nuevos)

## Accomplishments

- `analytics-range.js` (139 lineas): `initRange(onChange)`/`currentRange()` resuelven los cuatro presets (`today`/`7d`/`30d`/`custom`) con fechas locales inclusivas (`ymd()`/`daysAgo()` propios, cero `toISOString()`), persisten en `localStorage` bajo lista blanca de presets conocidos y validan el rango personalizado **solo** al pulsar "Aplicar rango" con las dos cadenas de error literales del 422 de `_resolve_range()` (31-05). Los `input[type=date]` no llevan listener de `input`/`change`: nada se dispara al teclear.
- `analytics-ranking.js` (123 lineas): `renderCards(summary)` escribe las cuatro tarjetas de tendencia (total, delta frente al periodo anterior, hora punta, conocidas/desconocidas) siempre en `#94a3b8` — la direccion la da la flecha, nunca el color. `renderRanking(data)` repinta `#an-rank-list` con una plantilla constante de nodos vacios + `textContent`, importando `isSafeMediaUrl` de `timeline-row.js` para el avatar (nunca una imagen rota: cae a la inicial del nombre). Sin periodo anterior comparable, fila y tarjeta dicen "sin comparación" con el `title` exacto del UI-SPEC.
- Cero `.reduce()`/`.sort()`/`.filter()`/`Math.max()` en ambos ficheros, verificado por grep y por lectura literal (incluidos comentarios).

## Task Commits

1. **Task 1: analytics-range.js — presets, validacion, persistencia y subtitulo** - `e68afd9` (feat)
2. **Task 2: analytics-ranking.js — cuatro tarjetas de tendencia y filas del ranking** - `b903919` (feat)

## Files Created/Modified

- `frontend/js/views/analytics-range.js` (nuevo, 139 lineas) — `initRange`/`currentRange`
- `frontend/js/views/analytics-ranking.js` (nuevo, 123 lineas) — `renderCards`/`renderRanking`

## Decisions Made

Ver `key-decisions` en el frontmatter: toggle de `hidden` por clase (no por atributo) porque el marcado de 31-03 usa `class="hidden ..."` en `#an-custom` y `#an-range-error`; y selectores de clase en vez de indices numericos en `renderRanking` por el anidamiento real del `.rank-initial` dentro de `.rank-avatar`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Bug de indexado propio detectado antes de comitear: `.rank-initial` anidado desplaza `querySelectorAll('span')`**

- **Found during:** Task 2, primera escritura de `renderRanking` siguiendo literalmente los indices sugeridos por el plan (`querySelectorAll('span')[4]`/`[5]`)
- **Issue:** La plantilla `ROW_HTML` anida `<span class="rank-initial">` dentro de `<span class="rank-avatar">`. `querySelectorAll('span')` sobre la fila devuelve los spans en orden de documento (incluye el anidado), asi que los indices planos no correspondian a las columnas visuales previstas — se habria escrito la etiqueta "visitas" en la celda de visitas y la tendencia en la etiqueta.
- **Fix:** sustituidos todos los accesos por indice por selectores de clase unicos dentro de la fila (`.w-5`, `.truncate`, `.text-base`, `.text-slate-500`, `.text-slate-400`), que no dependen del orden de anidamiento.
- **Files modified:** `frontend/js/views/analytics-ranking.js` (nunca comiteado con el bug; se corrigio en la misma escritura antes del primer commit de la Task 2)
- **Commit:** `b903919`

**2. [Rule 1 - Bug] Comentario con la cadena literal `toISOString` disparaba el criterio de aceptacion de `analytics-range.js`**

- **Found during:** Task 1, verificacion de criterios de aceptacion
- **Issue:** El comentario explicativo citaba `new Date().toISOString()` literalmente, y el criterio exige `grep -c "toISOString"` = 0 (incluidos comentarios), mismo patron de hallazgo que 31-03 con `location.hash =`.
- **Fix:** reformulado el comentario sin citar el metodo literal, sin cambiar el codigo.
- **Files modified:** `frontend/js/views/analytics-range.js`
- **Commit:** `e68afd9`

---

**Total deviations:** 2 auto-fixed (Rule 1, ambas encontradas y corregidas antes del commit correspondiente — ningun commit quedo con el bug o el criterio incumplido).

## Issues Encountered

Ninguno mas alla de las dos correcciones documentadas arriba.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Los dos modulos exponen exactamente las firmas del contrato de `<interfaces>` (`initRange`/`currentRange`, `renderCards`/`renderRanking`) y estan listos para que 31-10 los cablee: el orquestador decide cuando llamar a `currentRange()` y cuando pedir `/summary` y `/persons`.
- `initRange()` no dispara ninguna carga al arrancar (solo restaura estado visual y subtitulo), asi que 31-10 sigue siendo el unico punto que decide la primera peticion — evita las "dos tandas de cuatro peticiones" que el plan advertia.
- OPS-14 ya estaba cerrado por 31-04/31-05. OPS-13 avanza pero no se cierra en este plan: los modulos existen y pasan sus criterios de aceptacion, pero nada los cablea al DOM todavia — se cierra en la puerta de fase 31-11, mismo patron ya usado en las Fases 27 y 30 (ver `31-04-SUMMARY.md`).
- Los dos ficheros entran en `LOCKED_JS` en 31-11, junto con los otros cuatro modulos de la fase.
- Suite dirigida verde (`tests/test_frontend_modules.py` 8 passed). Este plan no toca pipeline/API/config — no se relanzo la suite completa (`pytest tests/ -v`), consistente con el criterio del CLAUDE.md del proyecto.

---
*Phase: 31-vista-de-anal-tica*
*Completed: 2026-08-23*

## Self-Check: PASSED
