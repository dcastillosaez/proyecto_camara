---
phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
plan: 13
subsystem: ui
tags: [wiring, canvas, dom, anti-xss, integration]

# Dependency graph
requires:
  - phase: 33-editores-visuales-de-zonas-l-neas-y-reglas
    provides: "initZoneEditor()/loadZones() (33-10, frontend/js/components/zoneEditor.js), initLineEditor()/loadLines() (33-11, frontend/js/components/lineEditor.js), initRulesEditor() (33-12, frontend/js/views/rules-editor.js/rules-form.js), endpoints /api/v2/zones|lines|rules ya arrancados desde el modelo v2 (33-08)"
provides:
  - "Armazon HTML real de los tres editores dentro de #view-camara (index.html): #zone-line-canvas superpuesto a #camera-feed, panel de zonas/lineas, #rules-panel"
  - "camera.js: initCamera() llama initZoneEditor()/initLineEditor()/initRulesEditor(); mutex de _editMode entre zonas y lineas sobre el canvas compartido"
  - "app.js sin referencias al modulo legacy bindZoneForm/loadZones (zoneEditor.js ya no las exporta desde 33-10)"
  - "settings-section.js: 3 subsecciones de solo lectura (zonas/lineas/reglas) enlazando a la pestana Camara en vez de a Operaciones/YAML"
  - "Tarjeta 'Zonas de interes' legacy (Fase 13, formulario JSON manual) retirada de Operaciones"
affects: ["33-14 (checkpoint manual, verificacion visual con servidor real)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Un unico <canvas> compartido entre dos modulos (zoneEditor.js/lineEditor.js): cada modulo expone una funcion disableXEditMode() que el orquestador (camera.js) llama desde el listener del boton DEL OTRO modulo, evitando que ambos _editMode esten activos a la vez sin recurrir a click() sintetico (que crea un bucle de retroalimentacion, descartado tras trazarlo)"
    - "#rule-form usa el mismo patron display:none/.open que #restore-config-popover/#alert-mute-popover (componentes.css), ninguna clase Tailwind arbitraria nueva"
    - "settings-section.js pasa de un ternario de 2 vias a un lookup object (_GROUP_INFO) para resolver items/hint por 3 tipos de grupo externo, evitando anidar ternarios"

key-files:
  created: []
  modified:
    - frontend/index.html
    - frontend/css/components.css
    - frontend/js/views/camera.js
    - frontend/js/app.js
    - frontend/js/views/settings-section.js
    - frontend/js/components/zoneEditor.js
    - frontend/js/components/lineEditor.js
    - tests/test_frontend_modules.py

key-decisions:
  - "Canvas #zone-line-canvas montado con position:absolute;inset:0 dentro de la misma .card position:relative que ya envolvia #camera-feed, sin crear un contenedor nuevo"
  - "Panel de zonas/lineas y #rules-panel anadidos como tarjetas .card adicionales en la columna izquierda de #view-camara (lg:col-span-7), despues de 'Ajustes rapidos' -- no como fila nueva a ancho completo, para mantener el video y sus controles en el mismo bloque visual"
  - "Mutex de edicion (zonas vs lineas) resuelto con dos funciones exportadas nuevas (disableZoneEditMode/disableLineEditMode) en vez de simular clicks -- ver Deviations, Rule 2"
  - "loadZones() ya no se llama desde app.js al arrancar (el modulo la dispara el mismo bajo demanda al entrar en modo edicion, tal como zoneEditor.js/lineEditor.js documentan explicitamente en su cabecera: 'sin disparar red hasta modo edicion')"

requirements-completed: [OPS-21, OPS-22, OPS-23, OPS-24, RULE-05]

# Metrics
duration: ~35min
completed: 2026-08-24
---

# Phase 33 Plan 13: Integración frontend — montaje en Cámara, retirada de UI legacy Summary

**Los tres editores visuales de la Fase 33 (zonas, líneas, reglas) quedan montados con marcado real dentro de la pestaña Cámara, cableados desde `camera.js`, con la tarjeta JSON manual de zonas (Fase 13) retirada y las tres subsecciones de solo lectura de Ajustes apuntando al lugar correcto.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3/3 completadas
- **Files modified:** 8

## Accomplishments
- `#zone-line-canvas` superpuesto a `#camera-feed` (mismo `.card` `position:relative`, sin romper `aspect-ratio:16/9`), con todos los ids exactos que `zoneEditor.js`/`lineEditor.js` esperaban desde sus cabeceras (33-10/33-11) verificados uno a uno por grep.
- `#rules-panel` con `#rules-list`/`#rule-new-btn`/`#rule-form`/`#rule-test-btn`/`#rule-test-result` montado dentro de `#view-camara`, consumido tal cual por `rules-editor.js` (33-12).
- Tarjeta "Zonas de interés" legacy (formulario JSON manual `/api/zones` v1, Fase 13) retirada por completo de `#view-operaciones` — el editor visual de Cámara es ahora la única superficie de edición de zonas (D-02).
- `camera.js`: `initCamera()` llama `initZoneEditor()`/`initLineEditor()`/`initRulesEditor()`; un selector de mutex evita que ambos `_editMode` (zonas/líneas) estén activos a la vez sobre el `<canvas>` compartido.
- `app.js`: retirado el import de `bindZoneForm`/`loadZones` de `zoneEditor.js` (símbolo `bindZoneForm` ya no existe desde 33-10 — dejarlo habría roto la carga del módulo ES en el navegador) y las dos llamadas correspondientes.
- `settings-section.js`: `_loadExternalGroup` gestiona ahora 3 grupos (`zonas_definidas`/`lineas_definidas`/`reglas_cargadas`) vía un objeto de lookup (`_GROUP_INFO`), con los textos de "vacío" actualizados para referenciar la pestaña Cámara en vez de "Operaciones" (ya no existe) o "config/rules.yaml" (ya no es cierto desde 33-06/33-08).
- `LOCKED_JS` incorpora `components/lineEditor.js`, `views/rules-form.js`, `views/rules-editor.js`.
- `components.css` gana `#rule-form.open` (mismo patrón `display:none`/`.open` que `#restore-config-popover`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Armazón HTML de los tres editores en #view-camara + retirada de la tarjeta legacy** - `2f79733` (feat)
2. **Task 2: Wiring en camera.js/app.js + enlaces de Ajustes actualizados** - `f9992c4` (feat)
3. **Task 3: LOCKED_JS/LOCKED_CSS + suite completa** - `68e8220` (docs)

**Fixup post-Task 3:** `ecf7665` (docs) — cabecera de `settings-section.js` actualizada a "3 subsecciones", detalle menor detectado al releer el fichero tras el commit de Task 2.

## Files Created/Modified
- `frontend/index.html` — `<canvas id="zone-line-canvas">` sobre `#camera-feed`; panel de zonas/líneas y `#rules-panel` dentro de `#view-camara`; tarjeta "Zonas de interés" retirada de `#view-operaciones`.
- `frontend/css/components.css` — `#rule-form { display:none } #rule-form.open { display:flex }`.
- `frontend/js/views/camera.js` — imports de `initZoneEditor`/`disableZoneEditMode`, `initLineEditor`/`disableLineEditMode`, `initRulesEditor`; las tres llamadas + mutex al final de `initCamera()`.
- `frontend/js/app.js` — retirado `import { loadZones, bindZoneForm } from './components/zoneEditor.js'` y las llamadas `bindZoneForm()`/`loadZones()`.
- `frontend/js/views/settings-section.js` — `_GROUP_INFO` (lookup de 3 grupos) sustituye al ternario `isZones ? ... : ...`; `_externalRow` recibe `kind` en vez de `isZones`.
- `frontend/js/components/zoneEditor.js` — nueva función exportada `disableZoneEditMode()`; cabecera compactada para mantener el fichero en 300 líneas exactas (límite duro).
- `frontend/js/components/lineEditor.js` — nueva función exportada `disableLineEditMode()`.
- `tests/test_frontend_modules.py` — `LOCKED_JS` +3 entradas (`components/lineEditor.js`, `views/rules-form.js`, `views/rules-editor.js`).

## Decisions Made
Ver `key-decisions` en el frontmatter. La más relevante: el mutex de modo edición zonas/líneas se resolvió con funciones exportadas explícitas (`disableZoneEditMode`/`disableLineEditMode`) en vez de disparar `.click()` sobre el botón contrario — se trazó ese enfoque mentalmente antes de escribirlo y produce un bucle de eco (el click sintético dispara de vuelta el listener del primer botón, cancelando el toggle que el operador acababa de pulsar). La solución con funciones exportadas evita el bucle por construcción: cada módulo solo apaga su propio estado cuando se le pide explícitamente, sin volver a disparar el evento `click` del otro botón.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Mutex de `_editMode` entre `zoneEditor.js` y `lineEditor.js` no existía**
- **Found during:** Task 2 (wiring en camera.js)
- **Issue:** Ambos módulos comparten el mismo `<canvas>` (`#zone-line-canvas`) y cada uno mantiene su propio `_editMode` privado sin ninguna forma de que el otro lo desactivara. El propio header de `lineEditor.js` (33-11) documentaba explícitamente que "el Plan 33-13 debe añadir un selector Zonas/Líneas que active solo un `_editMode` a la vez, nunca ambos simultáneamente" — sin esto, activar ambos modos habría hecho que un solo click en el vídeo intentara añadir un vértice de zona Y trazar una línea a la vez, comportamiento roto/confuso para el operador.
- **Fix:** Se añadió una función exportada `disableZoneEditMode()`/`disableLineEditMode()` en cada módulo (guardas `if (!_editMode) return`, sin efectos colaterales si ya estaba desactivado), y `camera.js` las llama desde un listener adicional en el botón del modo contrario.
- **Files modified:** `frontend/js/components/zoneEditor.js`, `frontend/js/components/lineEditor.js`, `frontend/js/views/camera.js`
- **Verification:** `tests/test_frontend_modules.py -q` en verde (9/9); revisión manual del orden de registro de listeners (el mutex se registra después de `initZoneEditor()`/`initLineEditor()`, así que corre después del toggle interno de cada módulo en el mismo evento `click`).
- **Committed in:** `f9992c4` (Task 2 commit)

**2. [Rule 3 - Blocking] `zoneEditor.js` superaba el límite de 300 líneas tras añadir `disableZoneEditMode()`**
- **Found during:** Task 2, verificación previa al commit
- **Issue:** `wc -l` reportó 305 líneas tras la nueva función exportada — por encima del `LINE_LIMIT = 300` que `TEST_line_limit` exige.
- **Fix:** Compactado el comentario de cabecera del fichero (de 11 líneas a 8) y la nueva función a un comentario de una sola línea, sin tocar lógica.
- **Files modified:** `frontend/js/components/zoneEditor.js`
- **Verification:** `wc -l frontend/js/components/zoneEditor.js` → 300 (justo en el límite); `pytest tests/test_frontend_modules.py -q` verde.
- **Committed in:** `f9992c4` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 2 — funcionalidad crítica faltante explícitamente señalada por los planes previos, 1 Rule 3 — bloqueante mecánico del límite de líneas)
**Impact on plan:** Ambos ajustes necesarios para que el wiring funcione correctamente en el navegador y pase el contrato mecánico existente. Sin scope creep — ninguno de los dos toca ficheros fuera de lo ya previsto por el `<objective>` del plan (extender `zoneEditor.js`/`lineEditor.js` con el hook que sus propias cabeceras pedían a 33-13).

## Issues Encountered
Ninguno más allá de las dos desviaciones documentadas arriba. El hueco conocido dejado por 33-10 (`app.js` importaba `bindZoneForm`, símbolo ya no exportado) se cerró tal como estaba previsto en el propio objetivo del plan, sin sorpresas.

## User Setup Required
None - no requiere configuración de servicios externos.

## Next Phase Readiness
- El frontend queda en un estado real y coherente: los tres editores (zonas/líneas/reglas) están montados dentro de `#view-camara`, cableados desde `camera.js`, contra los endpoints `/api/v2/zones`/`/api/v2/lines`/`/api/v2/rules` ya arrancados por 33-08.
- Suite completa: **767 passed, 2 skipped** — sin regresiones tras el wiring final de la fase.
- Pendiente para **33-14** (checkpoint manual, `autonomous: false`): verificación visual con servidor y navegador reales — dibujar una zona/línea sobre el vídeo en vivo, guardar/borrar contra los endpoints v2, componer y probar una regla, y confirmar que las 3 subsecciones de Ajustes muestran el listado real con el enlace correcto a Cámara. Ningún plan autónomo queda pendiente después de este.

---
*Phase: 33-editores-visuales-de-zonas-l-neas-y-reglas*
*Completed: 2026-08-24*

## Self-Check: PASSED

- FOUND: frontend/index.html
- FOUND: frontend/css/components.css
- FOUND: frontend/js/views/camera.js
- FOUND: frontend/js/app.js
- FOUND: frontend/js/views/settings-section.js
- FOUND: frontend/js/components/zoneEditor.js
- FOUND: frontend/js/components/lineEditor.js
- FOUND: tests/test_frontend_modules.py
- FOUND: .planning/phases/33-editores-visuales-de-zonas-l-neas-y-reglas/33-13-SUMMARY.md
- FOUND: commit 2f79733
- FOUND: commit f9992c4
- FOUND: commit 68e8220
- FOUND: commit ecf7665
