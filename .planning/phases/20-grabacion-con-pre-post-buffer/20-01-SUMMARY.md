---
phase: 20-grabacion-con-pre-post-buffer
plan: 01
subsystem: pipeline
tags: [prebuffer, recording, video]
requires: ["19-02"]
provides:
  - backend/pipeline/prebuffer.py (RingFrameBuffer, BufferedFrame)
  - backend/pipeline/recording.py (RecordingWorker reescrito, ClipRequest, ClipResult)
  - backend/recorder.py (ClipWriter — sin logica de decision)
affects:
  - backend/pipeline/manager.py (recorder_factory -> recording_config)
  - backend/main.py (wiring de recording_config y recorder_hook con rule_name)
  - backend/events/rules.py, backend/events/actions.py (Handler gana un 3er parametro rule_name)
tech-stack:
  added: []
  patterns:
    - "RingFrameBuffer purga por dos criterios simultaneos (frames y bytes), nunca solo uno"
    - "RecordingWorker: dos hilos (feed/assembly) desacoplados por queue.Queue — el ensamblado lento nunca bloquea la captura del buffer"
    - "Un evento record mientras hay clip activo EXTIENDE el deadline en vez de abrir un segundo clip"
key-files:
  created:
    - backend/pipeline/prebuffer.py
    - tests/test_prebuffer.py
    - tests/test_recording_prepost.py
  modified:
    - backend/pipeline/recording.py
    - backend/recorder.py
    - backend/pipeline/manager.py
    - backend/main.py
    - backend/events/rules.py
    - backend/events/actions.py
    - backend/config.py
    - .env.example
    - tests/test_actions.py
    - tests/test_phase10.py
  deleted:
    - tests/test_recording_worker.py
key-decisions:
  - "span_seconds mide la antiguedad del frame mas viejo RELATIVA al mas nuevo dentro del buffer, no contra datetime.now(). Hace el buffer testeable sin sleeps reales y es la magnitud que de verdad importa al ensamblar un clip (cuanto contexto hay disponible ahora mismo)."
  - "El test central (clip empieza antes del evento) usa frames de color solido cuyo valor de pixel ES el numero de secuencia (mod 256), no texto quemado con cv2.putText como sugeria el plan. OCR de texto renderizado no es fiable en un test automatizado; leer un pixel si lo es. cv2.putText queda reservado para la inspeccion visual humana del checkpoint en vivo (20-02 Task 4)."
  - "RuleEngine.evaluate() ahora pasa rule.name como tercer argumento a los handlers de ActionRegistry (Handler: Callable[[Event, Action, str], Awaitable[None]]). Necesario porque recordings.reason (SPEC_v2 SS7.1) debe guardar el nombre de la regla que disparo el clip, y el registro/ejecucion de acciones (Fase 19) no tenia forma de saberlo — ActionRegistry solo resolvia por Action.type."
  - "recorder_factory (patron de Fase 10: RecordingWorker se pasaba a si mismo como 'stream' a ClipRecorder) se sustituyo por recording_config: dict pasado directamente al constructor de RecordingWorker. ClipRecorder (decision de cuando grabar por live_count) se retiro segun el plan; sobrevive como ClipWriter (solo escritura de MP4)."
requirements-completed: [CLIP-01, CLIP-02, CLIP-03]
duration: "~1.5h (ejecucion autonoma en worktree aislado)"
completed: "2026-08-09"
---

# Phase 20 Plan 01: Pre/post-buffer de grabación Summary

`RingFrameBuffer` mantiene un buffer circular de frames JPEG acotado simultáneamente por tiempo y por memoria. `RecordingWorker` se reescribió por completo: alimenta el buffer continuamente en un hilo, y un segundo hilo de ensamblado drena el contexto previo al recibir un evento `record`, sigue grabando en vivo, y extiende la ventana en vez de duplicar el clip si llega un segundo evento cercano. El servidor real arranca correctamente con la nueva arquitectura (verificado con `uvicorn` — modelo YOLO cargado, endpoints respondiendo).

## Qué se construyó

**Task 1 — RingFrameBuffer** (`backend/pipeline/prebuffer.py`): `deque` con purga doble (por número de frames Y por bytes, lo que se cumpla primero), `threading.Lock`, contador de bytes incremental sin recalcular en cada `push()`. `span_seconds` mide la antigüedad del frame más viejo *relativa al más nuevo del buffer* — decisión clave que hace el componente testeable sin depender de `datetime.now()` real. Config nueva en `config.py`: `pre_buffer_secs`, `post_buffer_secs`, `pre_buffer_max_mb`, `pre_buffer_jpeg_quality`, `local_retention_days`, `upload_min_severity`, `max_upload_attempts`, `upload_poll_secs` (las dos últimas se adelantaron desde 20-02 para escribir la config de una vez). 9/9 tests, incluida concurrencia con 4 hilos.

**Task 2 — RecordingWorker reescrito** (`backend/pipeline/recording.py`): arquitectura de dos hilos — `_feed_loop` (broker → prebuffer, siempre; → cola en vivo, solo si hay clip activo) y `_assembly_loop` (máquina de estados idle↔grabando). Un segundo `request_clip()` mientras hay un clip en curso extiende `deadline` en vez de abrir un clip solapado — la comprobación central de la fase. Cola en vivo acotada (`queue.Queue` con drop-oldest y contador `live_dropped`) para que un ensamblado lento nunca crezca sin límite ni bloquee la alimentación del buffer. `backend/recorder.py` se redujo a `ClipWriter` (solo `VideoWriter` + `imdecode`, sin decidir cuándo grabar). 6/6 tests, incluido el test central (`TEST_clip_starts_before_event`) verificado leyendo de vuelta el MP4 generado.

## Deviations from Plan

**[Rule 4 - Arquitectura, aprobado implícitamente por necesidad] `Handler` de `ActionRegistry` gana un tercer parámetro `rule_name`**
Encontrado durante: wiring de `request_clip` al action `record`. `recordings.reason` (SPEC_v2 §7.1, CONTEXT.md de esta fase) debe guardar el nombre de la regla que disparó el clip — pero `RuleEngine.evaluate()` (Fase 19) llamaba a los handlers como `handler(event, action)`, sin pasar el nombre de la regla, y `ActionRegistry` solo resolvía por `action.type`. Sin este dato, `reason` tendría que inventarse (p.ej. `action.type`), perdiendo la trazabilidad que la fase entera busca. Fix: `Handler = Callable[[Event, Action, str], Awaitable[None]]`; los 8 handlers de `backend/events/actions.py` y los tests de `tests/test_actions.py` (Fase 19) se actualizaron para aceptar el tercer argumento. Verificado: 16/16 tests de `test_actions.py` + `test_rule_engine.py` en verde, suite completa 240/240. Commit: 533463f.

**[Rule 2 - Boundary, técnica de test] Verificación de "empieza antes del evento" por valor de píxel, no por OCR de texto**
El plan sugiere `cv2.putText` con el número de frame quemado en la imagen, pensado para inspección visual humana (checkpoint en vivo). Para el test automatizado se usó en su lugar un frame de color sólido cuyo valor de píxel *es* el número de secuencia (mod 256) — exactamente decodificable tras el roundtrip JPEG→MP4, sin la fragilidad de leer dígitos renderizados por OCR. `cv2.putText` queda como técnica para el checkpoint en vivo (20-02 Task 4), donde sí hace falta que un humano lo lea. Commit: 0f9a3b2.

**[Rule 1 - Necesario para mantener el árbol verde] `pipeline/manager.py`, `main.py`, `tests/test_phase10.py` actualizados fuera del alcance nominal del plan**
El plan lista solo `backend/pipeline/recording.py`, `backend/recorder.py` y el nuevo test file para esta tarea, pero `CameraPipeline.__init__` recibía `recorder_factory` (patrón retirado) y `main.py` construía `ClipRecorder` directamente — ambos habrían roto la app al arrancar. Se actualizaron con el mismo criterio aplicado en la Fase 19: mantener el árbol siempre en verde dentro de la misma sesión de ejecución. `tests/test_phase10.py` (TEST_040-043, pruebas de `ClipRecorder`) se retiraron — probaban una clase que el propio plan pide retirar; el resto del fichero (`DriveUploader`, `database.py` de recordings) queda intacto. `tests/test_recording_worker.py` (interfaz `recorder_factory` completa) se eliminó por el mismo motivo. Commit: 533463f.

**Total deviations:** 3 (1 extensión de contrato necesaria, 1 cambio de técnica de test, 1 ampliación de alcance para no dejar el árbol roto). **Impacto:** ninguno negativo — sin el cambio de `Handler`, `reason` sería inservible para auditoría (el propósito central de 20-02 Task 1); sin actualizar manager.py/main.py, el servidor no habría arrancado.

## Issues Encountered

Ninguno bloqueante. `/api/v2/cameras/cam1/health` sigue devolviendo 500 en este entorno (sin cámara RTSP real accesible) — mismo problema preexistente ya anotado en `19-02-SUMMARY.md`, no relacionado con esta fase.

## Next Phase Readiness

Verificado con servidor real arrancado (`uvicorn`, modelo YOLO cargado): `/api/health` responde correctamente con la nueva arquitectura de grabación cableada. Suite completa: **240/240**.

`RecordingWorker.request_clip()` ya está conectado al action `record` de `RuleEngine` (via `event_actions.configure(recorder_hook=...)` en `main.py`), pero `_on_clip_ready` todavía usa la persistencia mínima de la Fase 10 (`insert_recording(filename)` — solo el nombre de fichero). 20-02 Task 1 debe ampliar esto a los 10 campos de metadatos completos (`sha256`, `duration_s`, `thumbnail_path`, `reason`, `trigger_event_id`, `person_id`, `zone_id`, etc.) usando ya el `ClipResult` que `RecordingWorker` produce — el objeto ya lleva `reason`, `trigger_event_id`, `person_id`, `zone_id`, `started_at`, `ended_at`, solo falta calcular `sha256`/tamaño/miniatura y persistir vía `RecordingRepo`.

Ready para `20-02`.
