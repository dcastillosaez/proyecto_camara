---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 06
subsystem: ui
tags: [vanilla-js, config-api, settings, aria-tablist, anti-xss]

# Dependency graph
requires:
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 05
    provides: "settings-field.js (renderField/readFieldValue/markFieldDirty/setFieldError/clearFieldError/fieldKeyOf) y settings-save.js (trackChange/pendingCount/discardChanges/isDirty/saveSection/restoreSection/setOnSectionSaved) -- las dos piezas hoja del motor de Ajustes, mas la convencion de marcado [data-cfg-section]/[data-cfg-action]/#restore-config-popover documentada en su cabecera"
provides:
  - "frontend/js/views/settings.js: initSettings() -- carga de GET /api/v2/config, tablist vertical de 8 secciones con navegacion de teclado ARIA completa, deep-link #ajustes/{seccion}, punto azul de dirty en el arbol"
  - "frontend/js/views/settings-section.js: renderSection(section, sectionKey, requiresRestart) -- un fieldset por grupo, subsecciones de solo lectura zonas_definidas/reglas_cargadas bajo demanda, barra de guardado sticky, boton Restaurar"
  - "setOnSectionSaved(sectionKey, freshFields, requiresRestart) en settings-save.js: tercer argumento anadido (requires_restart de la respuesta del PUT) para que la barra ambar de OPS-19 sea posible"
affects: [32-07, 32-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Arbol de secciones como tablist vertical con un unico listener de keydown delegado en el contenedor (roving tabindex: flechas/Home/End mueven el foco sin activar, Enter/Space activa) -- mismo mecanismo ARIA que el tablist horizontal de vistas de la Fase 31, aplicado en vertical"
    - "Esquema completo (GET /api/v2/config) vive en memoria de modulo (_schema) y se actualiza in-place con los fields frescos que devuelve cada PUT/restore (_mergeFreshFields por key), en vez de repintar desde una copia que quedaria obsoleta tras guardar"
    - "Subsecciones de solo lectura resueltas bajo demanda: el fieldset se construye sincronamente y su fetch (GET /api/zones o /api/v2/rules) rellena el cuerpo despues, solo cuando esa seccion se pinta -- nunca al cargar el esquema completo"
    - "Panel unico repintado por seccion ([data-cfg-section] se reescribe en cada renderSection): saveSection/restoreSection de 32-05 siguen localizandolo solo con el sectionKey, sin que este plan cree un nodo por seccion"
  key-files:
    created:
      - frontend/js/views/settings.js
      - frontend/js/views/settings-section.js
    modified:
      - frontend/js/views/settings-save.js

key-decisions:
  - "_openSection()/renderSection() ganan un tercer parametro opcional requiresRestart=[] (no forma parte de la firma literal del <action> del plan, que solo lista section/sectionKey): la unica via para que la barra ambar de OPS-19 ('N cambios no se aplicaran hasta reiniciar') tenga el dato, ya que discardChanges() borra el diff pendiente ANTES de invocar el callback de guardado, y por tanto no queda ningun rastro en pendingCount/isDirty de que esos campos concretos necesitaban reinicio."
  - "Merge de fields frescos por key (_mergeFreshFields) en vez de confiar en el _schema anterior al guardado: sin este merge, _openSection() repintaria la seccion recien guardada con los valores ANTERIORES al PUT (bug visible: el campo parece revertirse un instante despues de guardar), porque renderSection() reconstruye el DOM entero desde section.groups[].fields en memoria."
  - "Boton 'Restaurar valores por defecto' vive en una cabecera propia que renderSection() inserta al principio del panel (panel.insertBefore) despues de pintar los fieldsets, en vez de reestructurar el orden literal del pseudocodigo del plan (fieldsets primero, savebar/restore despues) -- visualmente queda arriba del todo porque se inserta como primer hijo, sin tocar la secuencia de llamadas que fija el <action>."
  - "Fila de zona/regla usa 'habilitada'/'deshabilitada' como texto de estado (el plan describe el criterio como 'nombre + estado enabled/deshabilitada' sin fijar una cadena literal entre comillas, a diferencia de los dos empty states que si van citados exactos en el UI-SPEC)."

patterns-established:
  - "El arbol de Ajustes queda funcional (interface-first, sin marcado real todavia) como el ultimo orquestador de vista de la Fase 32 antes de que 32-07 monte los ids reales en index.html."

requirements-completed: []

# Metrics
duration: ~35min
completed: 2026-08-24
---

# Phase 32 Plan 06: Vista Ajustes — settings.js y settings-section.js Summary

**`frontend/js/views/settings.js` (198 líneas) carga el esquema de `GET /api/v2/config` una sola vez y pinta el árbol de las 8 secciones fijas como `tablist` vertical con navegación de teclado ARIA completa y deep-link `#ajustes/{sección}`; `frontend/js/views/settings-section.js` (177 líneas) pinta cada sección como un único panel con un `<fieldset>` por grupo, resolviendo bajo demanda las dos subsecciones de solo lectura y la barra de guardado/restaurar de `32-05`.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 (1 commit de código cada una; sin ciclo RED/GREEN, no hay framework de test JS en el repo — mismo criterio que `32-03`/`32-04`/`32-05`)
- **Files modified:** 3 (2 creados, 1 extendido con una línea aditiva)

## Accomplishments

- `settings.js` expone `initSettings()`: `_loadSchema()` pinta 8 filas esqueleto (`.cfg-node.animate-pulse`, sin texto ni spinner) mientras el `fetch` está en vuelo, guarda `_schema` completo en memoria y llama `_renderTree()`; en fallo pinta `_renderLoadError()` con "No se pudo cargar la configuración." y "Reintentar carga" que repite el mismo fetch.
- `_renderTree()` pinta `role="tablist" aria-orientation="vertical"` con un `role="tab"` de 32px (`.cfg-node`) por sección — las 8 en el orden que ya devuelve el servidor (camara/deteccion/tracking/reconocimiento/zonas/reglas/alertas/almacenamiento, confirmado en `backend/api/v2/config_schema.py`) — con `section.label` por `textContent`.
- `_onTreeKeydown` (único listener delegado en el contenedor, enlazado una sola vez con una guarda `_keydownBound` para que "Reintentar carga" no lo duplique): `↑`/`↓` mueven el foco con roving `tabIndex` sin activar la sección, `Home`/`End` a los extremos, `Enter`/`Espacio` activa la pestaña enfocada — mismo mecanismo ARIA que el `tablist` horizontal de vistas de la Fase 31.
- `_openSection(key, requiresRestart)` actualiza `aria-selected`/`aria-current`/`tabIndex` de los tabs, llama `renderSection()` con los datos ya en memoria (sin nuevo fetch) y hace `history.replaceState(null, '', '#ajustes/' + key)` — nunca `location.hash` directo.
- Deep-link: `_sectionFromHash()` valida el hash contra las secciones reales del esquema ya cargado; una sección desconocida o un esquema aún no cargado caen en `null` → `'camara'`.
- `_refreshTreeDirtyDots()` añade/quita `.cfg-node-dot` según `isDirty(sectionKey)` de `32-05`, registrado como callback de `setOnSectionSaved` en `initSettings()` — cambiar de sección con cambios pendientes no los pierde ni muestra ningún diálogo (D-09): el punto azul es la única señal.
- `settings-section.js` expone `renderSection(section, sectionKey, requiresRestart=[])`: un `<fieldset><legend>` por grupo normal delegando cada fila a `renderField(field, sectionKey)` de `32-05`, y `_renderExternalGroup(group)` para `zonas_definidas`/`reglas_cargadas` — el fieldset se pinta síncronamente y su `fetch(group.external_source)` rellena el cuerpo después (bajo demanda, solo al abrir esa sección), con los dos empty states exactos del UI-SPEC y el error "No se pudo cargar." sin romper el resto del panel (T-32-20).
- Fila de zona: nombre (`item.name`) + `item.kind` (`kind` de `backend/database.py::get_zones()`); fila de regla: nombre + "habilitada"/"deshabilitada" (`item.enabled` de `GET /api/v2/rules`) — ambos por `textContent` (T-32-19), nunca interpolados.
- `_renderSaveBar`: `.cfg-savebar` visible solo con `pendingCount(sectionKey) > 0`, texto `aria-live="polite"` con singular "1 cambio sin guardar"; "Descartar cambios" llama `discardChanges` + repinta desde el `section` en memoria (sin fetch); "Guardar cambios" (`[data-cfg-action="save"]`, requerido por `_setBusy` de `32-05`) llama `saveSection`.
- `_renderRestoreButton`: cuenta campos `origin==="runtime"` de la sección entera; deshabilitado con el `title` literal del UI-SPEC cuando el recuento es 0, si no llama `restoreSection(sectionKey, count)`.
- `node --check` limpio en ambos ficheros; `tests/test_frontend_modules.py` 9 passed (`TEST_line_limit` en verde: 198 y 177 líneas); `grep -n "innerHTML"` solo encuentra los dos comentarios que documentan la regla anti-XSS, cero interpolación real de datos de servidor.

## Task Commits

1. **Task 1: settings.js** — `97524f9` (feat)
2. **Task 2: settings-section.js** (+ extensión de `settings-save.js`) — `602916b` (feat)

**Plan metadata:** (este commit, `docs(32-06)`)

## Files Created/Modified

- `frontend/js/views/settings.js` (198 líneas, nuevo) — `initSettings`, árbol tablist vertical, deep-link, `_mergeFreshFields`
- `frontend/js/views/settings-section.js` (177 líneas, nuevo) — `renderSection`, subsecciones de solo lectura, savebar, botón Restaurar
- `frontend/js/views/settings-save.js` (180 → 181 líneas, extendido) — `setOnSectionSaved` gana un tercer argumento (`requires_restart`)

## Decisions Made

- **`requiresRestart` como tercer argumento aditivo de `_openSection`/`renderSection`**: ver `key-decisions` arriba — el diff pendiente se descarta antes de invocar el callback de guardado, así que `pendingCount`/`isDirty` no pueden reconstruir qué campos concretos requerían reinicio; el único canal posible era ampliar `setOnSectionSaved(sectionKey, freshFields, requiresRestart)` en `settings-save.js` con la extensión mínima ya hecha en `saveSection` (`_onSectionSaved?.(sectionKey, data.fields, data.requires_restart)`), sin tocar ningún otro comportamiento de `32-05` (el toast, el mapeo 422, el popover de restaurar siguen intactos).
- **`_mergeFreshFields` por `key`**: sin él, guardar una sección la repintaría con los valores previos al `PUT` (bug de reversión visual). El servidor devuelve `data.fields` como lista plana (`_section_fields_payload`, misma forma que el payload de `GET`), así que el merge es un simple `Map` por `key` sobre `section.groups[].fields`.
- **Botón Restaurar insertado como cabecera al final del pintado**: `renderSection()` sigue literalmente el orden del `<action>` del plan (fieldsets → savebar → restore), y `_renderRestoreButton` usa `panel.insertBefore(header, panel.firstChild)` para que el resultado visual quede arriba del panel sin reordenar las llamadas.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Repintado tras guardar revertía visualmente los valores recién confirmados**
- **Found during:** Task 1, al trazar el flujo completo `saveSection` → `setOnSectionSaved` → `_openSection` → `renderSection`.
- **Issue:** El callback registrado en `initSettings()` (`(sectionKey) => {...; _openSection(sectionKey);}`) repinta la sección desde `_schema`, pero `_schema` seguía teniendo los valores anteriores al `PUT` — el usuario vería su cambio "desaparecer" un instante después de guardar.
- **Fix:** `_mergeFreshFields(sectionKey, freshFields)` reinyecta por `key` los campos frescos que ya devuelve `saveSection`/`restoreSection` (`data.fields`) en `_schema` antes de repintar.
- **Files modified:** `frontend/js/views/settings.js`
- **Commit:** `97524f9`

**2. [Rule 3 - Bloqueo] `setOnSectionSaved` no exponía `requires_restart`, necesario para la barra ámbar de OPS-19**
- **Found during:** Task 2, al implementar `_renderRestartNotice` según el `<behavior>` del plan ("se calcula sobre `data.requires_restart` que devuelve `saveSection` tras el 200, recibido vía el callback `setOnSectionSaved`").
- **Issue:** El callback de `32-05` solo pasaba `(sectionKey, freshFields)`; `data.requires_restart` no llegaba a `settings.js`/`settings-section.js` por ningún otro canal (el diff pendiente ya se ha descartado en ese punto).
- **Fix:** Extensión aditiva de una línea en `saveSection` (`settings-save.js`): `_onSectionSaved?.(sectionKey, data.fields, data.requires_restart)`. El resto del contrato de `32-05` (firma de los demás exports, toast, mapeo 422, popover) no cambia.
- **Files modified:** `frontend/js/views/settings-save.js` (fuera de `files_modified` del plan, pero acoplado directamente al comportamiento pedido en el `<behavior>` de la Task 2)
- **Commit:** `602916b`

Ninguna decisión arquitectónica (Rule 4): ambas piezas se construyeron dentro del contrato de `<interfaces>` fijado por el plan; la única extensión de firma es aditiva y retrocompatible con el único llamador existente.

## Issues Encountered

Ninguno bloqueante. `#settings-tree`/`#settings-panel` no existen todavía en `index.html` — los crea `32-07` — así que ambos módulos toleran su ausencia con `?.`/comprobaciones de nulidad explícitas, igual que `32-04`/`32-05`. La verificación funcional completa (árbol real, navegación de teclado sobre DOM real, subsecciones de zonas/reglas con datos reales) queda diferida al checkpoint manual de `32-08`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `settings.js`/`settings-section.js` están listos para que `32-07` monte el marcado real (`#settings-tree`, `#settings-panel`, tabpanel de Ajustes) y llame `initSettings()` desde `app.js`/`nav.js`.
- El contrato de marcado documentado en la cabecera de `settings-save.js` (`[data-cfg-section]`, `[data-cfg-action]`, `#restore-config-popover` + 4 sub-ids) queda cerrado por el lado del consumidor: `renderSection()` escribe `[data-cfg-section]`/`data-section-label` en `#settings-panel` y los botones "Guardar"/"Restaurar" llevan `[data-cfg-action]`.
- OPS-18, OPS-19, OPS-20, SET-03 y SET-04 avanzan (los cuatro módulos del motor de Ajustes existen y pasan sus criterios de aceptación mecánicos) pero no se cierran formalmente: exigen interfaz visible funcionando con el marcado real de `32-07`, que se marca en la puerta de fase `32-08` — mismo patrón que `32-03`/`32-04`/`32-05`.
- Suite dirigida verde (`tests/test_frontend_modules.py` 9 passed); plan solo de frontend, sin tocar pipeline/API/config, así que no se relanzó la suite completa.

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/views/settings.js
- FOUND: frontend/js/views/settings-section.js
- FOUND: frontend/js/views/settings-save.js
- FOUND commit: 97524f9
- FOUND commit: 602916b
