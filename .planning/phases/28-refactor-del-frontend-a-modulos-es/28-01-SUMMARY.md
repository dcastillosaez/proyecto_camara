---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 01
subsystem: testing
tags: [pytest, css, static-files, frontend, contract-test]

# Dependency graph
requires:
  - phase: 21-observabilidad
    provides: "backend/main.py con /api/v2/metrics estable (dependencia declarada en ROADMAP para la Fase 28)"
provides:
  - "tests/test_frontend_modules.py: contrato pytest de 8 tests que verifica mecanicamente OPS-01/OPS-02/OPS-03 para toda la Fase 28"
  - "frontend/css/base.css, frontend/css/layout.css, frontend/css/components.css: los 3 CSS locked por ADR-08, extraidos 1:1 del <style> inline"
affects: [28-02, 28-03, 28-04, 28-05, 28-06, 28-07, 28-08, 28-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Contrato mecanico de fase escrito antes de que exista el codigo que verifica (Wave 0 Gap) — el resto de la fase corre `pytest tests/test_frontend_modules.py -k <patron>` para verificar su propio alcance sin tocar los tests de otros planes"
    - "CSS locked por ADR-08 extraido 1:1 sin reformatear selectores, con layout.css documentado como vacio a proposito en vez de omitido"

key-files:
  created:
    - tests/test_frontend_modules.py
    - frontend/css/base.css
    - frontend/css/layout.css
    - frontend/css/components.css
  modified: []

key-decisions:
  - "layout.css se crea vacio (solo comentario) porque no existe CSS de layout real hoy — el grid de columnas es una clase de utilidad Tailwind en el marcado, no una regla CSS propia (verificado: 0 coincidencias de media queries en el <style> original)"
  - "El comentario de layout.css evita el string literal '@media' para no romper el propio acceptance criteria del plan (grep -c '@media' == 0), usando 'media queries' en su lugar sin cambiar el significado"
  - "frontend/index.html no se toca en este plan — el <style> original sigue vivo hasta que 28-08 reescriba el shell completo, una vez existan todos los modulos JS"

requirements-completed: [OPS-01, OPS-02]

duration: ~10min
completed: 2026-08-18
---

# Phase 28 Plan 01: Contrato pytest y extracción de CSS locked Summary

**Contrato pytest de 8 tests (`tests/test_frontend_modules.py`) que fija mecánicamente OPS-01/OPS-02/OPS-03 para toda la Fase 28, más los 3 CSS locked por ADR-08 extraídos 1:1 del `<style>` inline de `index.html`.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 completadas
- **Files modified:** 4 (1 test file, 3 CSS)

## Accomplishments
- `tests/test_frontend_modules.py` existe, es recolectable por pytest (8 funciones `TEST_*`), y sirve de contrato `-k`-scoped para los planes 28-02..28-08.
- Los 3 CSS locked por ADR-08 (`base.css`, `layout.css`, `components.css`) existen con el contenido 1:1 del `<style>` actual, cada uno bajo 300 líneas.
- `frontend/index.html` queda sin ningún cambio (confirmado por `git diff --stat` vacío).

## Task Commits

1. **Task 1: Contrato pytest — tests/test_frontend_modules.py** - `a9c4303` (test)
2. **Task 2: Extracción 1:1 — frontend/css/{base,layout,components}.css** - `0b4826f` (feat)

_Nota: no se genera un commit de metadata separado en este entorno (STATE/ROADMAP/REQUIREMENTS los actualiza el orquestador centralmente); el commit final de este plan es únicamente este SUMMARY.md._

## Files Created/Modified
- `tests/test_frontend_modules.py` - 8 funciones `TEST_*`: existencia de CSS/JS locked, límite de 300 líneas, ausencia de lógica inline en `index.html`, entry point real de `app.js`, MIME type real de `/static/js/*.js` y `/static/css/*.css`, servido de `/`.
- `frontend/css/base.css` - reset, tipografía, scrollbar, animación `pulse-ring` (de `index.html:12-34`).
- `frontend/css/components.css` - `.ptz-btn`, `.preset-btn`, `.event-item`, `.toast`, `.cam-toggle`, `.intrusion-badge`, `.gallery-grid`/`.gallery-thumb`, `.filter-input`/`.filter-select`, `#clip-modal` (de `index.html:36-116`).
- `frontend/css/layout.css` - vacío a propósito (solo comentario explicativo), layout es 100% Tailwind utility-driven.

## Decisions Made
- Ver `key-decisions` en el frontmatter. Ninguna decisión arquitectónica nueva — extracción 1:1 tal como fija `28-CONTEXT.md`/`28-PATTERNS.md`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comentario de layout.css contenía el string literal que su propio acceptance criteria prohibía**
- **Found during:** Task 2, verificación de acceptance criteria (`grep -c "@media" frontend/css/layout.css` debía dar `0`)
- **Issue:** El comentario explicativo citaba literalmente "0 coincidencias de `@media`" para justificar por qué el fichero está vacío, lo que hacía que el propio grep de verificación encontrara 1 coincidencia (la mención en el comentario, no una regla real) y fallara el criterio de aceptación tal como está escrito.
- **Fix:** Reescrito el comentario para decir "media queries" en vez de "`@media`" literal — mismo significado, sin el string que rompía el grep.
- **Files modified:** `frontend/css/layout.css`
- **Verification:** `grep -c "@media" frontend/css/layout.css` → `0`
- **Committed in:** `0b4826f` (Task 2 commit, corregido antes del commit — no generó un commit adicional)

---

**Total deviations:** 1 auto-fijado (Rule 1 - bug de auto-verificación, no de comportamiento)
**Impact on plan:** Sin impacto en alcance ni arquitectura — ajuste de redacción de un comentario para pasar el propio criterio de aceptación del plan.

## Issues Encountered
- El worktree de ejecución no tiene `.venv` propio (está en el repo principal `F:\Documentos\IA\Proyecto_Camara\.venv`, fuera del worktree, no compartido por git). Se resolvió invocando el intérprete del repo principal por ruta absoluta (`/f/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe -m pytest ...`) sin modificar nada del entorno. No es un problema de código, solo de invocación en este entorno concreto.

## User Setup Required
None - no se requiere configuración de servicios externos.

## Next Phase Readiness
- El contrato pytest está listo para que `28-02`..`28-08` verifiquen su propio alcance con `-k <patrón>` sin tocar este fichero.
- Verificación completa ejecutada: `pytest tests/test_frontend_modules.py -q` → 4 passed, 4 failed — exactamente el estado esperado documentado en el `<verification>` del plan (fallan `TEST_js_modules_exist`, `TEST_no_inline_logic`, `TEST_app_entry_point_is_real`, `TEST_static_js_mime_type` porque ningún módulo JS existe todavía; pasan `TEST_css_modules_exist`, `TEST_line_limit`, `TEST_static_css_served`, `TEST_root_serves_index_html`). No es una regresión de este plan.
- Ningún bloqueante para continuar con `28-02` (que empieza a crear los módulos JS).

## Self-Check: PASSED

Ficheros verificados:
- FOUND: tests/test_frontend_modules.py
- FOUND: frontend/css/base.css
- FOUND: frontend/css/layout.css
- FOUND: frontend/css/components.css

Commits verificados:
- FOUND: a9c4303
- FOUND: 0b4826f

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*
