# Roadmap: Tapo Dashboard

## Overview

Desde la captura RTSP cruda hasta un dashboard funcional con deteccion y conteo de personas en tiempo real. El orden de construccion sigue la cadena de datos: primero asegurar que llegan frames de la camara, luego detectar personas, luego contar cruces, persistir eventos, exponer APIs, y finalmente renderizar el dashboard. La configuracion y el hardening cierran el proyecto.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Scaffolding y entorno** - Estructura de proyecto, entorno virtual, dependencias y configuracion base (completed 2026-04-16)
- [x] **Phase 2: Captura RTSP y stream MJPEG** - Hilo de captura con drain de buffer, reconexion automatica y endpoint MJPEG crudo (completed 2026-04-17)
- [x] **Phase 3: Deteccion de personas con YOLO26n** - Inferencia por frame con bounding boxes y confianza en overlay (completed 2026-04-17)
- [x] **Phase 4: Tracking y conteo por linea virtual** - ByteTrack para IDs persistentes + LineZone para contar cruces con direccion (completed 2026-04-17)
- [x] **Phase 5: Persistencia en SQLite** - Almacenamiento asincrono de eventos de cruce con WAL mode y recuperacion tras reinicio (completed 2026-04-18)
- [x] **Phase 6: API REST y WebSocket** - Endpoints de estadisticas, eventos recientes y stream de eventos en tiempo real (completed 2026-04-18)
- [x] **Phase 7: Dashboard web** - Interfaz completa con video, contador, histograma, eventos y estado de conexion (completed 2026-04-18)
- [x] **Phase 8: Configuracion centralizada y arranque** - pydantic-settings con .env validado y arranque con un solo comando (completed 2026-04-16)
- [x] **Phase 9: Reconocimiento facial y enrolamiento** - Identificar personas con face-recognition, guardar embeddings, comparar rostros detectados (completed 2026-04-19)
- [x] **Phase 10: Grabacion de video y upload a Google Drive** - Grabar clips .mp4 cuando se detecte persona, subir automaticamente a Google Drive via API (completed 2026-04-19)
- [x] **Phase 11: Rendimiento y estabilidad** - Migrar a YOLO26n, usar stream2 (720p), watchdog para reinicio automático (completed 2026-04-23)
- [x] **Phase 12: Alertas y notificaciones** - Push/email al detectar desconocido + Web Push API en el navegador (completed 2026-04-26)
- [x] **Phase 13: Detección avanzada e historial** - Zonas de interés configurables, detección de intrusión por horario, galería de capturas por individuo (completed 2026-04-25)
- [x] **Phase 14: Seguridad** - Autenticación básica en el dashboard, HTTPS con certificado autofirmado (completed 2026-04-23)
- [x] **Phase 15: UI y exportación** - Filtros en tabla de eventos, vista de clips reproducible desde dashboard, exportar CSV de eventos (completed 2026-04-26)
- [x] **Phase 16: Operaciones** - Docker Compose, rotación automática de eventos antiguos (>30 días), métricas de salud (CPU/RAM/FPS) en dashboard (completed 2026-05-01)

## Phase Details

### Phase 1: Scaffolding y entorno
**Goal**: El proyecto tiene estructura de directorios, entorno virtual funcional y todas las dependencias instaladas
**Depends on**: Nothing (first phase)
**Requirements**: Ninguno (infraestructura de soporte)
**Success Criteria** (what must be TRUE):
  1. El entorno virtual de Python 3.12 se activa y contiene todas las dependencias del stack (FastAPI, OpenCV, ultralytics, supervision, aiosqlite, SQLAlchemy, pydantic-settings, uvicorn)
  2. La estructura de directorios del proyecto existe (backend/, frontend/, tests/) y el comando `python -c "import fastapi, cv2, ultralytics, supervision"` no da error
  3. Un fichero `.env.example` documenta todas las variables de configuracion necesarias con valores por defecto
**Plans:** 2/2 plans complete

Plans:
- [x] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [x] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias

### Phase 2: Captura RTSP y stream MJPEG
**Goal**: El usuario ve el video en directo de la camara Tapo C212 en su navegador, sin procesamiento de deteccion
**Depends on**: Phase 1
**Requirements**: CAP-01, CAP-02, CAP-03
**Success Criteria** (what must be TRUE):
  1. Al abrir `http://localhost:8000/video_feed` en el navegador se ve el stream de la camara en tiempo real con latencia inferior a 2 segundos
  2. Si se desconecta la camara o la red, el sistema se reconecta automaticamente con backoff exponencial sin crashear
  3. El hilo de captura drena el buffer RTSP activamente: el video nunca acumula retraso progresivo aunque se deje corriendo horas
  4. Desconectar el navegador libera los recursos del generador MJPEG sin dejar procesos zombi
**Plans:** 2/2 plans complete

Plans:
- [x] 02-01-PLAN.md — RTSPStream con drain thread, reconexion y tests unitarios
- [x] 02-02-PLAN.md — FastAPI app con endpoint /video_feed MJPEG y verificacion manual

### Phase 3: Deteccion de personas con YOLO26n
**Goal**: El stream MJPEG muestra bounding boxes con nivel de confianza sobre cada persona detectada, sin degradar la fluidez del video
**Depends on**: Phase 2
**Requirements**: DET-01, DET-02, DET-03, DET-04
**Success Criteria** (what must be TRUE):
  1. El stream MJPEG en `/video_feed` muestra rectangulos de deteccion sobre las personas visibles en la escena ✓
  2. Cada bounding box muestra el porcentaje de confianza de la deteccion como texto en overlay ✓
  3. La inferencia YOLO26n se ejecuta en un hilo separado del de captura ✓
  4. El nivel de confianza minimo (default 0.45) filtra detecciones de baja calidad ✓
**Plans:** Completado (inline via stream.py + detector.py)

Artifacts:
- ✓ `backend/detector.py` — PersonDetector con YOLO inference y annotate
- ✓ `backend/stream.py` — Integracion en capture_loop con PersonDetector

### Phase 4: Tracking y conteo por linea virtual
**Goal**: El sistema cuenta personas que cruzan una linea virtual sin contar dos veces a la misma persona
**Depends on**: Phase 3
**Requirements**: CNT-01, CNT-02, CNT-03
**Success Criteria** (what must be TRUE):
  1. Cada persona detectada recibe un ID persistente visible en el overlay (ByteTrack) ✓
  2. Una linea virtual es visible en el stream y el sistema cuenta los cruces en ambas direcciones ✓
  3. Una persona parada genera exactamente 0 o 1 evento de cruce ✓
  4. Los eventos de cruce registran timestamp y direccion, listos para persistir ✓
**Plans:** Completado (inline via tracker.py + stream.py)

Artifacts:
- ✓ `backend/tracker.py` — PersonTracker con ByteTrack + LineZone
- ✓ `backend/stream.py` — Integracion en capture_loop con PersonTracker
- ✓ `backend/config.py` — Variables de linea virtual (line_start_x, line_start_y, line_end_x, line_end_y)

### Phase 5: Persistencia en SQLite
**Goal**: Los eventos de cruce se almacenan en SQLite y sobreviven reinicios del servidor
**Depends on**: Phase 4
**Requirements**: DB-01, DB-02, DB-03
**Success Criteria** (what must be TRUE):
  1. Cada cruce de linea se inserta en la base de datos SQLite con timestamp y direccion, verificable con una consulta SQL directa
  2. Los accesos a la base de datos son asincronos (aiosqlite): el event loop de FastAPI nunca se bloquea esperando una escritura
  3. Tras reiniciar el servidor con `uvicorn`, los eventos historicos anteriores al reinicio siguen disponibles y consultables
  4. La base de datos opera en WAL mode, permitiendo lecturas concurrentes mientras el hilo de deteccion escribe
**Plans:** Completado (inline)

Artifacts:
- ✓ `backend/database.py` — CrossingEvent model, init_db (WAL), insert_event, get_recent_events, get_stats_today
- ✓ `backend/tracker.py` — update() devuelve (tracked, crossings) con timestamp y dirección
- ✓ `backend/stream.py` — enqueue crossings via loop.call_soon_threadsafe
- ✓ `backend/main.py` — init_db en lifespan, drain task, /api/stats, /api/events

Status: COMPLETE (completed 2026-04-18)

### Phase 6: API REST y WebSocket
**Goal**: Los datos de deteccion y conteo son accesibles via endpoints HTTP y eventos en tiempo real
**Depends on**: Phase 5
**Requirements**: API-01, API-02, API-03, API-04
**Success Criteria** (what must be TRUE):
  1. `GET /api/stats` devuelve un JSON con el total de personas hoy y el conteo desglosado por hora de las ultimas 24 horas
  2. `GET /api/events` devuelve los ultimos 50 eventos con timestamp y direccion en formato JSON
  3. Una conexion WebSocket a `WS /ws` recibe un mensaje JSON cada vez que alguien cruza la linea, con timestamp, total del dia y ultimo conteo horario
  4. `GET /video_feed` sirve el stream MJPEG procesado (con bounding boxes y linea virtual) y cierra limpiamente al desconectar el cliente ✓
**Plans:** Parcial (2/4 endpoints implementados)

Artifacts:
- ✓ `GET /video_feed` — MJPEG stream con bounding boxes y linea virtual
- ✓ `GET /detections` — Ultimas detecciones en formato JSON
- ✓ `GET /counts` — Conteos acumulados (in/out/total)
- ✗ `GET /api/stats` — Pendiente (requiere Phase 5)
- ✗ `GET /api/events` — Pendiente (requiere Phase 5)
- ✗ `WS /ws` — Pendiente (requiere Phase 5)

Status: IN PROGRESS (esperando Phase 5)

### Phase 7: Dashboard web
**Goal**: El usuario accede a un panel unico donde ve el video en directo, el contador de personas, el histograma de actividad y los eventos recientes
**Depends on**: Phase 6
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06
**Success Criteria** (what must be TRUE):
  1. El dashboard en `http://localhost:8000` muestra el video en directo con bounding boxes, el contador de personas del dia, el histograma de las ultimas 24 horas y la tabla de eventos recientes, todo en una sola pagina
  2. Cuando alguien cruza la linea, el contador y la tabla de eventos se actualizan en tiempo real sin recargar la pagina (via WebSocket)
  3. El histograma de barras (Chart.js) muestra las 24 horas con la actividad de cada hora y se actualiza al recibir nuevos eventos
  4. El dashboard muestra un indicador visual de estado de conexion a la camara (online/reconectando) que cambia en tiempo real
  5. El dashboard usa modo oscuro por defecto y es legible en movil, tablet y PC sin scroll horizontal
**Plans:** Pending (stub: `frontend/index.html` es placeholder)

Artifacts:
- ⚠ `frontend/index.html` — Placeholder, se implementa cuando Phase 6 esté completo
- ⚠ `frontend/app.js` — Stub, necesita WebSocket listener y Chart.js integration

Status: NOT STARTED (bloqueado por Phase 6)
**UI hint**: yes

### Phase 8: Configuracion centralizada y arranque
**Goal**: El sistema se configura desde un unico fichero .env validado y arranca con un solo comando
**Depends on**: Phase 7 (planejado, pero config.py ya implementado independientemente)
**Requirements**: CFG-01, CFG-02
**Success Criteria** (what must be TRUE):
  1. Todas las variables configurables se leen de un fichero `.env` y se validan al arrancar con pydantic-settings ✓
  2. El sistema arranca con `uvicorn backend.main:app --reload` (parcial: falta la integracion de base de datos y WebSocket)
  3. El fichero `.env.example` documenta cada variable con su valor por defecto y una descripcion breve ✓
**Plans:** Completado (inline via config.py)

Artifacts:
- ✓ `backend/config.py` — BaseSettings con todas las variables: CAMERA_URL, YOLO_CONFIDENCE, DB_PATH, HOST, PORT, tapo_host, tapo_user, tapo_pass, linea virtual coords
- ✓ `.env.example` — Plantilla documentada en Phase 1

Status: DONE (infraestructura base lista; persistencia de config en DB pendiente Phase 5)

### Phase 9: Reconocimiento facial y enrolamiento
**Goal**: El sistema identifica y diferencia personas por su rostro, no solo cuenta individuos anonimos
**Depends on**: Phase 7 (dashboard existente)
**Requirements**: FR-01, FR-02, FR-03
**Success Criteria** (what must be TRUE):
  1. Existe un endpoint POST /api/enroll_face para registrar un nuevo rostro con nombre, acepta imagen o frame actual ✓
  2. Cada deteccion de rostro se compara contra la base de datos de rostros enrolados usando distancia euclidiana (tolerance 0.55) ✓
  3. El dashboard muestra el nombre de la persona identificada o "Unknown" si no coincide ✓
  4. Los eventos de cruce registran el nombre o ID de la persona, no solo timestamp ✓
**Plans:** Completado (inline)

Artifacts:
- ✓ `backend/recognizer.py` — PersonRecognizer: embeddings 128-dim, cache por tracker_id, enroll_named_face
- ✓ `backend/database.py` — Columna person_name en CrossingEvent, migración ALTER TABLE
- ✓ `backend/stream.py` — Propagación de person_name en crossing events via _person_cache
- ✓ `backend/main.py` — POST /api/enroll_face, GET /persons, integración recognizer en RTSPStream
- ✓ `frontend/index.html` — Panel «Personas conocidas», modal de enrolamiento, nombre en eventos
- ✓ `tests/test_phase9.py` — 15 tests: tracker, DB, recognizer, API

Status: COMPLETE (completed 2026-04-19)

### Phase 10: Grabacion de video y upload a Google Drive
**Goal**: Grabar clips .mp4 cuando se detecte actividad y subirlos automaticamente a Google Drive
**Depends on**: Phase 7 (detecciones disponibles)
**Requirements**: REC-01, REC-02, REC-03, REC-04
**Success Criteria** (what must be TRUE):
  1. Cuando se detecta una persona, comienza una grabacion de video .mp4 (mp4v) en `data/clips/` ✓
  2. La grabacion termina 5 segundos despues de que la ultima persona sale del frame ✓
  3. El archivo grabado se sube automaticamente a la carpeta «Grabaciones Tapo» (ID: 1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir) via Google Drive API v3 OAuth2 ✓
  4. Tras upload exitoso el archivo local se elimina; en caso de fallo se reintenta con backoff exponencial hasta 3 veces ✓
**Plans:** Completado (inline)

Artifacts:
- ✓ `backend/recorder.py` — ClipRecorder: hilo daemon, VideoWriter mp4v, tail_secs, descarta clips < 4 KB
- ✓ `backend/gdrive.py` — DriveUploader: cola thread-safe, OAuth2 desktop flow, reintentos 2^n, on_uploaded/on_failed
- ✓ `backend/database.py` — Modelo Recording + insert_recording / update_recording / get_recent_recordings
- ✓ `backend/config.py` — 6 nuevas variables: clips_dir, gdrive_folder_id, gdrive_credentials_path, gdrive_token_path, recording_fps, recording_tail_secs
- ✓ `backend/main.py` — Lifespan wiring: ClipRecorder + DriveUploader con asyncio.run_coroutine_threadsafe
- ✓ `frontend/index.html` — Panel «Grabaciones» con estado en tiempo real (pending/uploaded/failed) via WebSocket
- ✓ `tests/test_phase10.py` — 14 tests: ClipRecorder, DriveUploader, DB recordings, API /api/recordings

**Pendiente manual**:
- Descargar `credentials.json` de Google Cloud Console (OAuth 2.0 → Desktop app) y colocarlo en la raíz del proyecto
- En el primer arranque con credentials.json presente, se abrirá el navegador para autorizar; el token se guarda en `data/token.json`
- Sin credentials.json el sistema funciona pero no sube clips a Drive

Status: COMPLETE (completed 2026-04-19)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Scaffolding y entorno | 2/2 | Complete   | 2026-04-16 |
| 2. Captura RTSP y stream MJPEG | 2/2 | Complete   | 2026-04-17 |
| 3. Deteccion de personas con YOLO26n | Done (inline) | Complete   | 2026-04-17 |
| 4. Tracking y conteo por linea virtual | Done (inline) | Complete   | 2026-04-17 |
| 5. Persistencia en SQLite | Done (inline) | Complete | 2026-04-18 |
| 6. API REST y WebSocket | Done (inline) | Complete | 2026-04-18 |
| 7. Dashboard web | Done (inline) | Complete | 2026-04-18 |
| 8. Configuracion centralizada y arranque | Done (inline) | Complete   | 2026-04-16 |
| 9. Reconocimiento facial y enrolamiento | Done (inline) | Complete | 2026-04-19 |
| 10. Grabacion de video y upload a Google Drive | Done (inline) | Complete | 2026-04-19 |
| 11. Rendimiento y estabilidad | Done (inline) | Complete | 2026-04-23 |
| 12. Alertas y notificaciones | Done (inline) | Complete | 2026-04-26 |
| 13. Deteccion avanzada e historial | — | Complete | 2026-04-25 |
| 14. Seguridad | Done (inline) | Complete | 2026-04-23 |
| 15. UI y exportacion | Done (inline) | Complete | 2026-04-26 |
| 16. Operaciones | Done (inline) | Complete | 2026-05-01 |

---
*Roadmap created: 2026-04-16*
*Last updated: 2026-05-01*
*Status snapshot: 16/16 phases complete — proyecto finalizado.*

---

# Milestone v2.0 — Plataforma de Video Analytics

**Planificado:** 2026-08-07
**Origen:** `propuesta_mejora/mejoras_inmediatas.md` (25 puntos) + `propuesta_mejora/vulnerabilidades.md`
**Especificación técnica de referencia:** `propuesta_mejora/SPEC_v2.md`
**Fases:** 17 a 38 (22 fases, 4 bloques)

## Overview v2.0

La v1.2 resolvió el pipeline funcional completo (RTSP → YOLO → ByteTrack → LineZone → reconocimiento → eventos → SQLite → grabación → Drive → dashboard). La v2.0 ataca el siguiente cuello de botella: **acoplamiento**. Todo el procesamiento vive hoy dentro de `RTSPStream` (534 LOC, 8 responsabilidades) y toda la interfaz dentro de `index.html` (1843 LOC).

El orden de construcción va de dentro hacia fuera: primero se desacopla el pipeline y se introduce el motor de eventos (Fase A), sobre esa base se mejora la percepción con ArcFace, ReID y análisis de comportamiento (Fase B), después se construye la interfaz de operaciones que expone todo eso (Fase C), y por último se prepara la escalabilidad multi-cámara (Fase D).

**Invariante del milestone:** cada fase deja el sistema operativo. Los cambios estructurales entran tras un flag con default = comportamiento v1, que se invierte al cerrar la fase.

## Phases v2.0

### Bloque A — Robustez

- [x] **Phase 17: Frame Broker y Capture Worker** — Fan-out latest-frame; la captura nunca espera a la IA (completed 2026-08-07)
- [x] **Phase 18: Workers desacoplados e inferencia adaptativa** — Detección, streaming y grabación como workers con FPS objetivo propios (completed 2026-08-08)
- [x] **Phase 19: Event Engine, Rule Engine y esquema de datos v2** — Eventos tipados + reglas YAML + separación detections/events (completed 2026-08-09; checkpoints de migración de BD real y validación de reglas en vivo pendientes de cámara real)
- [x] **Phase 20: Grabación con pre/post-buffer y metadatos** — Ningún clip empieza después del evento (completed 2026-08-09; checkpoint de validación visual en vivo pendiente de cámara real)
- [x] **Phase 21: Observabilidad y latencia end-to-end** — Métricas Prometheus, frames descartados, latencia real (completed 2026-08-09; checkpoint de coste de instrumentación y línea base de 30 min pendiente de cámara real)
- [x] **Phase 22: Deuda de seguridad y gestión de memoria** — Eliminar pickle, validar model path, operación 24/7 estable (completed 2026-08-09; checkpoint de prueba de resistencia de 8 h pendiente de cámara real)

### Bloque B — Inteligencia artificial

- [x] **Phase 23: Migración a InsightFace/ArcFace con quality gating** — Embeddings 512D + filtro de calidad de rostro (completed 2026-08-10; checkpoint de tasa de aciertos vs dlib pendiente de cámara real)
- [x] **Phase 24: Identidad temporal — votación y máquina de estados** — UNKNOWN → CANDIDATE → CONFIRMED → TEMPORARILY_LOST
- [x] **Phase 25: Re-identificación de personas (ReID)** — Continuidad de identidad sin cara visible (completed 2026-08-15; checkpoint de tasa de falsos positivos con cámara real pendiente)
- [x] **Phase 26: Análisis de comportamiento** — Merodeo, carrera, inmovilidad, aglomeración, zonas
- [x] **Phase 27: Multi-clase y contexto de escena** — Objetos abandonados/retirados + estado agregado de la escena (completed 2026-08-17; checkpoint de calibración de `object_person_radius_px` y tasa de falsos positivos de `OBJECT_LEFT` pendiente de cámara real)

### Bloque C — Producto

- [ ] **Phase 28: Refactor del frontend a módulos ES** — index.html deja de contener lógica
- [x] **Phase 29: Vista de operaciones** — Centro de operaciones que responde en 3 segundos (completed 2026-08-20; checkpoint visual de Task 3 de 29-03-PLAN.md — criterios de éxito 1/4/5/6 — pendiente de verificación en persona)
- [x] **Phase 30: Event Timeline y centro de alertas** — Línea temporal accionable con miniaturas (completed 2026-08-21; checkpoint visual de Task 2 de 30-12-PLAN.md — criterios de éxito 3/4/5 del ROADMAP y el ciclo completo de silenciado — diferido por falta de cámara real)
- [ ] **Phase 31: Vista de analítica** — Ocupación, heatmap, ranking de personas, tendencias
- [ ] **Phase 32: Vista de cámara y configuración visual** — Operar y configurar sin tocar .env
- [ ] **Phase 33: Editores visuales de zonas, líneas y reglas** — Dibujar sobre el vídeo, componer reglas por formulario
- [ ] **Phase 34: Tests E2E e integración del pipeline** — Playwright + pipeline completo con fuente sintética

### Bloque D — Escalabilidad

- [ ] **Phase 35: CameraManager y camera_id transversal** — El código deja de asumir una única cámara
- [ ] **Phase 36: Multi-cámara en runtime y UI** — Añadir cámaras sin reiniciar; vista mosaico
- [ ] **Phase 37: Backends opcionales — PostgreSQL y Redis** — Repositorios intercambiables, SQLite sigue siendo default
- [ ] **Phase 38: Worker de inferencia en GPU (opcional)** — Aprovechar GPU si existe, fallback limpio a CPU

## Phase Details v2.0

### Phase 17: Frame Broker y Capture Worker
**Goal**: La captura RTSP produce frames a ritmo nativo y nunca espera a ningún consumidor
**Depends on**: Nothing (primera fase v2.0)
**Requirements**: PIPE-01, PIPE-02, PIPE-03
**Success Criteria**:
  1. `FrameBroker.publish()` nunca bloquea, demostrado con un suscriptor que duerme 1 s por frame
  2. Con 3 suscriptores de velocidad distinta, solo el lento acumula frames descartados
  3. `CaptureWorker` contiene únicamente captura, reescalado y publicación (cero referencias a YOLO, reconocimiento, zonas o heatmap)
  4. El stream MJPEG mantiene la fluidez de v1.2 (verificación visual A/B)
  5. `GET /api/v2/cameras/{id}/health` devuelve fps, connected, reconnects y last_frame_age_s
**Spec**: SPEC_v2.md §5.1, §5.2
**Plans:** 2/2 plans complete — `.planning/phases/17-frame-broker-y-capture-worker/`

Plans:
- [x] 17-01-PLAN.md — FrameBroker: fan-out latest-frame con slot por suscriptor
- [x] 17-02-PLAN.md — CaptureWorker puro, flag PIPELINE_V2, endpoints de salud (comparativa A/B + soak de 30 min contra camara real: ver 17-02-SUMMARY.md)

### Phase 18: Workers desacoplados e inferencia adaptativa
**Goal**: Detección, tracking, streaming y grabación corren como workers independientes con FPS objetivo propios
**Depends on**: Phase 17
**Requirements**: PIPE-04, PIPE-05, PIPE-06, DET-05
**Success Criteria**:
  1. DetectionWorker, StreamingWorker y RecordingWorker arrancan y fallan de forma independiente; el supervisor reinicia el caído y emite DEGRADED_MODE
  2. Con cámara a 20 FPS y objetivo de detección 8 FPS, el vídeo se sirve a ~20 FPS y la detección corre a 8±1
  3. `AdaptiveRate` baja el FPS de detección cuando la latencia de inferencia supera el presupuesto
  4. El uso de CPU en escena con una persona baja respecto a v1.2, con medición documentada antes/después
  5. Ningún hilo hace await y ninguna corrutina hace inferencia (verificado por test de arquitectura)
**Spec**: SPEC_v2.md §5.3
**Plans:** 2/2 plans complete — `.planning/phases/18-workers-desacoplados-e-inferencia-adaptativa/`

Plans:
- [x] 18-01-PLAN.md — AdaptiveRate, TrackRegistry y DetectionWorker
- [x] 18-02-PLAN.md — Streaming/Recording/Recognition workers, supervisor y retirada de RTSPStream (checkpoint completo, ver 18-02-CHECKPOINT.md — 3/4 criterios con evidencia, 1h de latencia inconcluso por corte externo de camara)

### Phase 19: Event Engine, Rule Engine y esquema de datos v2
**Goal**: El sistema deja de razonar en detecciones y pasa a emitir eventos tipados evaluados contra reglas
**Depends on**: Phase 18
**Requirements**: EVT-01..EVT-05, RULE-01..RULE-04, DB-10..DB-14
**Success Criteria**:
  1. El catálogo de 22 EventType existe y `Event` valida con Pydantic
  2. El EventBus entrega el mismo objeto Event a persistencia, WebSocket y RuleEngine
  3. Las 3 reglas de ejemplo de rules.yaml cargan, validan y disparan sus acciones en test de integración
  4. Una regla mal formada se desactiva con log de error legible sin tumbar el servidor
  5. `debounce_secs` reduce 10 eventos idénticos en 5 s a 1 sola acción
  6. Las detecciones no se persisten fila a fila: `detection_stats` tiene 1 fila por minuto
  7. La migración de `crossing_events` a `events` conserva todas las filas y es idempotente
**Spec**: SPEC_v2.md §6, §7
**Plans:** 2/2 plans complete — `.planning/phases/19-event-engine-y-esquema-de-datos-v2/`

Plans:
- [x] 19-01-PLAN.md — Catalogo de eventos, EventBus, esquema v2 y migraciones (Task 5 checkpoint — migración de BD real — pendiente)
- [x] 19-02-PLAN.md — EventEngine, RuleEngine, acciones e integracion (Task 5 checkpoint — validación de reglas en vivo — pendiente)

### Phase 20: Grabación con pre/post-buffer y metadatos
**Goal**: Ningún clip empieza después del evento y cada clip es auditable
**Depends on**: Phase 19
**Requirements**: CLIP-01..CLIP-07
**Success Criteria**:
  1. Con pre_buffer_secs=10, el clip contiene imagen desde 10 s antes del evento (verificado con timestamp quemado)
  2. El post-buffer añade el margen configurado tras la última detección
  3. Cada recording tiene sha256, duration_s, size_bytes, thumbnail_path, trigger_event_id, reason y upload_state
  4. La miniatura se sirve por `/api/v2/recordings/{id}/thumbnail`
  5. El pre-buffer se mantiene por debajo de 40 MB de RAM con la configuración por defecto
  6. Retención local 7 días y subida a Drive solo de eventos con severity != info
  7. Tres fallos consecutivos de Drive no bloquean el pipeline y el cuarto intento tiene éxito
**Spec**: SPEC_v2.md ADR-07
**Plans:** 2/2 plans complete — `.planning/phases/20-grabacion-con-pre-post-buffer/`

Plans:
- [x] 20-01-PLAN.md — RingFrameBuffer y RecordingWorker con pre/post-buffer
- [x] 20-02-PLAN.md — Metadatos, miniaturas, cola de subida y retencion (Task 4 checkpoint — validación en vivo — pendiente)

### Phase 21: Observabilidad y latencia end-to-end
**Goal**: El sistema es diagnosticable sin adjuntar un depurador
**Depends on**: Phase 20
**Requirements**: OBS-01..OBS-06
**Success Criteria**:
  1. `/metrics` expone el catálogo completo en formato Prometheus
  2. `/api/v2/metrics` devuelve el mismo snapshot en JSON y el dashboard lo pinta
  3. `frames_dropped_total` se incrementa de forma demostrable al ralentizar el detector
  4. `e2e_latency_seconds` se calcula desde captured_at hasta el envío por WebSocket, con tres tramos desglosados
  5. Una latencia inyectada de 2 s se refleja en el percentil 95
  6. La instrumentación añade menos del 2% de CPU
**Spec**: SPEC_v2.md §8.4
**Plans:** 1/1 plans complete — `.planning/phases/21-observabilidad-y-latencia-e2e/`

Plans:
- [x] 21-01-PLAN.md — Registro de metricas, LatencyTracker, instrumentacion y endpoints (Task 5 checkpoint — coste y línea base de 30 min — pendiente)

### Phase 22: Deuda de seguridad y gestión de memoria
**Goal**: Cerrar los puntos de seguridad pendientes y garantizar operación 24/7 sin crecimiento de memoria
**Depends on**: Phase 21
**Requirements**: SEC-15, SEC-16, PIPE-07
**Success Criteria**:
  1. `grep -rn "pickle" backend/` no devuelve resultados en código de producción
  2. `yolo_model_path` valida extensión y contención dentro del proyecto; un path externo aborta el arranque con mensaje claro
  3. Todos los endpoints v2 tienen rate limiting y cotas de paginación
  4. Prueba de 8 h con RSS estable dentro de ±10% tras la primera hora
  5. Toda estructura con crecimiento potencial tiene política de expiración verificada por test
  6. `queue_depth` permanece acotado durante la prueba de resistencia
**Spec**: SPEC_v2.md §1.3
**Plans:** 1/1 plans complete — `.planning/phases/22-seguridad-y-gestion-de-memoria/`

Plans:
- [x] 22-01-PLAN.md — Erradicar pickle, validar model path, cotas de memoria y soak test (Task 4 checkpoint — prueba de resistencia de 8 h — pendiente)

### Phase 23: Migración a InsightFace/ArcFace con quality gating
**Goal**: El reconocimiento facial usa embeddings ArcFace 512D y descarta caras que no valen la pena procesar
**Depends on**: Phase 22
**Requirements**: FACE-01..FACE-06
**Success Criteria**:
  1. ✅ Puerta de entrada superada (2026-08-09): `insightface` + `onnxruntime` instalan sin compilar y ejecutan una inferencia real (buffalo_s, 5 submodelos ONNX, embedding 512D confirmado) en el entorno Windows del proyecto — Plan A de ADR-02 viable, ver `23-CONTEXT.md`
  2. ✅ FaceEngine produce embeddings 512D L2-normalizados con buffalo_s
  3. ✅ FaceQualityAssessor rechaza y etiqueta el motivo para caras pequeñas, borrosas y de pose extrema
  4. ✅ IdentityIndex resuelve una búsqueda sobre 1.000 identidades en menos de 5 ms
  5. ✅ `scripts/reenroll.py` reconstruye las identidades desde data/gallery/ y reporta migradas vs no migradas
  6. ⧗ La tasa de aciertos sobre un set de validación de 50+ recortes reales es igual o mejor que dlib, documentada en el SUMMARY — pendiente, checkpoint 23-02 Task 4, requiere cámara real y galería poblada
  7. ✅ `dlib` y `face-recognition` desaparecen de requirements.txt
**Spec**: SPEC_v2.md ADR-02, ADR-03, §5.4
**Plans:** 2/2 plans complete — `.planning/phases/23-migracion-a-insightface-arcface-con-quality-gating/`

Plans:
- [x] 23-01-PLAN.md — FaceEngine, FaceQualityAssessor, IdentityIndex (aislados, sin tocar recognizer.py)
- [x] 23-02-PLAN.md — Integración en recognizer.py, re-enrolamiento real, retirada de dlib (Task 4 checkpoint — benchmark real con cámara — pendiente)

### Phase 24: Identidad temporal — votación y máquina de estados
**Goal**: Una persona es identificada tras evidencia coherente, no tras un frame afortunado
**Depends on**: Phase 23
**Requirements**: FACE-07..FACE-11
**Success Criteria**:
  1. Los 4 estados (UNKNOWN, CANDIDATE, CONFIRMED, TEMPORARILY_LOST) y sus transiciones están testeados uno a uno
  2. Una secuencia de 200 frames de una persona conocida emite exactamente un PERSON_RECOGNIZED
  3. Con embeddings ruidosos alternando dos identidades, el track permanece en CANDIDATE y no confirma ninguna
  4. Cero identidades duplicadas tras pérdida y recuperación de track
  5. La revalidación tras 120 s funciona y tres fallos consecutivos emiten IDENTITY_LOST
  6. Las inferencias faciales por minuto con una persona estática bajan al menos un 70% respecto a la Phase 23
**Spec**: SPEC_v2.md §5.5
**Plans:** 6/6 plans complete — `.planning/phases/24-identidad-temporal-votaci-n-y-m-quina-de-estados/`

Plans:
- [x] 24-01-PLAN.md — TemporalVoter + IdentityState y los 5 parámetros de configuración (wave 1)
- [x] 24-02-PLAN.md — IdentityStateMachine: 4 estados, revalidación, herencia de identidad y gate de FACE-11 (wave 2)
- [x] 24-03-PLAN.md — recognizer.py expone el score y retira su votación interna; tests de cota (wave 3)
- [x] 24-04-PLAN.md — identity_state en TrackRegistry y EventEngine.emit_identity (wave 3)
- [x] 24-05-PLAN.md — Cableado del pipeline: RecognitionWorker, manager y medición del criterio 6 (wave 4)
- [x] 24-06-PLAN.md — Puerta de fase: suite completa y trazabilidad de los 6 criterios (wave 5)

### Phase 25: Re-identificación de personas (ReID)
**Goal**: El sistema mantiene la identidad cuando la cara no es visible
**Depends on**: Phase 24
**Requirements**: REID-01..REID-04
**Success Criteria**:
  1. ReIDEngine produce embeddings 512D con osnet_x0_25 ONNX en menos de 20 ms por crop en CPU
  2. TrackGallery hereda identidad de un track cerrado hace menos de 15 s con similitud > 0.7, y no la hereda si hay conflicto con un track activo
  3. Una persona identificada que se gira de espaldas 10 s y vuelve conserva su person_id sin UNKNOWN_PERSON intermedio
  4. Dos personas distintas con ropa similar no se fusionan; tasa de falsos positivos documentada
     — **verificado en su parte determinista** (`TEST_gallery_does_not_merge_distinct_identities`);
     la tasa real con personas reales queda pendiente del checkpoint manual de cámara (25-06 Task 2)
  5. ReID corre como máximo 1 vez cada 2 s por track
**Spec**: SPEC_v2.md ADR-04, §5.6
**Plans**: 6/6 plans complete (5 waves)
Plans:
- [x] 25-01-PLAN.md — Modelo ONNX de OSNet (descarga + sha256 + eje de batch dinámico) y `ReIDEngine`
- [x] 25-02-PLAN.md — `IdentityStateMachine.on_reid_result()`: herencia de identidad por apariencia
- [x] 25-03-PLAN.md — `TrackGallery`: ventana, umbral, conflicto, intervalo y expiración acotada
- [x] 25-04-PLAN.md — Vía ReID dentro de `RecognitionWorker` (criterios 3 y 5, modo solo-observación)
- [x] 25-05-PLAN.md — Parámetros `reid_*` en `config.py` + cableado en `manager.py` y `main.py`
- [x] 25-06-PLAN.md — Puerta de fase: trazabilidad de los 5 criterios + checkpoint del criterio 4 (diferido, ver 25-06-SUMMARY.md)

### Phase 26: Análisis de comportamiento
**Goal**: El sistema responde a qué está ocurriendo, no solo a si hay alguien
**Depends on**: Phase 25
**Requirements**: BEH-01..BEH-05
**Success Criteria**:
  1. Se emiten LOITERING, RUNNING, IMMOBILE, CROWD_DETECTED, ZONE_ENTERED y ZONE_EXITED con umbrales configurables
  2. Seis trayectorias sintéticas producen exactamente el evento esperado y ninguno más
  3. Cada evento incluye en payload las magnitudes que lo justifican
  4. El historial por track está acotado y no crece con el tiempo de sesión
  5. Los eventos de comportamiento son usables como `when.event` en rules.yaml sin cambios en el RuleEngine
**Spec**: SPEC_v2.md §5.7
**Plans**: 5/5 plans complete (4 waves)
Plans:
- [x] 26-01-PLAN.md — `BehaviorAnalyzer` (dominio puro): agregados O(1), las 4 reglas con latch por episodio y doble guarda de expiración
- [x] 26-02-PLAN.md — 10 umbrales `behavior_*`/`loiter_*`/`run_*`/`immobile_*`/`crowd_*` en `config.py` + `validate_behavior_params`
- [x] 26-03-PLAN.md — `EventEngine.emit_behavior()` + tiempo de permanencia (`duration_s`) en `ZONE_EXITED`
- [x] 26-04-PLAN.md — Cableado: `DetectionWorker._analyze_behavior`, construcción fuera de la factoría en `manager.py`, propagación en `main.py`
- [x] 26-05-PLAN.md — Criterio 5 (`when.event` desde YAML real) + puerta de fase + checkpoint de calibración con cámara (diferido, ver 26-05-SUMMARY.md)

### Phase 27: Multi-clase y contexto de escena
**Goal**: Capa semántica: además de personas, el sistema entiende objetos y describe el estado de la escena
**Depends on**: Phase 26
**Requirements**: BEH-06..BEH-09
**Success Criteria**:
  1. Las clases detectadas (persona, bicicleta, coche, moto, mochila, maleta) son configurables desde la UI
  2. OBJECT_LEFT se emite tras 60 s de objeto inmóvil sin persona asociada cerca
  3. OBJECT_REMOVED se emite cuando un objeto estable desaparece con una persona cerca
  4. `/api/v2/analytics/context` devuelve el estado agregado con nivel de actividad calculado contra la media móvil de 7 días
  5. Escena con mochila abandonada emite un único OBJECT_LEFT; con la persona presente no lo emite
  6. Activar 6 clases no incrementa la latencia de inferencia más de un 15%
**Spec**: SPEC_v2.md Phase 27
**Plans**: 11/11 plans complete (6 waves)
Plans:
- [x] 27-01-PLAN.md — ObjectAnalyzer (dominio puro): OBJECT_LEFT/OBJECT_REMOVED con doble guarda de expiración
- [x] 27-02-PLAN.md — D-03 (yolo26n.pt) + 14 parámetros object_*/context_* + PersonDetector.set_classes()
- [x] 27-03-PLAN.md — ObjectTracker + partición por clase antes del tracker (riesgo ByteTrack)
- [x] 27-04-PLAN.md — DetectionStatRepo.hourly_baseline() + kind en zonas legacy
- [x] 27-05-PLAN.md — EventEngine.emit_object() + config_changed()
- [x] 27-06-PLAN.md — Cableado del ObjectAnalyzer en DetectionWorker + construcción fuera de la factoría
- [x] 27-07-PLAN.md — GET/PUT /api/v2/detection/classes con persistencia en app_config
- [x] 27-08-PLAN.md — Overlay de objetos en el feed MJPEG
- [x] 27-09-PLAN.md — GET /api/v2/analytics/context (BEH-08/BEH-09)
- [x] 27-10-PLAN.md — Panel de clases activas en el dashboard
- [x] 27-11-PLAN.md — Puerta de fase: trazabilidad de los 6 criterios + checkpoint de calibración

### Phase 28: Refactor del frontend a módulos ES
**Goal**: index.html deja de contener lógica y el frontend pasa a ser mantenible
**Depends on**: Phase 21
**Requirements**: OPS-01, OPS-02, OPS-03
**Success Criteria**:
  1. La estructura css/ + js/{views,components} existe e index.html no contiene lógica: cero `<script>`/`<style>` inline, solo shell (marcado, contenedores con `id`, `<link>` a los 3 CSS y un único `<script type="module" src="/static/js/app.js">`). El fichero real de partida mide 2.038 líneas (no 1.843 — cifra desactualizada desde antes de la Fase 27-10) y su `<body>` sin `<style>`/`<script>` ya mide 667 líneas; el criterio de líneas no es aplicable a `index.html` en sí (ver 28-CONTEXT.md/28-RESEARCH.md Pitfall 1) — se mide por ausencia de lógica inline, no por recuento
  2. `frontend/js/app.js` es el punto de entrada real, no un placeholder
  3. Ningún módulo supera las 300 líneas y cada uno declara su responsabilidad
  4. Paridad funcional total con v1.2, con checklist manual firmada en el SUMMARY
  5. FastAPI sirve /static y el SRI de Chart.js se mantiene
  6. La carga inicial no supera 1 s en LAN
**Spec**: SPEC_v2.md ADR-08, §8.2
**Plans**: 8/9 plans complete (5 waves) — falta el checkpoint manual 28-09
Plans:
- [x] 28-01-PLAN.md — Contrato pytest (tests/test_frontend_modules.py) + extracción CSS (base/layout/components)
- [x] 28-02-PLAN.md — views/dashboard.js (núcleo) + views/dashboard-events.js (chart + eventos, ciclo de import real)
- [x] 28-03-PLAN.md — views/dashboard-ptz.js + views/dashboard-observability.js
- [x] 28-04-PLAN.md — components/videoCanvas.js (dueño de #rec-badge/#res-badge) + components/zoneEditor.js
- [x] 28-05-PLAN.md — components/eventCard.js + components/detectionClasses.js
- [x] 28-06-PLAN.md — components/personGallery.js + js/api.js
- [x] 28-07-PLAN.md — js/websocket.js + verificación cruzada de imports contra 28-02/28-04/28-05
- [x] 28-08-PLAN.md — js/app.js (bootstrap real) + reescritura de index.html a shell puro + suite completa en verde (525/525 + 2 skipped)
- [ ] 28-09-PLAN.md — Checkpoint: checklist de paridad funcional + medición de carga en LAN (pendiente, requiere verificación manual del usuario)

### Phase 29: Vista de operaciones
**Goal**: La pantalla principal responde en 3 segundos a las tres preguntas del operador
**Depends on**: Phase 28
**Requirements**: OPS-04, OPS-05, OPS-06
**Success Criteria**:
  1. El layout de operaciones es responsive hasta 1366×768 sin scroll
  2. La barra superior refleja el estado real del pipeline (online / degradado / offline)
  3. El panel "Personas ahora" lista identidades activas con su estado de confirmación
  4. El overlay de tracks se dibuja sobre canvas alimentado por WebSocket a 2 Hz, sin re-renderizar el MJPEG
  5. El WebSocket reconecta automáticamente con backoff y la UI lo indica sin recargar
  6. Un observador no familiarizado identifica si hay alerta activa en menos de 3 s
**Spec**: SPEC_v2.md §8.3
**Plans:** 3 plans (2 waves) — `.planning/phases/29-vista-de-operaciones/`

Plans:
- [ ] 29-01-PLAN.md — Backend: CameraPipeline.get_person_boxes() + _tracks_broadcast_loop() a 2Hz por /ws (OPS-05)
- [ ] 29-02-PLAN.md — Frontend: canvas overlay de tracks sobre #video-feed, sincronizado con object-fit:cover (OPS-05)
- [ ] 29-03-PLAN.md — Frontend: header de 3 estados, paneles "Personas ahora"/"Alertas activas", checkpoint visual (OPS-04, OPS-06)

### Phase 30: Event Timeline y centro de alertas
**Goal**: Sustituir la tabla plana de eventos por una línea temporal accionable
**Depends on**: Phase 29
**Requirements**: OPS-07..OPS-11
**Success Criteria**:
  1. Cada entrada muestra hora, severidad, descripción legible, zona, miniatura y acciones
  2. Los filtros combinables se resuelven en servidor con paginación por cursor
  3. 10.000 eventos son navegables con scroll infinito sin degradación perceptible
  4. Un evento nuevo aparece en menos de 1 s sin recargar
  5. "Marcar como persona" precarga el crop y actualiza retroactivamente los eventos del track
  6. El centro de alertas agrupa, permite silenciar por regla y muestra qué regla disparó
**Spec**: SPEC_v2.md §8.1
**Plans:** 12/12 plans complete — `.planning/phases/30-event-timeline-y-centro-de-alertas/`

Plans:
- [x] 30-01-PLAN.md — Pipeline de eventos ordenado: `match`/`run_actions`, `payload.rules` y mensaje WS `type:"event"` (OPS-10, OPS-11)
- [x] 30-02-PLAN.md — Índice `idx_events_ts_id`, migración de esquema v3 y `EventRepo.query()` multi-tipo/regla + `count()` (OPS-09)
- [x] 30-03-PLAN.md — Alcance de track, asignación retroactiva y mapa evento→grabación (OPS-08)
- [x] 30-04-PLAN.md — Snapshot de evento: recorte en disco, mount `/snapshots`, throttle y retención (OPS-07, OPS-08)
- [x] 30-05-PLAN.md — Router `/api/v2/events`: lista paginada con `media`/`total`, detalle, track-scope y assign-person (OPS-07..09)
- [x] 30-06-PLAN.md — Centro de alertas backend: agrupación por regla y silenciado en `app_config` (OPS-11)
- [x] 30-07-PLAN.md — Marcado y estilos: card de línea temporal, campana, cajón, modal; retirada del card de eventos (OPS-07, OPS-08, OPS-11)
- [x] 30-08-PLAN.md — `timeline-row.js` + `timeline.js`: fila, filtros en servidor, cursor, virtualización y evento en vivo (OPS-07..10)
- [x] 30-09-PLAN.md — `alertCenter.js`: badge, cajón, silenciado y top-3 de la Fase 29 (OPS-11)
- [x] 30-10-PLAN.md — Cableado: `case 'event'` en el WebSocket, arranque en `app.js` y `LOCKED_JS` (OPS-07, OPS-10, OPS-11)
- [x] 30-11-PLAN.md — "Marcar como persona": recorte precargado, aviso de alcance y repintado en sitio (OPS-08)
- [x] 30-12-PLAN.md — Puerta de fase: criterio 3 medido con 10.000 eventos, suite completa y checkpoint visual (OPS-07..11)

### Phase 31: Vista de analítica
**Goal**: Convertir el histórico en información operativa
**Depends on**: Phase 30
**Requirements**: OPS-12..OPS-15
**Success Criteria**:
  1. La vista muestra personas por hora, ocupación por zona, heatmap, ranking de personas y tendencias con % de variación
  2. El selector de rango cubre hoy, 7 días, 30 días y personalizado
  3. Las agregaciones se calculan en SQL: el payload de 30 días es menor de 100 KB
  4. Las consultas sobre 100.000 eventos responden en menos de 500 ms
  5. Exportación CSV/JSON del rango visible
**Spec**: SPEC_v2.md Phase 31

### Phase 32: Vista de cámara y configuración visual
**Goal**: Operar y configurar el sistema sin tocar .env
**Depends on**: Phase 31
**Requirements**: OPS-16..OPS-20, SET-01..SET-04
**Success Criteria**:
  1. La vista Cámara muestra live view, FPS, latencia e2e, CPU, RAM, FPS de detector y estado RTSP
  2. El árbol de configuración completo (Cámara, Detección, Tracking, Reconocimiento, Zonas, Reglas, Alertas, Almacenamiento) está implementado
  3. Los cambios se persisten en app_config y se aplican en caliente cuando el parámetro lo permite
  4. Un valor fuera de rango devuelve 422 con mensaje legible mostrado junto al campo
  5. Existe "Restaurar valores por defecto" por sección
  6. Cada cambio genera un evento CONFIG_CHANGED con el diff
  7. La precedencia app_config > .env > default está documentada y testeada
**Spec**: SPEC_v2.md Phase 32

### Phase 33: Editores visuales de zonas, líneas y reglas
**Goal**: Dibujar zonas y componer reglas sin escribir YAML ni fracciones de coordenadas
**Depends on**: Phase 32
**Requirements**: OPS-21..OPS-24, RULE-05
**Success Criteria**:
  1. Se pueden dibujar, mover, editar vértices y borrar polígonos sobre el frame de vídeo con coordenadas normalizadas
  2. Lo mismo para líneas de conteo, con indicador visual de dirección
  3. Las zonas soportan tipo (counting, restricted, exclusion) y horario propio
  4. El editor de reglas compone el esquema completo por formularios y valida en servidor antes de guardar
  5. `POST /api/v2/rules/{id}/test` evalúa la regla contra los últimos 500 eventos y reporta cuántos habrían disparado
  6. Cambiar una zona recarga el pipeline en menos de 1 s sin reiniciar
  7. Zonas dibujadas a 720p siguen siendo correctas al cambiar a 1080p
**Spec**: SPEC_v2.md §6.4

### Phase 34: Tests E2E e integración del pipeline
**Goal**: Una red de seguridad que cubra el camino completo, no solo unidades aisladas
**Depends on**: Phase 33
**Requirements**: TEST-01..TEST-05
**Success Criteria**:
  1. Test de integración FakeRTSP → Detector mock → Tracker → EventEngine → RuleEngine → BD → WebSocket, ejecutable en CI sin cámara real
  2. Playwright cubre los 10 escenarios de frontend definidos en la spec
  3. La suite completa corre en menos de 5 minutos
  4. GitHub Actions ejecuta unit + integración en cada push y E2E en cada PR
  5. Cobertura superior al 80% en backend/events/, backend/pipeline/ y backend/perception/
  6. Los endpoints /api/* v1 quedan formalmente marcados como deprecados
**Spec**: SPEC_v2.md Phase 34

### Phase 35: CameraManager y camera_id transversal
**Goal**: El código deja de asumir una única cámara, aunque solo haya una
**Depends on**: Phase 34
**Requirements**: SCALE-01..SCALE-04
**Success Criteria**:
  1. CameraPipeline encapsula el pipeline de una cámara y CameraManager gestiona N con arranque/parada independientes
  2. camera_id es NOT NULL en events, tracks, detection_stats, recordings, zones, lines y system_metrics
  3. Todos los endpoints v2 aceptan camera_id con default a la única cámara existente
  4. Dos pipelines contra la misma URL RTSP producen eventos con camera_id distintos
  5. Parar una cámara no afecta a la otra ni al servidor
  6. Regresión cero en un despliegue de una sola cámara
**Spec**: SPEC_v2.md Phase 35

### Phase 36: Multi-cámara en runtime y UI
**Goal**: Añadir, configurar y visualizar varias cámaras desde la interfaz
**Depends on**: Phase 35
**Requirements**: SCALE-05..SCALE-08
**Success Criteria**:
  1. El CRUD de cámaras desde la UI arranca la cámara nueva sin reiniciar el servidor
  2. Existe selector de cámara y vista mosaico con N streams
  3. Cada cámara tiene zonas, líneas y reglas propias; las reglas admiten camera "*"
  4. La UI muestra el coste estimado de CPU por cámara y advierte al superar el umbral
  5. La analítica agrega por cámara y en total
  6. Con 2 cámaras durante 1 h, el FPS no baja del 80% del valor mono-cámara o la degradación queda documentada
**Spec**: SPEC_v2.md Phase 36

### Phase 37: Backends opcionales — PostgreSQL y Redis
**Goal**: Permitir escalar almacenamiento y bus sin reescribir el código
**Depends on**: Phase 36
**Requirements**: SCALE-09, SCALE-10
**Success Criteria**:
  1. Todo el acceso a datos pasa por storage/repositories.py, verificado por grep
  2. Cambiar DATABASE_URL a postgresql+asyncpg funciona sin cambios de código y la suite de repositorio pasa contra ambos motores
  3. EventBus tiene implementaciones InProcessBus y RedisBus intercambiables; sin Redis el sistema arranca en modo in-process
  4. SQLite sigue siendo el default y la ruta soportada de primera clase
  5. Está documentado cuándo merece la pena migrar
**Spec**: SPEC_v2.md ADR-06

### Phase 38: Worker de inferencia en GPU (opcional)
**Goal**: Aprovechar GPU si existe, sin degradar la ruta CPU
**Depends on**: Phase 37
**Requirements**: SCALE-11, SCALE-12
**Success Criteria**:
  1. La GPU disponible (CUDA / DirectML) se detecta automáticamente con log claro del dispositivo elegido
  2. YOLO, ArcFace y OSNet usan el proveedor adecuado, seleccionable por configuración
  3. Con GPU, el FPS de detección sostenible sube al menos 3× respecto a CPU, medido y documentado
  4. Sin GPU, el comportamiento es idéntico al de la Phase 37
  5. Un fallo de inicialización de GPU cae a CPU automáticamente y emite DEGRADED_MODE
  6. El batching multi-cámara en GPU es opcional y desactivable
**Spec**: SPEC_v2.md Phase 38

## Execution Order v2.0

```
A: 17 → 18 → 19 → 20 → 21 → 22
                      ↓
B:                   23 → 24 → 25 → 26 → 27
                      ↓
C:        28 (tras 21) → 29 → 30 → 31 → 32 → 33 → 34
                                                   ↓
D:                                                35 → 36 → 37 → 38
```

La Phase 28 solo depende de la 21, por lo que el bloque C puede solaparse con el bloque B si se trabaja en paralelo. Las fases 29-33 asumen que B está completa para mostrar identidad, comportamiento y contexto en la interfaz.

Estado real y detallado de cada fase (completa/pendiente/sin planificar,
checkpoints, fechas): ver `.planning/STATE.md` § Estado de las 22 fases de
v2.0 — es la fuente única, para no mantener dos tablas de progreso
envejeciendo a ritmos distintos.

---
*Milestone v2.0 planificado: 2026-08-07*
*Especificación de referencia: propuesta_mejora/SPEC_v2.md*
*Status snapshot: 6/22 fases v2.0 completas — bloque A (fases 17-22) cerrado en código y tests; 4 checkpoints con cámara real pendientes de acción del usuario (ver .planning/STATE.md).*
