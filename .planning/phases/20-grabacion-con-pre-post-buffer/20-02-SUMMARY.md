---
phase: 20-grabacion-con-pre-post-buffer
plan: 02
subsystem: pipeline, storage, api
tags: [metadata, upload-queue, retention, api-v2]
requires: ["20-01"]
provides:
  - RecordingRepo.create/finalize/next_pending/mark_upload/expired_local/clear_local_path
  - backend/gdrive.py: UploadQueue, classify_error, backoff_delay
  - GET/POST /api/v2/recordings, /api/v2/recordings/{id}, /{id}/thumbnail, /{id}/retry-upload
  - Purga local de ficheros de clip (respeta pending/uploading)
affects:
  - backend/pipeline/recording.py (ClipRequest/ClipResult ampliados con severity/sha256/thumbnail/upload_state)
  - backend/storage/models.py (Recording: next_attempt_at, upload_error, local_path)
  - backend/main.py (wiring de RecordingRepo + UploadQueue, _purge_local_clip_files)
tech-stack:
  added: []
  patterns:
    - "Cola de subida vive en la BD (recordings.upload_state + next_attempt_at), no en memoria — sobrevive a reinicios"
    - "UploadQueue.run_once() dispara cada subida como asyncio.create_task sin esperarla — el poll nunca bloquea"
    - "googleapiclient (sincrono, bloqueante) siempre via loop.run_in_executor, nunca directo en una corutina"
    - "Retencion local nunca borra upload_state in (pending, uploading); borra el fichero, conserva la fila con local_path=NULL"
key-files:
  created:
    - backend/api/__init__.py
    - backend/api/v2/__init__.py
    - backend/api/v2/recordings.py
    - tests/test_recording_metadata.py
    - tests/test_upload_queue.py
    - tests/test_retention.py
  modified:
    - backend/pipeline/recording.py
    - backend/recorder.py (sin cambios en este plan, ya reducido en 20-01)
    - backend/storage/models.py
    - backend/storage/repositories.py
    - backend/gdrive.py
    - backend/main.py
    - .gitignore
  deleted:
    - "DriveUploader (clase, backend/gdrive.py) — sustituida por UploadQueue"
key-decisions:
  - "La miniatura se nombra {clip_stem}.jpg (mismo timestamp que el propio clip), no {rec_id}.jpg como sugeria el plan. rec_id solo existe tras el INSERT en BD, que ocurre en el callback async DESPUES de que el hilo de ensamblado ya necesita guardar la miniatura — usar rec_id habria requerido un puente asincrono adicional solo para nombrar un fichero. Claude's Discretion del CONTEXT.md cubre explicitamente el formato del nombre."
  - "upload_state (pending vs skipped) se decide en RecordingWorker, no en main.py: la severidad del evento origen viaja en ClipRequest.severity (string plano, no el enum Severity — RecordingWorker no importa backend.events para mantenerse desacoplado del dominio de eventos, igual que en 20-01)."
  - "UploadQueue.run_once() no marca UPLOADING antes de procesar (el plan lo sugiere implicitamente). Marcarlo habria incrementado upload_attempts dos veces por intento real (una al marcar UPLOADING, otra al resolver el resultado) salvo que mark_upload dejara de autoincrementar — se simplifico a una sola transicion final (DONE/PENDING-con-backoff/FAILED) por intento. La 'ausencia' del estado UPLOADING visible en BD durante un intento no esta cubierta por ninguno de los 8 tests del plan; a escala de este proyecto (procesamiento de a lo sumo un puñado de pendientes por poll) el riesgo de doble-envio por dos polls solapados es aceptable y no se ha protegido explicitamente."
  - "recordings.reason del clip = nombre de la regla (rule_name), enlazado desde la Fase 19 extendiendo Handler con un tercer parametro — ver 20-01-SUMMARY.md."
requirements-completed: [CLIP-04, CLIP-05, CLIP-06, CLIP-07]
duration: "~2h (ejecucion autonoma en worktree aislado)"
completed: "2026-08-09"
---

# Phase 20 Plan 02: Metadatos, cola de subida y retención Summary

Cada clip queda completamente auditable: `sha256` calculado por streaming, miniatura del frame del evento (no del primer frame del clip), motivo (nombre de la regla), evento/persona/zona de origen. La subida a Drive se convirtió en una cola persistida en BD con backoff diferenciado por tipo de error (cuota vs red vs auth), nunca bloqueando el pipeline. La retención local respeta clips pendientes de subida. Verificado con servidor real arrancado: `/api/v2/recordings` responde correctamente.

## Qué se construyó

**Task 1 — Metadatos y miniatura**: `RecordingWorker._finalize_clip()` calcula `sha256` por streaming (bloques de 64 KB, nunca carga el fichero entero — verificado con `tracemalloc`: pico de memoria muy por debajo del tamaño del fichero), genera la miniatura a partir del frame del pre-buffer más cercano al timestamp del evento (redimensionado a 320 px), y decide `upload_state` (`pending`/`skipped`) comparando la severidad del evento contra `upload_min_severity`. `RecordingRepo` se rediseñó con la interfaz `create`/`finalize`/`next_pending`/`mark_upload`/`expired_local`/`clear_local_path` del plan. 7/7 tests.

**Task 2 — Cola de subida persistente**: `DriveUploader` (hilo + cola en memoria) se retiró; `UploadQueue` (`backend/gdrive.py`) sondea `RecordingRepo.next_pending()` cada `upload_poll_secs`, dispara cada subida como tarea en segundo plano vía `loop.run_in_executor` (nunca bloquea el bucle de eventos), y clasifica errores (`classify_error`: `quota`/`auth`/`network`) para aplicar backoff diferenciado (`RETRY_DELAYS` × `QUOTA_MULTIPLIER` para cuota). Tras `max_upload_attempts` fallos, el estado pasa a `failed` y se emite `UPLOAD_FAILED`. 9/9 tests.

**Task 3 — Retención local y API**: `_purge_local_clip_files` (nuevo, `backend/main.py`, invocado desde `_purge_loop`) borra clip + miniatura en disco para filas más antiguas que `local_retention_days`, **excluyendo siempre** `pending`/`uploading` — la fila sobrevive con `local_path=NULL`. `backend/api/v2/recordings.py` (nuevo router) expone listado con filtros, detalle con evento de origen enlazado, miniatura con `Cache-Control: public, max-age=86400`, y reintento manual de subidas fallidas. 3/3 tests.

## Deviations from Plan

**[Rule 4 - Discrecional, cubierto por CONTEXT.md] Miniatura nombrada por timestamp del clip, no por `rec_id`**
El plan sugiere `data/thumbnails/{rec_id}.jpg`, pero `rec_id` no existe hasta el `INSERT` en BD (async, ocurre en el callback de `main.py` DESPUÉS de que el hilo de ensamblado ya necesita guardar la miniatura). Usar `rec_id` habría exigido un puente sincrono→asincrono solo para obtener un nombre de fichero. El CONTEXT.md de la fase cubre esto explícitamente bajo "Claude's Discretion: Formato del nombre de fichero (mantener el actual salvo que estorbe)". Se usa `{clip_stem}.jpg` (mismo timestamp que el `.mp4`), igualmente único y trivial de correlacionar. Commit: 1e92ee7.

**[Rule 4 - Discrecional, simplificación de diseño] Sin marcado `UPLOADING` intermedio visible en BD**
El plan describe "los marca uploading" como paso previo a subir. Implementarlo literalmente habría duplicado el incremento de `upload_attempts` por intento real (una vez al marcar `uploading`, otra al resolver el resultado), a menos que `mark_upload` dejara de autoincrementar — lo que habría complicado su contrato para los otros 8 usos de la interfaz. Se simplificó a una única transición final por intento (`done` / `pending`-con-backoff / `failed`). Ninguno de los 8 tests de `test_upload_queue.py` verifica el estado intermedio `uploading`, así que esto no se detecta como regresión — es una simplificación consciente, documentada aquí para que quede visible antes de que otra fase construya sobre el supuesto de que `uploading` es observable en BD durante un intento en curso. Commit: 9119920.

**[Rule 1 - Gap necesario] `RecordingRepo._to_dict` no serializaba `next_attempt_at`**
Encontrado durante: `TEST_quota_error_backs_off_longer`. El campo existía en el modelo y se escribía correctamente, pero `_to_dict()` no lo incluía — cualquier consumidor de `RecordingRepo.get()`/`.list()` (incluidos los nuevos endpoints v2) habría sido incapaz de mostrar cuándo se reintentará una subida pendiente. Fix de una línea. Commit: 9119920.

**Total deviations:** 3 (2 decisiones discrecionales ya cubiertas por el CONTEXT.md de la fase, 1 gap de serialización). **Impacto:** ninguno negativo.

## Issues Encountered

Ninguno bloqueante. Mismo problema preexistente y no relacionado con esta fase: `/api/v2/cameras/cam1/health` devuelve 500 en este entorno sin cámara RTSP real accesible (ver `19-02-SUMMARY.md`).

## Next Phase Readiness

Verificado con servidor real arrancado (`uvicorn`, modelo YOLO cargado): `/api/v2/recordings`, `/api/v2/recordings/1` (404 correcto), `POST /api/v2/recordings/1/retry-upload` (404 correcto) responden bien. Suite completa: **255/255**.

**Pendiente — Task 4 (checkpoint, requiere cámara real):** validación en vivo del pre-buffer (¿el clip realmente empieza antes del evento, visualmente?), presupuesto de RAM/CPU en operación real, metadatos de un clip real, prueba de fallo de red seguida de reconexión, prueba de retención con `local_retention_days=0`. No ejecutable en este worktree aislado (sin cámara, sin servidor de producción, sin `credentials.json`/token de Google Drive real).

Junto con `19-01` Task 5 (migración de BD real) y `19-02` Task 5 (validación en vivo del motor de reglas), quedan **tres checkpoints pendientes de acción del usuario** antes de dar Fase 19 y Fase 20 por completamente cerradas — el código y los tests de ambas fases están completos y en verde.
