# Tapo Dashboard

## What This Is

Dashboard web local que consume el stream RTSP de una cámara Tapo C220, detecta personas en tiempo real con YOLOv8 y muestra estadísticas de actividad: personas contadas hoy, histograma de actividad por hora, y feed de vídeo en directo con las detecciones marcadas. Todo accesible desde cualquier dispositivo de la red local sin depender de la nube.

## Core Value

Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo integrado en el mismo panel.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Stream RTSP de la cámara Tapo C220 capturado y retransmitido vía MJPEG al navegador
- [ ] Detección de personas en cada frame usando YOLOv8 nano
- [ ] Contador de cruces basado en línea virtual para evitar dobles conteos
- [ ] Almacenamiento de eventos de detección en SQLite con timestamp
- [ ] Dashboard web con vídeo en directo + bounding boxes visuales
- [ ] Contador de personas del día actual visible en el dashboard
- [ ] Histograma de actividad por hora (últimas 24 h) con Chart.js
- [ ] API REST para consultar estadísticas históricas
- [ ] WebSocket que emite eventos en tiempo real al frontend
- [ ] Configuración centralizada (URL cámara, confianza YOLO, puerto)
- [ ] Servicio arrancable con un solo comando (uvicorn)

### Out of Scope

- Notificaciones push / alertas por correo — complejidad innecesaria para v1
- Grabación de vídeo a disco — el objetivo es estadísticas, no almacenamiento de vídeo
- Autenticación de usuarios — es un dashboard local de red privada
- Acceso remoto / túnel — se opera exclusivamente en LAN
- Múltiples cámaras — una sola cámara en v1

## Context

- **Cámara**: Tapo C220, IP local `192.168.1.132`, stream RTSP en `rtsp://192.168.1.132:554/stream1`
- **Entorno**: Windows 11, red local, sin acceso GPU garantizado → YOLOv8 nano (CPU-friendly)
- **Acceso**: Dashboard disponible en `http://localhost:8000` para cualquier dispositivo de la LAN
- El usuario quiere que el README.md se vaya documentando conforme avanza el proyecto

## Constraints

- **Hardware**: Sin GPU dedicada confirmada — YOLOv8n para mantener inferencia <50 ms en CPU
- **Red**: Solo LAN — no se diseña para exposición pública
- **Stack**: Python 3.11+, FastAPI, OpenCV, Ultralytics YOLOv8, SQLite, HTML+JS vanilla con Chart.js
- **Streaming**: MJPEG sobre HTTP (no WebRTC) — suficiente para LAN, sin infraestructura de señalización

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| MJPEG en lugar de WebRTC | Más simple, cero dependencias de STUN/TURN, latencia aceptable en LAN | — Pending |
| YOLOv8 nano | Inferencia rápida en CPU, suficiente precisión para conteo de personas | — Pending |
| Línea virtual de conteo | Evita contar la misma persona múltiples veces mientras permanece en escena | — Pending |
| SQLite en lugar de PostgreSQL | Volumen bajo de eventos, sin usuarios concurrentes, sin servidores extra | — Pending |
| Frontend sin framework JS | Sin build step, carga instantánea, fácil de mantener para un dashboard local | — Pending |

## Evolution

Este documento evoluciona en cada transición de fase y al cerrar milestones.

**Después de cada fase:**
1. ¿Requisitos invalidados? → Mover a Out of Scope con motivo
2. ¿Requisitos validados? → Mover a Validated con referencia de fase
3. ¿Nuevos requisitos emergieron? → Añadir a Active
4. ¿Decisiones que registrar? → Añadir a Key Decisions
5. ¿"What This Is" sigue siendo preciso? → Actualizar si hay deriva

**Después de cada milestone:**
1. Revisión completa de todas las secciones
2. Comprobación del Core Value — ¿sigue siendo la prioridad correcta?
3. Auditoría de Out of Scope — ¿los motivos siguen siendo válidos?
4. Actualizar Context con el estado actual

---
*Last updated: 2026-04-16 after initialization*
