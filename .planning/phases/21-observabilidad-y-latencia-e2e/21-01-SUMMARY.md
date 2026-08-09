---
phase: 21-observabilidad-y-latencia-e2e
plan: 01
subsystem: observability, pipeline, api
tags: [prometheus, metrics, latency, e2e, dashboard]
requires: ["20-02"]
provides:
  - backend/observability/metrics.py: Metrics, REGISTRY, snapshot(), generate_latest_text()
  - backend/observability/latency.py: LatencyTracker, Stage, e2e_percentiles()
  - backend/observability/sampler.py: MetricsSampler (asyncio.Task periodico)
  - GET /metrics (texto Prometheus), GET /api/v2/metrics (JSON snapshot)
  - Panel "OBSERVABILITY METRICS" en el dashboard
affects:
  - backend/events/engine.py (EventEngine acepta latency_tracker, estampa payload["_emitted_at"/"_captured_at"])
  - backend/events/bus.py (events_total, queue_depth)
  - backend/pipeline/detection.py (inference_latency_seconds, active_tracks, mark_processed)
  - backend/pipeline/recognition.py (inference_latency_seconds{stage=face})
  - backend/pipeline/recording.py (requests_queue_depth)
  - backend/pipeline/manager.py (CameraPipeline propaga latency_tracker)
  - backend/storage/repositories.py (RecordingRepo.count_by_upload_state)
  - backend/gdrive.py (upload_failures_total)
  - backend/main.py (wiring de latency_tracker, metrics_v2 configure, MetricsSampler)
tech-stack:
  added: ["prometheus-client>=0.21"]
  patterns:
    - "CollectorRegistry propio por instancia (no el REGISTRY global de prometheus_client) — evita 'Duplicated timeseries' al reinstanciar en tests"
    - "FPS calculados por el MetricsSampler a partir de deltas de contadores ya existentes, nunca en el bucle caliente de cada worker"
    - "Percentiles e2e via deque acotado + statistics.quantiles, no derivados de los buckets de Histogram"
    - "Event.payload['_emitted_at']/['_captured_at'] son campos internos no publicos, solo para cerrar el circuito de latencia"
    - "configure(x) setter en backend/api/v2/metrics.py para evitar import circular con main.py, igual que event_actions.configure"
key-files:
  created:
    - backend/observability/__init__.py
    - backend/observability/metrics.py
    - backend/observability/latency.py
    - backend/observability/sampler.py
    - backend/api/v2/metrics.py
    - tests/test_metrics.py
    - tests/test_latency.py
    - tests/test_metrics_sampler.py
  modified:
    - backend/events/engine.py
    - backend/events/bus.py
    - backend/pipeline/detection.py
    - backend/pipeline/recognition.py
    - backend/pipeline/recording.py
    - backend/pipeline/manager.py
    - backend/storage/repositories.py
    - backend/gdrive.py
    - backend/main.py
    - backend/config.py
    - frontend/index.html
    - requirements.txt
    - .env.example
key-decisions:
  - "snapshot() reconstruye las claves de counters como f'{family.name}_total' porque prometheus_client recorta el sufijo _total del nombre de familia (pero no de las muestras) — de lo contrario las claves del JSON no coincidirian con el catalogo documentado."
  - "MetricsSampler se construye DESPUES de camera_manager = CameraManager() y de pipeline.set_zones(), no antes: capturar el global camera_manager en el momento equivocado del lifespan lo dejaba en None de forma permanente (closure sobre el valor, no sobre el nombre). Bug encontrado en verificacion en vivo, no en los tests unitarios de MetricsSampler (que inyectan un camera_manager fake y por tanto no ejercitan el orden real de main.py)."
requirements-completed: [OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, OBS-06]
duration: "~2h (ejecucion autonoma en worktree aislado, continuacion tras Fases 19-20)"
completed: "2026-08-09"
---

# Phase 21 Plan 01: Metricas Prometheus, latencia e2e y panel de dashboard — Summary

Pipeline completo instrumentado con el catalogo de métricas de `SPEC_v2.md` §8.4, expuesto en `/metrics` (Prometheus) y `/api/v2/metrics` (JSON), con la latencia end-to-end desglosada en tres tramos (`capture_to_process`, `process_to_event`, `event_to_ws`) y un panel de dashboard con polling cada 5 s. Verificado con servidor real: eventos reales incrementan `events_total`, la latencia `event_to_ws` registra observaciones reales, y tras corregir un bug de orden de inicialización, los gauges de FPS por cámara se pueblan correctamente en cada tick del `MetricsSampler`.

## Qué se construyó

**Task 1 — Registro de métricas**: `backend/observability/metrics.py` define las 20 métricas del catálogo (más `prebuffer_bytes`, justificada por `20-CONTEXT.md`) en un `CollectorRegistry` propio por instancia. `snapshot()` produce un dict serializable con `gauges`/`counters`/`histograms`. 7/7 tests.

**Task 2 — LatencyTracker**: tres tramos medidos con reloj monotónico exclusivamente (`time.monotonic()`, nunca `datetime.now()`), percentiles p50/p95/p99 vía `deque` acotado + `statistics.quantiles`, latencia end-to-end definida como la suma de los percentiles de cada tramo. Guarda de anomalías para duraciones negativas (reloj corregido). 6/6 tests, todos pasaron a la primera.

**Task 3 — Instrumentación de workers y bus**: los cinco workers (`CaptureWorker` vía health existente, `DetectionWorker`, `RecognitionWorker`, `RecordingWorker`, cola de subida) y el `EventBus` quedaron instrumentados. Los FPS se calculan en `MetricsSampler` (nuevo `asyncio.Task` periódico, 5 s por defecto) a partir de deltas de contadores ya existentes — nunca con una división por frame en el bucle caliente. `EventEngine` propaga `latency_tracker` y estampa `payload["_emitted_at"]`/`["_captured_at"]` (campos internos, no parte del contrato público de `Event`) para cerrar el circuito de latencia hasta el envío WebSocket. 5/5 tests del sampler (con fakes), suite completa en verde.

**Task 4 — Endpoints y panel**: `GET /metrics` (texto Prometheus vía `generate_latest`) y `GET /api/v2/metrics` (JSON snapshot + `e2e_percentiles`), ambos heredando la autenticación HTTP Basic de toda la app sin necesitar sesión de dashboard aparte. Panel "OBSERVABILITY METRICS" añadido al dashboard con FPS diferenciados (captura/detección/facial), descartes, latencia e2e, profundidad de colas, refrescado cada 5 s.

## Deviations from Plan

**[Rule 1 - Gap necesario] Bug de orden de inicialización: `MetricsSampler` capturaba `camera_manager=None`**
Encontrado durante la verificación en vivo del Task 4 (no detectado por `tests/test_metrics_sampler.py`, que inyecta un `camera_manager` fake y por tanto no ejercita el orden real del `lifespan` de `main.py`). El código original construía `metrics_sampler = MetricsSampler(obs_metrics, camera_manager, ...)` **antes** de que la variable global `camera_manager` fuera reasignada a una instancia real (`camera_manager = CameraManager()`, más adelante en la misma función). Python captura el valor de `camera_manager` en el momento de la llamada, no una referencia viva al nombre — el sampler quedaba con `None` para siempre, y cada tick de 5 s lanzaba `AttributeError: 'NoneType' object has no attribute 'all'` (visible en el log del servidor). Fix: mover la construcción y arranque de `MetricsSampler` a después de `pipeline.set_zones(await get_zones())`, ya con `camera_manager` y `pipeline` completamente inicializados. Commit incluido en `4710e58`.

**Total deviations:** 1 (gap de orden de inicialización, encontrado y corregido en la misma sesión). **Impacto:** ninguno negativo — corregido antes del commit.

## Issues Encountered

Durante la verificación en vivo se detectó (y se descartó como irrelevante) un problema de entorno: lanzar `uvicorn` con el directorio de trabajo apuntando al repositorio principal (rama `main`, fuera del worktree) hace que Python resuelva `backend.main` contra el código de `main`, no contra el del worktree — los routers de Fase 19-21 no existían ahí y devolvían 404. No es un bug del código; es un recordatorio operativo para futuras verificaciones en vivo dentro de worktrees: `cd` siempre al worktree antes de `python -m uvicorn`, usando la ruta absoluta al intérprete del venv compartido (`.venv` vive en el repo principal, no en cada worktree).

También se confirmó, de nuevo, un proceso `python.exe` huérfano de una sesión anterior (previo a esta) que seguía vivo y mantenía bloqueados los ficheros WAL de SQLite — terminado manualmente antes de la limpieza final.

## Next Phase Readiness

Verificado con servidor real arrancado desde el worktree correcto: `/openapi.json` lista `/metrics`, `/api/v2/metrics`, `/api/v2/recordings` y variantes; `/api/v2/metrics` devuelve los 15 gauges con la etiqueta `{'camera': 'cam1'}` poblada tras el primer tick del sampler (valores en 0.0 porque no hay cámara RTSP real accesible en este entorno — comportamiento esperado, no un fallo). Suite completa: **275/275**.

**Pendiente — Task 5 (checkpoint, requiere cámara real):** medición de coste de instrumentación (<2% CPU comparando `metrics_enabled=true/false`), prueba de `frames_dropped_total` ralentizando artificialmente el detector, prueba de `capture_frame_age_seconds` con el `StreamingWorker` bloqueado 30 s, y línea base operativa de 30 min (FPS típicos, latencia e2e p50/p95, RSS) como referencia para las fases del bloque B. No ejecutable en este worktree aislado (sin cámara RTSP real).

Junto con `19-01` Task 5, `19-02` Task 5 y `20-02` Task 4, quedan **cuatro checkpoints pendientes de acción del usuario** antes de dar las Fases 19-21 por completamente cerradas — el código y los tests de las tres fases están completos y en verde.
