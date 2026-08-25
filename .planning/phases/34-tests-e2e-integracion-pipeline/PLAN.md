# Fase 34 — Tests E2E e integración del pipeline

Plan redactado a mano (sin `gsd-sdk`, no disponible en esta sesión — ver nota
al pie). Sigue el mismo criterio de fases anteriores: sub-tareas verificables,
una por commit.

**Depends on**: Fase 33 (completa, mergeada a `main`)
**Requirements**: TEST-01..TEST-05 (`.planning/REQUIREMENTS.md:277-281`)
**Spec**: `propuesta_mejora/SPEC_v2.md:968` (una línea: ficheros esperados)

## Criterios de éxito (ROADMAP.md:673-679)

1. Test de integración FakeRTSP → Detector mock → Tracker → EventEngine → RuleEngine → BD → WebSocket, ejecutable en CI sin cámara real
2. Playwright cubre los 10 escenarios de frontend (TEST-02)
3. La suite completa corre en menos de 5 minutos
4. GitHub Actions ejecuta unit + integración en cada push y E2E en cada PR
5. Cobertura > 80% en `backend/events/`, `backend/pipeline/` y `backend/perception/`
6. Los endpoints `/api/*` v1 quedan formalmente marcados como deprecados

## Sub-tareas

- [x] **34-01** — `tests/integration/test_pipeline_e2e.py`: FakeRTSP → detector mock →
  `PersonTracker` real → `EventEngine` → `EventBus` → `make_event_pipeline()` real
  (RuleEngine → INSERT SQLite → broadcast). Reutiliza `mock_video_capture` (ya existía
  en `tests/conftest.py`) y `make_event_pipeline()` (ya diseñado "para poder probar la
  secuencia sin levantar la app entera", Fase 30 D-14). Dos tests: camino feliz
  (PERSON_ENTERED persistido + regla disparada + broadcast) y control negativo (sin
  detecciones, cero eventos). 769 passed, 2 skipped, suite completa en 3m47s. Ver
  commit correspondiente.
- [x] **34-02** — Cobertura (TEST-05): `pytest-cov` en `requirements.txt`, `.coveragerc`
  con `source = backend/events, backend/pipeline, backend/perception` y
  `fail_under = 80`. Medido: events 90.8%, pipeline 89.7%, perception 94.3% (total
  91.18%) — los tres paquetes ya superaban el 80% sin cambios de producción; el hueco
  más bajo es `pipeline/manager.py` (69%, en su mayoría getters de la fachada de
  solo lectura ya cubiertos indirectamente vía los tests de API) pero no hacía falta
  tocarlo para cumplir el criterio a nivel de paquete. Nuevo marker `perf` (registrado
  en `pytest.ini`) en `TEST_multiclass_latency_under_15_percent`
  (`tests/test_detector.py`): bajo instrumentación de `coverage.py` ese test pasó de
  130ms/51ms de subida real medida (>15%, falla) frente a los ~4,7% documentados sin
  cobertura — el trazado línea a línea de coverage.py infla desproporcionadamente las
  rutas con mucho glue Python (post-proceso de YOLO) y colaba una regresión falsa; los
  demás tests de latencia (`test_identity_index.py`, `test_reid_engine.py`,
  `test_repositories.py`, con presupuestos más laxos o rutas más nativas) pasaron bajo
  cobertura sin necesidad de marcarlos, así que se dejaron tal cual (sin marcar
  especulativamente lo que no falló). Nuevo step "Coverage gate" en
  `.github/workflows/tests.yml` (`pytest tests/ -q -m "not perf" --cov
  --cov-report=term-missing`, sin `continue-on-error`: si baja del 80% rompe el
  build). Ese step re-ejecuta la suite completa aparte del step de tests -- decision
  deliberada (34-03): fusionar ambos con --cov-append obligaria a excluir el test
  perf tambien del step de correctness (que si debe correr sin instrumentar), a
  cambio de ahorrar ~30s en un job que ya tarda minutos por la instalacion de
  dlib/face_recognition. Mas simple mantenerlos separados.
- [x] **34-03** — CI (TEST-04, mitad "push"): la separacion unit/integracion por
  directorio ya existia desde 34-01 (`tests/integration/` aparte de `tests/*.py`), asi
  que no hizo falta reestructurar nada ahi -- `pytest tests/` de `tests.yml` ya recorre
  ambos. El fallo real era `continue-on-error: true` en el step "Run tests": el job
  quedaba siempre en verde en GitHub Actions pasara lo que pasara, asi que cualquier
  regresion real en `main` no rompia el build ni bloqueaba un PR -- enmascaraba
  exactamente lo que TEST-04 pide que CI garantice. Retirado sin mas cambios; el step
  de "Coverage gate" (34-02) ya no llevaba `continue-on-error` tampoco. La mitad "E2E en
  cada PR" del criterio queda para 34-06, cuando exista el job de Playwright.
- [x] **34-04** — Playwright (TEST-02, 3/10 escenarios): `package.json` +
  `@playwright/test` (Chromium ya estaba instalado en la maquina, build 1234), config
  en `playwright.config.js` con `webServer` propio (uvicorn en el puerto 8011, no el
  8000 de desarrollo; `DB_PATH=data/e2e-events.db`, aislada de la base real del
  usuario y ya cubierta por `data/*.db` en `.gitignore`) y deteccion de interprete
  Python por plataforma (`.venv/Scripts/python.exe` en Windows vs `python` en la CI de
  Linux, sin venv). `CAMERA_URL` se deja en su valor por defecto (la Tapo real de la
  LAN del usuario, inalcanzable aqui y en CI): eso ES el escenario "camara offline",
  no hacia falta simularlo.
  - `tests/e2e/video-feed.spec.js` — el feed apunta a `/video_feed`, el overlay de
    tracks esta presente, sin errores de consola.
  - `tests/e2e/camera-offline.spec.js` — la tarjeta RTSP (semaforo de 3 estados,
    `camera.js:loadRtspCard`) cae a "Sin señal" con la camara inalcanzable.
  - `tests/e2e/ws-reconnect.spec.js` — el badge de eventos en vivo pasa de "Activo" a
    "Reconectando" y vuelve a "Activo" tras un corte simulado del WebSocket.

  Dos hallazgos reales durante la implementacion, no anticipados por el plan:
  1. `page.goto('/')` con el `waitUntil` por defecto (`'load'`) **nunca resuelve**:
     `backend/main.py:mjpeg_generator` no cierra la respuesta MJPEG cuando no hay
     frames (bucle `sleep(0.02)` infinito por diseño, para servir video en directo
     indefinidamente), asi que el navegador nunca dispara su evento `load` mientras
     `#video-feed`/`#camera-feed` sigan "cargando". Se necesita
     `waitUntil: 'domcontentloaded'` en todo `goto()` de esta app — centralizado en
     `tests/e2e/helpers.js:gotoHome()` para no repetirlo (y no olvidarlo) en los 7
     escenarios que faltan.
  2. `context.setOffline(true)` (el mecanismo "de libro" para simular una caida de
     red en Playwright) **no cierra un WebSocket ya establecido** — solo bloquea
     peticiones nuevas, probado empiricamente (el badge se quedaba en "Activo" 10s
     despues de forzar el corte). Sustituido por `page.routeWebSocket()` (Playwright
     >= 1.48, disponible en la 1.62.1 instalada), que intercepta la conexion real y
     permite cerrarla desde el lado del cliente para disparar el `onclose` real de
     `websocket.js` con su backoff real (1s → 30s).

  El bug preexistente de `GET /api/v2/cameras/cam1/health` (500 por division por
  cero en el calculo de FPS sin frames, confirmado ajeno a la Fase 30 en el
  checkpoint de la Fase 30 y de nuevo visible en los logs de este webServer) **no se
  tocó**: `loadRtspCard()` ya lo captura con su propio `catch` y cae a "Sin señal" de
  todos modos, asi que no bloqueaba el escenario que si es responsabilidad de esta
  fase. Sigue pendiente de un `/gsd:debug` propio, ajeno a TEST-01..06.

  3 specs, 3 passed, ~13s en total (dentro de sobra del presupuesto de 5 min,
  TEST-03).
- [x] **34-05** — Resto de escenarios Playwright (TEST-02, 10/10 completo):
  `live-event.spec.js` (evento nuevo), `timeline-filters.spec.js` (filtros),
  `clips.spec.js` (clips), `modal-dialog.spec.js` (modales, 2 tests: Escape y click en
  el fondo), `ptz.spec.js` (PTZ), `alerts.spec.js` (alertas), `zone-editor.spec.js`
  (editor de zonas). `tests/e2e/helpers.js` gana `routeWsProxy(page)`: envuelve
  `page.routeWebSocket` para inyectar mensajes `{"type":"event",...}` reales (formato
  exacto de `backend/main.py:_broadcast_event`) directamente al cliente sin pipeline
  real detras — reutilizado por `live-event`/`clips`/`ws-reconnect` (34-04).

  Un bug real de producción encontrado y corregido, no solo documentado: el listener
  que cierra `#clip-modal` al hacer click en el fondo vivía envuelto en
  `document.addEventListener('DOMContentLoaded', ...)` dentro de
  `frontend/js/components/eventCard.js` — con `type="module"` ese evento ya ha
  disparado para cuando el módulo se ejecuta, así que el listener **nunca llegaba a
  registrarse** y el click en el fondo no cerraba nada en producción real, solo
  Escape funcionaba. Confirmado con un probe manual (`page.on('console')` +
  `addEventListener` de diagnóstico) antes de tocar el código. Arreglado quitando el
  envoltorio — el listener de `#recordings-list` dos líneas arriba, sin envoltorio,
  ya probaba que el DOM está completo en ese punto. `tests/test_frontend_modules.py`
  verde tras el cambio (9 passed).

  Dos hallazgos de infraestructura de test, no de producción:
  1. `workers: 1` en `playwright.config.js` (antes `undefined`, varios workers en
     paralelo): los 11 specs comparten UN único `webServer` (un solo proceso uvicorn,
     una sola conexión SQLite), así que correrlos en paralelo generaba contención real
     entre tests — peticiones `GET /api/v2/events` fallando bajo carga concurrente,
     visto como `#timeline-empty` quedándose oculto porque el fetch entraba en el
     `catch` de `timeline.js`. No es solo una cuestión de velocidad: con un backend
     compartido y mutable, la ejecución en serie es la que da resultados correctos.
  2. Ninguna prueba puede asumir que la línea temporal/las alertas arrancan vacías:
     `backend/main.py:_camera_watchdog` (cada 10s) emite un `CAMERA_OFFLINE` real
     (severidad `CRITICAL`) en cuanto detecta que la cámara configurada es
     inalcanzable — exactamente la realidad de la base de e2e — y
     `GET /api/v2/alerts` cuenta por severidad, no solo eventos que casan alguna
     regla, así que también aparece ahí. `live-event`, `timeline-filters` y `alerts`
     se reescribieron para no depender de ese vacío (verifican la fila/el filtro/el
     foco concretos en vez de la ausencia total de contenido) — verificado corriendo
     la suite dos veces seguidas sin limpiar `data/e2e-events.db` entre medias. Un
     intento de añadir un `globalSetup` que borrara la base entre ejecuciones se
     descartó: chocaba con un lock EPERM de Windows persistente durante la propia
     ejecución de Playwright (no reproducible con `rm`/`Remove-Item` sueltos fuera de
     ese contexto) que ni reintentos con backoff resolvían, y en CI el problema no
     puede darse — cada job arranca de un checkout limpio sin `data/e2e-*.db`
     preexistente (gitignorado). No merecía la complejidad para un caso que solo pasa
     en desarrollo local repetido y que los tests ya toleran.

  11 specs, 11 passed, ~22-25s en total, verificado en dos ejecuciones consecutivas
  sin resetear la base entre medias (dentro de sobra del presupuesto de 5 min,
  TEST-03).
- [x] **34-06** — CI (TEST-04, mitad "PR"): job `e2e` nuevo en `tests.yml`, gateado con
  `if: github.event_name == 'pull_request'` — no corre en cada `push`, solo cuando hay
  PR abierto o se le añaden commits (`synchronize`, incluido por defecto en
  `pull_request:` sin lista explícita de tipos). Independiente del job `test`
  (sin `needs`): corren en paralelo, no hay razón para serializarlos. Instala Python
  (igual que `test`, el `webServer` de Playwright levanta el backend real) + Node 22 +
  `npm ci` + `npx playwright install --with-deps chromium` (solo Chromium, un único
  `project` en `playwright.config.js` — mismo criterio de CPU moderada que el resto
  del proyecto) y sube `playwright-report/` como artefacto siempre (`if: always()`),
  igual que el `report/index.html` del job `test`.

  Riesgo real identificado y no resuelto por no poder verificarse sin hacer push (el
  agente no empuja al remoto sin permiso explícito): `yolo26n.pt` no está trackeado en
  git (`git ls-files` vacío) y el `webServer` construye un `PersonDetector` real en el
  lifespan de `backend/main.py` al arrancar. `tests/research/STACK.md:97` documenta que
  `YOLO("yolo26n.pt")` de Ultralytics lo descarga solo si no existe localmente (mismo
  mecanismo por el que el fichero ya vive en este equipo), y `gh run view --log` sobre
  la última ejecución en verde del job `test` confirma que ese job **nunca** ha tocado
  un detector real hasta ahora (`real_detector` de `tests/test_detector.py` se salta
  siempre en el runner Linux, porque `_BUS_JPG` es una ruta absoluta de Windows) — el
  job `e2e` es el primer camino de CI que de verdad instancia YOLO26n, dependiendo de
  que Ultralytics pueda descargarlo (~5 MB, nano) dentro del `webServer.timeout` de 60s
  de `playwright.config.js`. Verificación real pendiente: la primera vez que se abra un
  PR con estos cambios.
- [x] **34-07** — Marcar formalmente como deprecados los endpoints `/api/*` v1 en
  `backend/main.py` (criterio 6 — no tiene id `TEST-0N` propio en REQUIREMENTS.md, solo
  aparece en ROADMAP.md como sexto criterio de la fase). `deprecated=True` nativo de
  FastAPI (aparece marcado en Swagger/ReDoc y en el JSON de `/openapi.json`, verificado
  por script) + una nota en el docstring citando el reemplazo v2 exacto, sin retirar
  nada ni tocar comportamiento.

  Antes de tocar nada: `grep` de cada endpoint `/api/*` no-v2 contra `frontend/js/` y
  `frontend/index.html` para separar lo genuinamente muerto de lo que sigue sirviendo
  al frontend actual con ese mismo nombre "v1" — marcar como deprecado algo que la UI
  todavía usa activamente habría sido peor que no marcar nada. Resultado: de los ~20
  endpoints no-v2 de `main.py`, solo **6** no tienen ningún consumidor en el frontend
  vigente y sí tienen reemplazo v2 real:
  - `GET`/`DELETE /api/events` → `GET /api/v2/events` (Fase 30)
  - `GET /api/zones/stats` → `GET /api/v2/analytics/occupancy` (Fase 31)
  - `GET /api/heatmap` → `GET /api/v2/analytics/heatmap` + `/heatmap/scale` (Fase 31)
  - `GET /api/alerts/config`, `POST /api/alerts/test`, `GET /api/alerts/status` →
    notifier global de la Fase <18 (`alert_webhook_url`/`alert_on_*`), superado por las
    acciones por-regla del RuleEngine (Fase 30, `backend/events/actions.py`), no por un
    endpoint v2 1:1

  Deliberadamente **sin tocar**: `/detections`, `/counts`, `/api/stats`, `/api/health`,
  `/api/events/export`, `/api/ws-token`, `/persons*`, `/api/enroll_face`,
  `/api/recordings`, `/video_feed`, `/ptz/*`, `/camera/*`, `/ws` — todos con
  consumidores reales confirmados en el frontend actual (`dashboard.js`,
  `dashboard-events.js`, `websocket.js`, `markPerson.js`, `eventCard.js`,
  `personGallery.js`...), varios de ellos documentados en el propio código como
  decisión deliberada de no duplicar en v2 (`/api/enroll_face`: "no tiene endpoint
  propio a proposito"; `/api/events/export`: "sigue apuntando al endpoint v1... tabla
  crossing_events"). Marcarlos deprecados habría sido factualmente falso.

  Verificado con `app.openapi()`: exactamente los 6 endpoints (7 entradas, `/api/events`
  cuenta dos veces por sus dos métodos) llevan `deprecated: true`. Suite completa
  **769 passed, 2 skipped, 3m44s** — sin regresiones (cambio de metadata pura, cero
  comportamiento tocado).
- [x] **34-08** — Puerta de fase: trazabilidad de los 6 criterios + checkpoint.

  | # | Criterio | Evidencia |
  |---|---|---|
  | 1 | Test de integración FakeRTSP→...→WebSocket, CI sin cámara real | `tests/integration/test_pipeline_e2e.py` (2 tests), 34-01 |
  | 2 | Playwright cubre los 10 escenarios | `tests/e2e/*.spec.js` (10 ficheros, 11 tests — modales tiene 2), 34-04/34-05 |
  | 3 | Suite completa < 5 min | pytest: **769 passed, 2 skipped, 3m44s** (verificación final tras 34-07). Playwright: **11 passed, 22.4s** (verificación final). Ambos muy por debajo del presupuesto, corren como jobs de CI separados |
  | 4 | CI: unit+integración en push, E2E en PR | `.github/workflows/tests.yml` — job `test` sin gate (push+PR), job `e2e` con `if: github.event_name == 'pull_request'`. YAML validado. **Sin verificar en una ejecución real de GitHub Actions** — ver nota de riesgo en 34-06, pendiente del primer PR real |
  | 5 | Cobertura > 80% en events/pipeline/perception | `.coveragerc` + step "Coverage gate" en CI. Medido: events 90.8%, pipeline 89.7%, perception 94.3% |
  | 6 | Endpoints `/api/*` v1 marcados deprecados | 6 endpoints con `deprecated=True`, verificado vía `app.openapi()`, 34-07 |

  **Checkpoint manual pendiente** (mismo criterio no bloqueante que el resto de fases
  del proyecto, p.ej. Fase 30/31/33): la primera apertura de un PR real con estos
  cambios, para confirmar que el job `e2e` arranca de verdad en el runner de GitHub
  (Ubuntu, sin `.venv`, con la descarga real de `yolo26n.pt` por Ultralytics dentro del
  `webServer.timeout` de 60s) — es el único tramo de esta fase que no se pudo ejecutar
  desde este entorno (requiere `git push`, fuera del alcance de esta sesión sin permiso
  explícito del usuario).

  Los 6 criterios de éxito de la fase quedan cubiertos con evidencia verificable salvo
  el punto marcado arriba. TEST-01..05 cerrados en `.planning/REQUIREMENTS.md` (el
  criterio 6 no tiene id `TEST-0N` propio, solo aparece en `ROADMAP.md`).

## Nota sobre tooling GSD

`gsd-sdk` (referenciado por
`~/.claude/get-shit-done/workflows/plan-phase.md` y `execute-phase.md`) no está
instalado/en el PATH de esta sesión — los agentes `gsd-planner`/`gsd-executor`
siguen disponibles como subagentes, pero el orquestador de los workflows `/gsd:*`
no se pudo invocar. Decisión del usuario: planificar y ejecutar a mano, sin la
ceremonia completa de PLAN.md por sub-tarea ni SUMMARY.md — este único fichero
hace de plan y de bitácora.
