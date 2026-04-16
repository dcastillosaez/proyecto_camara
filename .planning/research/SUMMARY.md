# Research Summary -- Tapo Dashboard

**Proyecto:** Tapo Dashboard
**Dominio:** Dashboard local de videovigilancia con deteccion IA en tiempo real
**Investigado:** 2026-04-16
**Confianza general:** HIGH

## Resumen ejecutivo

Tapo Dashboard es un sistema de deteccion y conteo de personas en tiempo real que consume un stream RTSP de una camara Tapo C220, ejecuta inferencia YOLO en CPU y presenta estadisticas en un dashboard web local. El patron arquitectonico esta bien establecido en el ecosistema open source (Frigate, LightNVR, camera.ui): hilo dedicado de captura, hilo de deteccion/tracking, y servidor web async que sirve frames anotados y estadisticas via API REST y WebSocket.

La investigacion revela un cambio importante respecto a PROJECT.md: YOLO26n sustituye a YOLOv8n. Misma libreria (ultralytics), misma API, pero 31% mas rapido en CPU (38.9 ms vs 56.1 ms). Tambien emerge supervision (Roboflow) como pieza critica para el conteo por linea virtual: resolver tracking + cruce de linea desde cero es el principal foco de bugs del dominio, y supervision lo resuelve en ~10 lineas con ByteTrack + LineZone.

Los riesgos mas graves son de infraestructura, no de logica de negocio. El buffer RTSP de OpenCV acumula retraso si no se drena activamente, cap.read() puede colgarse indefinidamente al perder conexion, y los generadores MJPEG de FastAPI no detectan la desconexion del cliente por defecto. Todos tienen soluciones conocidas que deben implementarse desde la fase 1, no como fix posterior.

## Stack recomendado

| Tecnologia | Version | Proposito | Razon |
|---|---|---|---|
| Python | 3.12.x | Runtime | Estable hasta oct 2028, sin features experimentales innecesarios |
| FastAPI + Uvicorn | >=0.115 / >=0.30 | API REST, WebSocket, MJPEG | StreamingResponse nativo, async-first, soporte WS integrado |
| OpenCV (opencv-python) | 4.13.x | Captura RTSP, procesamiento de frames | Estandar de facto para captura RTSP, validado con camaras Tapo |
| Ultralytics (YOLO26n) | >=8.4 | Deteccion de personas | 38.9 ms en CPU, sin NMS, misma API que YOLOv8n |
| supervision | >=0.27 | Tracking (ByteTrack) + conteo por linea (LineZone) | Evita reimplementar logica de cruce propensa a errores |
| aiosqlite + SQLAlchemy | >=0.20 / >=2.0 | Persistencia de eventos | Async para no bloquear event loop, WAL mode para lecturas concurrentes |
| pydantic-settings | >=2.0 | Configuracion centralizada | Validacion de tipos al arrancar, lectura de .env integrada |
| Chart.js | 4.5.x (CDN) | Histograma horario | 11 KB, API simple, sin build step |
| HTML + JS vanilla | - | Dashboard | Sin framework, carga instantanea, un solo archivo basta |

## Funcionalidades table stakes (v1)

Ordenadas por prioridad y dependencia:

1. **Video en directo en el navegador** -- MJPEG sobre HTTP. Sin feed no hay dashboard.
2. **Bounding boxes sobre personas** -- Feedback visual de que la deteccion funciona.
3. **Contador de personas del dia** -- La metrica central del proyecto.
4. **Histograma de actividad por hora (24 h)** -- Patron temporal, la estadistica mas intuitiva.
5. **Indicador de estado de conexion** -- Distingue "camara caida" de "bug en el software".
6. **Eventos recientes** -- Lista de las ultimas 5-10 detecciones con timestamp.
7. **Modo oscuro por defecto** -- Estandar universal en dashboards de monitorizacion.
8. **Diseno responsive** -- Consulta desde movil, tablet y PC.

Diferenciadores de bajo esfuerzo para anadir tras el MVP:

- Thumbnail de ultima deteccion
- Score de confianza en overlay
- Estadisticas comparativas (hoy vs ayer)
- Exportar datos a CSV

Diferir a v2: heatmap semanal, zona de deteccion configurable, configuracion desde la UI, log paginado completo.

## Arquitectura

```
Thread principal (asyncio event loop - uvicorn)
    |-- MJPEGStreamer  [GET /video]     <-- lee AnnotatedFrameSlot
    |-- BroadcastHub   [WS /ws/events]  <-- recibe eventos via call_soon_threadsafe
    |-- API REST       [GET /api/stats] <-- consulta SQLite (lectura)

Thread "capture" (daemon)
    |-- cv2.VideoCapture(rtsp://) --> grab() en bucle continuo
    |-- Escribe en threading.Queue(maxsize=4) con descarte activo

Thread "detection" (daemon)
    |-- Lee de Queue, ejecuta model.track(frame, tracker="bytetrack.yaml")
    |-- Logica de cruce de linea (centroide vs linea virtual)
    |-- Escribe frame anotado en AnnotatedFrameSlot (variable + Lock, no cola)
    |-- Inserta evento en SQLite (WAL mode, writer unico)
    |-- Notifica BroadcastHub via loop.call_soon_threadsafe()
```

Puntos clave del diseno:

- **AnnotatedFrameSlot** es una variable compartida, no una cola. Siempre contiene el ultimo frame. Los clientes MJPEG nunca ven frames viejos.
- **Queue(maxsize=4)** entre captura y deteccion con descarte activo: si la deteccion es mas lenta que la captura, se descartan frames viejos para mantener frescura.
- **call_soon_threadsafe** es el unico puente seguro entre threads nativos y el event loop asyncio.
- **SQLite con WAL mode** permite lectura concurrente (API REST) mientras el thread de deteccion escribe.
- **Lifespan** de FastAPI (no on_event deprecado) para arrancar y parar threads limpiamente.

## Pitfalls criticos (top 5)

1. **Buffer RTSP acumulativo** -- El video se retrasa progresivamente si no se drena el buffer de OpenCV. Prevencion: hilo de captura dedicado que llama grab() continuamente, compartiendo solo el ultimo frame. Fase 1.

2. **cap.read() se cuelga al perder conexion** -- Sin timeout por defecto en OpenCV para RTSP. Prevencion: watchdog que destruye y recrea el VideoCapture si no hay frame en 10 s, con backoff exponencial para reconexion. Fase 1.

3. **Generadores MJPEG zombi** -- FastAPI no cancela el generador cuando el cliente cierra la pestana. Prevencion: verificar request.is_disconnected(), capturar CancelledError, bloque finally para cleanup. Fase 2.

4. **Conteo doble** -- Contar detecciones por frame en vez de tracking + line crossing produce conteos absurdos (persona parada 1 min = 1800 conteos). Prevencion: ByteTrack para IDs persistentes + linea virtual + set de IDs ya contados. Fase 3.

5. **Deadlock threading/asyncio** -- Adquirir threading.Lock desde una corrutina congela el event loop entero. Prevencion: acceso al frame slot via asignacion atomica (GIL protege la referencia) o run_in_executor(). Nunca llamar a threading.Lock.acquire() desde async def. Fase 2.

## Orden de construccion sugerido

### Fase 0: Setup y verificacion de camara
**Razon:** Si las credenciales RTSP no funcionan, nada mas importa. La Tapo C220 requiere cuenta de camara separada (no la cuenta Tapo/TP-Link).
**Entrega:** Conexion RTSP verificada con VLC, entorno virtual Python configurado, dependencias instaladas, .env con credenciales.
**Evita:** Pitfall #8 (credenciales incorrectas).

### Fase 1: Captura RTSP + streaming MJPEG crudo
**Razon:** Valida la pieza de mayor riesgo tecnico (conexion a la camara, streaming HTTP) sin complejidad de deteccion.
**Entrega:** Endpoint GET /video que muestra el stream de la camara en el navegador, sin deteccion.
**Features:** Video en directo en el navegador.
**Evita:** Pitfalls #1 (buffer acumulativo) y #2 (cuelgue en desconexion). Implementar hilo de captura con drain de buffer y watchdog desde el primer momento.

### Fase 2: Deteccion YOLO26n + bounding boxes
**Razon:** Anade la deteccion al pipeline de streaming. Valida rendimiento en CPU y calidad de detecciones.
**Entrega:** Stream MJPEG con bounding boxes dibujados sobre personas detectadas.
**Features:** Bounding boxes en overlay, score de confianza.
**Evita:** Pitfalls #3 (generadores zombi), #5 (deadlock threading/async), #10 (todo en un solo loop). Definir la separacion captura/deteccion/streaming como arquitectura de 3 componentes.
**Stack clave:** ultralytics (YOLO26n), supervision (ByteTrack).

### Fase 3: Tracking + conteo por linea + persistencia
**Razon:** El conteo por cruce de linea es el requisito central del proyecto y depende de tener detecciones funcionales.
**Entrega:** Eventos de cruce almacenados en SQLite con timestamp, direccion y confianza. Conteo verificable manualmente.
**Features:** Contador de personas del dia, linea virtual de conteo.
**Evita:** Pitfalls #4 (conteo doble), #6 (YOLO lento), #7 (SQLite locked).
**Stack clave:** supervision (LineZone + ByteTrack), aiosqlite + SQLAlchemy, SQLite con WAL mode.

### Fase 4: API REST + WebSocket
**Razon:** Exponer los datos para que el frontend los consuma. Construir APIs antes de UI permite probar con curl/Postman.
**Entrega:** GET /api/stats (conteo diario, histograma horario), GET /api/history, WebSocket /ws/events que emite cruces en tiempo real.
**Features:** API REST para estadisticas, WebSocket para tiempo real, indicador de estado de conexion.
**Stack clave:** FastAPI endpoints, BroadcastHub con call_soon_threadsafe.

### Fase 5: Dashboard frontend
**Razon:** Todo el backend esta probado. El frontend solo consume APIs ya validadas. Riesgo minimo.
**Entrega:** Dashboard HTML+JS con video en directo, contador, histograma horario (Chart.js), lista de eventos recientes. Modo oscuro, responsive.
**Features:** Todas las table stakes de UI: contador visible, histograma, eventos recientes, modo oscuro, responsive.
**Evita:** Pitfall #9 (retraso acumulado en el navegador). Headers anti-cache, fps limitado a 10-15.
**Stack clave:** HTML + JS vanilla, Chart.js via CDN.

### Fase 6: Configuracion centralizada + hardening
**Razon:** Transversal. No bloquea funcionalidad pero mejora la operabilidad.
**Entrega:** pydantic-settings con .env, arranque con un solo comando, reconexion automatica robusta, logging estructurado.
**Features:** Configuracion centralizada (URL camara, confianza YOLO, puerto).

### Razon del orden

- Las fases 0-1 eliminan el riesgo tecnico mas alto (conexion RTSP) al menor coste.
- La fase 2 se separa de la 3 porque deteccion y conteo son problemas distintos. Validar que YOLO detecta antes de implementar tracking.
- La fase 4 antes de la 5 porque testear APIs con curl es mas rapido que debuggear a traves de una UI.
- La fase 6 al final porque la configuracion es un refinamiento, no un bloqueo.

### Flags de investigacion

Fases que podrian necesitar investigacion adicional durante la planificacion:
- **Fase 1:** Comportamiento especifico de cv2.CAP_PROP_BUFFERSIZE y timeouts en Windows 11. La documentacion de OpenCV es inconsistente entre plataformas.
- **Fase 3:** Calibracion de la linea virtual. La posicion optima depende de la escena real de la camara. Requiere prueba empirica.

Fases con patrones bien documentados (no necesitan investigacion adicional):
- **Fase 4:** API REST y WebSocket en FastAPI. Documentacion oficial excelente.
- **Fase 5:** Dashboard HTML con Chart.js. Patrones triviales, bien establecidos.
- **Fase 6:** pydantic-settings. Documentacion completa.

## Decisiones que actualizan PROJECT.md

| Decision en PROJECT.md | Hallazgo de la investigacion | Accion |
|---|---|---|
| YOLOv8 nano | YOLO26n es 31% mas rapido en CPU (38.9 ms vs 56.1 ms), mismo paquete ultralytics, misma API. Estrictamente superior. | Actualizar a YOLO26n |
| Conteo por linea virtual a mano | La libreria supervision (Roboflow) resuelve tracking + line crossing en ~10 lineas con ByteTrack + LineZone. Reimplementar es propenso a errores. | Usar supervision |
| SQLite directo | Usar aiosqlite + SQLAlchemy 2.0 async para no bloquear el event loop. WAL mode obligatorio. | Anadir al stack |
| python-dotenv (implicito) | pydantic-settings valida tipos al arrancar y falla rapido si falta config critica. | Usar pydantic-settings |
| Python 3.11+ | Python 3.12 es la version estable recomendada. 3.13 tiene features experimentales innecesarios para este proyecto. | Fijar Python 3.12 |

## Evaluacion de confianza

| Area | Confianza | Notas |
|---|---|---|
| Stack | HIGH | Todas las librerias verificadas en PyPI con versiones actuales. YOLO26n benchmarks de docs oficiales. |
| Features | HIGH | Patrones validados contra Frigate, LightNVR, camera.ui y dashboards de seguridad profesionales. |
| Arquitectura | HIGH | Patron de 3 hilos (captura/deteccion/servidor) es estandar en proyectos de streaming + IA. Multiples referencias. |
| Pitfalls | HIGH | Los 5 pitfalls criticos tienen issues de GitHub, documentacion oficial o posts comunitarios que los confirman. |

**Confianza global:** HIGH

### Gaps pendientes

- **Rendimiento real de YOLO26n en el hardware especifico del usuario:** Los benchmarks son genericos. Hay que medir en la maquina destino en fase 2.
- **Comportamiento de cv2.CAP_PROP_BUFFERSIZE en Windows:** No todas las plataformas lo respetan. Puede requerir el patron grab()/retrieve() como alternativa.
- **Posicion optima de la linea virtual:** Depende de la escena real. Solo se puede calibrar con la camara instalada.

## Fuentes

### Primarias (HIGH)
- [Ultralytics YOLO26 docs](https://docs.ultralytics.com/models/yolo26/)
- [Supervision LineZone docs](https://supervision.roboflow.com/detection/tools/line_zone/)
- [FastAPI StreamingResponse docs](https://fastapi.tiangolo.com/advanced/custom-response/)
- [FastAPI WebSocket docs](https://fastapi.tiangolo.com/advanced/websockets/)
- [FastAPI Concurrency docs](https://fastapi.tiangolo.com/async/)
- [SQLite WAL mode](https://www.sqlite.org/wal.html)
- [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

### Secundarias (MEDIUM-HIGH)
- [OpenCV Issue #22677](https://github.com/opencv/opencv/issues/22677) -- VideoCapture.read() stuck
- [FastAPI Issue #1342](https://github.com/fastapi/fastapi/issues/1342) -- StreamingResponse disconnect
- [Tapo RTSP FAQ](https://www.tapo.com/us/faq/724/)
- [Frigate NVR](https://frigate.video/) -- referencia de arquitectura
- [Chart.js docs](https://www.chartjs.org/docs/)

---
*Investigacion completada: 2026-04-16*
*Listo para roadmap: si*
