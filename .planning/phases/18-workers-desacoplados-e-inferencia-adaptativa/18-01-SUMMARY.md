# 18-01 Summary — AdaptiveRate + TrackRegistry + DetectionWorker

**Plan:** 18-01-PLAN.md · **Wave:** 1 · **Estado:** COMPLETO

## Qué se construyó

**`backend/pipeline/rate.py` — `AdaptiveRate`:** control de FPS por escalones discretos (12/8/5/3, filtrados por `min_fps`/`max_fps`). `should_process(now)` decide por tiempo transcurrido, nunca por contador de frames. `observe(latency)` alimenta una media móvil exponencial (α=0.2); baja de escalón tras 3 observaciones seguidas por encima del presupuesto (`1/fps × 0.8`), sube tras 10 seguidas por debajo de la mitad del presupuesto — la histéresis por rachas (no un solo dato) evita oscilar en cada frame.

**`backend/pipeline/tracking.py` — `TrackRegistry`/`TrackState`:** estado compartido de tracks bajo un único `RLock`. `centroid_history` es un `deque(maxlen=history_len)` — sin esto sería una fuga de memoria garantizada en 24/7. `snapshot()` devuelve copia superficial del dict; `prune()` devuelve los ids expirados para que cada worker limpie sus propias cachés.

**`backend/pipeline/detection.py` — `DetectionWorker`:** consume del broker con su propia `Subscription`, gobernado por `AdaptiveRate`. Porta de `RTSPStream._process_frame` (Fase 17) la detección YOLO, el tracking, las zonas de interés (`PolygonZone`) y el heatmap — todo intacto, solo movido de sitio. Publica en `TrackRegistry` y reutiliza el mecanismo de eventos existente (`event_loop`/`event_queue`) sin cambios.

**`backend/tracker.py` — `PersonTracker.set_frame_rate` (desviación del plan, ver abajo):** sincroniza `ByteTrack.max_time_lost` cuando `AdaptiveRate` cambia de escalón, mutando el atributo in-place en vez de recrear el tracker (recrearlo perdería todos los tracks activos y sus IDs).

## Verificación realizada

- 8/8 tests de `AdaptiveRate` con reloj simulado (nunca `time.sleep`).
- 7/7 tests de `TrackRegistry`, incluida escritura concurrente desde 100 hilos.
- 7/7 tests de `DetectionWorker`: ritmo desacoplado del de publicación (target 8 FPS con productor a ~25-100 FPS), no bloqueo del broker con detector lento, sincronización de `set_frame_rate` al bajar de escalón, actualización del registro, observación de latencia real, parada limpia, supervivencia a excepciones de inferencia.
- 1 test añadido a `test_tracker.py` (`TEST_093`) confirmando que `set_frame_rate` muta `max_time_lost` sin recrear el objeto `ByteTrack`.
- Suite completa: **155/155**, sin regresión.

## Desviaciones del plan

- **`backend/tracker.py` no estaba en `files_modified` de 18-01-PLAN.md**, pero el propio plan señala revisar cómo se pasa `frame_rate` a `ByteTrack` como "el riesgo número uno de la fase", y no existía forma pública de actualizarlo tras la construcción. Se añadió `set_frame_rate()` como método público mínimo y seguro (muta un atributo simple, ya confirmado mutable en runtime).
- `DetectionWorker` no está todavía cableado en `backend/main.py` ni sustituye a `RTSPStream` — eso es explícitamente la Task 5 de 18-02 ("Retirar RTSPStream e integrar el pipeline completo"). El dashboard en producción sigue funcionando exactamente igual que al cierre de la Fase 17 (pipeline v2 con `RTSPStream._consume_loop`/`_process_frame`).

## Habilita

18-02 puede construir `StreamingWorker`, `RecordingWorker`, `RecognitionWorker` y el `WorkerSupervisor` sobre estas tres piezas, y finalmente retirar `RTSPStream`.
