# Phase 17: Frame Broker y Capture Worker - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md §5.1, §5.2, ADR-01
**Requirements:** PIPE-01, PIPE-02, PIPE-03

<domain>
## Phase Boundary

Esta fase desacopla la captura RTSP del resto del procesamiento. Introduce `FrameBroker` (fan-out latest-frame, un slot por suscriptor) y `CaptureWorker` (solo captura, reescalado y publicacion).

**Dentro:** `backend/pipeline/{broker,capture,manager}.py`, fachada de compatibilidad en `backend/stream.py`, endpoint `/api/v2/cameras/{id}/health`, tests unitarios.

**Fuera:** mover deteccion, tracking, zonas, heatmap o reconocimiento a workers — eso es la Fase 18. En esta fase `RTSPStream` sigue haciendo todo eso; lo unico que cambia es de donde saca los frames.

**Criterio dominante:** no cambiar nada visible. El stream MJPEG debe comportarse igual que en v1.2.
</domain>

<decisions>
## Implementation Decisions

### FrameBroker: slot por suscriptor, no cola compartida
Cada suscriptor tiene su propio `Frame | None` protegido por un `threading.Condition`. `publish()` recorre los suscriptores y sobreescribe su slot, incrementando `dropped` si el slot anterior no se habia consumido. Nunca bloquea.

Descartado: `queue.Queue(maxsize=1)` por suscriptor (semantica `put_nowait`/`Full` mas fragil) y cola compartida (un consumidor lento roba frames a otro).

### Frame lleva timestamps desde el origen
`Frame.captured_at` usa `time.monotonic()` (para medir latencia, inmune a cambios de reloj) y `Frame.wall_clock` usa `datetime.now()` (para timestamp de eventos). Ambos se fijan justo despues de `cap.read()`, no al publicar.

### Sin copia defensiva en publish
El `CaptureWorker` crea un ndarray nuevo en cada iteracion (`cap.read()` ya devuelve buffer propio tras el `resize`), asi que el broker publica la referencia sin copiar. `Subscription.get()` tampoco copia: el contrato es que un suscriptor no muta el frame que recibe. Esto se documenta en el docstring y se verifica por convencion, no por runtime.

### Flag de activacion
`PIPELINE_V2` en `Settings` (default `False`). Con `False`, `RTSPStream` mantiene su `_capture_loop` actual intacto. Con `True`, `RTSPStream` deja de capturar y consume del broker. El flag se invierte a `True` como ultimo paso de la fase, tras la verificacion visual.

### camera_id desde ya
`Frame.camera_id` y el endpoint de salud usan `camera_id`, con valor fijo `"cam1"` en esta fase. Introducirlo ahora evita reescribir firmas en la Fase 35.

### Claude's Discretion
- Nombre exacto de los suscriptores (`"detector"`, `"streaming"`, `"recording"`) y si se declaran como constantes o strings libres.
- Si `Subscription.get()` con `timeout=None` bloquea indefinidamente o usa un timeout interno de seguridad.
- Estructura interna de `CaptureHealth` (dataclass o dict).
</decisions>

<canonical_refs>
## Canonical References

### Especificacion
- `propuesta_mejora/SPEC_v2.md` §2.2 (invariantes), §2.3 (modelo de concurrencia), §5.1-5.2 (contratos), ADR-01

### Codigo existente que se toca
- `backend/stream.py` — `RTSPStream._capture_loop` (linea 265), `_create_capture` (508), `_reconnect` (514), `get_frame` (131)
- `backend/config.py` — `Settings`, `build_rtsp_url`, `get_settings`
- `backend/main.py` — `lifespan` (153), `mjpeg_generator` (362)

### Planificacion
- `.planning/ROADMAP.md` § Phase 17
- `.planning/REQUIREMENTS.md` § PIPE-01, PIPE-02, PIPE-03
</canonical_refs>

<specifics>
## Specific Ideas

- El test de "publish nunca bloquea" es el corazon de la fase: un suscriptor que duerme 1 s por frame no debe reducir el ritmo del productor. Medir con `time.monotonic()` alrededor de N publicaciones.
- El test de aislamiento entre suscriptores necesita tres suscriptores con velocidades distintas y comprobar que solo el lento acumula `dropped`.
- `grep -cE "YOLO|recogn|zone|heat" backend/pipeline/capture.py` debe devolver 0. Es un criterio automatizable y conviene dejarlo escrito en el plan.
- Fugas de hilos: test que hace 10 ciclos `start()`/`stop()` y comprueba que `threading.active_count()` vuelve al valor inicial.
</specifics>

<deferred>
## Deferred Ideas

- Metricas Prometheus del broker (`frames_dropped_total`) → Fase 21. En esta fase basta con `FrameBroker.stats()` en memoria.
- Multiples camaras en `CameraManager` → Fase 35. Aqui `CameraManager` gestiona una sola instancia, pero la firma ya acepta N.
- Reencolado de frames o ring buffer de N frames → no se hara: el invariante es "perder frames antes que acumular latencia".
</deferred>

---
*Context creado: 2026-08-07*
