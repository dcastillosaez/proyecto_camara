# Fase 36 — Multi-cámara en runtime y UI

Plan redactado a mano (sin `gsd-sdk`, no disponible en esta sesión — mismo
criterio que las Fases 34/35). Research previo con un agente Explore
(auditoría completa de CameraManager/CameraRepo/cameras.py/zonas-líneas-reglas/
AdaptiveRate/frontend/analítica), hallazgos resumidos en "Punto de partida".

**Depends on**: Fase 35 (completa, PR #19 sin mergear todavía)
**Requirements**: SCALE-05..SCALE-08 (`.planning/REQUIREMENTS.md:289-292`)
**Spec**: `propuesta_mejora/SPEC_v2.md:982` (ficheros:
`frontend/js/views/{operations,settings}.js`, `components/cameraGrid.js`,
`backend/api/v2/cameras.py`)

## Punto de partida (hallazgos del research, no asunciones)

`CameraManager` solo tiene `add/get/all/start_all/stop_all` — **no existe
`remove()`**. `CameraRepo` solo tiene `default_camera_id()` — **sin
CRUD**. `backend/api/v2/cameras.py` solo tiene GET (lista + salud) — **sin
POST/PUT/DELETE**. El arranque es 100% estático: `main.py` construye UNA
`CameraPipeline` a mano con `detector`/`tracker`/`recognizer` globales
creados inline (líneas ~478-694) y la registra como `camera_manager.add("cam1",
...)`; nada lee la tabla `cameras` al arrancar. La tabla `cameras` (models.py:31)
ya tiene columna `rtsp_url_ref` pero **nadie la escribe ni la lee todavía**
(vestigial, como `system_metrics.camera_id` en la Fase 35).

El wildcard de reglas (`camera: "*"`) **ya está implementado en el motor**
(`backend/events/rules.py:27,77`) — el hueco es solo de UI (el editor de
reglas no expone el selector). Zonas y líneas ya tienen `camera_id NOT NULL`
y sus repos ya filtran por cámara (Fase 35).

Se han detectado **tres bugs latentes de acoplamiento a "cam1"** que esta
fase debe corregir para que una segunda cámara funcione de verdad, no solo
en apariencia:
- `main.py:509,530` — `_on_clip_ready`/`_on_upload_failed` escriben
  `camera_id="cam1"` literal al persistir grabaciones, sin importar qué
  pipeline generó el clip.
- `main.py:719-728` — `_recorder_hook` (dispara clips desde una regla)
  siempre usa la variable `pipeline` (la primera cámara), nunca resuelve
  por `event.camera_id`.
- `main.py:885-890` — `/video_feed` sirve siempre `rtsp_stream` (alias de la
  primera cámara), sin parámetro `camera_id`.

`AdaptiveRate` (`backend/pipeline/rate.py`) es puramente por-pipeline, sin
coordinación de presupuesto entre cámaras — el riesgo que el propio
SPEC_v2.md anticipa ("CPU insuficiente para N cámaras" → "AdaptiveRate
global con presupuesto compartido"). No existe ninguna métrica de coste de
CPU por cámara en ningún endpoint hoy.

El frontend es 100% mono-cámara: `camera.js` tiene `"cam1"` hardcodeado,
no hay selector ni vista mosaico, ni CRUD de cámaras en Ajustes.
`AnalyticsRepo`/`analytics.py` exigen un único `camera_id`, sin modo
"todas" ni desglose `GROUP BY camera_id`.

**Decisión de test de carga (criterio 6)**: test corto (segundos, no 1h)
con 2 pipelines reales tipo `test_multi_camera.py` de la Fase 35, midiendo
FPS estabilizado y documentando la extrapolación a 1h en el SUMMARY —
decisión tomada con el usuario, no una elección unilateral.

**Decisión de diseño (detector/tracker por cámara)**: cada cámara nueva
obtiene su propia instancia de `PersonDetector`/`PersonTracker` (igual que
anticipa el propio SPEC_v2.md al hablar del riesgo de CPU) — nunca se
comparte un modelo YOLO entre pipelines. El `recognizer` (galería facial)
SÍ se comparte entre cámaras: identificar a la misma persona da igual por
qué cámara entre, es el comportamiento correcto, no un atajo.

## Criterios de éxito (ROADMAP.md:699-705)

1. El CRUD de cámaras desde la UI arranca la cámara nueva sin reiniciar el servidor
2. Existe selector de cámara y vista mosaico con N streams
3. Cada cámara tiene zonas, líneas y reglas propias; las reglas admiten camera "*"
4. La UI muestra el coste estimado de CPU por cámara y advierte al superar el umbral
5. La analítica agrega por cámara y en total
6. Con 2 cámaras durante 1h, el FPS no baja del 80% del valor mono-cámara o la degradación queda documentada

## Sub-tareas

- [x] **36-01** — `CameraRepo` CRUD (`list/create/update/delete`) +
  `CameraManager.remove()`. Base de datos y gestor en memoria listos para
  que 36-03 los use; sin endpoints todavía. `CameraManager.remove()` solo
  hace `pop()`+`pipeline.stop()` — quien lo llame es responsable de borrar
  también el catálogo (`CameraRepo.delete()`), simetría deliberada con
  `add()` que tampoco toca la BD. Tests: 8 nuevos en `test_repositories.py`
  (CRUD completo, sobre los 3 ya existentes de `default_camera_id`) y 3
  nuevos en `test_manager.py` (con pipelines falsas — el patrón ya
  establecido del fichero evita construir `CameraPipeline` real para no
  levantar `CaptureWorker`/RTSP). 18 tests dirigidos verdes; no toca
  `main.py`/wiring, sin relanzar la suite completa.
- [x] **36-02** — Factoría `backend/pipeline/factory.py::build_camera_pipeline()`
  que extrae de `main.py` la construcción completa de una `CameraPipeline`
  (detector, tracker propios por cámara; `recording_config` con
  `on_clip_ready`/`on_failure` ligados al `camera_id` real) detrás de un
  `SharedPipelineServices` (recognizer, recording_repo, event_bus,
  latency_tracker, active_classes, is_intrusion, on_identified, broadcast,
  loop — los servicios que SÍ se comparten entre cámaras). `main.py` pasa a
  consumir la factoría para "cam1"; el refactor es deliberadamente
  comportamiento-preservado para el caso mono-cámara, verificado por la
  suite completa sin ningún fallo.

  De paso, el research había detectado (no una suposición: leído línea a
  línea) que el propio arranque de "cam1" ya tenía **tres bugs latentes**
  que habrían roto una segunda cámara real aunque la Fase 36 añadiera CRUD y
  UI perfectos por encima — corregidos aquí, antes de construir nada nuevo
  encima:
  - `EventEngine` pasaba de ser un único objeto global con `camera_id="cam1"`
    fijo (`main.py:425`, usado por CUALQUIER pipeline) a uno **por cámara**,
    creado dentro de la factoría con el `camera_id` real — sin esto, todos
    los eventos de detección/comportamiento de una segunda cámara se habrían
    persistido con `camera_id="cam1"`.
  - `_on_clip_ready` escribía `camera_id="cam1"` literal al persistir
    grabaciones (`main.py:509` original) — ahora lo cierra la factoría sobre
    el `camera_id` real de cada pipeline.
  - `_recorder_hook` (dispara clips desde una regla) usaba siempre la
    variable `pipeline` de la primera cámara (`main.py:719-728` original) —
    ahora resuelve `camera_manager.get(event.camera_id)`.
  - Bug relacionado, mismo origen: `UploadQueue.on_permanent_failure`
    (`backend/gdrive.py`) solo recibía `(rec_id, message)`, así que
    `_on_upload_failed` en `main.py` hardcodeaba `camera_id="cam1"` en el
    evento `UPLOAD_FAILED` — `UploadQueue._process()` ya tenía la fila
    `rec` completa (con su `camera_id` real) y simplemente no la pasaba;
    ahora el callback recibe `(rec_id, camera_id, message)`. 2 tests nuevos
    en `test_upload_queue.py` (uno confirma el camino feliz con "cam1",
    otro fuerza una grabación de "cam2" y comprueba que el evento reporta
    "cam2", no "cam1").

  Alcance deliberadamente NO tocado (documentado, no un hueco): el watchdog
  de `camera_offline`/`camera_recovered` (`main.py` línea ~284) y los
  endpoints v1 (`/video_feed`, `/api/enroll_face`, heatmap, zonas v1...)
  siguen atados a `rtsp_stream` = la cámara primaria — mismo patrón ya
  establecido en la Fase 34 para los endpoints v1 que la UI real todavía usa
  (deliberadamente mono-cámara, fuera del alcance de "multi-cámara en la
  UI v2" que pide esta fase).

  Suite completa: **801 passed, 2 skipped, 4m20s** (+1 sobre el cierre de
  36-01: 8+3 de 36-01, +1 de los 2 tests nuevos de upload_queue que sustituye
  al test existente modificado). Playwright completo: **11 passed, 24.4s**
  (con un warning preexistente de `ValueError: Out of range float... inf` en
  el log del servidor de tests, verificado con `git stash` que ya aparecía
  ANTES de este cambio — no es una regresión, no se ha tocado).
- [x] **36-03** — Endpoints `POST/PUT/DELETE /api/v2/cameras` +
  `GET /api/v2/cameras/catalog` en `backend/api/v2/cameras.py`. De paso,
  `backend/pipeline/factory.py` gana `start_camera_pipeline()` (construir +
  `.start()` + cargar zonas/líneas persistidas — la secuencia completa que
  antes solo vivía inline en `main.py`), que ahora usan **tanto** el
  arranque de "cam1" en `main.py` **como** el endpoint de creación — un solo
  sitio que sabe arrancar una cámara de producción de principio a fin, para
  que 36-04 (arranque de N cámaras) no tenga que reinventar la secuencia.

  - `POST` — 409 si el id ya existe (`CameraRepo.get()` primero); si
    `enabled`, arranca la pipeline en caliente antes de responder.
    `CameraIn` valida `rtsp_url` con `rtsp://` obligatorio (mismo criterio
    que el resto de validación v2, `ZoneIn`/`LineIn` como referencia).
  - `PUT` — solo reinicia la pipeline (`camera_manager.remove()` +
    `start_camera_pipeline()`) si el cambio afecta a algo que la pipeline
    necesita reconstruir (`rtsp_url`/`process_w`/`process_h`/`enabled`);
    renombrar una cámara en marcha NO la reinicia — el nombre es un
    atributo de catálogo, nunca se pasa a `CameraPipeline`.
  - `DELETE` — para la pipeline (no-op si no corría) + borra la fila.
  - `GET /catalog` (nuevo, no en el research original — necesario para que
    36-08 pueda listar TODAS las cámaras del catálogo, incluidas las
    deshabilitadas/paradas, ya que `GET ""` solo lista pipelines VIVAS).
    `rtsp_url` siempre enmascarada en toda respuesta saliente
    (`mask_rtsp_url`, mismo criterio que `config.py` de la Fase 32) — nunca
    se devuelven credenciales RTSP en claro por la API.

  20 tests dirigidos verdes (13 nuevos) en `test_cameras_api.py`, con
  `CameraRepo`/`CameraManager` sustituidos por dobles de prueba (mismo
  patrón que `test_zones_api.py`) — sin tocar una base de datos real.
  Suite completa: **814 passed, 2 skipped, 4m12s** (+13 sobre 36-02).
  Playwright completo: **11 passed, 21.2s** (mismo warning preexistente de
  `inf`, sin regresión).
- [x] **36-04** — Arranque dinámico desde la tabla `cameras`. Hallazgo real
  (no una suposición): la migración v1→v2 (`backend/storage/migrations.py:134`)
  YA siembra la fila `cam1` en cada arranque desde hace fases — no hizo
  falta añadir esa siembra, solo consumirla. `main.py` gana
  `_start_configured_cameras()`: recorre `CameraRepo.list(enabled=True)` y
  llama `start_camera_pipeline()` (36-03) por cada fila, en vez del único
  `camera_manager.add("cam1", ...)` de antes.

  Decisiones de compatibilidad, documentadas porque no eran obvias:
  - `cam1` es la ÚNICA cámara cuyo `rtsp_url_ref` puede venir NULL en el
    catálogo (la migración nunca lo escribe) — cuando es así, cae a
    `build_rtsp_url(settings)` (`CAMERA_URL`/`RTSP_USER`/`RTSP_PASS`), igual
    que siempre. Cualquier OTRA cámara sin `rtsp_url` propia se omite con
    un `logger.warning` (no hay otro sitio de donde sacar su URL) — no
    rompe el arranque de las demás.
  - El tamaño de proceso (`process_w`/`process_h`) por cámara cae al
    `process_size` global (`settings.process_width/height`) salvo que la
    fila del catálogo tenga el suyo propio — ninguna cámara existente
    pierde su configuración por defecto al pasar por este camino.
  - La fachada `rtsp_stream` (v1, deliberadamente mono-cámara) sigue
    apuntando a "cam1" si existe; si el operador la borró desde la UI, cae
    a la primera cámara que arrancó con éxito — nunca se queda sin fachada
    mientras haya al menos una cámara viva.

  5 tests nuevos en `tests/test_stream.py` (arranque de N cámaras, cámara
  sin `rtsp_url` omitida sin tumbar el arranque, catálogo vacío → `None`,
  fallback de primaria sin "cam1", reparto de `process_size` por cámara).
  Un fallo real de edición detectado y corregido antes de comitear: un
  `old_string` corto en un fichero de tests denso hizo que `Edit`
  empalmara mis tests nuevos ENCIMA de la última aserción de un test ya
  existente (`TEST_tracks_broadcast_loop_sends_normalized_payload`),
  dejándola huérfana — verificado con `git diff | grep '^-'` (debía no
  mostrar nada, ya que el cambio es puramente aditivo) antes de dar la
  sub-tarea por cerrada, y corregido restaurando la aserción en su sitio.

  Suite completa: **819 passed, 2 skipped, 4m14s** (+5 sobre 36-03).
  Playwright completo: **11 passed, 21.1s** (servidor real arrancando por
  el camino nuevo, sin regresión).
- [x] **36-05** — Coste de CPU estimado por cámara. `CameraPipeline.
  estimated_cpu_pct` (nueva `@property`, `backend/pipeline/manager.py`):
  `fps_efectivo × latencia_media` de detección + reconocimiento, como
  fracción de UN core — documentado explícitamente como estimación, no
  medición real del sistema operativo (no hay instrumentación de SO en
  este proyecto). `behavior`/`objects` corren dentro del bucle de
  detección, así que su coste ya está incluido en la latencia medida de
  `detection`, no se contabilizan aparte. Nuevo campo de configuración
  `Settings.cpu_budget_warn_pct` (default 200.0 — "hasta 2 cores llenos"),
  registrado también en `config_schema.py` (`applies="hot"`, sin reinicio)
  porque `TEST_config_schema_covers_every_settings_field` así lo exige.
  `GET /api/v2/cameras` gana `estimated_cpu_pct` por cámara y, a nivel de
  respuesta, `total_estimated_cpu_pct`/`cpu_budget_warn_pct`/`over_budget`
  — todo lo que 36-08 necesita para pintar un aviso sin cálculos en
  cliente (D-02, mismo criterio que el resto del proyecto: agregaciones en
  servidor).

  9 tests nuevos (3 en `test_manager.py` sobre `estimated_cpu_pct`, 2 en
  `test_cameras_api.py` sobre el agregado/umbral, 4 indirectos vía
  `test_config_schema.py`/`test_config_api.py` que ya cubrían el nuevo
  campo por construcción). Suite completa: **824 passed, 2 skipped, 4m8s**
  (+5 sobre 36-04). Playwright: **11 passed, 23.0s**.
- [x] **36-06** — Presupuesto de FPS compartido. `AdaptiveRate` gana
  `set_external_cap()`/`min_fps` (`backend/pipeline/rate.py`): un techo
  impuesto desde fuera de la propia histeresis de latencia, que clampa
  `effective_fps` sin tocar el escalón interno (`_idx`) — quitar el techo
  restaura exactamente el ritmo que la latencia real habría elegido, sin
  recalcular nada. `DetectionWorker` expone ese `AdaptiveRate` por una
  nueva `@property rate` (antes privado, `_rate`). `CameraManager.
  rebalance_fps(budget_pct)` (nuevo) suma `estimated_cpu_pct` (36-05) de
  todas las cámaras y, si supera el presupuesto, impone un techo
  proporcional en el `AdaptiveRate` de DETECCIÓN de cada una (nunca por
  debajo de su `min_fps`); si vuelve a estar por debajo, libera el techo.

  Decisión deliberada: **no** toca `recognition` — su `AdaptiveRate` tiene
  `min_fps == max_fps` (un único escalón fijo por diseño, Fase 24), así que
  imponerle un techo lo dejaría mudo en vez de más lento; solo `detection`
  tiene margen real para bajar sin perder la funcionalidad.

  `main.py` gana `_cpu_rebalance_loop()` (cada 10s, mismo patrón que
  `_housekeeping_loop`), enganchado al lifespan junto al resto de tareas
  periódicas.

  16 tests nuevos (5 en `test_adaptive_rate.py` sobre el techo externo, 7
  en `test_manager.py` sobre `rebalance_fps`, 2 en `test_stream.py` sobre
  el wiring del loop). Suite completa: **836 passed, 2 skipped, 4m14s**
  (+12 sobre 36-05 — 4 de los 16 ya estaban cubiertos por rutas
  existentes). Un fallo real detectado y descartado como no-regresión:
  `TEST_multiclass_latency_under_15_percent` (marcado `@pytest.mark.perf`,
  inferencia YOLO real con márgenes estrechos, documentado así en
  `pytest.ini`) falló en la corrida completa pero pasó en aislamiento —
  contención de CPU de la máquina tras ~4 min de suite, no algo que este
  cambio toque (no roza `detector.py`). Playwright completo: **11 passed,
  20.9s**.
- [x] **36-07** — Frontend: selector de cámara + vista mosaico.

  **Backend**: `/video_feed` acepta `?camera_id=` opcional (`backend/main.py`) —
  sin él, la fachada v1 de siempre (cámara primaria, tolerante: sin pipeline
  activo, 200 con stream vacío en vez de error, igual que antes); con él,
  resuelve vía `camera_manager.get(camera_id)` para el selector/mosaico — una
  cámara desconocida también da stream vacío, nunca 404 (es un `<img>`, no
  una API JSON). `mjpeg_generator()` pasa a recibir la pipeline como
  parámetro explícito en vez de leer el global `rtsp_stream` internamente.

  **Frontend**: `components/activeCamera.js` (nuevo, ~22 líneas) es el único
  estado compartido de "qué cámara está activa" — import por módulo, nunca
  `window`/`localStorage` (es estado de la pestaña, no configuración
  persistente). `views/camera-mosaic.js` (nuevo) pinta un grid de teselas de
  solo lectura (`GET /api/v2/cameras` + `/video_feed?camera_id=X` por
  tesela), alterna con `#camera-single-left`/`#camera-single-right` vía
  `#mosaic-toggle`, y clicar una tesela selecciona esa cámara sin salir del
  mosaico. `camera.js` gana el selector (`#camera-select`, poblado desde el
  mismo `GET /api/v2/cameras` que ya usaba `loadRtspCard()` en su tick de 5s
  — sin fetch duplicado), el aviso de CPU (`#camera-cpu-warning`,
  reutilizando `total_estimated_cpu_pct`/`over_budget` de 36-05) y sale de
  cualquier modo de edición en curso al cambiar de cámara (un trazado a
  medias no debe quedar atribuido a la cámara equivocada). El botón
  "Reintentar conexión", que vivía como `onclick=` inline en `index.html`,
  se movió a un listener real en `camera.js` (ya no podía preservar
  `camera_id` desde un atributo inline).

  **zoneEditor.js/lineEditor.js se vuelven conscientes de la cámara activa**
  (`camera_id: getActiveCameraId()` en el POST, filtro `?camera_id=` en el
  GET) — sin esto, cualquier zona/línea creada habría seguido cayendo
  siempre en `"cam1"` pase lo que pase en el selector, pese a que el backend
  (Fase 33/35) ya soportaba `camera_id` de punta a punta. `zoneEditor.js`
  estaba EXACTAMENTE en el límite de 300 líneas — se compensó comprimiendo
  la cabecera y retirando el flag `_zonesLoaded`/`_linesLoaded` (recargar la
  lista al entrar en modo edición siempre, no solo la primera vez, es más
  correcto Y más corto: una lista de zonas/líneas es barata de repetir).
  `rules-form.js` **no se tocó**: ya tenía `_renderCameraField` (Fase 33) con
  el wildcard `"*"` como valor por defecto — el criterio 3 ("reglas admiten
  camera \*") ya estaba resuelto, un hallazgo real del research, no una
  decisión de esta sub-tarea.

  `LOCKED_JS` gana `components/activeCamera.js` y `views/camera-mosaic.js`.

  **Verificación manual con servidor y navegador reales** (no solo suite
  automatizada): selector y botón de mosaico se renderizan correctamente en
  `#view-camara`; alternar "Vista mosaico" oculta/muestra
  `#camera-single-left`/`#camera-single-right` sin errores de JavaScript
  (confirmado con `read_console_messages`, ida y vuelta). **Hallazgo real,
  no introducido por esta fase** (confirmado con `git stash` que ya existía
  antes de tocar nada): `GET /api/v2/cameras`/`GET /api/v2/cameras/{id}/health`
  devuelven 500 cuando una cámara nunca ha capturado un frame (RTSP
  inalcanzable, el caso real de esta máquina de desarrollo sin cámara
  conectada) — `backend/pipeline/capture.py:111` usa `float("inf")` como
  centinela de "sin frame", que el JSON estricto de Starlette
  (`allow_nan=False`) rechaza. Esto vació el selector/mosaico en la
  verificación manual (sin datos que pintar) pero no crasheó la página — el
  código nuevo degrada con gracia (mismo criterio que el `try/catch` de
  `loadRtspCard()` ya establecido en la Fase 32). Deliberadamente NO
  arreglado aquí (toca `capture.py`, invariantes críticas del proyecto, sin
  relación con SCALE-05..08) — reportado aparte con `spawn_task`
  (`task_27f60468`) para una sesión propia.

  Suite completa: **840 passed, 2 skipped, 4m9s** (+4 sobre 36-06, incluido
  el flaky de 36-06 ya en verde). Playwright: **11 passed, 20.8s**.
- [x] **36-08** — Frontend: CRUD de cámaras en Ajustes
  (`frontend/js/views/cameras-crud.js`, nuevo), consumidor de 36-03.
  "Cámaras" es una pestaña **estática** en el árbol de `settings.js`, fuera
  de `_schema.sections` (`GET /api/v2/config`) — no es un editor de campos
  de Settings, es alta/baja/edición de entidades, mismo espíritu que
  `zoneEditor.js`/`rules-editor.js` en la pestaña Cámara. Reutiliza el
  estilo visual de `settings-section.js` (fieldset/legend, `filter-input`/
  `filter-chip`) para no introducir un patrón nuevo. Lista todas las
  cámaras del catálogo (`GET /api/v2/cameras/catalog`, 36-03 — incluye
  deshabilitadas, a diferencia de `GET ""` que solo lista pipelines vivas),
  con botones Habilitar/Deshabilitar (`PUT`) y Eliminar (`DELETE`,
  confirmación nativa) por fila, y un formulario para dar de alta una
  cámara nueva (id/nombre/URL RTSP).

  **Verificación manual de extremo a extremo con servidor y navegador
  reales** — no solo lectura de código: crear "cam-test" con una URL RTSP
  real (inalcanzable a propósito) → aparece en la lista con estado
  "en marcha" (la pipeline se arrancó de verdad, en caliente, sin reiniciar
  el servidor — el criterio 1 de la fase comprobado en vivo, no solo en
  test) → Eliminar → confirmado por `DELETE /api/v2/cameras/cam-test` (200)
  → la fila desaparece y el catálogo vuelve a mostrar solo "cam1". Un
  contratiempo de la propia sesión de verificación, no del código: la
  pestaña del navegador reutilizada entre sub-tareas se quedó con una
  versión cacheada de `settings.js` de antes de este cambio (ni
  `location.reload()` ni `navigate()` la invalidaron) — diagnosticado
  reimportando el módulo con un parámetro que rompe caché
  (`import('/static/js/views/settings.js?bust=...')`) y comprobando que la
  versión fresca sí pintaba las 9 pestañas correctamente, confirmando que
  el código estaba bien y el problema era de la sesión de navegador, no del
  cambio.

  `LOCKED_JS` gana `views/cameras-crud.js`. Suite dirigida
  (`test_frontend_modules.py`, 9 passed); cambio solo de frontend, sin
  relanzar la suite completa (mismo criterio que el resto de sub-tareas de
  frontend de fases anteriores).
- [x] **36-09** — Analítica por cámara y total. `AnalyticsRepo` (`hourly`,
  `summary`, `occupancy`, `persons_ranking`) acepta `camera_id: str | None`
  — `None` omite el filtro `WHERE camera_id = :cam` (helper `_camera_clause()`
  nuevo) y agrega TODAS las cámaras. Decisión documentada en
  `persons_ranking()`: el `INDEXED BY idx_events_analytics` (obligatorio,
  26,7ms vs 212,6ms @100k) solo se aplica con `camera_id` concreto — forzar
  un índice que empieza por `camera_id` sin filtrarlo no aporta nada con
  "todas las cámaras", así que se omite en ese caso (sin medir esa ruta:
  no hay presupuesto de rendimiento para el agregado total en el ROADMAP).

  `analytics.py`: `camera_id="*"` (mismo comodín que usan las reglas desde
  la Fase 33) pide el total — interceptado por `_resolve_analytics_camera_id()`
  ANTES de `resolve_camera_id()` (Fase 35), así que con 2+ cámaras dejar de
  especificar una sigue dando 400 (ambiguo) pero pedir `"*"` explícitamente
  nunca lo hace. Aplicado a `/hourly`, `/summary`, `/occupancy`, `/persons`
  y `/export`; **`/heatmap`/`/heatmap/scale` deliberadamente sin tocar** —
  un mapa de calor es la máscara acumulada de UNA cámara, "todas" no tiene
  sentido ahí.

  `analytics.js` gana un selector `#an-camera-filter` (default `"*"`,
  poblado con `GET /api/v2/cameras`) que sustituye los tres `camera_id=cam1`
  literales que arrastraba desde la Fase 31. El heatmap, que no admite
  comodín, omite el parámetro cuando el filtro es `"*"` (cae al default del
  servidor) en vez de forzar `cam1`.

  9 tests nuevos en `test_repositories.py` (4, `camera_id=None` por
  método) y `test_analytics_api.py` (4 de endpoint + el de ambigüedad ya
  existente verificado que sigue en 400). Suite completa: **849 passed, 2
  skipped, 4m13s** (+9 sobre 36-07 — 36-08 no tocó nada de Python).
  Playwright: **10 passed, 1 fallo preexistente** (`camera-offline.spec.js`,
  ver nota abajo) — el resto sin regresión.

  **Hallazgo real, no introducido por esta fase**: durante la verificación
  de esta sub-tarea, `camera-offline.spec.js` empezó a fallar
  ("Sin señal" esperado, "Conectado" recibido). Antes de asumir una
  regresión propia, se verificó con `git stash` (revirtiendo TODOS los
  cambios de la Fase 36, no solo los de esta sub-tarea) que el mismo test
  falla igual sobre el código de antes de esta sesión — confirmado con
  `playwright.config.js` en `reuseExistingServer: false` (cada ejecución
  arranca un servidor fresco, no hay contaminación entre corridas).
  Reportado aparte con `spawn_task` (`task_b41aa1cf`) en vez de arreglado
  aquí — toca `backend/pipeline/capture.py`, fuera del alcance de SCALE-05.
- [ ] **36-10** — Puerta de fase: test de carga corto + extrapolación
  (criterio 6), trazabilidad de los 6 criterios y SCALE-05..08, suite
  completa final.

## Nota sobre tooling GSD

Mismo criterio que las Fases 34/35: `gsd-sdk` no disponible en esta sesión.
Este único fichero hace de plan y de bitácora por sub-tarea (cada casilla
se documenta con hallazgos/decisiones/resultado de tests al cerrarla), sin
la ceremonia completa de PLAN.md/SUMMARY.md por sub-tarea de otras fases.
