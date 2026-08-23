---
phase: 32-vista-de-c-mara-y-configuraci-n-visual
plan: 04
subsystem: ui
tags: [vanilla-js, config-api, mjpeg, camera-view]

# Dependency graph
requires:
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 02
    provides: "GET/PUT /api/v2/config: contrato JSON (sections/groups/fields con origin/applies/secret) que camera.js y camera-quick.js consumen tal cual"
  - phase: 32-vista-de-c-mara-y-configuraci-n-visual
    plan: 03
    provides: ".metric-tile/.rtsp-card en components.css, listas para que 32-07 las use en el marcado que consumira este modulo"
provides:
  - "frontend/js/views/camera.js: activateCameraFeed()/loadRtspCard()/tickCameraFooter()/initCamera() -- panel de salud consolidada de la vista Camara"
  - "frontend/js/views/camera-quick.js: bindQuickClasses/bindQuickResolution/bindQuickConfidence/bindQuickSeverity/initCameraQuick() -- 4 ajustes rapidos contra PUT /api/v2/config"
  - "dashboard-observability.js extendido: loadHealth()/loadObservability() pintan tambien los ids #cam-* de la vista Camara desde el mismo tick de 5s, sin fetch ni intervalo nuevos"
  - "Contrato de ids de la barra de ajustes rapidos (#quick-classes/#quick-resolution/#quick-confidence/#quick-severity + sus badges) que 32-07 debe respetar al construir el marcado"
affects: [32-07, 32-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Activacion diferida de <img> de coste real (activateCameraFeed): flag de modulo _feedActivated que garantiza una sola asignacion de src, evitando que el onerror de reconexion se dispare en cada cambio de pestana"
    - "Segundo set de ids (#cam-*) pintado desde el MISMO fetch/tick que un set anterior (#health-*/#obs-*), en vez de un modulo/timer propio -- misma disciplina de 'no duplicar peticiones que ya existen a ese ritmo' que 31-10 aplico con el heatmap"
    - "bindQuick*/reloadQuick* por control (molde de detectionClasses.js::saveDetectionClasses): deshabilitar solo el propio control durante el PUT, badge de aplicacion pintado siempre desde la respuesta del servidor, revertir al valor real via GET en cualquier error"

key-files:
  created:
    - frontend/js/views/camera.js
    - frontend/js/views/camera-quick.js
  modified:
    - frontend/js/views/dashboard-observability.js

key-decisions:
  - "Contrato de ids de la barra de ajustes rapidos definido en este plan (no en el UI-SPEC, que no fija ids literales para esta barra): #quick-classes (contenedor de .quick-class-checkbox[data-class-id]), #quick-resolution (<select> value=\"ANCHOxALTO\"), #quick-confidence (<input type=range>) + #quick-confidence-value, #quick-severity (<select> info|warning|critical), y un #<control>-badge por cada uno. Documentado en la cabecera de camera-quick.js para que 32-07 lo consuma literalmente al construir el marcado del tabpanel."
  - "#cam-latency usa el formato entero de milisegundos 'p50/p95 ms' del UI-SPEC (tabla de teselas de la vista Camara), distinto del formato en segundos con 2 decimales que ya usa #obs-latency en Operaciones -- son dos presentaciones del mismo dato p50/p95, cada vista sigue su propio formato ya documentado, no una tercera convencion inventada."
  - "_findField() en camera-quick.js busca un campo por key recorriendo todas las secciones/grupos de GET /api/v2/config, en vez de fijar la seccion de antemano por control: las 4 keys (yolo_classes, process_width, process_height, yolo_confidence, upload_min_severity) son unicas en todo el esquema (invariante verificado por TEST del 32-01: set(Settings.model_fields) == {f.key for f in all_fields()}), asi que no hace falta duplicar el mapeo seccion->campo que ya vive en el esquema del servidor."

patterns-established:
  - "Vista de monitorizacion (Camara) que NUNCA abre un fetch/timer propio para datos que otro modulo ya resuelve al mismo ritmo: solo anade ids adicionales a las funciones existentes (loadHealth/loadObservability), extendiendo el mismo tick de 5s en vez de crear un segundo bucle de refresco."

requirements-completed: [OPS-16, OPS-17]

# Metrics
duration: ~30min
completed: 2026-08-23
---

# Phase 32 Plan 04: Vista Cámara — panel de salud y ajustes rápidos Summary

**`frontend/js/views/camera.js` (119 líneas) y `frontend/js/views/camera-quick.js` (240 líneas) construyen el panel de salud consolidada y la barra de 4 ajustes rápidos de la vista Cámara, mientras `dashboard-observability.js` (65 → 77 líneas) gana un segundo set de ids `#cam-*` pintado desde el mismo tick de 5s ya existente, sin abrir ningún fetch nuevo.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 (1 commit de código cada una, sin ciclo RED/GREEN — no hay framework de test JS en el repo, mismo criterio que 32-03 con CSS)
- **Files modified:** 3 (2 creados, 1 modificado)

## Accomplishments
- `camera.js` expone `activateCameraFeed()` (asigna `src="/video_feed"` a `#camera-feed` una sola vez, con flag de módulo), `loadRtspCard()` (semáforo de 3 estados heredado de la Fase 29, edad de último frame, reconexiones, resolución nativa desde `GET /api/v2/cameras/cam1/health`, y URL RTSP enmascarada desde `GET /api/v2/config`), `tickCameraFooter()` e `initCamera()`.
- Toda lectura de `getElementById` usa encadenamiento opcional o comprobación de nulidad: las funciones no lanzan aunque `32-07` todavía no haya creado los ids en el DOM.
- `dashboard-observability.js` extiende `loadHealth()` con `#cam-cpu`/`#cam-ram` y `loadObservability()` con `#cam-capture-fps`/`#cam-detection-fps`/`#cam-dropped`/`#cam-latency` — mismos valores ya resueltos por el fetch existente, sin segunda petición ni segundo `setInterval`.
- `camera-quick.js` implementa los 4 controles de la barra de ajustes rápidos (clases, resolución, confianza con debounce de 600ms, severidad de subida), todos escribiendo contra el mismo `PUT /api/v2/config` del árbol de Ajustes (`32-02`): sin endpoint paralelo, sin toast en éxito (D-13, el vídeo es la confirmación), badge de aplicación siempre pintado desde la respuesta del servidor, y reversión al valor real vía `GET /api/v2/config` + `showToast('error')` en cualquier fallo.
- El deslizador de confianza limita a 1 petición por ráfaga de 600ms de arrastre con `setTimeout`/`clearTimeout` (T-32-13).
- `node --check` limpio en los 3 ficheros; `tests/test_frontend_modules.py` 9 passed (incluye `TEST_line_limit` sobre los 2 ficheros nuevos, aunque todavía no están en `LOCKED_JS` — eso lo añade `32-07`, que es quien monta el marcado que estos módulos consumen).

## Task Commits

1. **Task 1: camera.js + extender dashboard-observability.js** - `2138113` (feat)
2. **Task 2: camera-quick.js** - `1b0d861` (feat)

**Plan metadata:** (este commit, `docs(32-04)`)

## Files Created/Modified
- `frontend/js/views/camera.js` (119 líneas, nuevo) - activación diferida del feed, tarjeta RTSP, pie de actualización, `initCamera()`
- `frontend/js/views/camera-quick.js` (240 líneas, nuevo) - 4 controles bind independientes contra `PUT /api/v2/config`, `initCameraQuick()`
- `frontend/js/views/dashboard-observability.js` (65 → 77 líneas) - `loadHealth()`/`loadObservability()` pintan también los ids `#cam-*`

## Decisions Made
- **Contrato de ids de la barra de ajustes rápidos definido en este plan**: `32-UI-SPEC.md` describe los 4 controles por tipo/parámetro/aplicación pero no fija ids literales (a diferencia de la tarjeta RTSP, cuyos ids salían implícitos del pseudocódigo de la propia `32-04-PLAN.md`). Se documentó el contrato completo en la cabecera de `camera-quick.js` (`#quick-classes`, `#quick-resolution`, `#quick-confidence` + `#quick-confidence-value`, `#quick-severity`, y un `#<control>-badge` por cada uno) para que `32-07` lo consuma sin ambigüedad al construir el marcado del `tabpanel` de Cámara.
- **`#cam-latency` en milisegundos enteros, no en segundos con 2 decimales**: el UI-SPEC fija explícitamente `120/380 ms` para la tesela de latencia de la vista Cámara, distinto del formato `0.12s / 0.38s` que ya usa `#obs-latency` en Operaciones desde la Fase 21. Ambos formatos conviven porque son dos vistas con su propia convención ya documentada — no se inventó una tercera.
- **`_findField()` busca por key en todo el esquema**, sin fijar la sección por adelantado en el cliente: las 5 keys que tocan los 4 controles rápidos son únicas en todo `GET /api/v2/config` (invariante verificado por test desde `32-01`), así que no hace falta duplicar en el navegador el mapeo sección→campo que ya vive en el esquema del servidor.

## Deviations from Plan

### Auto-documented deviations (ya anticipadas por el propio `<behavior>` de la Task 1, no son Rule 1-4)

**1. Sin countdown de backoff en el estado "Reconectando"**
- El UI-SPEC pedía opcionalmente ".mono: reintentando en {N} s" en el estado "Reconectando".
- `CaptureHealth` (`backend/pipeline/capture.py:26`) y el log de backoff de `capture.py:185` no exponen ese valor por ninguna API — inventar un número en el cliente sería un dato falso.
- `loadRtspCard()` pinta solo el texto "Reconectando…" sin cifra, tal como el propio `<behavior>` de la Task 1 ya anticipaba como desviación documentada.

**2. "Frames descartados" desde `/api/v2/metrics`, no desde `/api/v2/cameras/{id}/health`**
- La tabla de teselas del UI-SPEC atribuye el dato al endpoint de salud de cámara.
- El código real ya establecido (`dashboard-observability.js::loadObservability`) lo resuelve desde `/api/v2/metrics` con `_counterSum(d, 'frames_dropped_total')`, mismo valor que ya pinta `#obs-dropped`.
- `#cam-dropped` reutiliza exactamente esa misma variable — se siguió el código real, no el texto del documento, tal como pedía el propio `<behavior>` de la Task 1.

Ninguna de las dos es una desviación de comportamiento no anticipada (Rule 1-4): ambas estaban ya explícitamente previstas y ordenadas por el `<behavior>` de la Task 1 de `32-04-PLAN.md`, que exigía documentarlas en el SUMMARY en vez de improvisar. No hubo autofixes adicionales de Rule 1-3 ni decisiones arquitectónicas de Rule 4.

## Issues Encountered

Ninguno. Los 4 ids de la barra de ajustes rápidos y los ids de la tarjeta RTSP/teselas no existen todavía en `index.html` (los crea `32-07`), así que la verificación funcional completa queda diferida al checkpoint manual de `32-08` (puerta de fase), como el propio plan ya indicaba en su bloque `<verification>`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `camera.js` y `camera-quick.js` están listos para que `32-07` los importe y los cablee al marcado del `tabpanel` de Cámara: solo falta crear los ids documentados en la cabecera de `camera-quick.js` y en el pseudocódigo de `camera.js` (`#camera-feed`, `#rtsp-dot`, `#rtsp-status-text`, `#rtsp-last-frame`, `#rtsp-reconnects`, `#rtsp-resolution`, `#rtsp-url`, `#camera-updated`, `#cam-cpu`, `#cam-ram`, `#cam-capture-fps`, `#cam-detection-fps`, `#cam-dropped`, `#cam-latency`).
- `dashboard-observability.js` no necesita más cambios para esta fase: los 6 ids de teselas de la vista Cámara ya están cableados a su fetch/tick existente.
- OPS-16 y OPS-17 avanzan (los dos módulos de la vista existen y pasan sus criterios de aceptación mecánicos) pero no se cierran formalmente: exigen interfaz visible funcionando con el marcado real de `32-07`, que se marca en la puerta de fase `32-08` — mismo patrón que SET-01..04 en `32-01`/`32-02` y que OPS-18 en `32-03`.
- Suite dirigida verde (`tests/test_frontend_modules.py` 9 passed); plan solo de frontend, sin tocar pipeline/API/config, así que no se relanzó la suite completa (mismo criterio que `32-03`, `31-04`, `31-07`, `31-08`, `31-10`).

---
*Phase: 32-vista-de-c-mara-y-configuraci-n-visual*
*Completed: 2026-08-23*

## Self-Check: PASSED

- FOUND: frontend/js/views/camera.js
- FOUND: frontend/js/views/camera-quick.js
- FOUND: .planning/phases/32-vista-de-c-mara-y-configuraci-n-visual/32-04-SUMMARY.md
- FOUND commit: 2138113
- FOUND commit: 1b0d861
