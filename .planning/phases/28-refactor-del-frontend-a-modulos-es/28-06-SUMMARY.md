---
phase: 28-refactor-del-frontend-a-modulos-es
plan: 06
subsystem: ui
tags: [frontend, es-modules, fetch, refactor]

# Dependency graph
requires:
  - phase: 28-01
    provides: "estructura base de directorios frontend/js/ y frontend/js/views/dashboard.js con showToast exportado"
provides:
  - "frontend/js/components/personGallery.js: panel de personas conocidas + modal de enrolamiento (frame actual o subida) + galeria de capturas, extraccion 1:1 de index.html:1518-1687"
  - "frontend/js/api.js: wrapper fetch fino (apiFetch) para consumo de fases futuras (29+), sin analog directo en el codigo original"
affects: [29-vista-de-operaciones, 30-event-timeline-y-alertas, 31-vista-de-analitica, 32-vista-de-camara-y-config-visual]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "apiFetch(path, opts): wrapper fetch centralizado (try/fetch/res.ok implicito via throw) disponible para codigo nuevo, sin migrar call-sites existentes"

key-files:
  created:
    - frontend/js/components/personGallery.js
    - frontend/js/api.js
  modified: []

key-decisions:
  - "api.js no reescribe los ~25 call-sites fetch ya extraidos en 28-02..28-05 (decision explicita del plan, dentro del margen de discrecion de 28-RESEARCH.md): cada call-site tiene su propio manejo de error/mensaje al usuario, no intercambiable mecanicamente con throw new Error sin riesgo de regresion; api.js queda disponible para que las Fases 29+ lo adopten en codigo nuevo"

patterns-established:
  - "personGallery.js interpola p.name directo en innerHTML (mismo patron preexistente que zoneEditor.js, 28-04) — aceptado en el threat model como T-28-11, no se endurece en esta fase"

requirements-completed: [OPS-01, OPS-02]

# Metrics
duration: 15min
completed: 2026-08-18
---

# Phase 28 Plan 06: personGallery.js + api.js Summary

**Extraccion 1:1 del panel de personas reconocidas + modal de enrolamiento + galeria de capturas a `personGallery.js`, y creacion de `api.js` (wrapper `apiFetch`) — ultimo fichero de nivel superior que cierra la estructura de directorios LOCKED por ADR-08**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-08-18T14:31:22Z
- **Tasks:** 2/2
- **Files modified:** 2 (ambos nuevos)

## Accomplishments
- `frontend/js/components/personGallery.js` exporta `loadPersons`, `openGallery` y `bindPersonGallery` — panel de personas conocidas, modal de enrolamiento (frame actual o subida de fichero via `FormData`) y galeria de capturas, comportamiento identico al bloque original de `index.html:1518-1687`.
- `frontend/js/api.js` exporta `apiFetch`, el wrapper `fetch` fino que autoriza `28-CONTEXT.md`, sin necesidad de tipado real.
- Ningun modulo creado en planes anteriores (28-02..28-05) fue tocado.

## Task Commits

Each task was committed atomically:

1. **Task 1: frontend/js/components/personGallery.js** - `0a6b0c8` (feat)
2. **Task 2: frontend/js/api.js** - `ffd9053` (feat)

_Nota: sin plan metadata commit adicional — se documenta en el commit final de este SUMMARY._

## Files Created/Modified
- `frontend/js/components/personGallery.js` (172 lineas) - panel personas conocidas + modal enrolamiento + galeria de capturas
- `frontend/js/api.js` (9 lineas) - wrapper `apiFetch` centralizado

## Decisions Made
- No se reescriben los ~25 call-sites `fetch` existentes de 28-02..28-05 para usar `apiFetch` en este plan — decision explicita documentada en el propio `28-06-PLAN.md` (Task 2), dentro del margen de discrecion de `28-RESEARCH.md`. `api.js` queda listo para codigo nuevo de fases 29+.

## Deviations from Plan

None - plan executed exactly as written. El codigo de ambos ficheros es una copia literal verificada linea por linea contra `frontend/index.html:1518-1687` (personGallery.js) y la especificacion inline del plan (api.js).

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `personGallery.js` y `api.js` listos para ser importados por `frontend/js/app.js` en 28-08 (`loadPersons(); setInterval(loadPersons, 30000); bindPersonGallery();`).
- `frontend/js/api.js` disponible como base para las Fases 29+ que escriban codigo `fetch` nuevo.
- Verificacion automatizada de ambos ficheros pasa: 3 exports en `personGallery.js`, 1 export en `api.js`, ambos bajo 300 lineas, sin diffs en `frontend/js/views` ni en los demas componentes de `frontend/js/components`.

## Self-Check: PASSED

- FOUND: frontend/js/components/personGallery.js
- FOUND: frontend/js/api.js
- FOUND: 0a6b0c8
- FOUND: ffd9053

---
*Phase: 28-refactor-del-frontend-a-modulos-es*
*Completed: 2026-08-18*
