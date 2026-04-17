# Tapo Dashboard

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta personas en tiempo real con YOLOv8 y muestra estadísticas de actividad.

## Características

- **Stream RTSP en vivo**: Conexión directa a cámara Tapo C220 vía `rtsp://192.168.1.132:554/stream1`
- **Detección de personas**: YOLOv8 nano con inferencia <50 ms en CPU
- **Conteo por línea virtual**: Evita dobles conteos con tracking persistente (ByteTrack)
- **Estadísticas en tiempo real**: Personas hoy, histograma por hora, últimos eventos
- **WebSocket**: Actualizaciones en vivo sin polling
- **Dashboard integrado**: HTML + Tailwind + Chart.js, sin build step ni dependencias pesadas

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + Uvicorn |
| Captura | OpenCV (RTSP) |
| Detección | YOLOv8 nano (Ultralytics) |
| Tracking | supervision (ByteTrack + LineZone) |
| Base de datos | SQLite + aiosqlite |
| Streaming | MJPEG sobre HTTP |
| Tiempo real | WebSocket |
| Frontend | HTML + Tailwind + Chart.js |

## Requisitos

- Python 3.12+
- Cámara Tapo C220 con acceso RTSP en red local
- Dependencias en `requirements.txt`

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

## Uso

```bash
# Arrancar servidor (recarga automática en desarrollo)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Verificar conexión RTSP
python -c "import cv2; cap=cv2.VideoCapture('rtsp://192.168.1.132:554/stream1'); print('OK' if cap.isOpened() else 'FAIL'); cap.release()"
```

Dashboard disponible en `http://localhost:8000` desde cualquier dispositivo de la red local.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Dashboard HTML |
| GET | `/video_feed` | Stream MJPEG |
| WS | `/ws` | Eventos en tiempo real (JSON) |
| GET | `/api/stats` | Resumen de estadísticas (últimas 24h) |

## Arquitectura

```
Cámara RTSP
  └─► stream.py (hilo de captura)
        ├─► /video_feed (MJPEG → <img> dashboard)
        └─► detector.py (YOLOv8n)
              └─► tracker.py (ByteTrack + LineZone)
                    └─► database.py (SQLite)
                          └─► WebSocket → app.js → Chart.js
```

## Decisiones de diseño

- **MJPEG en lugar de WebRTC**: Simplicidad en LAN, sin STUN/TURN
- **YOLOv8n**: Inferencia <50 ms en CPU modesta
- **Línea virtual de conteo**: Evita contar personas múltiples veces
- **SQLite**: Suficiente para volumen bajo de eventos
- **Frontend vanilla**: Sin build step, carga instantánea

## Desarrollo

Consulta `CLAUDE.md` para detalles de arquitectura, convenciones y stack recomendado.

Ejecuta tests con:
```bash
pytest tests/ -v
```

## Variables de entorno (`.env`)

```
CAMERA_URL=rtsp://192.168.1.132:554/stream1
YOLO_CONFIDENCE=0.45
DB_PATH=data/events.db
HOST=0.0.0.0
PORT=8000
```

## Licencia

Proyecto local, sin restricciones de distribución pública.
