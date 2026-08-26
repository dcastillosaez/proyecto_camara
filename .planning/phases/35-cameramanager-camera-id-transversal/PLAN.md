# Fase 35 — CameraManager y camera_id transversal

Plan redactado a mano (sin `gsd-sdk`, mismo criterio que la Fase 34 — no
disponible en esta sesión). Research previo hecho con un agente Explore
(auditoría completa de esquema/hardcodes/endpoints/repos/tests, ver hallazgos
resumidos en cada sub-tarea).

**Depends on**: Fase 34 (completa, PR #18 mergeado)
**Requirements**: SCALE-01..SCALE-04 (`.planning/REQUIREMENTS.md:285-288`)
**Spec**: `propuesta_mejora/SPEC_v2.md:976` (ficheros: `backend/pipeline/manager.py`,
`backend/storage/migrations.py`, `backend/api/v2/cameras.py`)

## Punto de partida (hallazgos del research, no asunciones)

`CameraPipeline`/`CameraManager` (`backend/pipeline/manager.py`) YA existen,
diseñadas desde el principio para N cámaras (`.add()`/`.get()`/`.all()`/
`.start_all()`/`.stop_all()`) — nadie las instancia con más de una cámara
todavía, ni hay un test que lo pruebe. El esquema YA tiene `camera_id NOT
NULL` en `events`, `tracks`, `detection_stats`, `recordings`, `zones` y
`lines` (con `server_default='cam1'` en las tres últimas) — el único hueco
real es `system_metrics.camera_id` (`nullable=True`), y esa tabla **no tiene
ni un solo escritor en todo `backend/`** (ni `MetricsSampler`, que solo
alimenta gauges de Prometheus en memoria) — schema vestigial, sin datos que
migrar en la práctica. Los endpoints v2 que ya aceptan `camera_id` de verdad
(`zones.py`, `lines.py`, `events.py`, `recordings.py`) están limpios; los que
lo aceptan pero con default literal `"cam1"` (`context.py`, `analytics.py` ×7)
son el hueco real del criterio 3. `config.py`, `rules.py`, `metrics.py` y
`detection.py` son deliberadamente globales/multi-cámara-por-diseño (aplican
a todas las cámaras a la vez o no tienen dimensión de cámara) — no es scope
de esta fase forzarles un parámetro que no necesitan.

## Criterios de éxito (ROADMAP.md:687-692)

1. CameraPipeline encapsula el pipeline de una cámara y CameraManager gestiona N con arranque/parada independientes
2. camera_id es NOT NULL en events, tracks, detection_stats, recordings, zones, lines y system_metrics
3. Todos los endpoints v2 aceptan camera_id con default a la única cámara existente
4. Dos pipelines contra la misma URL RTSP producen eventos con camera_id distintos
5. Parar una cámara no afecta a la otra ni al servidor
6. Regresión cero en un despliegue de una sola cámara

## Sub-tareas

- [x] **35-01** — Migración v5→v6 (criterio 2): `system_metrics.camera_id` NOT
  NULL. `backend/storage/models.py` pasa a `nullable=False, server_default="cam1"`
  (mismo patrón que `Recording`/`Zone`/`Line`); `_migrate_v5_to_v6` en
  `backend/storage/migrations.py` reconstruye la tabla (SQLite no soporta
  `ALTER COLUMN ... SET NOT NULL`, patrón estándar de crear-copiar-renombrar) con
  backfill defensivo a `'cam1'` antes de copiar — defensivo, no correctivo:
  `system_metrics` no tiene ni un solo escritor en todo `backend/`
  (`MetricsSampler` solo alimenta gauges de Prometheus en memoria), así que no
  hay filas `NULL` reales que migrar hoy, pero la tabla no puede dejar pasar las
  que pudiera haber de una edición manual. `SCHEMA_VERSION` 5→6. 5 tests nuevos en
  `tests/test_migrations.py` (backfill, `NOT NULL` real a nivel SQL vía
  `pytest.raises`, preservación de filas/JSON, idempotencia, tabla ausente no
  rompe la cadena). Suite completa: **774 passed, 2 skipped, 3m48s** (+5 sobre el
  cierre de la Fase 34).
- [x] **35-02** — Resolución dinámica del `camera_id` por defecto (criterio 3).
  `CameraRepo.default_camera_id()` nuevo en `backend/storage/repositories.py`:
  resuelve contra la tabla `cameras` (catálogo persistido), no contra el
  `CameraManager` en memoria — decisión tomada tras romper 26 tests existentes
  con la primera versión (basada en `camera_manager`): varios tests de
  `analytics.py` resetean `_camera_manager` a `None` a propósito (`autouse`)
  porque prueban matemática de buckets/formato CSV sin pipeline real, pero SÍ
  siembran una fila `Camera(id="cam1")` en la base — la tabla es la fuente de
  verdad correcta para "qué cámaras existen", el `CameraManager` solo para "qué
  pipelines están vivos ahora mismo", y estos endpoints consultan histórico en
  BD, no estado de pipeline. `resolve_camera_id()` (nuevo, `backend/api/v2/deps.py`,
  async) devuelve el `camera_id` del cliente tal cual si lo mandó; si no, resuelve
  contra `CameraRepo` SOLO cuando hay exactamente una cámara registrada — con 0 o
  ≥2, `HTTPException(400)` en vez de adivinar. Sustituye los 8 defaults
  `Query(default="cam1")` de `context.py` (1) y `analytics.py` (7) por
  `Query(default=None)` + `camera_id = await resolve_camera_id(camera_id,
  get_session_factory())`. 6 tests nuevos: 3 de `CameraRepo.default_camera_id()`
  (1/0/2 cámaras) en `tests/test_repositories.py`, 2 de extremo a extremo en
  `tests/test_scene_context.py` (default con 1 cámara, 400 con 2) y 1 en
  `tests/test_analytics_api.py` (mismo 400, otro router). Suite completa:
  **780 passed, 2 skipped, 3m52s** (+6 sobre 35-01).
- [x] **35-03** — `/api/v2/cameras` y `/api/v2/cameras/{camera_id}/health`
  extraídos de `backend/main.py` a `backend/api/v2/cameras.py` (router propio +
  `configure(camera_manager)` desde el lifespan, mismo patrón que el resto de
  `backend/api/v2/`, en vez de vivir embebidos en `main.py` con el
  `v2_limiter`/`V2_RATE_LIMIT` importados ahí solo para esto). De paso,
  `dataclasses.asdict` y el alias `v2_limiter`/`V2_RATE_LIMIT` quedaron sin
  ningún otro uso en `main.py` tras la extracción — imports retirados en vez de
  dejarlos muertos. Hallazgo real: **ningún test de Python cubría estos dos
  endpoints hasta ahora** (`tests/e2e/camera-offline.spec.js` de Playwright era
  la única cobertura, y solo de forma indirecta) — coincide con lo que ya había
  detectado el research previo a la fase. `tests/test_cameras_api.py` nuevo (7
  tests): 503 sin pipeline activo, listado con N cámaras (con dos, no solo una),
  listado vacío con pipeline activo, 404 por cámara desconocida, `capture_fps`
  vs `detection_fps` deliberadamente distintos, y forma completa de la
  respuesta de salud. Suite completa: **787 passed, 2 skipped, 3m52s** (+7 sobre
  35-02). Verificado también `tests/e2e/camera-offline.spec.js` (Playwright)
  sin regresión tras la extracción.
- [x] **35-04** — `tests/integration/test_multi_camera.py` (criterios 1, 4, 5):
  dos `CameraPipeline` reales gestionados por UN `CameraManager` real (mismo
  cableado que `backend/main.py:lifespan` — `CameraManager()` + 2×`.add()`),
  contra la MISMA URL RTSP falsa (`mock_video_capture` no distingue por URL) y
  con detectores mock independientes, exactamente el escenario que pedía el
  criterio 4. Dos `EventEngine` (uno por `camera_id`) comparten un único
  `EventBus`, igual que en producción sería un único bus para N cámaras.
  - `TEST_two_pipelines_same_rtsp_url_produce_distinct_camera_ids`: los
    `PERSON_ENTERED` de cada pipeline llegan con su `camera_id` propio y quedan
    persistidos correctamente separados en `EventRepo.query(camera_id=...)`
    (cierra también el hueco de cobertura del criterio 1: hasta ahora ningún
    test instanciaba `CameraManager` con más de una cámara).
  - `TEST_stopping_one_camera_does_not_affect_the_other`: parar `cam1`
    (`pipeline.stop()`) no lanza excepción, `cam2` sigue procesando frames
    (su detector mock sigue recibiendo llamadas) y `cam1` deja de verdad de
    procesar (su contador de llamadas se congela) — el propio `CameraManager`
    sigue operable después.

  Suite completa: **789 passed, 2 skipped, 4m10s** (+2 sobre 35-03, dentro del
  presupuesto de 5 min de TEST-03 pero con menos margen: cada pipeline real
  añade un par de hilos CaptureWorker/DetectionWorker — a vigilar si futuras
  fases añaden más tests de este tipo). Extendido en 35-05 para cubrir también
  el reinicio (SCALE-04 pide "parar O reiniciar", no solo parar).

- [x] **35-05** — Puerta de fase: regresión cero + trazabilidad de los 6 criterios.

  Antes de cerrar, `TEST_stopping_one_camera_does_not_affect_the_other` de
  35-04 se extendió y renombró a
  `TEST_stopping_and_restarting_one_camera_does_not_affect_the_other`: llama
  `cam1_pipeline.start()` tras el `stop()` y comprueba que reanuda
  (`detectors["cam1"].calls` vuelve a subir) sin que `cam2` se haya visto
  afectada en ningún momento — cierra la mitad "reiniciar" de SCALE-04, que el
  test original solo cubría a medias.

  | # | Criterio | Evidencia |
  |---|---|---|
  | 1 | CameraPipeline/CameraManager, N cámaras, arranque/parada independiente | Clases ya existían (`backend/pipeline/manager.py`); `tests/integration/test_multi_camera.py` es el primer test que las ejercita con N=2 reales |
  | 2 | `camera_id` NOT NULL en las 7 tablas | 6 ya lo tenían; `system_metrics` cerrado en 35-01 (migración v5→v6) |
  | 3 | Todos los endpoints v2 aceptan `camera_id` con default a la única cámara | 8 endpoints migrados de `"cam1"` literal a `CameraRepo.default_camera_id()` (35-02); `zones`/`lines`/`events`/`recordings`/`cameras` ya lo hacían bien; `config`/`rules`/`metrics`/`detection` excluidos deliberadamente (globales por diseño, ver "Punto de partida") |
  | 4 | Dos pipelines, misma URL RTSP, `camera_id` distintos | `TEST_two_pipelines_same_rtsp_url_produce_distinct_camera_ids` (35-04) |
  | 5 | Parar una cámara no afecta a la otra ni al servidor | `TEST_stopping_and_restarting_one_camera_does_not_affect_the_other` (35-04, extendido en 35-05) |
  | 6 | Regresión cero en despliegue de una sola cámara | Suite pytest completa tras cada sub-tarea (774→780→787→789 passed, 2 skipped, siempre 0 fallos) + suite Playwright completa (11/11) verificada al cierre |

  **Sin checkpoint manual pendiente** (a diferencia de la Fase 34): esta fase es
  puramente backend/infraestructura, sin superficie visual nueva que revisar a
  ojo — el criterio 6 ya lo cubre la suite automatizada de extremo a extremo.

  Verificación final: suite pytest completa **789 passed, 2 skipped, 4m19s**
  (dentro del presupuesto de 5 min, con margen ajustado — ver nota de 35-04) y
  suite Playwright completa **11 passed, 24.4s**, ambas sin resetear nada entre
  medias. SCALE-01..04 cerrados en `.planning/REQUIREMENTS.md`; Fase 35 marcada
  completa en `.planning/ROADMAP.md`.

## Nota sobre tooling GSD

Mismo criterio que la Fase 34: `gsd-sdk` no disponible en esta sesión. Este
único fichero hace de plan y de bitácora, sin la ceremonia completa de
PLAN.md/SUMMARY.md por sub-tarea de otras fases.
