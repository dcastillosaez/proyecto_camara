# 17-02 Summary — CaptureWorker y RTSPStream como consumidor del broker

**Plan:** 17-02-PLAN.md · **Wave:** 2 · **Estado:** Tasks 1-4 completas, Task 5 (checkpoint) pendiente

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

## Task 5 — PENDIENTE (requiere hardware real, no automatizable)

No se pudo completar: la cámara Tapo (`192.168.1.132:554`) no responde desde este entorno (conexión rechazada en el puerto RTSP) al momento de ejecutar este plan. Esta tarea es un checkpoint (`autonomous: false`) que requiere:

1. Arrancar con `PIPELINE_V2=false`, observar el dashboard 5 min (FPS, fluidez, latencia, detecciones, conteo, reconocimiento).
2. Arrancar con `PIPELINE_V2=true`, repetir la observación.
3. Comparar — el vídeo con el flag activo debe ser indistinguible o mejor. `broker_stats.dropped` creciente en el suscriptor `"processing"` es **esperado y correcto**.
4. Dejar corriendo 30 min y comprobar que la latencia no crece progresivamente.
5. Si todo es correcto: cambiar `pipeline_v2` a `True` por defecto en `backend/config.py` y `.env.example`.
6. Si hay regresión: NO invertir el flag, documentar el síntoma.

**El flag sigue en `False` por defecto** — el sistema en producción se comporta exactamente como v1.2 hasta que esta verificación se complete y se decida activar el default.

## Cómo retomar

Cuando la cámara esté accesible:
```bash
# Modo v1 (control)
PIPELINE_V2=false .venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# Modo v2 (a comparar)
PIPELINE_V2=true .venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# Salud del pipeline v2 durante la prueba:
curl http://localhost:8000/api/v2/cameras/cam1/health
```

## Desviaciones del plan

- `time.perf_counter()` en vez de derivar `fps`/`last_frame_age_s` de `captured_at` (ver Task 1-2 arriba). No afecta al contrato del broker.
- Task 5 no ejecutada por falta de acceso a la cámara real en este entorno — no es una desviación de diseño, es un bloqueo externo documentado.

## Habilita

Con Task 5 pendiente, la Fase 18 (workers desacoplados) puede empezar a planificarse pero no debería darse por buena la Fase 17 hasta cerrar la comparativa A/B con hardware real.
