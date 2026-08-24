---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 12
subsystem: ui
tags: [vanilla-js, forms, rules-engine, xss-safe]

# Dependency graph
requires:
  - phase: 32-ajustes
    provides: "settings-field.js/settings-save.js — patron de renderers por tipo de campo y mapeo de errores 422 a replicar (sin importar, contexto DOM distinto)"
provides:
  - "renderWhenFields/renderActionFields (frontend/js/views/rules-form.js) — un renderer de campo por atributo de When/Action, con data-when-field para mapeo de errores 422"
  - "initRulesEditor() (frontend/js/views/rules-editor.js) — lista de reglas, CRUD y Probar regla contra /api/v2/rules"
affects: ["33-13 (integracion: monta el panel #rules-panel/#rules-list/#rule-form/... en camera.js y llama initRulesEditor)", "33-06 (backend consumido por este frontend, se ejecuta en la Wave 2)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Renderer de campo por tipo (event/zone/camera/time_range/days/min_confidence/duration_gte/person), imitando settings-field.js sin importarlo — estado del formulario vive en el orquestador, no en el renderer"
    - "Mapeo de errores 422 por selector [data-when-field=\"<field>\"] tras despojar el prefijo 'when.' del path Pydantic anidado"
    - "Acciones como lista editable con campos condicionales por tipo (pre_secs/post_secs solo en record, template en notify/telegram, url_ref en webhook)"

key-files:
  created:
    - frontend/js/views/rules-form.js
    - frontend/js/views/rules-editor.js
  modified: []

key-decisions:
  - "Selector [data-when-field] se fija con setAttribute('data-when-field', ...) en vez de dataset.whenField, para que el marcado quede literal en el codigo fuente (verificable por grep, contrato de la Task 1)"
  - "POST /{id}/test solo opera sobre reglas ya persistidas (requiere id existente en BD) — el boton #rule-test-btn prueba la version guardada de la regla que esta abierta en el formulario, no el borrador sin guardar en memoria, porque el endpoint del Plan 33-06 busca la regla por id en RuleRepo"
  - "Boton 'Cancelar' anadido al formulario (no descrito literalmente en <behavior> pero necesario para cerrar sin guardar) — UX minima, sin coste de CSS nueva"

patterns-established: []

requirements-completed: [OPS-24, RULE-05]

# Metrics
duration: ~3min (segunda mitad tras corte de sesion por limite de API; Task 1 ya estaba escrita en disco sin commitear al reanudar)
completed: 2026-08-24
---

# Phase 33 Plan 12: Editor de reglas por formularios Summary

**Composición de reglas por formulario (When/Action) contra `/api/v2/rules`, con mapeo de errores 422 por campo y botón "Probar regla" que muestra `would_fire/total_checked` sin persistir nada.**

## Performance

- **Duration:** ~3 min (continuación tras corte de sesión; Task 1 ya estaba escrita en disco al reanudar, solo faltaba verificar/corregir y commitear)
- **Tasks:** 2/2 completadas
- **Files modified:** 2 (ambos nuevos)

## Accomplishments
- `rules-form.js`: `renderWhenFields`/`renderActionFields`, un control DOM por atributo de `When`/`Action`, con los 22 valores reales de `EventType` y los 8 de `Action.type` (Literal), sin adivinar ninguno.
- `rules-editor.js`: `initRulesEditor()` como punto de entrada único — lista de reglas, formulario inline, CRUD contra `/api/v2/rules`, y `testRule()` contra `POST /{id}/test`.
- Mapeo de errores 422 por campo: `err.field` (p.ej. `"when.time_range"`) se despoja de su prefijo `when.` y se localiza vía `[data-when-field="time_range"]`.
- Cache de zonas: `GET /api/v2/zones` se llama una sola vez (no en cada apertura de formulario) para poblar el `<select>` de zona.

## Task Commits

Each task was committed atomically:

1. **Task 1: rules-form.js — renderers de campo para When/Action** - `ef872ae` (feat)
2. **Task 2: rules-editor.js — CRUD + Probar regla contra /api/v2/rules** - `5bc59f2` (feat)

**Plan metadata:** (este commit, pendiente)

## Files Created/Modified
- `frontend/js/views/rules-form.js` (300 líneas) — renderers de campo `When`/`Action`, sin estado propio, `onChange(field, value)` reenviado al orquestador.
- `frontend/js/views/rules-editor.js` (258 líneas) — `loadRules`, `openRuleForm`, `saveRule`, `testRule`, `deleteRule`, `initRulesEditor`.

## Decisions Made
- El marcado `data-when-field` se escribe con `setAttribute` explícito (no `dataset.whenField`) para que el contrato quede como texto literal en el código fuente, verificable mecánicamente por grep (acceptance criteria de la Task 1).
- El botón "Probar regla" del formulario (`#rule-test-btn`) solo actúa si la regla abierta ya tiene `id` persistido — el endpoint `/rules/{id}/test` del Plan 33-06 busca la regla en `RuleRepo`, no acepta un borrador en memoria sin guardar. Las filas de la lista (`loadRules`) siempre tienen `id`, así que su botón "Probar" funciona sin restricción.
- Se añadió un botón "Cancelar" al formulario para cerrar sin guardar — no estaba en el `<behavior>` literal de la Task 2 pero es necesario para que el panel inline sea usable (Rule 2, funcionalidad mínima faltante).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comentario con la palabra "innerHTML" disparaba el propio check anti-XSS de `rules-form.js`**
- **Found during:** Task 1 (verificación de acceptance criteria)
- **Issue:** El comentario de cabecera citaba literalmente "nunca innerHTML interpolando..." como buena práctica documentada, pero el acceptance criteria `grep -n "innerHTML" frontend/js/views/rules-form.js` NO debe producir coincidencias — el check es un grep ciego sobre todo el fichero, sin distinguir comentario de código.
- **Fix:** Reescrito el comentario para decir "nunca HTML crudo interpolando..." sin usar el token literal `innerHTML`, preservando el mismo significado.
- **Files modified:** `frontend/js/views/rules-form.js`
- **Commit:** `ef872ae` (parte del commit de Task 1)

**2. [Rule 1 - Bug] `dataset.whenField` no deja el string `data-when-field` literal en el código fuente**
- **Found during:** Task 1 (verificación de acceptance criteria)
- **Issue:** `row.dataset.whenField = fieldName` sí produce el atributo `data-when-field` en el DOM en tiempo de ejecución, pero el acceptance criteria `grep -n "data-when-field" frontend/js/views/rules-form.js` busca el texto literal en el fichero fuente, que con la sintaxis `dataset.whenField` no aparece nunca.
- **Fix:** Cambiado a `row.setAttribute('data-when-field', fieldName)` — mismo resultado en el DOM, contrato verificable por grep.
- **Files modified:** `frontend/js/views/rules-form.js`
- **Commit:** `ef872ae` (parte del commit de Task 1)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 — ambos ajustes mecánicos para satisfacer los acceptance criteria del propio plan, sin cambio de comportamiento funcional)
**Impact on plan:** Ninguno sobre el alcance; ambos son correcciones de forma para que el contrato verificable por grep (Task 1) se cumpla literalmente. Sin scope creep.

## Issues Encountered
La sesión de ejecución se cortó por límite de la API justo tras escribir `rules-form.js` en disco (sin commitear). Al reanudar se verificó el fichero completo, se corrigieron los dos puntos anteriores, se commiteó la Task 1, y se completó la Task 2 sin más incidencias.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `rules-form.js`/`rules-editor.js` listos para que el Plan 33-13 monte el panel `#rules-panel` (con `#rules-list`, `#rule-new-btn`, `#rule-form`, `#rule-test-btn`, `#rule-test-result`) en `camera.js` y llame `initRulesEditor()`.
- Este módulo asume que `/api/v2/rules` (Plan 33-06, Wave 2) devuelve el shape `{"detail": {"errors": [{"field", "message"}]}}` en 422 — sin ese backend aún ejecutado, el comportamiento real de guardado/prueba solo se puede verificar end-to-end en el checkpoint manual del Plan 33-14.
- Sin bloqueos conocidos para 33-13.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/views/rules-form.js
- FOUND: frontend/js/views/rules-editor.js
- FOUND: ef872ae
- FOUND: 5bc59f2
