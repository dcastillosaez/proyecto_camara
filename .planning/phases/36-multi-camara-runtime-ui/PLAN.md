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
- [ ] **36-04** — Arranque dinámico desde la tabla `cameras`: `main.py` siembra
  `cam1` una sola vez desde `settings` si la tabla está vacía (migración
  desde variables de entorno, compatibilidad hacia atrás) y luego arranca
  TODAS las cámaras `enabled=True` de `CameraRepo.list()` con la factoría de
  36-02, en vez del único `camera_manager.add("cam1", ...)` de hoy.
- [ ] **36-05** — Coste de CPU estimado por cámara: `estimated_cpu_pct` en
  `pipeline.stats()`/`GET /api/v2/cameras` (proxy `detection_fps ×
  latencia_media`, documentado como estimación, no medición de SO), umbral
  configurable (`Settings.cpu_budget_warn_pct`) y flag `over_budget` en la
  respuesta agregada.
- [ ] **36-06** — Presupuesto de FPS compartido: `CameraManager` reparte el
  FPS objetivo de detección entre pipelines cuando el coste total estimado
  supera el presupuesto (reduce proporcionalmente, restaura al bajar).
- [ ] **36-07** — Frontend: selector de cámara + vista mosaico
  (`frontend/js/views/mosaic.js`), `/video_feed` acepta `?camera_id=`.
- [ ] **36-08** — Frontend: CRUD de cámaras en Ajustes
  (`frontend/js/views/cameras-crud.js`), consumidor de 36-03.
- [ ] **36-09** — Analítica por cámara y total: `AnalyticsRepo`/
  `analytics.py` con `camera_id=None` → agregación `GROUP BY camera_id` +
  total combinado; filtro de cámara en `analytics.js`.
- [ ] **36-10** — Puerta de fase: test de carga corto + extrapolación
  (criterio 6), trazabilidad de los 6 criterios y SCALE-05..08, suite
  completa final.

## Nota sobre tooling GSD

Mismo criterio que las Fases 34/35: `gsd-sdk` no disponible en esta sesión.
Este único fichero hace de plan y de bitácora por sub-tarea (cada casilla
se documenta con hallazgos/decisiones/resultado de tests al cerrarla), sin
la ceremonia completa de PLAN.md/SUMMARY.md por sub-tarea de otras fases.
