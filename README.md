# Tapo Dashboard

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta personas en tiempo real con YOLOv8, identifica rostros conocidos y graba clips automáticos con subida a Google Drive.

## Características

- **Stream RTSP en vivo**: Conexión directa a cámara Tapo C220 vía `rtsp://192.168.1.132:554/stream1`
- **Detección de personas**: YOLOv8 nano con inferencia <50 ms en CPU
- **Conteo por línea virtual**: Evita dobles conteos con tracking persistente (ByteTrack + LineZone)
- **Reconocimiento facial**: Identifica personas por nombre usando embeddings de 128 dimensiones (face-recognition/dlib)
- **Enrolamiento de rostros**: Registro vía API con imagen subida o frame actual de la cámara
- **Grabación automática**: Clips .mp4 generados cuando hay actividad; se detienen 5 s después de la última detección
- **Subida a Google Drive**: Upload automático de cada clip a la carpeta «Grabaciones Tapo» con reintentos exponenciales
- **Estadísticas en tiempo real**: Personas hoy, histograma por hora, últimos eventos con nombre de persona
- **WebSocket**: Actualizaciones en vivo sin polling — detecciones, grabaciones, uploads
- **Dashboard integrado**: HTML + Tailwind + Chart.js, sin build step

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + Uvicorn |
| Captura | OpenCV (RTSP) |
| Detección | YOLOv8 nano (Ultralytics) |
| Tracking | supervision (ByteTrack + LineZone) |
| Reconocimiento | face-recognition + dlib |
| Grabación | cv2.VideoWriter (mp4v) |
| Cloud storage | Google Drive API v3 (OAuth2 desktop) |
| Base de datos | SQLite + aiosqlite + SQLAlchemy async |
| Streaming | MJPEG sobre HTTP |
| Tiempo real | WebSocket |
| Frontend | HTML + Tailwind + Chart.js |

## Requisitos

- Python 3.12+
- Cámara Tapo C220 con acceso RTSP en red local
- Dependencias en `requirements.txt`
- *(Opcional)* `credentials.json` de Google Cloud Console para subida a Drive

## Instalación

```bash
# Crear entorno virtual
py -3.12 -m venv .venv
.venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Descargar modelo YOLOv8n (auto en primer uso)
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

## Configuración de Google Drive (opcional)

Para que los clips se suban automáticamente a Drive:

1. Ve a [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Crea credenciales de tipo **OAuth 2.0 → Desktop app**
3. Descarga el JSON y guárdalo en la raíz del proyecto como `credentials.json`
4. En el primer arranque se abrirá el navegador para autorizar acceso; el token queda en `data/token.json`

Los clips se subirán a la carpeta **«Grabaciones Tapo»** (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`) de tu Google Drive. Sin `credentials.json` el sistema funciona con normalidad pero no sube los clips.

## Uso

### Producción (recomendado)

```bash
# Arrancar con watchdog (reinicio automático si cae) + HTTPS
.venv\Scripts\python.exe watchdog.py
```

Dashboard disponible en `https://<IP-local>:8000` desde cualquier dispositivo de la red.  
Obtén tu IP local con `ipconfig` → busca «Dirección IPv4».  
El navegador mostrará aviso de certificado autofirmado — click en «Avanzado» → «Continuar».

### Desarrollo

```bash
# Sin watchdog, sin SSL (HTTP plano, recarga automática)
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Dashboard en `http://localhost:8000`.

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
| WS | `/ws` | Eventos en tiempo real (detecciones, grabaciones) |
| GET | `/api/stats` | Resumen de estadísticas (últimas 24 h) |
| GET | `/api/events` | Últimos eventos de cruce con nombre de persona |
| GET | `/api/recordings` | Clips grabados con estado de subida |
| GET | `/persons` | Personas enroladas con historial de visitas |
| POST | `/api/enroll_face` | Registrar rostro (imagen o frame actual) |
| GET | `/detections` | Detecciones y bounding boxes del frame actual |
| GET | `/counts` | Conteos acumulados in/out/total |

## Arquitectura

```
Cámara RTSP
  └─► stream.py (hilo de captura)
        ├─► /video_feed (MJPEG + overlays)
        ├─► detector.py (YOLOv8n)
        │     └─► tracker.py (ByteTrack + LineZone)
        │           ├─► recognizer.py (face-recognition — embeddings 128-dim)
        │           └─► database.py events (SQLite async)
        │                 └─► WebSocket → dashboard
        └─► recorder.py (ClipRecorder — hilo)
              └─► VideoWriter mp4v → data/clips/
                    └─► gdrive.py (DriveUploader — hilo)
                          └─► Google Drive API v3 → carpeta Grabaciones Tapo
                                └─► database.py recordings (insert/update)
                                      └─► WebSocket → panel grabaciones
```

## Variables de entorno (`.env`)

```
CAMERA_URL=rtsp://192.168.1.132:554/stream1
YOLO_CONFIDENCE=0.45
DB_PATH=data/events.db
HOST=0.0.0.0
PORT=8000

# Google Drive
GDRIVE_FOLDER_ID=1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir
GDRIVE_CREDENTIALS_PATH=credentials.json
GDRIVE_TOKEN_PATH=data/token.json

# Grabación
CLIPS_DIR=data/clips
RECORDING_FPS=15.0
RECORDING_TAIL_SECS=5.0
```

## Tests

```bash
# Suite completa (38 tests)
pytest tests/ -v

# Módulo específico
pytest tests/test_phase10.py -v
```

## Decisiones de diseño

- **MJPEG en lugar de WebRTC**: Simplicidad en LAN, sin STUN/TURN
- **YOLOv8n**: Inferencia <50 ms en CPU modesta
- **face-recognition/dlib HOG**: Más ligero que modelos CNN para LAN local sin GPU
- **mp4v fourcc en Windows**: Más fiable que H.264/avc1 en VideoWriter sin codecs externos
- **Thread→async bridge**: `asyncio.run_coroutine_threadsafe` para llamar a DB async desde hilos de grabación/upload
- **Degradación elegante sin credentials.json**: El sistema arranca y funciona; solo deshabilita el upload
- **Línea virtual de conteo**: Evita contar personas múltiples veces mientras permanecen en escena

## Desarrollo

Consulta `CLAUDE.md` para detalles de arquitectura, convenciones y stack.

## Licencia

Proyecto local, sin restricciones de distribución pública.
