# 18-02 Summary — Workers desacoplados, supervisor y retirada de RTSPStream

**Plan:** 18-02-PLAN.md · **Wave:** 2 · **Estado:** Tasks 1-5 completas, Task 6 (checkpoint) pendiente

## Qué se construyó

**Task 1 — `StreamingWorker`:** consume del broker y dibuja el overlay reconstruyendo `sv.Detections` desde `TrackRegistry.snapshot()`, reutilizando `PersonTracker.annotate`. No importa `PersonDetector` (verificado por test). Con cero clientes conectados **no ejecuta `imencode`**: en una cámara que nadie mira, encodear es gasto puro.

**Task 2 — `RecordingWorker` y `RecognitionWorker`:** el primero es un adaptador broker → `ClipRecorder` que expone la misma interfaz mínima (`get_frame`/`get_live_count`) que el recorder ya consumía de `RTSPStream`, así que la lógica de grabación se porta sin tocarla. El segundo porta `_recognition_worker` con ritmo propio vía `AdaptiveRate` (2 FPS por defecto), eligiendo candidatos del registry por antigüedad sin identidad.

**Task 3 — `WorkerSupervisor`:** hilo que comprueba `is_alive()` de cada worker y recrea con su factory los caídos. Ventana deslizante: tres caídas en 60 s marcan `FAILED` y se deja de reintentar. `degraded` refleja cualquier worker en `FAILED`. Reloj inyectable para probar la ventana sin esperar.

**Task 4 — Tests de arquitectura:** análisis estático con `ast` que verifica los invariantes de concurrencia (PIPE-06): ningún target de `threading.Thread` contiene `await` ni es corrutina; ninguna corrutina invoca inferencia; `CaptureWorker` sigue puro; el pipeline no importa `fastapi`.

**Task 5 — Retirada de `RTSPStream`:** `CameraPipeline` pasa a ser la fachada que consume la capa web, arma los cinco workers, los registra en el supervisor y expone los accesores que antes daba `RTSPStream`. `backend/stream.py` eliminado.

## Decisiones y desviaciones

- **Limpieza de cachés del recognizer contra `registry.active_ids()`** en vez de los ids devueltos por `registry.prune()`. El `DetectionWorker` también poda el registry, así que depender de quién llama primero sería una carrera; con el set de activos el resultado es idéntico sin importar el orden.
- **Semántica de `max_restarts` precisada:** cuenta caídas toleradas en la ventana, no reinicios ya efectuados. Con el default de 3, reinicia tras la primera y la segunda caída y la tercera marca `FAILED` — que es lo que pide el criterio del plan.
- **`FrameBroker.subscribe(replace=True)` y `latest()`** (no previstos en el plan): el primero es necesario porque un worker que muere por excepción nunca cierra su suscripción y la factory que lo recrea debe poder reclamar el nombre; `_unsubscribe` comprueba identidad para que una suscripción reemplazada no se lleve por delante a su sustituta al cerrarse tarde. El segundo evita montar un worker solo para snapshots puntuales (enrolar, watchdog).
- **`PersonTracker.set_frame_rate`** llegó en 18-01 (ver su SUMMARY).
- **Watchdog de cámara** pasa a usar `CaptureHealth.connected`/`last_frame_age_s` en vez de sondear `get_frame() is None` — más preciso y sin copiar un frame cada 10 s.
- **`detect_every` y `pipeline_v2` eliminados de la configuración:** ya no existe la ruta legacy que los leía. `AdaptiveRate` sustituye al primero; el pipeline v2 es ahora el único camino.

## Verificación realizada

- Suite completa: **176/176**.
- Tests nuevos en esta fase: 5 (`StreamingWorker`), 3+6 (`Recording`/`Recognition`), 6 (supervisor), 4 (arquitectura), 3 (broker: `latest`/`replace`), 2 (zonas y heatmap migrados a `DetectionWorker`), 4 (capa web: `/video_feed` y ciclo de vida).
- Tests de arquitectura comprobados contra una infracción inyectada: detectan fichero, línea y función, no pasan de forma vacua.
- Arranque end-to-end con cámara mockeada: los cinco workers en `running`, `degraded=false`, `capture_fps` (≈720 con mock) y `detection_fps` (12) claramente distintos, JPEG válido servido y apagado limpio.

## Task 6 — PENDIENTE (checkpoint con cámara real)

No automatizable. Requiere:

1. **Medición de CPU antes/después** con una persona en escena, 60 s, mismo script en ambos casos.
2. **Prueba de aislamiento en vivo:** forzar el crash de un worker y verificar que el vídeo sigue fluyendo, que el supervisor lo reinicia y que tras tres fallos `degraded: true` aparece en el health endpoint.
3. **Prueba de ritmo:** confirmar en `/api/v2/cameras/cam1/health` que `capture_fps` es el nativo de la cámara y `detection_fps` ≈8. Son números distintos: esa es la prueba del desacoplamiento.
4. **1 h de operación** sin crecimiento de latencia.

## Habilita

Fase 19 (Event Engine y esquema de datos v2) puede empezar. El `DEGRADED_MODE` como evento tipado y las métricas por worker en Prometheus quedan diferidos a las fases 19 y 21 respectivamente, tal como marca el CONTEXT.
