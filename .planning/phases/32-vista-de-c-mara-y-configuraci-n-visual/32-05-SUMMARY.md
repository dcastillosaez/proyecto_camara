---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 05
subsystem: ui
tags: [vanilla-js, config-api, settings, anti-xss]

# Dependency graph
requires:
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 02
    provides: "GET/PUT /api/v2/config + POST /{section}/restore: contrato JSON (FieldValue con origin/applies/secret/readonly, errores 422 {field,message}, fields frescos tras guardar/restaurar) que settings-field.js y settings-save.js consumen tal cual"
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 03
    provides: ".cfg-row/.cfg-badge/.cfg-applies/.cfg-savebar en components.css, listas para el marcado que estos dos modulos rellenan"
provides:
  - "frontend/js/views/settings-field.js: renderField/readFieldValue/setFieldError/clearFieldError/markFieldDirty/fieldKeyOf -- un control DOM por tipo de campo (bool/int/float/str/enum/time/list_int/list_str/secret/readonly)"
  - "frontend/js/views/settings-save.js: trackChange/pendingCount/discardChanges/isDirty/saveSection/restoreSection/setOnSectionSaved -- diff en memoria por seccion, PUT, mapeo 422, popover de restaurar"
  - "Convencion de marcado para 32-06: [data-cfg-section=\"<key>\"] (panel), [data-cfg-action=\"save\"|\"restore\"] (botones), #restore-config-popover + #restore-popover-title + #restore-popover-body + [data-restore-confirm]/[data-restore-cancel] (popover unico compartido)"
affects: [32-06, 32-07, 32-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Plantilla vacia por tipo de control (switch(field.type) -> renderer dedicado) rellenada solo con createElement/textContent, nunca innerHTML con datos de servidor -- mismo patron anti-XSS que timeline-row.js, explicitamente NO el atajo con innerHTML que detectionClasses.js:18-21 usa hoy"
    - "Diff pendiente en Map<sectionKey, Map<fieldKey,value>> a nivel de modulo (nunca en el DOM ni en localStorage): cambiar de seccion o de pestana no lo pierde, sin beforeunload"
    - "Popover de confirmacion destructiva (D-07 de la Fase 30) replicando literalmente _muteTarget/openMutePopover/closeMutePopover de alertCenter.js: variable de modulo fuera del DOM, textContent para dato de servidor/cliente, click-fuera-cierra delegado en document, Escape cierra el popover antes que cualquier otra cosa"
    - "422 no descarta el diff: cada error se mapea a su .cfg-row por dataset.fieldKey, la primera fila con error recibe scrollIntoView+foco, las filas validas siguen .dirty (D-10)"
  key-files:
    created:
      - frontend/js/views/settings-field.js
      - frontend/js/views/settings-save.js
    modified: []

key-decisions:
  - "Noveno renderer para type:\"str\" (texto libre: tapo_host, host, yolo_model_path, detection_label...), tipo real del esquema de 32-01/32-02 que la lista de 8 tipos del contrato de <interfaces> no menciona explicitamente. Confirmado en backend/api/v2/config.py:134 (rama 'else: str' de la validacion de rango) -- Rule 2, cobertura obligatoria para que el arbol de Ajustes no se quede sin control en esas filas."
  - "Convencion de marcado nueva para que settings-save.js localice el DOM de una seccion solo con el string sectionKey (el contrato de <interfaces> no le pasa nodos): [data-cfg-section], [data-cfg-action=\"save\"|\"restore\"] y el popover unico #restore-config-popover con sus 4 sub-ids. Documentada en la cabecera del fichero para que 32-06 la use literalmente al montar el marcado real, mismo principio interface-first que el contrato de ids de camera-quick.js en 32-04."
  - "readFieldValue/trackChange en list_int usan Number(chip.dataset.value) como id COCO o indice de dia de la semana (schedule_days): mismo catalogo COCO_CLASS_LABELS replicado literalmente de detectionClasses.js::DETECTION_CLASS_LABELS (no exportado alli), evitando el ciclo de import views/ -> components/ -> views/ que trackChange ya crea en sentido inverso (settings-field.js importa trackChange de settings-save.js)."
  - "saveSection distingue res.status===422 (HTTPException con detail={errors:[...]}, FastAPI anida bajo 'detail') de cualquier otro !res.ok (red/5xx): solo el primero mapea errores por fila sin descartar el diff; el segundo usa el toast generico 'los cambios siguen aqui' que pide el UI-SPEC."

patterns-established:
  - "Las dos piezas 'hoja' del motor de Ajustes quedan completas y verificables de forma aislada, sin ningun elemento real en index.html todavia -- 32-06 las importa como dado (interface-first, mismo principio que 32-01 antes de 32-02)."

requirements-completed: []

# Metrics
duration: ~25min
completed: 2026-08-24
---

# Phase 32 Plan 05: Vista Ajustes — settings-field.js y settings-save.js Summary

**`frontend/js/views/settings-field.js` (298 líneas) renderiza un control DOM nativo por cada uno de los 9 tipos reales del esquema de configuración con badges de origen/aplicación y estado de error 422, y `frontend/js/views/settings-save.js` (180 líneas) lleva el diff pendiente por sección en memoria, el `PUT` con mapeo de errores fila a fila, y "Restaurar valores por defecto" mediante un popover que replica literalmente el patrón de silenciado de `alertCenter.js`.**

## Performance

- **Duration:** ~25 min (Task 1 ya estaba escrita de una sesión previa interrumpida; esta sesión confirmó su verificación, la comiteó, y construyó Task 2 completa)
- **Tasks:** 2 (1 commit de código cada una, sin ciclo RED/GREEN — no hay framework de test JS en el repo, mismo criterio que 32-03/32-04)
- **Files modified:** 2 (ambos creados)

## Accomplishments

- `settings-field.js` expone `renderField(field, sectionKey)` con un `switch(field.type)` que delega a 9 renderers (`_renderBool`/`_renderNumber` para int y float/`_renderStr`/`_renderEnum`/`_renderTime`/`_renderListInt`/`_renderListStr`/`_renderSecret`/`_renderReadonly`), todos devolviendo el mismo esqueleto `.cfg-row` con columna izquierda (label/env/hint/rango `min–max · por defecto N`) y columna derecha (control + 2 badges).
- Chips `.filter-chip` con `aria-pressed` reales para `list_int` — primera vez que se establece ese patrón en el repo (32-PATTERNS.md lo marcaba como pendiente): `yolo_classes`/`object_class_ids` usan el catálogo COCO replicado de `detectionClasses.js`, `schedule_days` usa los 7 chips fijos "L M X J V S D".
- `readFieldValue(rowEl)` lee según `rowEl.dataset.fieldType` y devuelve el tipo nativo correcto por tipo; `setFieldError`/`clearFieldError` pintan/quitan `aria-invalid`+`aria-describedby`+`.cfg-row.error` con el mensaje 422 literal, nunca reescrito.
- Cero `innerHTML`: todo dato de servidor (`label`, `hint`, `env`, mensaje 422) entra por `textContent` sobre nodos creados con `createElement`, ni siquiera el atajo con interpolación que `detectionClasses.js:18-21` usa hoy — verificado por `grep -n "innerHTML"` (solo aparece en un comentario explicando la regla anti-XSS, cero coincidencias de código real).
- `settings-save.js` mantiene `_pending: Map<sectionKey, Map<fieldKey,value>>` a nivel de módulo (nunca en el DOM); `trackChange`/`pendingCount`/`discardChanges`/`isDirty` operan puramente sobre ese mapa.
- `saveSection(sectionKey)`: `PUT /api/v2/config {section, changes}` con el botón `[data-cfg-action="save"]` y todos los controles de la sección en `.busy`/`disabled` durante el vuelo; en 200 descarta el diff, repinta `.dirty=false`, invoca el callback `_onSectionSaved` inyectado por `setOnSectionSaved`, y muestra el toast con el recuento real de campos guardados (con la variante "se aplicarán al reiniciar" si `requires_restart.length > 0`, D-19); en 422 NO descarta el diff — mapea cada `{field, message}` a su `.cfg-row` por `dataset.fieldKey`, hace `scrollIntoView({block:'center'})` + foco sobre la primera fila con error, y deja las filas válidas sin tocar (siguen `.dirty`); en fallo de red/5xx muestra el toast rojo "Los cambios siguen aquí, inténtalo de nuevo." sin tocar el diff.
- `restoreSection(sectionKey, fieldCountRuntime)`: con `fieldCountRuntime === 0` solo fija un `title` explicativo en el botón sin abrir nada; en otro caso abre el popover con título `Restaurar «{sección}»`, cuerpo con el copy exacto del UI-SPEC y botón `Restaurar {N} valores` — al confirmar, `POST /{section}/restore`, descarta el diff, repinta y muestra el toast `«{sección}» restaurada. {N} valores devueltos a su origen.` (copy literal del UI-SPEC línea 298).
- Popover replicado literalmente sobre `_muteTarget`/`openMutePopover`/`closeMutePopover` de `alertCenter.js`: variable de módulo `_restoreTarget` (nunca en el DOM), `textContent` para título/cuerpo, click-fuera-cierra delegado en `document` (excluyendo el propio popover y el botón disparador), `Escape` cierra el popover.
- `node --check` limpio en ambos ficheros; `tests/test_frontend_modules.py` 9 passed (`TEST_line_limit` en verde: 298 y 180 líneas, ninguno cerca del tope de 300).

## Task Commits

1. **Task 1: settings-field.js** — `bd2cc81` (feat)
2. **Task 2: settings-save.js** — `5ce29ca` (feat)

**Plan metadata:** (este commit, `docs(32-05)`)

## Files Created/Modified

- `frontend/js/views/settings-field.js` (298 líneas, nuevo) — `renderField`/`readFieldValue`/`setFieldError`/`clearFieldError`/`markFieldDirty`/`fieldKeyOf`, 9 renderers por tipo, badges de origen/aplicación
- `frontend/js/views/settings-save.js` (180 líneas, nuevo) — `trackChange`/`pendingCount`/`discardChanges`/`isDirty`/`saveSection`/`restoreSection`/`setOnSectionSaved`, popover de restaurar

## Decisions Made

- **Noveno renderer para `type:"str"`**: la lista de 8 tipos del contrato de `<interfaces>` (bool/int/float/enum/time/list_int/list_str/secret/readonly, en realidad 9 con readonly) no menciona `"str"`, pero el esquema real de `32-01`/`32-02` lo usa para texto libre (`tapo_host`, `host`, `yolo_model_path`, `detection_label`...) — confirmado en `backend/api/v2/config.py:134`. Sin este renderer esas filas se quedarían sin control interactivo. Documentado como Rule 2 (cobertura obligatoria), no una desviación de comportamiento.
- **Convención de marcado para que `settings-save.js` localice el DOM de una sección solo con el `sectionKey`** (string, no nodo — así lo define el contrato de `<interfaces>`): `[data-cfg-section="<key>"]` para el panel, `[data-cfg-action="save"|"restore"]` para los botones, y un único popover compartido `#restore-config-popover` con `#restore-popover-title`/`#restore-popover-body`/`[data-restore-confirm]`/`[data-restore-cancel]`. Documentada en la cabecera de `settings-save.js` para que `32-06` la use literalmente al montar el marcado real de cada sección, mismo principio interface-first que el contrato de ids de `camera-quick.js` en `32-04`.
- **Catálogo COCO replicado, no importado**: `COCO_CLASS_LABELS` en `settings-field.js` repite el mismo subconjunto que `detectionClasses.js::DETECTION_CLASS_LABELS` (no exportado allí) en vez de importarlo, porque `settings-field.js` ya importa `trackChange` de `settings-save.js` — un import adicional a `components/detectionClasses.js` no crearía ciclo técnico pero sí acoplaría dos vistas independientes a una tabla que el plan explícitamente permite replicar ("si importar crea dependencia circular con `components/`, o replicando la misma tabla literal").
- **422 vs red/5xx distinguidos por `res.status === 422`**: FastAPI anida los errores de `HTTPException(422, detail={"errors":[...]})` bajo la clave `detail`, así que `saveSection` lee `body.detail?.errors ?? body.errors ?? []` (tolerante a ambas formas) — solo esta rama mapea errores a filas sin descartar el diff; cualquier otro `!res.ok` (incluida excepción de red) usa el toast genérico del UI-SPEC.

## Deviations from Plan

### Auto-fixed Issues

Ninguna de Rule 1/3 — el código no tenía bugs que corregir ni bloqueos que resolver.

**1. [Rule 2 - Cobertura obligatoria] Renderer para `type:"str"` no listado en `<interfaces>`**
- Ver "Decisions Made" arriba. Sin este renderer, campos reales del esquema (`tapo_host`, `host`, etc.) se habrían quedado sin control — correctitud básica del árbol de Ajustes, no una funcionalidad nueva.
- Archivo: `frontend/js/views/settings-field.js`
- Commit: `bd2cc81`

Ninguna decisión arquitectónica (Rule 4): ambas piezas se construyeron dentro del contrato de `<interfaces>` fijado por el plan, con la única extensión de cobertura de tipo ya justificada.

## Issues Encountered

Ninguno. Ningún id real de `[data-cfg-section]`/`#restore-config-popover` existe todavía en `index.html` — los crea `32-06` — así que ambos módulos toleran su ausencia con `?.`/comprobaciones de nulidad explícitas (`_openRestorePopover` no hace nada si falta cualquiera de los 4 sub-elementos del popover), igual que `camera.js`/`camera-quick.js` en `32-04`. La verificación funcional completa queda diferida al checkpoint manual de `32-08`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `settings-field.js` y `settings-save.js` están listos para que `32-06` (`settings.js`/`settings-section.js`) los importe y los cablee al marcado real del árbol de Ajustes: solo falta crear el marcado con la convención de ids/atributos documentada en la cabecera de `settings-save.js` (`[data-cfg-section]`, `[data-cfg-action]`, `#restore-config-popover` + sus 4 sub-ids) y llamar a `renderField(field, sectionKey)` por cada fila.
- `setOnSectionSaved(cb)` queda listo para que `32-06` reciba los `fields` frescos tras un guardado o restauración exitosos y repinte el árbol (punto azul de `isDirty`, badges actualizados).
- OPS-18, OPS-19, OPS-20, SET-03 y SET-04 avanzan (las dos piezas del motor de renderizado y guardado existen y pasan sus criterios de aceptación mecánicos) pero no se cierran formalmente: exigen interfaz visible funcionando con el marcado real de `32-06`/`32-07`, que se marca en la puerta de fase `32-08` — mismo patrón que OPS-16/OPS-17 en `32-04` y OPS-18 en `32-03`.
- Suite dirigida verde (`tests/test_frontend_modules.py` 9 passed); plan solo de frontend, sin tocar pipeline/API/config, así que no se relanzó la suite completa (mismo criterio que `32-03`, `32-04`, `31-04`, `31-07`, `31-08`, `31-10`).

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/js/views/settings-field.js
- FOUND: frontend/js/views/settings-save.js
- FOUND: .planning/phases/32-vista-de-c-mara-y-configuraci-n-visual/32-05-SUMMARY.md
- FOUND commit: bd2cc81
- FOUND commit: 5ce29ca
