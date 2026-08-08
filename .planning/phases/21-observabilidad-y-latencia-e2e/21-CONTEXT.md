# Phase 21: Observabilidad y latencia end-to-end - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md §8.4, ADR-10
**Requirements:** OBS-01..OBS-06

<domain>
## Phase Boundary

Hasta aqui el sistema es correcto pero opaco: cuando algo va mal, la unica herramienta es leer logs. Esta fase lo hace diagnosticable.

**Dentro:** registro Prometheus, instrumentacion de los cinco workers, medicion de latencia end-to-end en tres tramos, endpoints `/metrics` y `/api/v2/metrics`, y el panel de metricas del dashboard actual.

**Fuera:** la vista de camara completa (Fase 32), Grafana o alerting sobre metricas (fuera de v2.0), metricas de negocio como visitas por persona (Fase 31, salen de la BD, no del registro de metricas).

**Criterio dominante:** `frames_dropped` y la latencia real deben ser visibles, porque son las metricas que delatan un sistema que "parece" ir bien.
</domain>

<decisions>
## Implementation Decisions

### prometheus-client con registry propio
No usar el registry global por defecto: un `CollectorRegistry` propio evita colisiones al reinstanciar en tests y permite exponer un snapshot JSON limpio.

### Instrumentacion fuera del bucle caliente
Los histogramas se actualizan una vez por frame procesado, nunca por deteccion individual. Un histograma por bounding box multiplicaria el coste por 10 sin aportar informacion.

### Latencia en tres tramos, no en uno
- `captured_at → processed_at`: cuanto tarda el pipeline de percepcion.
- `processed_at → event_emitted_at`: cuanto tarda el motor de eventos.
- `event_emitted_at → ws_sent_at`: cuanto tarda la entrega al navegador.

Un unico numero agregado no permite saber donde esta el problema. Los tres tramos si.

### El reloj de latencia es monotonico
Todos los tramos usan `time.monotonic()`, que ya viaja en `Frame.captured_at` desde la Fase 17. `wall_clock` solo se usa para timestamps de eventos, nunca para medir duraciones.

### FPS medidos, no configurados
`detection_fps` es el ritmo real observado, no `detection_target_fps`. La diferencia entre ambos es informacion valiosa: significa que el sistema no alcanza su objetivo.

### El endpoint /metrics no requiere autenticacion de dashboard
Pero si esta detras del rate limiter y solo escucha en la LAN. Un scraper de Prometheus no puede autenticarse con el flujo de sesion del dashboard.

### Claude's Discretion
- Nombres exactos de las metricas dentro del catalogo de SPEC_v2.md §8.4 (respetar convencion Prometheus: `_total` para counters, `_seconds` para duraciones).
- Buckets de los histogramas de latencia.
- Si el panel del dashboard reutiliza el widget de salud existente o anade uno nuevo.
</decisions>

<canonical_refs>
## Canonical References

### Especificacion
- `propuesta_mejora/SPEC_v2.md` §8.4 (catalogo de metricas), ADR-10

### Codigo existente que se instrumenta
- `backend/pipeline/broker.py` — `FrameBroker.stats()` (Fase 17)
- `backend/pipeline/capture.py` — `CaptureHealth` (Fase 17)
- `backend/pipeline/rate.py` — `AdaptiveRate.stats` (Fase 18)
- `backend/pipeline/supervisor.py` — `WorkerSupervisor.status()` (Fase 18)
- `backend/events/bus.py` — `EventBus.stats` (Fase 19)
- `backend/pipeline/prebuffer.py` — `RingFrameBuffer.bytes_used` (Fase 20)
- `backend/main.py` — `api_health` (418), ya expone CPU/RAM/FPS

### Planificacion
- `.planning/ROADMAP.md` § Phase 21
- `.planning/phases/20-grabacion-con-pre-post-buffer/20-02-SUMMARY.md`
</canonical_refs>

<specifics>
## Specific Ideas

- Buena parte del trabajo ya esta hecho: cada componente de las fases 17-20 expone su propio `stats()`. Esta fase sobre todo los unifica y les da formato estandar.
- El test de "latencia inyectada de 2 s aparece en el p95" es la forma de verificar que la medicion es real y no un placeholder.
- El coste de la instrumentacion debe medirse, no suponerse: comparar CPU con y sin el registro activo. El criterio es menos del 2%.
- `capture_frame_age_seconds` es la metrica que detecta el caso patologico "FPS=25 con 15 s de retraso": el FPS es correcto pero el frame que se esta sirviendo es viejo.

</specifics>

<deferred>
## Deferred Ideas

- Persistencia historica de metricas en `system_metrics` para graficas de tendencia → util pero no critico; se puede anadir en la Fase 31 si la vista de analitica lo pide.
- Alerting sobre metricas (por ejemplo, evento `DEGRADED_MODE` si `frames_dropped` supera un umbral) → se puede expresar como regla en la Fase 33.
- Trazado distribuido (OpenTelemetry) → innecesario en un proceso unico.
</deferred>

---
*Context creado: 2026-08-07*
