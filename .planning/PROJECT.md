# Tapo Dashboard

## What This Is

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta y reconoce personas en tiempo real con YOLOv8 + face-recognition, muestra estadísticas de actividad y graba clips automáticos con subida a Google Drive. Todo accesible desde cualquier dispositivo de la red local sin depender de la nube para el funcionamiento básico.

## Core Value

Ver en tiempo real cuántas personas han pasado frente a la cámara, a qué horas hay más actividad y quiénes son, con el vídeo en vivo y las grabaciones integrados en el mismo panel.

## Requirements

### Validated (v1.0 — 2026-04-19)

- [x] Stream RTSP de la cámara Tapo C220 capturado y retransmitido vía MJPEG al navegador
- [x] Detección de personas en cada frame usando YOLOv8 nano
- [x] Contador de cruces basado en línea virtual para evitar dobles conteos
- [x] Almacenamiento de eventos de detección en SQLite con timestamp y nombre de persona
- [x] Dashboard web con vídeo en directo + bounding boxes visuales
- [x] Contador de personas del día actual visible en el dashboard
- [x] Histograma de actividad por hora (últimas 24 h) con Chart.js
- [x] API REST para consultar estadísticas históricas, eventos y grabaciones
- [x] WebSocket que emite eventos en tiempo real al frontend
- [x] Configuración centralizada (URL cámara, confianza YOLO, puerto, Drive, grabación)
- [x] Servicio arrancable con un solo comando (uvicorn)
- [x] Reconocimiento facial por embeddings 128-dim (face-recognition/dlib); enrolamiento vía API
- [x] Grabación automática de clips .mp4 al detectar actividad; se detiene 5 s después de la última detección
- [x] Subida automática de clips a Google Drive (carpeta «Grabaciones Tapo») con reintentos exponenciales
- [x] Panel de grabaciones en dashboard con estado en tiempo real (pending / uploaded / failed)

### Out of Scope

- Notificaciones push / alertas — complejidad innecesaria para v1; el dashboard es observacional
- Autenticación de usuarios — es un dashboard local de red privada
- Acceso remoto / túnel — se opera exclusivamente en LAN
- Múltiples cámaras — una sola cámara en v1
- WebRTC — MJPEG suficiente para LAN, sin señalización

## Context

- **Cámara**: Tapo C220, IP local `192.168.1.132`, stream RTSP en `rtsp://192.168.1.132:554/stream1`
- **Entorno**: Windows 11, red local, sin acceso GPU → YOLOv8 nano (CPU-friendly)
- **Acceso**: Dashboard en `http://localhost:8000` para cualquier dispositivo de la LAN
- **Drive**: Carpeta «Grabaciones Tapo» (ID: `1OJTWvYoHCDU28ZyzwlpOlongxs8lqWir`); requiere `credentials.json` OAuth2 Desktop descargado de Google Cloud Console

## Constraints

- **Hardware**: Sin GPU dedicada — YOLOv8n para mantener inferencia < 50 ms en CPU
- **Red**: Solo LAN — no se diseña para exposición pública
- **Stack**: Python 3.12, FastAPI, OpenCV, Ultralytics, supervision, face-recognition, SQLite, HTML+JS vanilla
- **Streaming**: MJPEG sobre HTTP — sin WebRTC

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| MJPEG en lugar de WebRTC | Más simple, cero dependencias de STUN/TURN, latencia aceptable en LAN | ✓ Validado |
| YOLOv8 nano | Inferencia rápida en CPU, suficiente precisión para conteo de personas | ✓ Validado |
| Línea virtual de conteo | Evita contar la misma persona múltiples veces mientras permanece en escena | ✓ Validado |
| SQLite en lugar de PostgreSQL | Volumen bajo de eventos, sin usuarios concurrentes, sin servidores extra | ✓ Validado |
| Frontend sin framework JS | Sin build step, carga instantánea, fácil de mantener para un dashboard local | ✓ Validado |
| face-recognition/dlib HOG | Más ligero que CNNs para LAN sin GPU; embeddings 128-dim suficientes | ✓ Validado |
| mp4v fourcc en VideoWriter | Más fiable que H.264/avc1 en Windows sin codecs externos | ✓ Validado |
| asyncio.run_coroutine_threadsafe | Bridge correcto entre hilos daemon y event loop async de FastAPI | ✓ Validado |
| Degradación sin credentials.json | El sistema arranca y funciona; Drive upload deshabilitado, no falla | ✓ Validado |

---
*Last updated: 2026-04-19 — v1.0 completo, 10/10 fases, 38/38 tests*
