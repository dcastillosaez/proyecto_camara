# Requirements: Tapo Dashboard

**Defined:** 2026-04-16
**Core Value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo integrado en el mismo panel.

## v1 Requirements

### Captura de vídeo

- [ ] **CAP-01**: El sistema captura el stream RTSP de `rtsp://192.168.1.132:554/stream1` en un hilo dedicado sin acumular buffer
- [ ] **CAP-02**: El sistema se reconecta automáticamente al stream RTSP si la cámara cae o la red se interrumpe (backoff exponencial)
- [ ] **CAP-03**: El sistema retransmite el vídeo en vivo al navegador vía MJPEG con latencia < 2 s en LAN

### Detección de personas

- [ ] **DET-01**: El sistema detecta personas en cada frame usando YOLO26n con confianza configurable (default 0.45)
- [ ] **DET-02**: Los bounding boxes de las personas detectadas se dibujan sobre el frame MJPEG visible en el dashboard
- [ ] **DET-03**: El nivel de confianza de cada detección se muestra en el overlay del bounding box
- [ ] **DET-04**: La detección se ejecuta en un hilo separado al de captura para no bloquear el stream

### Conteo de personas

- [ ] **CNT-01**: El sistema asigna IDs persistentes a cada persona mediante ByteTrack (supervision) para evitar dobles conteos
- [ ] **CNT-02**: El sistema cuenta cruces de una línea virtual configurable usando supervision LineZone
- [ ] **CNT-03**: Cada cruce registra timestamp y dirección (entrada/salida) en SQLite

### Persistencia de datos

- [ ] **DB-01**: La base de datos SQLite almacena todos los eventos de cruce con timestamp (WAL mode habilitado)
- [ ] **DB-02**: Los accesos a SQLite son asíncronos (aiosqlite) para no bloquear el event loop de FastAPI
- [ ] **DB-03**: El sistema recupera los eventos históricos correctamente tras reinicio

### API y tiempo real

- [ ] **API-01**: El endpoint `GET /api/stats` devuelve: total de personas hoy, conteo por hora de las últimas 24 h
- [ ] **API-02**: El endpoint `GET /api/events` devuelve los últimos 50 eventos con timestamp y dirección
- [ ] **API-03**: El WebSocket `WS /ws` emite en tiempo real cada evento de cruce con: timestamp, total del día, último conteo horario
- [ ] **API-04**: El endpoint `GET /video_feed` sirve el stream MJPEG con correcto cierre al desconectar el cliente

### Dashboard web

- [ ] **UI-01**: El dashboard muestra el vídeo en directo con bounding boxes en tiempo real
- [ ] **UI-02**: El dashboard muestra el contador total de personas del día actual, actualizado en tiempo real vía WebSocket
- [ ] **UI-03**: El dashboard muestra un histograma de barras con la actividad por hora de las últimas 24 h (Chart.js)
- [ ] **UI-04**: El dashboard muestra una tabla con los últimos eventos de cruce (hora, dirección)
- [ ] **UI-05**: El dashboard usa modo oscuro por defecto y es legible desde cualquier dispositivo de la LAN
- [ ] **UI-06**: El dashboard muestra un indicador de estado de conexión a la cámara (online / reconectando)

### Configuración

- [ ] **CFG-01**: Todas las variables configurables (URL cámara, confianza YOLO, puerto servidor, ruta BD) se gestionan desde un fichero `.env` con validación al arrancar (pydantic-settings)
- [ ] **CFG-02**: El sistema arranca con un único comando: `uvicorn backend.main:app --reload`

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
| Grabación de vídeo a disco | El objetivo es estadísticas, no almacenamiento. Añade complejidad de retención y espacio. |
| Notificaciones push / alertas | Fuera del alcance de v1; el dashboard es observacional |
| Autenticación de usuarios | Dashboard local de red privada, sin exposición pública |
| Acceso remoto / túnel | Diseño exclusivamente para LAN |
| Múltiples cámaras | Una cámara en v1; multi-cámara requiere refactor de arquitectura |
| WebRTC | MJPEG es suficiente para LAN y elimina complejidad de señalización |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CAP-01 | Phase 1 | Pending |
| CAP-02 | Phase 1 | Pending |
| CAP-03 | Phase 1 | Pending |
| DET-01 | Phase 2 | Pending |
| DET-02 | Phase 2 | Pending |
| DET-03 | Phase 2 | Pending |
| DET-04 | Phase 2 | Pending |
| CNT-01 | Phase 3 | Pending |
| CNT-02 | Phase 3 | Pending |
| CNT-03 | Phase 3 | Pending |
| DB-01 | Phase 3 | Pending |
| DB-02 | Phase 3 | Pending |
| DB-03 | Phase 3 | Pending |
| API-01 | Phase 4 | Pending |
| API-02 | Phase 4 | Pending |
| API-03 | Phase 4 | Pending |
| API-04 | Phase 4 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| UI-04 | Phase 5 | Pending |
| UI-05 | Phase 5 | Pending |
| UI-06 | Phase 5 | Pending |
| CFG-01 | Phase 6 | Pending |
| CFG-02 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-16*
*Last updated: 2026-04-16 after initial definition*
