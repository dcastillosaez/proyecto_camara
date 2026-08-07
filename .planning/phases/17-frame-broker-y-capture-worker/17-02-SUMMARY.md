# 17-02 Summary — CaptureWorker y RTSPStream como consumidor del broker

**Plan:** 17-02-PLAN.md · **Wave:** 2 · **Estado:** COMPLETO (Tasks 1-5)

## Qué se construyó

**Task 1-2 — `backend/pipeline/capture.py` + `backend/pipeline/manager.py`:**
`CaptureHealth` (dataclass) y `CaptureWorker`, que porta `_create_capture`/`_reconnect` de `RTSPStream` sin cambios de comportamiento (backoff exponencial 1s→30s, `CAP_PROP_BUFFERSIZE=1`). Publica en el `FrameBroker` de la Fase 17-01. `CameraPipeline` agrupa broker + capture worker de una cámara; `CameraManager` gestiona N (solo `"cam1"` en esta fase).

Desviación menor respecto al plan: `CaptureHealth.fps`/`last_frame_age_s` usan internamente `time.perf_counter()` en vez de derivarse de `Frame.captured_at` (que sigue siendo `time.monotonic()` tal como exige el contrato del broker de 17-01). Motivo: en este equipo Windows, `time.monotonic()` tiene granularidad de milisegundo y en un bucle de captura sin I/O real (mocks de test) produce `span == 0.0` entre 30 muestras consecutivas, dando `fps=0`. `time.perf_counter()` usa `QueryPerformanceCounter` y no tiene ese problema. No afecta a `Frame.captured_at`, que sigue el contrato de 17-01 sin modificar.

**Task 3 — `backend/config.py` + `backend/stream.py`:**
`Settings.pipeline_v2` (default `False`). `RTSPStream.__init__` acepta `broker: FrameBroker | None = None` sin romper llamadores existentes. `_capture_loop` es ahora un despachador: sin broker llama a `_legacy_capture_loop` (idéntica a v1.2); con broker, `_consume_loop` se suscribe como `"processing"` y alimenta `_process_frame` con los frames ya publicados. `_process_frame` contiene exactamente la lógica que antes vivía inline en `_capture_loop` — solo reindentada al extraerse del bucle `while`, sin cambios semánticos.

**Task 4 — `backend/main.py`:**
Con `pipeline_v2=True`, `lifespan` crea `CameraManager`, añade `"cam1"` con el `process_size` configurado y arranca su `CaptureWorker` antes de instanciar `RTSPStream`, pasándole el broker. El apagado detiene `RTSPStream` y después `camera_manager.stop_all()`. Nuevos endpoints `GET /api/v2/cameras` y `GET /api/v2/cameras/{camera_id}/health` (503 si el flag está desactivado); la autenticación la cubre la dependencia global de la app, igual que el resto de `/api/*`.

## Verificación realizada

- Suite completa: **132/132** con el flag apagado (default) — sin regresión.
- Test de arquitectura: `capture.py` no contiene `yolo|detector|recogn|zone|heatmap|tracker`.
- Verificación manual (cámara mockeada, sin hardware real): con `pipeline_v2=True`, el `lifespan` arranca `CameraManager`, el `CaptureWorker` publica en el broker, y `RTSPStream._consume_loop` → `_process_frame` recibe los frames, ejecuta detección/tracking y actualiza `get_frame()` con normalidad. Apagado limpio confirmado.

## Task 5 — COMPLETA (2026-08-07, cámara real 192.168.1.132)

La cámara Tapo, inaccesible al principio de la sesión, se encendió a mitad de sesión. Tras habilitar RTSP de terceros en la app Tapo (Ajustes → Avanzado → Cuenta de cámara), la comparativa A/B se ejecutó contra hardware real:

**Control (v1, `PIPELINE_V2=false`, default de entonces):** dashboard funcional — vídeo, contadores, reconocimiento facial ("David" identificado), eventos IN/OUT en tiempo real. `GET /api/v2/cameras/cam1/health` → 503 (correcto, pipeline v2 inactivo). `GET /api/health` → `fps: 7.3`.

**Pipeline v2 (`PIPELINE_V2=true`):** mismo comportamiento visible en el dashboard (vídeo, reconocimiento, eventos — indistinguible del control). `GET /api/v2/cameras/cam1/health` confirmó el pipeline activo: `connected: true`, captura a ~15 FPS (nativo de `stream2`), `broker_stats.processing.dropped` creciendo junto con `delivered` — la prueba directa de que la captura nunca espera al procesamiento.

**Grabación de clips en pipeline v2:** verificada end-to-end con una persona real delante de la cámara — inicio de grabación al detectar, `.mp4` escrito en `data/clips/`, cierre tras 5 s de tail, inserción en BD (`recordings.id=3`). El upload a Google Drive falló por `invalid_grant` (token OAuth caducado en `data/token.json`) — no relacionado con esta fase, `ClipRecorder` no se tocó en el refactor.

**Soak test de 30 minutos** (script propio sondeando `/api/v2/cameras/cam1/health` cada 15 s, 106 muestras, `soak_results.csv`):

| Métrica | Resultado |
|---|---|
| FPS captura | 14.54–15.64, media 15.04 — estable todo el test |
| `last_frame_age_s` | media primeros 10 min: 0.038 s · media últimos 10 min: 0.036 s — **sin crecimiento de latencia** |
| `reconnects` | 0 durante los 30 min |
| `connected` | `True` ininterrumpido |
| `dropped` / `delivered` | 845→7408 / 429→20706 — crecimiento sano de ambos, `dropped` se estabiliza (no explota) |

Ningún síntoma de acumulación de buffer. Los cinco criterios de éxito de la fase se cumplen.

**Flag invertido:** `pipeline_v2` pasa a `True` por defecto en `backend/config.py` y `.env.example`. La línea temporal `PIPELINE_V2=true` añadida a `.env` durante la verificación se retira (ya redundante con el nuevo default).

## Desviaciones del plan

- `time.perf_counter()` en vez de derivar `fps`/`last_frame_age_s` de `captured_at` (ver Task 1-2 arriba). No afecta al contrato del broker.
- La comparativa A/B se apoyó en métricas objetivas del health endpoint (FPS, `last_frame_age_s`, `reconnects`, `dropped`/`delivered`) más que en "fluidez subjetiva" — más rigurosa que la observación visual que pedía el plan original, y reproducible.

## Habilita

Fase 17 completa. Fase 18 (workers desacoplados e inferencia adaptativa) puede ejecutarse — depende de 17-02, ya cerrada.
