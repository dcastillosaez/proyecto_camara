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

- [ ] **36-01** — `CameraRepo` CRUD (`list/create/update/delete`) +
  `CameraManager.remove()`. Base de datos y gestor en memoria listos para
  que 36-03 los use; sin endpoints todavía. Tests en `test_repositories.py`
  y `test_stream.py`.
- [ ] **36-02** — Factoría `backend/pipeline/factory.py::build_camera_pipeline()`
  que extrae la construcción de una `CameraPipeline` completa (detector,
  tracker, recording_config con `on_clip_ready` ligado al `camera_id` real,
  identity/reid si aplica) de `main.py`, reutilizable para N cámaras.
  Refactor de `main.py` para consumir la factoría en el arranque — sin
  cambio de comportamiento observable, verificado por la suite completa.
  Corrige los tres bugs de "cam1" hardcodeado (`_on_clip_ready`,
  `_on_upload_failed`, `_recorder_hook` resuelto por `event.camera_id` vía
  `camera_manager.get(...)`).
- [ ] **36-03** — Endpoints `POST/PUT/DELETE /api/v2/cameras` en
  `backend/api/v2/cameras.py`: crear arranca la pipeline en caliente
  (factoría de 36-02 + `camera_manager.add()` + `pipeline.start()`, zonas/
  líneas vacías por defecto), editar permite renombrar/activar-desactivar/
  cambiar URL (reconstruye la pipeline si cambia la URL), borrar para +
  quita del `CameraManager` + borra la fila. Tests en `test_cameras_api.py`.
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
