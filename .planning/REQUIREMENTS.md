# Requirements: Tapo Dashboard

**Defined:** 2026-04-16
**Core Value:** Ver en tiempo real cuantas personas han pasado frente a la camara y a que horas hay mas actividad, con el video en vivo integrado en el mismo panel.

## v1 Requirements

### Captura de video

- [x] **CAP-01**: El sistema captura el stream RTSP de `rtsp://192.168.1.132:554/stream1` en un hilo dedicado sin acumular buffer
- [x] **CAP-02**: El sistema se reconecta automaticamente al stream RTSP si la camara cae o la red se interrumpe (backoff exponencial)
- [x] **CAP-03**: El sistema retransmite el video en vivo al navegador via MJPEG con latencia < 2 s en LAN

### Deteccion de personas

- [ ] **DET-01**: El sistema detecta personas en cada frame usando YOLO26n con confianza configurable (default 0.45)
- [ ] **DET-02**: Los bounding boxes de las personas detectadas se dibujan sobre el frame MJPEG visible en el dashboard
- [ ] **DET-03**: El nivel de confianza de cada deteccion se muestra en el overlay del bounding box
- [ ] **DET-04**: La deteccion se ejecuta en un hilo separado al de captura para no bloquear el stream

### Conteo de personas

- [ ] **CNT-01**: El sistema asigna IDs persistentes a cada persona mediante ByteTrack (supervision) para evitar dobles conteos
- [ ] **CNT-02**: El sistema cuenta cruces de una linea virtual configurable usando supervision LineZone
- [ ] **CNT-03**: Cada cruce registra timestamp y direccion (entrada/salida) en SQLite

### Persistencia de datos

- [ ] **DB-01**: La base de datos SQLite almacena todos los eventos de cruce con timestamp (WAL mode habilitado)
- [ ] **DB-02**: Los accesos a SQLite son asincronos (aiosqlite) para no bloquear el event loop de FastAPI
- [ ] **DB-03**: El sistema recupera los eventos historicos correctamente tras reinicio

### API y tiempo real

- [ ] **API-01**: El endpoint `GET /api/stats` devuelve: total de personas hoy, conteo por hora de las ultimas 24 h
- [ ] **API-02**: El endpoint `GET /api/events` devuelve los ultimos 50 eventos con timestamp y direccion
- [ ] **API-03**: El WebSocket `WS /ws` emite en tiempo real cada evento de cruce con: timestamp, total del dia, ultimo conteo horario
- [ ] **API-04**: El endpoint `GET /video_feed` sirve el stream MJPEG con correcto cierre al desconectar el cliente

### Dashboard web

- [ ] **UI-01**: El dashboard muestra el video en directo con bounding boxes en tiempo real
- [ ] **UI-02**: El dashboard muestra el contador total de personas del dia actual, actualizado en tiempo real via WebSocket
- [ ] **UI-03**: El dashboard muestra un histograma de barras con la actividad por hora de las ultimas 24 h (Chart.js)
- [ ] **UI-04**: El dashboard muestra una tabla con los ultimos eventos de cruce (hora, direccion)
- [ ] **UI-05**: El dashboard usa modo oscuro por defecto y es legible desde cualquier dispositivo de la LAN
- [ ] **UI-06**: El dashboard muestra un indicador de estado de conexion a la camara (online / reconectando)

### Configuracion

- [ ] **CFG-01**: Todas las variables configurables (URL camara, confianza YOLO, puerto servidor, ruta BD) se gestionan desde un fichero `.env` con validacion al arrancar (pydantic-settings)
- [ ] **CFG-02**: El sistema arranca con un unico comando: `uvicorn backend.main:app --reload`

## v2 Requirements

### Analisis avanzado

- **ANLZ-01**: Heatmap de actividad por hora del dia y dia de la semana
- **ANLZ-02**: Exportacion de historico a CSV
- **ANLZ-03**: Thumbnail de la ultima deteccion guardado en disco

### Configuracion avanzada

- **CFG-03**: Posicion de la linea virtual ajustable desde la interfaz web sin reiniciar
- **CFG-04**: Ajuste del umbral de confianza YOLO desde la interfaz web

## Out of Scope

| Feature | Razon |
|---------|-------|
| Grabacion de video a disco | El objetivo es estadisticas, no almacenamiento. Anade complejidad de retencion y espacio. |
| Notificaciones push / alertas | Fuera del alcance de v1; el dashboard es observacional |
| Autenticacion de usuarios | Dashboard local de red privada, sin exposicion publica |
| Acceso remoto / tunel | Diseno exclusivamente para LAN |
| Multiples camaras | Una camara en v1; multi-camara requiere refactor de arquitectura |
| WebRTC | MJPEG es suficiente para LAN y elimina complejidad de senalizacion |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CAP-01 | Phase 2 | Complete |
| CAP-02 | Phase 2 | Complete |
| CAP-03 | Phase 2 | Complete |
| DET-01 | Phase 3 | Pending |
| DET-02 | Phase 3 | Pending |
| DET-03 | Phase 3 | Pending |
| DET-04 | Phase 3 | Pending |
| CNT-01 | Phase 4 | Pending |
| CNT-02 | Phase 4 | Pending |
| CNT-03 | Phase 4 | Pending |
| DB-01 | Phase 5 | Pending |
| DB-02 | Phase 5 | Pending |
| DB-03 | Phase 5 | Pending |
| API-01 | Phase 6 | Pending |
| API-02 | Phase 6 | Pending |
| API-03 | Phase 6 | Pending |
| API-04 | Phase 6 | Pending |
| UI-01 | Phase 7 | Pending |
| UI-02 | Phase 7 | Pending |
| UI-03 | Phase 7 | Pending |
| UI-04 | Phase 7 | Pending |
| UI-05 | Phase 7 | Pending |
| UI-06 | Phase 7 | Pending |
| CFG-01 | Phase 8 | Pending |
| CFG-02 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-04-16*
*Last updated: 2026-04-16 after roadmap creation*
