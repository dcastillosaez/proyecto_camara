# Tapo Dashboard

Dashboard web local que consume el stream RTSP de una cámara Tapo C212, detecta, sigue y reconoce personas en tiempo real con YOLO26n, graba clips cuando una regla lo pide (con subida opcional a Google Drive) y muestra conteos, eventos, alertas, analítica y métricas del sistema desde un único panel en la red local.

## Características

- **Vídeo en vivo**: captura RTSP con OpenCV y retransmisión MJPEG al navegador.
- **Detección y conteo**: YOLO26n, ByteTrack y `LineZone` de supervision. El conteo sale del cruce de línea de cada track, no de sumar detecciones por frame.
- **Reconocimiento facial**: ArcFace (insightface, `buffalo_s`) en un worker propio, con filtros de calidad y voto temporal; ReID de apariencia opcional (OSNet).
- **Eventos y reglas**: motor de eventos tipados (entradas, cruces, zonas, intrusión, persona desconocida, comportamiento, objetos) y reglas con acciones `notify`, `telegram`, `webhook`, `record`, `upload_drive`, `snapshot` y `log`.
- **Grabación**: pre y post-buffer, duración máxima por clip, parada si falta disco y subida a Drive con cola persistente. Por defecto graban la intrusión y la persona desconocida (`config/rules.yaml`).
- **Zonas y líneas**: polígonos y líneas de conteo editables desde la vista Cámara; las zonas `restricted` generan `INTRUSION`.
- **Analítica**: actividad por hora, ocupación, mapa de calor y ranking.
- **Retención**: eventos, grabaciones, clips locales (por antigüedad y por tamaño), recortes de galería, snapshots y personas anónimas; al arrancar y cada día a `RETENTION_HOUR`.
- **Seguridad**: HTTP Basic con bloqueo tras fallos repetidos, HTTPS autofirmado, CSP sin hosts externos, validación de `Origin`, límites de tamaño de cuerpo y de peticiones.
- **Sin internet**: Tailwind, Chart.js y las fuentes se sirven desde `frontend/vendor/`.

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + Uvicorn |
| Captura | OpenCV (`cv2.VideoCapture`) |
| Detección | YOLO26n (Ultralytics) |
| Tracking y conteo | supervision: ByteTrack + `LineZone` |
| Reconocimiento | insightface (ArcFace) + onnxruntime |
| Base de datos | SQLite + SQLAlchemy 2 async + aiosqlite (PostgreSQL y Redis opcionales) |
| Tiempo real | MJPEG sobre HTTP + WebSocket |
| Frontend | HTML + JS vanilla (módulos ES), sin build; Tailwind y Chart.js en `frontend/vendor/` |
| Nube | Google Drive API v3 (OAuth2, aplicación de escritorio) |
| Alertas | Webhook HTTP + Telegram Bot API |

## Requisitos

- Windows 11 (también funciona en Linux) y Python 3.12.
- Cámara Tapo C212 accesible por RTSP en la red local.
- *(Opcional)* `credentials.json` de Google Cloud Console para subir clips a Drive.

## Instalación

```bash
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # y edita al menos CAMERA_URL, RTSP_USER y RTSP_PASS
```

Para desarrollo y tests: `pip install -r requirements-dev.txt` (incluye las de ejecución).

## Configuración de Google Drive (opcional)

1. En [Google Cloud Console](https://console.cloud.google.com/), APIs & Services → Credentials, crea credenciales **OAuth 2.0 → Desktop app**.
2. Descarga el JSON y guárdalo como `credentials.json` en la raíz del proyecto.
3. Autoriza una vez, en el equipo del servidor: `.venv\Scripts\python.exe scripts\gdrive_auth.py`. El token queda en `data/token.json`.

El backend nunca abre el navegador por su cuenta. Si el token falta o caduca, la cola de subida se pausa sin perder clips, lo avisa con un evento `DEGRADED_MODE` y en `GET /api/v2/recordings/upload-status`, y reanuda sola cuando se vuelve a ejecutar `scripts/gdrive_auth.py`.

## Uso

### Producción (HTTPS opcional)

```bash
.venv\Scripts\python.exe -m backend.run
```

Hay que ejecutarlo como módulo (`-m backend.run`). Abre `https://<IP-de-tu-PC>:8000` (o `http://` sin `SSL_CERTFILE`/`SSL_KEYFILE`). La IP es la del PC que sirve el dashboard, no la de la cámara; `0.0.0.0` en los logs significa «todas las interfaces».

### Desarrollo

```bash
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Antes de actualizar

La retención se aplica **al arrancar**. Antes de actualizar una instalación con datos, haz copia de `data/` y revisa los valores `*_RETENTION_DAYS` y `CLIPS_MAX_TOTAL_MB` de `.env`.

## API

- La documentación interactiva está en `/docs` (exige autenticación si `DASHBOARD_USER` está definido).
- La API actual vive bajo `/api/v2/` (cámaras, eventos, alertas, reglas, zonas, líneas, grabaciones, analítica, configuración, métricas) y el canal en tiempo real en `/ws` y `/api/v2/ws`.
- Siguen activas algunas rutas v1 (`/api/stats`, `/api/events/export`, `/persons`, `/api/enroll_face`, `/video_feed`, `/counts`, `/detections`); las marcadas como `deprecated` en `/docs` no tienen consumidor en el frontend.

## Tests

```bash
# Unitarios e integración (los de PostgreSQL y Redis se saltan sin TEST_POSTGRES_URL / TEST_REDIS_URL)
.venv\Scripts\python.exe -m pytest tests/ -q

# E2E con Playwright (levanta el backend en el puerto 8011)
npm ci
npx playwright install chromium
npx playwright test
```

`scripts/eval_detection.py` reproduce clips anotados y mide error de conteo, cambios de id y tracks falsos por hora; sirve para decidir con datos cualquier ajuste del detector o del tracker.

## Arquitectura

```text
RTSP
  │
  ▼
CaptureWorker
  │
  ▼
FrameBroker (último frame, 1 hueco por suscriptor)
  ├──► StreamingWorker ──► /video_feed ──► dashboard
  ├──► RecordingWorker ──► clips (.part.mp4 → .mp4) ──► UploadQueue ──► Drive
  ├──► RecognitionWorker ─► TrackRegistry
  └──► DetectionWorker
          └─► YOLO26n → ByteTrack → LineZone / zonas
                    │
                    ├─► TrackRegistry
                    └─► EventBus → reglas → SQLite → WebSocket → frontend
```

La captura nunca espera a la IA: cada worker consume del broker a su ritmo y se descartan frames antes que acumular latencia. Un `WorkerSupervisor` por cámara reinicia los workers caídos, avisa con `DEGRADED_MODE` y reintenta tras un enfriamiento. Los detalles y las reglas de diseño están en `CLAUDE.md`; el estado del proyecto, en `.planning/STATE.md`; la arquitectura original, en `docs/software_arquitecture.pdf`.

## Licencia

Proyecto local, sin restricciones de distribución pública. Las librerías incluidas en `frontend/vendor/` conservan sus licencias (MIT para Tailwind y Chart.js, SIL OFL 1.1 para las fuentes).
