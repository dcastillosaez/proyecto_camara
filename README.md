# Tapo Dashboard

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta y reconoce personas en tiempo real con YOLO26n, graba clips automáticos con subida a Google Drive y muestra estadísticas, alertas y métricas de sistema — todo desde un único panel accesible en red local.

## Características

- **Stream RTSP en vivo** — Conexión directa a Tapo C220 vía RTSP, retransmisión MJPEG al navegador
- **Detección de personas** — YOLO26n (38.9 ms en CPU, 31% más rápido que YOLOv8n)
- **Conteo por línea virtual** — ByteTrack + LineZone, sin dobles conteos
- **Reconocimiento facial** — Embeddings 128-dim (face-recognition/dlib) en hilo worker dedicado: no bloquea la captura RTSP. Filtros de calidad (tamaño mínimo, desenfoque, consenso de 3 muestras), ratio test por persona y re-verificación periódica con voto por mayoría
- **Grabación automática** — Clips .mp4 al detectar actividad, fin 5 s tras última detección
- **Subida a Google Drive** — Upload automático con reintentos exponenciales
- **Zonas de interés** — Polígonos configurables con overlay en el stream; conteo de ocupación en vivo y entradas acumuladas (`PolygonZone`)
- **Mapa de calor** — Acumulación de actividad por los pies de cada track, exportable como imagen
- **Detección de intrusión** — Eventos marcados como intrusión fuera del horario definido
- **Galería por persona** — Capturas automáticas, navegables por individuo
- **Alertas y notificaciones** — Webhook HTTP y Telegram al detectar desconocido/intrusión
- **Filtros y exportación** — Tabla de eventos filtrable (dirección, persona, fecha); exportar CSV
- **Reproductor de clips** — Clips reproducibles desde el dashboard sin salir de la página
- **Métricas de salud** — CPU%, RAM%, FPS y uptime actualizados cada 30 s
- **Rotación automática** — Eventos y grabaciones más antiguos de 30 días eliminados diariamente
- **Seguridad** — HTTPS con certificado autofirmado, autenticación HTTP Basic, rate limiting, SRI
- **Control PTZ** — Pan/Tilt/Zoom de la cámara desde el dashboard (driver Tapo)
- **Docker** — `docker-compose up` para arranque contenedorizado en producción

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + Uvicorn |
| Captura | OpenCV (RTSP) |
| Detección | YOLO26n (Ultralytics) |
| Tracking | supervision (ByteTrack + LineZone) |
| Reconocimiento | face-recognition + dlib |
| Grabación | cv2.VideoWriter (mp4v) |
| Cloud | Google Drive API v3 (OAuth2 desktop) |
| Base de datos | SQLite + aiosqlite + SQLAlchemy async |
| Streaming | MJPEG sobre HTTP |
| Tiempo real | WebSocket |
| Frontend | HTML + Tailwind + Chart.js |
| Contenerización | Docker + Docker Compose |
| Alertas | Webhook HTTP + Telegram Bot API |

## Requisitos

- Python 3.12+
- Cámara Tapo C220 con acceso RTSP en red local
- Dependencias en `requirements.txt`
- *(Opcional)* `credentials.json` de Google Cloud Console para subida a Drive

## Instalación — entorno local

```bash
# Crear entorno virtual
py -3.12 -m venv .venv
.venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

## Instalación — Docker

```bash
# Copiar y editar configuración
cp .env.example .env

# Arrancar
docker-compose up -d
```

El dashboard queda disponible en `http://<IP-local>:8000`.

## Configuración de Google Drive (opcional)

1. Ve a [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Crea credenciales **OAuth 2.0 → Desktop app**
3. Descarga el JSON y guárdalo como `credentials.json` en la raíz del proyecto
4. En el primer arranque se abrirá el navegador para autorizar; el token queda en `data/token.json`

Sin `credentials.json` el sistema funciona con normalidad pero no sube clips a Drive.

## Uso

### Producción (watchdog + HTTPS)

```bash
.venv\Scripts\python.exe backend/run.py
```

Dashboard disponible en `https://<IP-local>:8000`. Obtén tu IP con `ipconfig`.  
El navegador mostrará aviso de certificado autofirmado — click en «Avanzado» → «Continuar».

### Desarrollo (recarga automática, HTTP)

```bash
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Diagnóstico

```bash
# Verificar conexión RTSP
.venv\Scripts\python.exe -c "import cv2; cap=cv2.VideoCapture('rtsp://192.168.1.132:554/stream2'); print('OK' if cap.isOpened() else 'FAIL'); cap.release()"
```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Dashboard HTML |
| GET | `/video_feed` | Stream MJPEG con overlays |
| WS | `/ws` | Eventos en tiempo real |
| GET | `/api/stats` | Resumen estadísticas (últimas 24 h) |
| GET | `/api/events` | Eventos con filtros (dirección, persona, fecha, intrusión) |
| GET | `/api/events/export` | Exportar eventos filtrados a CSV |
| GET | `/api/recordings` | Clips grabados con estado de subida |
| GET | `/api/health` | Métricas de sistema: CPU%, RAM%, FPS, uptime |
| GET | `/api/zones` | Zonas de interés configuradas |
| POST | `/api/zones` | Crear / actualizar zona |
| DELETE | `/api/zones/{id}` | Eliminar zona |
| GET | `/api/zones/stats` | Ocupación actual y entradas acumuladas por zona |
| GET | `/api/heatmap` | Mapa de calor de actividad (imagen) |
| GET | `/api/alerts/config` | Configuración de alertas activa |
| POST | `/api/alerts/test` | Enviar alerta de prueba a todos los canales |
| GET | `/persons` | Personas enroladas con historial |
| POST | `/api/enroll_face` | Registrar rostro (imagen o frame actual) |
| GET | `/detections` | Detecciones y bounding boxes del frame actual |
| GET | `/counts` | Conteos acumulados in/out/total |

## Variables de entorno (`.env`)

```
# Cámara
CAMERA_URL=rtsp://192.168.1.132:554/stream2
RTSP_USER=
RTSP_PASS=
CAMERA_DRIVER=tapo

# Detección
YOLO_MODEL_PATH=yolo26n.pt
YOLO_CONFIDENCE=0.45
YOLO_IMGSZ=640
DETECT_EVERY=2
TRACKER_FRAME_RATE=15

# Base de datos
DB_PATH=data/events.db

# Servidor
HOST=0.0.0.0
PORT=8000

# Grabación
CLIPS_DIR=data/clips
RECORDING_FPS=15.0
RECORDING_TAIL_SECS=5.0

# Google Drive
GDRIVE_FOLDER_ID=1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir
GDRIVE_CREDENTIALS_PATH=credentials.json
GDRIVE_TOKEN_PATH=data/token.json

# Alertas
ALERT_WEBHOOK_URL=
ALERT_TELEGRAM_TOKEN=
ALERT_TELEGRAM_CHAT_ID=
ALERT_ON_INTRUSION=true
ALERT_ON_UNKNOWN=true
ALERT_COOLDOWN_SECS=60

# Horario (intrusión fuera de rango)
SCHEDULE_ENABLED=false
SCHEDULE_START=08:00
SCHEDULE_END=22:00

# Retención de datos
EVENTS_RETENTION_DAYS=30
RECORDINGS_RETENTION_DAYS=30
PERSONS_RETENTION_DAYS=30

# Seguridad
DASHBOARD_USER=
DASHBOARD_PASS=
SSL_CERTFILE=
SSL_KEYFILE=
```

## Tests

```bash
# Suite completa
pytest tests/ -v

# Módulo específico
pytest tests/test_phase9.py -v
```

## Arquitectura

```
Cámara RTSP
  └─► stream.py (hilo de captura)
        ├─► /video_feed (MJPEG + overlays: trazas, zonas, ocupación)
        ├─► detector.py (YOLO26n, 1 de cada N frames + DetectionsSmoother)
        │     └─► tracker.py (ByteTrack + LineZone + PolygonZone + heatmap)
        │           ├─► cola crops ─► _recognition_worker (hilo dedicado)
        │           │                    └─► recognizer.py (embeddings 128-dim)
        │           ├─► database.py — events (SQLite async)
        │           │     └─► WebSocket → dashboard
        │           └─► notifier.py — alertas (webhook + Telegram)
        └─► recorder.py (ClipRecorder — hilo daemon)
              └─► VideoWriter mp4v → data/clips/
                    └─► gdrive.py (DriveUploader — hilo)
                          └─► Google Drive API v3

FastAPI
  ├─► /api/health      — CPU / RAM / FPS / uptime
  ├─► /api/events      — filtros + CSV export
  ├─► /api/zones       — CRUD zonas + /api/zones/stats (ocupación)
  ├─► /api/heatmap     — mapa de calor de actividad
  ├─► /api/alerts/*    — configuración y test de alertas
  └─► _purge_loop      — rotación diaria de datos (eventos, clips y personas anónimas >30 días)
```

## Decisiones de diseño

- **YOLO26n en lugar de YOLOv8n**: 31% más rápido en CPU, misma API `ultralytics`
- **MJPEG en lugar de WebRTC**: Sin STUN/TURN, latencia aceptable en LAN
- **face-recognition/dlib HOG**: Más ligero que CNNs para LAN sin GPU
- **Worker de reconocimiento dedicado**: dlib (100–500 ms) fuera del hilo de captura — sin frames perdidos ni tirones MJPEG durante la identificación
- **Detección 1 de cada N frames**: ByteTrack interpola en los frames saltados; en CPU duplica el FPS efectivo sin perder tracks
- **mp4v fourcc en VideoWriter**: Más fiable que H.264/avc1 en Windows sin codecs externos
- **asyncio.run_coroutine_threadsafe**: Bridge correcto entre hilos daemon y event loop async de FastAPI
- **Línea virtual de conteo**: Evita contar personas múltiples veces mientras permanecen en escena
- **Rotación diaria automática**: Tarea async que elimina datos viejos sin bloquear el event loop
- **Degradación elegante**: Sin `credentials.json` el sistema arranca y funciona; solo se deshabilita Drive

## Licencia

Proyecto local, sin restricciones de distribución pública.
