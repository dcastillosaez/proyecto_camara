---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 07
subsystem: ui
tags: [vanilla-js, nav, aria-tablist, config-api, camera-view, settings-view]

# Dependency graph
requires:
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 04
    provides: "camera.js (activateCameraFeed/loadRtspCard/tickCameraFooter/initCamera) y camera-quick.js (initCameraQuick + contrato de ids #quick-*), consumidores puros de #camera-feed/#rtsp-*/#cam-*/#quick-* aun no montados en el DOM"
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 06
    provides: "settings.js (initSettings, arbol tablist vertical, deep-link #ajustes/{seccion}) y settings-section.js (renderSection), consumidores de #settings-tree/#settings-panel y del contrato [data-cfg-section]/[data-cfg-action]/#restore-config-popover de settings-save.js"
provides:
  - "frontend/js/nav.js: VIEWS de 4 vistas, _tabFor/_panelFor genericos por id, activateCameraFeed() en la primera activacion de Camara, hash de Ajustes que no pisa el segundo nivel (#ajustes/{seccion})"
  - "frontend/index.html: tabpanel Camara (feed diferido, tarjeta RTSP, 6 teselas, barra de ajustes rapidos) y tabpanel Ajustes (arbol + panel), con los ids exactos que 32-04/32-05/32-06 ya esperaban"
  - "frontend/js/app.js: initCamera()/initCameraQuick()/initSettings() arrancados en DOMContentLoaded"
  - "tests/test_frontend_modules.py: LOCKED_JS con los 8 modulos de la Fase 32"
affects: [32-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "nav.js resuelve tab/panel de cualquier vista por convencion de id (tab-{view}/view-{view}) en vez de un switch cerrado a dos vistas -- extensible sin reescritura para futuras pestanas"
    - "El hash de una vista con subrutas (#ajustes/{seccion}) no se pisa en activate(): solo se escribe #{view} cuando el hash actual no coincide ya con esa vista, para que initNav() y el deep-link de settings.js puedan convivir sin un segundo router"
    - "Checkboxes de 'Ajustes rapidos > Clases' son marcado estatico (mismos 6 valores fijos que DETECTION_CLASS_LABELS de detectionClasses.js): camera-quick.js solo alterna checkboxes ya presentes en el DOM, nunca los crea, a diferencia del panel de Operaciones que si los genera por fetch"
  key-files:
    created: []
    modified:
      - frontend/js/nav.js
      - frontend/index.html
      - frontend/js/app.js
      - frontend/css/components.css
      - tests/test_frontend_modules.py

key-decisions:
  - "activate() no reasigna el hash cuando ya apunta a la vista activa con un segundo nivel (#ajustes/{seccion}): sin esta guarda, initNav() resolviendo el hash al cargar la pagina lo habria sobrescrito con '#ajustes' plano en el mismo tick sincrono en que settings.js aun no ha arrancado, y el deep-link de 32-06 habria llegado siempre vacio."
  - "#restore-config-popover gana dos lineas de CSS (display:none/.open) fuera de los ficheros declarados por el plan: el contrato de marcado de settings-save.js (32-05) exige que el popover empiece oculto, y ningun plan anterior de la fase habia anadido esa regla porque el elemento no existia aun en el DOM."
  - "El PTZ duplicado que 32-UI-SPEC.md dibuja en la fila 3 de la reticula de Camara no se construyo: ni camera.js ni camera-quick.js (32-04) lo consumen, y duplicar los ids del PTZ real (#ptz-stop-btn, data-dir, #presets-container) habria roto bindPtzControls() sobre el unico control existente. Se sigue el contrato de ids literal de la Task 2 del plan, no el diagrama completo del UI-SPEC."
  - "Opciones de #quick-resolution son un conjunto estatico de 4 resoluciones tecnicas razonables (640x360/960x540/1280x720/1920x1080, con 1280x720 = default de process_width/process_height): camera-quick.js no genera ese <option> desde el servidor (solo ajusta select.value), asi que la lista tenia que fijarse en el marcado."

patterns-established:
  - "Cierre de fase: nav.js queda como unico punto de extension del tablist para futuras vistas, con contrato id-based reutilizable sin tocar el mecanismo de activacion/hash/teclado."

requirements-completed: []

# Metrics
duration: ~50min
completed: 2026-08-24
---

# Phase 32 Plan 07: Integración de navegación — nav.js + armazón HTML + wiring Summary

**`frontend/js/nav.js` pasa de 2 a 4 vistas sin reescribir el mecanismo de la Fase 31 (tablist horizontal, hash con `history.replaceState`, teclado con flechas/Home/End), `frontend/index.html` monta el armazón real de los tabpanel Cámara y Ajustes con los ids exactos que `camera.js`/`camera-quick.js`/`settings.js`/`settings-section.js` ya esperaban desde las waves 4-6, y `app.js` arranca los tres puntos de entrada nuevos.**

## Performance

- **Duration:** ~50 min
- **Tasks:** 3 (Task 1 de solo lectura, sin commit de código; Task 2 y Task 3 con un commit cada una)
- **Files modified:** 5 (`nav.js`, `index.html`, `app.js`, `components.css`, `tests/test_frontend_modules.py`)

## Accomplishments

- **Task 1 (precondición):** `frontend/js/nav.js` existía — la Fase 31 ya lo había construido con `registerAnalyticsBoot`/`activeView`/`initNav` (confirmado en `32-01-SUMMARY.md`, sin novedad). Contrato real extraído: `VIEWS` como array de claves, `_tabFor`/`activate` resolviendo tabs/panels por convención de id (`tab-{view}`/`view-{view}`), hash con `history.replaceState` nunca `location.hash` directo. Se usó ese contrato literal en Task 2, sin inventar una API paralela.
- `nav.js`: `VIEWS = ['operaciones', 'analitica', 'camara', 'ajustes']`; `_tabFor`/`_panelFor` pasan de un `switch` cerrado a resolución genérica `document.getElementById('tab-'+view)`/`'view-'+view`, extensible sin tocar el resto del módulo. `activate()` gana dos comportamientos aditivos: llama `activateCameraFeed()` (importado de `camera.js`) cada vez que `view === 'camara'` — el propio módulo ya se protege con su flag `_feedActivated` contra reasignar `src` en activaciones repetidas — y **no pisa** el hash cuando ya apunta a la vista activa con un segundo nivel (`#ajustes/{sección}`).
- `_resolveHash()` reconoce ahora `'camara'`, `'ajustes'` y el prefijo `'ajustes/'` (para que abrir directamente `#ajustes/deteccion` active la pestaña Ajustes, no Operaciones); cualquier hash desconocido sigue cayendo en `operaciones`.
- `frontend/index.html`: dos `<button role="tab">` más en el `tablist` (Cámara, Ajustes) con el mismo patrón de atributos que los dos existentes. Tabpanel Cámara: `<img id="camera-feed">` sin `src`, `#camera-offline` con el mismo copy/patrón que el bloque `#video-offline` de Operaciones (ids propios, sin tocar el original), `.rtsp-card` con `#rtsp-dot`/`#rtsp-status-text`/`#rtsp-url`/`#rtsp-last-frame`/`#rtsp-reconnects`/`#rtsp-resolution`, 6 `.metric-tile` (`#cam-capture-fps`/`#cam-detection-fps`/`#cam-latency`/`#cam-cpu`/`#cam-ram`/`#cam-dropped`), barra de ajustes rápidos de 44px con los 4 controles (`#quick-classes` con 6 checkboxes estáticos + `#quick-classes-badge`, `#quick-resolution` + badge, `#quick-confidence` + `#quick-confidence-value` + badge, `#quick-severity` + badge) y enlace "Ver todos los ajustes" (`href="#ajustes"`), `#camera-updated` como pie. Tabpanel Ajustes: `#settings-tree` (`<nav class="cfg-tree">`) y `#settings-panel`, ambos vacíos — "el esquema manda, el marcado no" (32-UI-SPEC.md).
- Popover `#restore-config-popover` montado fuera de los tabpanel (junto a `#alert-drawer`, mismo patrón de "diálogo único compartido") con `#restore-popover-title`/`#restore-popover-body`/`[data-restore-confirm]`/`[data-restore-cancel]`, contrato literal de `settings-save.js`.
- `frontend/js/app.js`: 3 imports nuevos (`initCamera`, `initCameraQuick`, `initSettings`) y las 3 llamadas al final de `DOMContentLoaded`, tras el bloque de `loadObservability()`.
- `tests/test_frontend_modules.py`: `LOCKED_JS` gana 6 entradas (`views/camera.js`, `views/camera-quick.js`, `views/settings.js`, `views/settings-section.js`, `views/settings-field.js`, `views/settings-save.js`); `nav.js` y `dashboard-observability.js` ya estaban.
- `node --check` limpio en `nav.js`/`app.js`; `tests/test_frontend_modules.py` 9 passed (`TEST_line_limit` en verde: 129 líneas `nav.js`, 75 líneas `app.js`, 237 líneas `components.css`); `TEST_no_inline_logic` en verde (cero `<script>`/`<style>` inline nuevo, el `onclick`/`onerror` del bloque `#camera-offline` replica literalmente el patrón ya existente y tolerado en `#video-offline` de Operaciones).
- Suite completa relanzada (el plan toca navegación/wiring compartido): **ver resultado exacto más abajo**.

## Task Commits

1. **Task 1: verificación de precondición (sin commit de código, solo lectura)**
2. **Task 2: nav.js + armazón HTML** — `b390011` (feat)
3. **Task 3: wiring de app.js + LOCKED_JS** — `7d3d917` (feat)

**Plan metadata:** (este commit, `docs(32-07)`)

## Files Created/Modified

- `frontend/js/nav.js` (101 → 129 líneas) — `VIEWS` a 4, `_tabFor`/`_panelFor` genéricos, `activateCameraFeed()` en Cámara, hash de Ajustes no pisado
- `frontend/index.html` (972 → 1142 líneas) — 2 tabs + 2 tabpanel + popover de restaurar
- `frontend/js/app.js` (64 → 75 líneas) — 3 imports + 3 llamadas
- `frontend/css/components.css` (231 → 237 líneas) — regla `display:none`/`.open` de `#restore-config-popover`
- `tests/test_frontend_modules.py` (150 → 156 líneas) — `LOCKED_JS` con los 8 módulos de la fase

## Decisions Made

- Ver `key-decisions` en el frontmatter: guarda de hash en `activate()`, CSS mínimo para el popover de restaurar, PTZ no duplicado, resoluciones estáticas de `#quick-resolution`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `activate()` habría pisado el deep-link `#ajustes/{sección}` de 32-06 en cada activación de pestaña**
- **Found during:** Task 2, al trazar el orden real de arranque (`initNav()` se llama antes que `initSettings()` en `app.js`, y ambos corren dentro del mismo `DOMContentLoaded` síncrono).
- **Issue:** La implementación heredada de `activate()` hacía `history.replaceState(null, '', '#'+view)` sin condición. Con `view === 'ajustes'`, esto habría reescrito `#ajustes/deteccion` (un marcador o URL pegada) a `#ajustes` plano *antes* de que `settings.js` leyera el hash, dejando el deep-link siempre inoperante.
- **Fix:** `activate()` solo reescribe el hash si el hash actual no coincide ya con la vista (ni exacto ni con el prefijo `{view}/`).
- **Files modified:** `frontend/js/nav.js`
- **Commit:** `b390011`

**2. [Rule 2 - Funcionalidad crítica faltante] `#restore-config-popover` sin regla CSS que lo mantuviera oculto por defecto**
- **Found during:** Task 2, al montar el popover en `index.html` siguiendo el contrato de `settings-save.js` (que solo alterna la clase `.open`, nunca `hidden`).
- **Issue:** Ningún plan anterior había añadido la regla `display:none` porque el elemento no existía en el DOM hasta ahora; sin ella, el popover de "Restaurar valores por defecto" habría aparecido visible en el centro de la pantalla desde el primer render de cualquier vista.
- **Fix:** Dos líneas en `components.css` (`#restore-config-popover { display:none; ... } .open { display:flex; }`), mismo patrón que `#alert-mute-popover` de la Fase 30.
- **Files modified:** `frontend/css/components.css` (fuera de `files_modified` del plan, acoplado directamente al marcado que la Task 2 pedía montar)
- **Commit:** `b390011`

Ninguna decisión arquitectónica (Rule 4): las dos correcciones son aditivas y locales, dentro del contrato ya fijado por `32-04`/`32-05`/`32-06`; no se introduce ningún mecanismo de navegación ni almacén paralelo.

## Issues Encountered

Ninguno bloqueante. `frontend/js/nav.js` existía desde antes de planificar esta fase (confirmado también por `32-01-SUMMARY.md`), así que la Task 1 no encontró el bloqueo que el propio plan contemplaba como caso principal — se documenta igualmente como verificación explícita, no como salto de paso.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Las cuatro pestañas (Operaciones, Analítica, Cámara, Ajustes) están montadas y cableadas de extremo a extremo por primera vez en la fase: `activateCameraFeed()`, la tarjeta RTSP, las 6 teselas, la barra de ajustes rápidos, el árbol de Ajustes y el popover de restaurar tienen ahora ids reales en el DOM.
- OPS-16/17/18 (requisitos de este plan) y OPS-19/OPS-20/SET-03/SET-04 (heredados de waves anteriores) avanzan con interfaz visible por primera vez, pero **no se cierran formalmente aquí** — mismo patrón que `32-03`..`32-06`: exigen el checkpoint visual con servidor y navegador reales, que es la Task 2 de `32-08-PLAN.md` (`autonomous: false`, puerta de fase, no ejecutable en modo autónomo).
- `32-08-PLAN.md` existe en disco y es el único plan pendiente de la fase; no se ejecutó como parte de este plan (fuera de alcance, requiere intervención manual).
- Suite completa relanzada tras el wiring de navegación: **711 passed, 2 skipped** en 212,56 s (sin cambios respecto al recuento previo salvo cero regresiones — este plan no toca pipeline/API/config, solo frontend/tests).

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/nav.js
- FOUND: frontend/index.html
- FOUND: frontend/js/app.js
- FOUND: frontend/css/components.css
- FOUND: tests/test_frontend_modules.py
- FOUND commit: b390011
- FOUND commit: 7d3d917
