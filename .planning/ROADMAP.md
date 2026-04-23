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
- [ ] **Phase 11: Rendimiento y estabilidad** - Migrar a YOLO26n, usar stream2 (720p), watchdog para reinicio automático de uvicorn
- [ ] **Phase 12: Alertas y notificaciones** - Push/email al detectar desconocido + Web Push API en el navegador
- [ ] **Phase 13: Detección avanzada e historial** - Zonas de interés configurables, detección de intrusión por horario, galería de capturas por individuo
- [ ] **Phase 14: Seguridad** - Autenticación básica en el dashboard, HTTPS con certificado autofirmado
- [ ] **Phase 15: UI y exportación** - Filtros en tabla de eventos, vista de clips reproducible desde dashboard, exportar CSV de eventos
- [ ] **Phase 16: Operaciones** - Docker Compose, rotación automática de eventos antiguos (>30 días), métricas de salud (CPU/RAM/FPS) en dashboard

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
**Goal**: El usuario ve el video en directo de la camara Tapo C220 en su navegador, sin procesamiento de deteccion
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
| 11. Rendimiento y estabilidad | — | Pending | — |
| 12. Alertas y notificaciones | — | Pending | — |
| 13. Deteccion avanzada e historial | — | Pending | — |
| 14. Seguridad | — | Pending | — |
| 15. UI y exportacion | — | Pending | — |
| 16. Operaciones | — | Pending | — |

---
*Roadmap created: 2026-04-16*
*Last updated: 2026-04-23*
*Status snapshot: 10/16 phases complete — v1.0 terminado. Fases 11-16 pendientes (v1.1+).*
