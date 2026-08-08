# Phase 20: Grabacion con pre/post-buffer y metadatos - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md ADR-07, §7.1 (tabla recordings)
**Requirements:** CLIP-01..CLIP-07

<domain>
## Phase Boundary

Hoy la grabacion empieza cuando se detecta actividad, asi que los primeros segundos de cualquier incidente se pierden. Esta fase introduce un buffer circular que permite grabar hacia atras.

**Dentro:** `RingFrameBuffer` (pre-buffer JPEG en RAM), reescritura de `RecordingWorker` con pre/post-buffer, metadatos completos de clip (sha256, duracion, tamano, miniatura, evento origen, motivo), cola de subida persistente con reintentos, politicas de retencion local y cloud independientes.

**Fuera:** la interfaz de reproduccion de clips (Fase 30), la retencion configurable desde UI (Fase 32).

**Criterio dominante:** ningun clip empieza despues del evento que lo dispara.
</domain>

<decisions>
## Implementation Decisions

### Pre-buffer en JPEG, no en BGR
Un frame BGR a 720p ocupa 2,7 MB. Diez segundos a 15 FPS serian 400 MB — inviable. Encodeado a JPEG q=85 son ~120 KB por frame, 18 MB para el mismo buffer. El coste es un `imdecode` por frame al ensamblar el clip, que ocurre una vez por evento y fuera del camino critico.

### El buffer se llena siempre, se vacia solo al grabar
`RingFrameBuffer` es alimentado continuamente por el `RecordingWorker` desde su suscripcion al broker. El coste constante es un `imencode` por frame recibido. Para reducirlo, el worker se suscribe pero aplica su propio `AdaptiveRate` a `recording_fps` (default 15), no procesa los 25 FPS de la camara.

### El ensamblado del clip va en su propio hilo
Decodificar el pre-buffer y escribir el MP4 puede tardar segundos. Se hace en un hilo dedicado con cola, para que el `RecordingWorker` siga alimentando el buffer circular mientras tanto.

### Cola de subida en la base de datos, no en memoria
`recordings.upload_state` es la cola: `pending`, `uploading`, `done`, `failed`, `skipped`. Sobrevive a reinicios. Un `asyncio.Task` periodico recoge los `pending` y los procesa con backoff. Los `failed` tras N intentos quedan visibles para reintento manual.

### Retencion local y cloud son politicas independientes
Local: borrar clips con mas de `local_retention_days` (default 7). Cloud: subir solo eventos con `severity != info` (configurable). Un clip que no se sube se marca `skipped`, no `failed` — la distincion importa para las metricas.

### Motivo de grabacion explicito
`recordings.reason` guarda por que existe el clip: nombre de la regla que lo disparo, o `"manual"`, o `"continuous"`. Sin este campo, un clip huerfano es indepurable.

### Claude's Discretion
- Calidad JPEG del pre-buffer (sugerido 85; medir el impacto en RAM y CPU).
- Si la miniatura se extrae del frame del evento o del primer frame del clip.
- Formato del nombre de fichero (mantener el actual salvo que estorbe).
</decisions>

<canonical_refs>
## Canonical References

### Especificacion
- `propuesta_mejora/SPEC_v2.md` ADR-07 (pre-buffer JPEG), §7.1 (tabla recordings extendida)

### Codigo existente que se toca
- `backend/recorder.py` — `ClipRecorder` completo (15), `_loop` (62), `_start_clip` (93), `_finalise` (104)
- `backend/pipeline/recording.py` — `RecordingWorker` (creado en 18-02)
- `backend/gdrive.py` — `DriveUploader` (52), `upload_file` (38)
- `backend/storage/models.py` — `Recording` (creado en 19-01)
- `backend/config.py` — `recording_fps` (91), `recording_tail_secs` (92), `recording_codec` (94), `clips_dir` (87)

### Planificacion
- `.planning/ROADMAP.md` § Phase 20
- `.planning/phases/19-event-engine-y-esquema-de-datos-v2/19-02-SUMMARY.md`
</canonical_refs>

<specifics>
## Specific Ideas

- El test del pre-buffer necesita frames distinguibles. La tecnica mas fiable es quemar el numero de frame en la imagen con `cv2.putText` y leerlo despues del clip generado; asi se verifica literalmente que el clip empieza antes del evento.
- El presupuesto de RAM del pre-buffer debe ser una metrica (`prebuffer_bytes`), no una estimacion. Se calcula sumando `len(jpeg)` de los elementos del deque.
- El `sha256` se calcula por streaming (bloques de 64 KB), no cargando el fichero entero.
- Google Drive falla de formas variadas (token expirado, cuota, red). El test de reintentos debe simular los tres, no solo una excepcion generica.
- La retencion local no debe borrar clips con `upload_state='pending'`: se perderia el clip antes de subirlo.

</specifics>

<deferred>
## Deferred Ideas

- Grabacion continua con segmentacion → no esta en v2.0; el modelo es por evento.
- Transcodificacion a H.264 para reducir tamano → v2.1. El codec actual (`mp4v`) se mantiene.
- Reproduccion con scrubbing por evento en el timeline → Fase 30.
- Almacenamiento en S3 o NAS → Fase 37.
</deferred>

---
*Context creado: 2026-08-07*
