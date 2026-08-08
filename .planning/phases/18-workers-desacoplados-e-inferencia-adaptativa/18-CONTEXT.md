# Phase 18: Workers desacoplados e inferencia adaptativa - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md §2.3, §5.3
**Requirements:** PIPE-04, PIPE-05, PIPE-06, DET-05

<domain>
## Phase Boundary

Esta fase vacia `RTSPStream`. Todo lo que hoy vive dentro de `_process_frame` se reparte en workers independientes que consumen del `FrameBroker` a su propio ritmo.

**Dentro:** `DetectionWorker` (YOLO + ByteTrack + zonas + heatmap), `StreamingWorker` (MJPEG), `RecordingWorker` (delega en el `ClipRecorder` actual), `RecognitionWorker` (mueve el hilo de reconocimiento existente), `AdaptiveRate`, supervisor que reinicia workers caidos, y la retirada de `RTSPStream`.

**Fuera:** el pre-buffer de grabacion (Fase 20), el motor de eventos (Fase 19), las metricas Prometheus (Fase 21). Los workers publican sus resultados por los mismos mecanismos que hoy (`event_queue`, estado compartido con lock).

**Criterio dominante:** el vídeo se sirve al ritmo de la cámara aunque la detección corra a 8 FPS.
</domain>

<decisions>
## Implementation Decisions

### Un worker por responsabilidad, no por frame
Cada worker es un `threading.Thread` con su propia `Subscription`. Ninguno conoce a los demas: se comunican por el `TrackRegistry` (estado compartido con lock) y por la cola de eventos existente.

### AdaptiveRate mide, no adivina
`should_process(now)` decide por tiempo transcurrido desde el ultimo procesado, no por contador de frames. `observe(latency)` alimenta una media movil exponencial; si la latencia media supera el presupuesto (`1 / target_fps * 0.8`), el FPS efectivo baja un escalon; si baja del 50% del presupuesto durante N ciclos, sube un escalon. Escalones discretos, no control continuo — es mas predecible y mas facil de testear.

Esto sustituye al `detect_every` actual (`backend/config.py:53`), que es un contador fijo de frames y no reacciona a la carga real.

### Supervisor simple, no framework
Un hilo supervisor que cada 5 s comprueba `worker.is_alive()` y reinicia los caidos con un contador de reinicios. Tres reinicios en 60 s marcan el worker como `FAILED` y dejan de intentarlo. En esta fase `DEGRADED_MODE` se loguea y se expone en el health endpoint; como evento tipado llega en la Fase 19.

### El TrackRegistry es el punto de encuentro
`DetectionWorker` escribe el estado de tracks; `StreamingWorker` lo lee para dibujar el overlay; `RecognitionWorker` lo lee para saber que tracks necesitan cara. Un unico `threading.RLock`. Se prohibe que dos workers escriban el mismo campo.

### RTSPStream se retira, no se deja como fachada muerta
Al terminar la fase, `backend/stream.py` contiene solo un alias de compatibilidad o desaparece. Dejar una clase de 534 lineas sin uso es peor que borrarla: el historial esta en git.

### Claude's Discretion
- Si `RecognitionWorker` es un worker de pleno derecho o sigue siendo el hilo actual (`_recognition_worker`, backend/stream.py:400) movido de sitio.
- Granularidad de los escalones de `AdaptiveRate` (sugerido: 12, 8, 5, 3 FPS).
- Si el supervisor vive en `CameraPipeline` o en un modulo aparte.
</decisions>

<canonical_refs>
## Canonical References

### Especificacion
- `propuesta_mejora/SPEC_v2.md` §2.3 (modelo de concurrencia), §5.3 (AdaptiveRate y DetectionWorker)

### Codigo existente que se reparte
- `backend/stream.py` — `_process_frame` (creado en 17-02), `_recognition_worker` (400), `_update_zones_and_heat` (424), `_rebuild_zone_states` (465), `_prune_caches` (492), `get_heatmap` (193), `get_zone_stats` (180)
- `backend/detector.py` — `PersonDetector.detect_sv`, `annotate`
- `backend/tracker.py` — `PersonTracker.update`, `annotate`, `get_counts`
- `backend/recorder.py` — `ClipRecorder`
- `backend/main.py` — `mjpeg_generator` (362), `lifespan` (153)

### Planificacion
- `.planning/ROADMAP.md` § Phase 18
- `.planning/phases/17-frame-broker-y-capture-worker/17-02-SUMMARY.md`
</canonical_refs>

<specifics>
## Specific Ideas

- El test de "ningun hilo hace await" se puede automatizar con `ast`: recorrer los modulos de `backend/pipeline/` y afirmar que ninguna funcion que se pasa como `target=` de un `Thread` es una corrutina, y que no hay `await` en el arbol de esas funciones.
- La medicion de CPU antes/despues es un criterio de exito de la fase. Conviene capturarla con el mismo script en ambos casos: `psutil.Process().cpu_percent(interval=30)` con una persona en escena.
- ByteTrack necesita `frame_rate` coherente con el ritmo real de detecciones. Al bajar el FPS de deteccion hay que actualizar el `frame_rate` del tracker, o los IDs se perderan antes de tiempo. Es el riesgo principal de la fase.
- El `StreamingWorker` no debe re-encodear si nadie esta mirando: si no hay clientes MJPEG conectados, puede saltarse el `imencode`.
</specifics>

<deferred>
## Deferred Ideas

- Emitir `DEGRADED_MODE` como evento tipado → Fase 19.
- Metricas por worker en Prometheus → Fase 21.
- Pre-buffer en `RecordingWorker` → Fase 20. Aqui el worker solo se mueve de sitio.
- Presupuesto de CPU compartido entre camaras → Fase 36.
</deferred>

---
*Context creado: 2026-08-07*
