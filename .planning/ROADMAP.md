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
- [ ] **Phase 3: Deteccion de personas con YOLO26n** - Inferencia por frame en hilo separado con bounding boxes y confianza en overlay
- [ ] **Phase 4: Tracking y conteo por linea virtual** - ByteTrack para IDs persistentes + LineZone para contar cruces con direccion
- [ ] **Phase 5: Persistencia en SQLite** - Almacenamiento asincrono de eventos de cruce con WAL mode y recuperacion tras reinicio
- [ ] **Phase 6: API REST y WebSocket** - Endpoints de estadisticas, eventos recientes y stream de eventos en tiempo real
- [ ] **Phase 7: Dashboard web** - Interfaz completa con video, contador, histograma, eventos y estado de conexion
- [ ] **Phase 8: Configuracion centralizada y arranque** - pydantic-settings con .env validado y arranque con un solo comando

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
  1. El stream MJPEG en `/video_feed` muestra rectangulos de deteccion sobre las personas visibles en la escena
  2. Cada bounding box muestra el porcentaje de confianza de la deteccion como texto en overlay
  3. La inferencia YOLO26n se ejecuta en un hilo separado del de captura: si la deteccion tarda mas de lo normal, el stream de captura sigue funcionando sin bloqueo
  4. El nivel de confianza minimo (default 0.45) filtra detecciones de baja calidad: solo aparecen boxes cuando la confianza supera el umbral
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [ ] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias

### Phase 4: Tracking y conteo por linea virtual
**Goal**: El sistema cuenta personas que cruzan una linea virtual sin contar dos veces a la misma persona
**Depends on**: Phase 3
**Requirements**: CNT-01, CNT-02, CNT-03
**Success Criteria** (what must be TRUE):
  1. Cada persona detectada recibe un ID persistente visible en el overlay (ByteTrack): al moverse por la escena mantiene el mismo ID
  2. Una linea virtual es visible en el stream y el sistema cuenta los cruces en ambas direcciones (entrada/salida)
  3. Una persona que permanece parada frente a la camara durante 1 minuto genera exactamente 0 o 1 evento de cruce, no cientos
  4. Los eventos de cruce registran timestamp y direccion, listos para persistir
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [ ] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias

### Phase 5: Persistencia en SQLite
**Goal**: Los eventos de cruce se almacenan en SQLite y sobreviven reinicios del servidor
**Depends on**: Phase 4
**Requirements**: DB-01, DB-02, DB-03
**Success Criteria** (what must be TRUE):
  1. Cada cruce de linea se inserta en la base de datos SQLite con timestamp y direccion, verificable con una consulta SQL directa
  2. Los accesos a la base de datos son asincronos (aiosqlite): el event loop de FastAPI nunca se bloquea esperando una escritura
  3. Tras reiniciar el servidor con `uvicorn`, los eventos historicos anteriores al reinicio siguen disponibles y consultables
  4. La base de datos opera en WAL mode, permitiendo lecturas concurrentes mientras el hilo de deteccion escribe
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [ ] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias

### Phase 6: API REST y WebSocket
**Goal**: Los datos de deteccion y conteo son accesibles via endpoints HTTP y eventos en tiempo real
**Depends on**: Phase 5
**Requirements**: API-01, API-02, API-03, API-04
**Success Criteria** (what must be TRUE):
  1. `GET /api/stats` devuelve un JSON con el total de personas hoy y el conteo desglosado por hora de las ultimas 24 horas
  2. `GET /api/events` devuelve los ultimos 50 eventos con timestamp y direccion en formato JSON
  3. Una conexion WebSocket a `WS /ws` recibe un mensaje JSON cada vez que alguien cruza la linea, con timestamp, total del dia y ultimo conteo horario
  4. `GET /video_feed` sirve el stream MJPEG procesado (con bounding boxes y linea virtual) y cierra limpiamente al desconectar el cliente
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [ ] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias

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
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [ ] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias
**UI hint**: yes

### Phase 8: Configuracion centralizada y arranque
**Goal**: El sistema se configura desde un unico fichero .env validado y arranca con un solo comando
**Depends on**: Phase 7
**Requirements**: CFG-01, CFG-02
**Success Criteria** (what must be TRUE):
  1. Todas las variables configurables (URL camara, confianza YOLO, puerto del servidor, ruta de la base de datos) se leen de un fichero `.env` y se validan al arrancar con pydantic-settings: si falta una variable critica, el servidor muestra un error claro y no arranca
  2. El sistema completo arranca con un unico comando `uvicorn backend.main:app --reload` y sirve el dashboard funcional
  3. El fichero `.env.example` documenta cada variable con su valor por defecto y una descripcion breve
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — Estructura de ficheros, .gitignore, requirements.txt, .env.example, config.py
- [ ] 01-02-PLAN.md — Crear venv con Python 3.12 e instalar dependencias

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Scaffolding y entorno | 2/2 | Complete   | 2026-04-16 |
| 2. Captura RTSP y stream MJPEG | 2/2 | Complete   | 2026-04-17 |
| 3. Deteccion de personas con YOLO26n | 0/? | Not started | - |
| 4. Tracking y conteo por linea virtual | 0/? | Not started | - |
| 5. Persistencia en SQLite | 0/? | Not started | - |
| 6. API REST y WebSocket | 0/? | Not started | - |
| 7. Dashboard web | 0/? | Not started | - |
| 8. Configuracion centralizada y arranque | 0/? | Not started | - |

---
*Roadmap created: 2026-04-16*
*Last updated: 2026-04-16*
