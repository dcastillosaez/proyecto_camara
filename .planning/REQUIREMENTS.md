# Requirements: Tapo Dashboard

**Defined:** 2026-04-16
**Core Value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo, reconocimiento facial y grabación automática integrados en el mismo panel.

## v1 Requirements

### Captura de video

- [x] **CAP-01**: El sistema captura el stream RTSP de `rtsp://192.168.1.132:554/stream1` en un hilo dedicado sin acumular buffer
- [x] **CAP-02**: El sistema se reconecta automáticamente al stream RTSP si la cámara cae o la red se interrumpe (backoff exponencial)
- [x] **CAP-03**: El sistema retransmite el vídeo en vivo al navegador vía MJPEG con latencia < 2 s en LAN

### Detección de personas

- [x] **DET-01**: El sistema detecta personas en cada frame usando YOLOv8n con confianza configurable (default 0.45)
- [x] **DET-02**: Los bounding boxes de las personas detectadas se dibujan sobre el frame MJPEG visible en el dashboard
- [x] **DET-03**: El nivel de confianza de cada detección se muestra en el overlay del bounding box
- [x] **DET-04**: La detección se ejecuta en un hilo separado al de captura para no bloquear el stream

### Conteo de personas

- [x] **CNT-01**: El sistema asigna IDs persistentes a cada persona mediante ByteTrack (supervision) para evitar dobles conteos
- [x] **CNT-02**: El sistema cuenta cruces de una línea virtual configurable usando supervision LineZone
- [x] **CNT-03**: Cada cruce registra timestamp y dirección (entrada/salida) en SQLite

### Persistencia de datos

- [x] **DB-01**: La base de datos SQLite almacena todos los eventos de cruce con timestamp (WAL mode habilitado)
- [x] **DB-02**: Los accesos a SQLite son asíncronos (aiosqlite) para no bloquear el event loop de FastAPI
- [x] **DB-03**: El sistema recupera los eventos históricos correctamente tras reinicio

### API y tiempo real

- [x] **API-01**: El endpoint `GET /api/stats` devuelve: total de personas hoy, conteo por hora de las últimas 24 h
- [x] **API-02**: El endpoint `GET /api/events` devuelve los últimos 50 eventos con timestamp, dirección y nombre de persona
- [x] **API-03**: El WebSocket `WS /ws` emite en tiempo real cada evento de cruce con: timestamp, total del día, último conteo horario
- [x] **API-04**: El endpoint `GET /video_feed` sirve el stream MJPEG con correcto cierre al desconectar el cliente

### Dashboard web

- [x] **UI-01**: El dashboard muestra el vídeo en directo con bounding boxes en tiempo real
- [x] **UI-02**: El dashboard muestra el contador total de personas del día actual, actualizado en tiempo real vía WebSocket
- [x] **UI-03**: El dashboard muestra un histograma de barras con la actividad por hora de las últimas 24 h (Chart.js)
- [x] **UI-04**: El dashboard muestra una tabla con los últimos eventos de cruce (hora, dirección, nombre de persona)
- [x] **UI-05**: El dashboard usa modo oscuro por defecto y es legible desde cualquier dispositivo de la LAN
- [x] **UI-06**: El dashboard muestra un indicador de estado de conexión a la cámara (online / reconectando)

### Configuración

- [x] **CFG-01**: Todas las variables configurables se gestionan desde un fichero `.env` con validación al arrancar (pydantic-settings)
- [x] **CFG-02**: El sistema arranca con un único comando: `uvicorn backend.main:app`

### Reconocimiento facial

- [x] **FR-01**: Endpoint `POST /api/enroll_face` registra un rostro con nombre; acepta imagen subida o frame actual de la cámara
- [x] **FR-02**: Cada detección de rostro se compara contra la BD de rostros enrolados (distancia euclidiana, tolerancia 0.55); se asigna nombre si coincide
- [x] **FR-03**: Los eventos de cruce registran el nombre de la persona identificada (o null si desconocida)

### Grabación y almacenamiento en nube

- [x] **REC-01**: Cuando se detecta actividad, comienza grabación .mp4 (mp4v) en `data/clips/`
- [x] **REC-02**: La grabación termina `recording_tail_secs` (default 5 s) después de que no hay personas en frame
- [x] **REC-03**: Cada clip finalizado se sube automáticamente a la carpeta «Grabaciones Tapo» en Google Drive vía OAuth2; el archivo local se elimina tras upload exitoso
- [x] **REC-04**: Si el upload falla, se reintenta con backoff exponencial (hasta 3 intentos); si todos fallan se marca como `failed` en BD

## v2 Requirements

### Análisis avanzado

- **ANLZ-01**: Heatmap de actividad por hora del día y día de la semana
- **ANLZ-02**: Exportación de histórico a CSV
- **ANLZ-03**: Thumbnail de la última detección guardado en disco

### Configuración avanzada

- **CFG-03**: Posición de la línea virtual ajustable desde la interfaz web sin reiniciar
- **CFG-04**: Ajuste del umbral de confianza YOLO desde la interfaz web

## Out of Scope

| Feature | Razón |
|---------|-------|
| Notificaciones push / alertas | Fuera del alcance de v1; el dashboard es observacional |
| Autenticación de usuarios | Dashboard local de red privada, sin exposición pública |
| Acceso remoto / túnel | Diseño exclusivamente para LAN |
| Múltiples cámaras | Una cámara en v1; multi-cámara requiere refactor de arquitectura |
| WebRTC | MJPEG es suficiente para LAN y elimina complejidad de señalización |

## Traceability

| Requirement | Phase | Status | Tests |
|-------------|-------|--------|-------|
| CAP-01 | Phase 2 | ✓ Complete | TEST_069, TEST_070 |
| CAP-02 | Phase 2 | ✓ Complete | TEST_071, TEST_072 |
| CAP-03 | Phase 2 | ✓ Complete | TEST_075, TEST_076 |
| DET-01 | Phase 3 | ✓ Complete | TEST_030, TEST_031, TEST_033 |
| DET-02 | Phase 3 | ✓ Complete | TEST_037, TEST_039 |
| DET-03 | Phase 3 | ✓ Complete | TEST_031, TEST_037 |
| DET-04 | Phase 3 | ✓ Complete | TEST_077 |
| CNT-01 | Phase 4 | ✓ Complete | TEST_054, TEST_055, TEST_082 |
| CNT-02 | Phase 4 | ✓ Complete | TEST_080, TEST_081, TEST_057 |
| CNT-03 | Phase 4 | ✓ Complete | TEST_058, TEST_084 |
| DB-01 | Phase 5 | ✓ Complete | TEST_011, TEST_058, TEST_029 |
| DB-02 | Phase 5 | ✓ Complete | TEST_061, TEST_023 |
| DB-03 | Phase 5 | ✓ Complete | TEST_058, TEST_060 |
| API-01 | Phase 6 | ✓ Complete | TEST_011, TEST_012, TEST_013 |
| API-02 | Phase 6 | ✓ Complete | TEST_015, TEST_016, TEST_023 |
| API-03 | Phase 6 | ✓ Complete | TEST_077 |
| API-04 | Phase 6 | ✓ Complete | TEST_075, TEST_076 |
| UI-01 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-02 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-03 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-04 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-05 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-06 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| CFG-01 | Phase 8 | ✓ Complete | TEST_000, TEST_001, TEST_002, TEST_003, TEST_004 |
| CFG-02 | Phase 8 | ✓ Complete | TEST_077 |
| FR-01 | Phase 9 | ✓ Complete | TEST_066, TEST_067, TEST_068 |
| FR-02 | Phase 9 | ✓ Complete | TEST_062, TEST_063, TEST_064 |
| FR-03 | Phase 9 | ✓ Complete | TEST_058, TEST_059, TEST_060 |
| REC-01 | Phase 10 | ✓ Complete | TEST_040, TEST_041 |
| REC-02 | Phase 10 | ✓ Complete | TEST_040, TEST_042 |
| REC-03 | Phase 10 | ✓ Complete | TEST_044, TEST_045 |
| REC-04 | Phase 10 | ✓ Complete | TEST_046, TEST_047 |

**Coverage:**
- v1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0
- Complete: 31/31

---
*Requirements defined: 2026-04-16*
*Last updated: 2026-04-19 — v1.0 completo, todas las fases implementadas*
