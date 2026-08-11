# Tapo Dashboard

## What This Is

Dashboard web local que consume el stream RTSP de una cámara Tapo C212, detecta y reconoce personas en tiempo real con YOLO26n + face-recognition, muestra estadísticas de actividad, graba clips automáticos con subida a Google Drive, lanza alertas por webhook/Telegram y expone métricas de salud del sistema. Todo accesible desde cualquier dispositivo de la red local sin depender de la nube para el funcionamiento básico.

## Core Value

Ver en tiempo real cuántas personas han pasado frente a la cámara, a qué horas hay más actividad y quiénes son, con el vídeo en vivo, las grabaciones y las métricas de sistema integrados en el mismo panel.

**Milestone en curso:** v2.0 — Plataforma de Video Analytics (ver `.planning/STATE.md`).

## Requirements

### Validated (v1.2 — 2026-05-01)

- [x] Stream RTSP de la cámara Tapo C212 capturado y retransmitido vía MJPEG al navegador
- [x] Detección de personas en cada frame usando YOLO26n (38.9 ms CPU)
- [x] Contador de cruces basado en línea virtual para evitar dobles conteos (ByteTrack + LineZone)
- [x] Almacenamiento de eventos de detección en SQLite con timestamp y nombre de persona
- [x] Dashboard web con vídeo en directo + bounding boxes visuales
- [x] Contador de personas del día actual visible en el dashboard
- [x] Histograma de actividad por hora (últimas 24 h) con Chart.js
- [x] API REST para consultar estadísticas históricas, eventos y grabaciones
- [x] WebSocket que emite eventos en tiempo real al frontend
- [x] Configuración centralizada con pydantic-settings + .env validado
- [x] Reconocimiento facial por embeddings 128-dim (face-recognition/dlib); enrolamiento vía API
- [x] Grabación automática de clips .mp4 al detectar actividad; se detiene 5 s después de la última detección
- [x] Subida automática de clips a Google Drive (carpeta «Grabaciones Tapo») con reintentos exponenciales
- [x] Panel de grabaciones en dashboard con estado en tiempo real (pending / uploaded / failed)
- [x] Rendimiento: YOLO26n en stream2 (720p), watchdog con reinicio automático
- [x] Alertas: webhook HTTP y Telegram al detectar desconocido, intrusión o umbral de conteo
- [x] Zonas de interés configurables con overlay en el stream; detección de intrusión por horario
- [x] Galería de capturas por persona, navegable desde el dashboard
- [x] Seguridad: HTTPS autofirmado, HTTP Basic Auth, rate limiting, SRI, headers de seguridad
- [x] Filtros en tabla de eventos (dirección, persona, fechas, intrusión); exportar CSV
- [x] Reproductor de clips integrado en el dashboard (modal de vídeo)
- [x] Métricas de salud: CPU%, RAM%, FPS, uptime — panel en dashboard, refresh 30 s
- [x] Rotación automática de datos: eventos y grabaciones más antiguos de 30 días, tarea diaria
- [x] Docker Compose para arranque contenedorizado en producción

### Out of Scope

- Múltiples cámaras simultáneas — fuera de alcance en v1.2; planeada en v2.0 Bloque D (fases 35-36)
- WebRTC — MJPEG suficiente para LAN, sin señalización
- Acceso remoto / túnel — se opera exclusivamente en LAN
- Autenticación OAuth / multi-usuario — dashboard local de red privada

## Context

- **Cámara**: Tapo C212, IP local `192.168.1.132`, stream RTSP en `rtsp://192.168.1.132:554/stream2`
- **Entorno**: Windows 11, red local, sin acceso GPU → YOLO26n (CPU-friendly)
- **Acceso**: Dashboard en `https://<IP-LAN>:8000` para cualquier dispositivo de la LAN
- **Drive**: Carpeta «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`); requiere `credentials.json` OAuth2 Desktop

## Constraints

- **Hardware**: Sin GPU dedicada — YOLO26n para mantener inferencia < 40 ms en CPU
- **Red**: Solo LAN — no se diseña para exposición pública
- **Stack**: Python 3.12, FastAPI, OpenCV, Ultralytics, supervision, face-recognition, SQLite, HTML+JS vanilla
- **Streaming**: MJPEG sobre HTTP — sin WebRTC

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| YOLO26n en lugar de YOLOv8n | 31% más rápido en CPU, sin NMS, misma API | ✓ Validado |
| MJPEG en lugar de WebRTC | Más simple, cero dependencias de STUN/TURN, latencia aceptable en LAN | ✓ Validado |
| Línea virtual de conteo | Evita contar la misma persona múltiples veces mientras permanece en escena | ✓ Validado |
| SQLite en lugar de PostgreSQL | Volumen bajo de eventos, sin usuarios concurrentes, sin servidores extra | ✓ Validado |
| Frontend sin framework JS | Sin build step, carga instantánea, fácil de mantener para un dashboard local | ✓ Validado |
| face-recognition/dlib HOG | Más ligero que CNNs para LAN sin GPU; embeddings 128-dim suficientes | ✓ Validado |
| mp4v fourcc en VideoWriter | Más fiable que H.264/avc1 en Windows sin codecs externos | ✓ Validado |
| asyncio.run_coroutine_threadsafe | Bridge correcto entre hilos daemon y event loop async de FastAPI | ✓ Validado |
| Degradación sin credentials.json | El sistema arranca y funciona; Drive upload deshabilitado, no falla | ✓ Validado |
| psutil para métricas de salud | Sin dependencias extra en el stack; CPU/RAM en una línea | ✓ Validado |
| Tarea async para rotación de datos | No bloquea el event loop; se ejecuta cada 24 h con asyncio.sleep | ✓ Validado |

---
*Last updated: 2026-05-01 — v1.2 completo, 16/16 fases*
