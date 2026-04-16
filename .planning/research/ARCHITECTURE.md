# Architecture Patterns

**Domain:** Dashboard de videovigilancia local con detección de personas en tiempo real
**Researched:** 2026-04-16

## Component Map

El sistema tiene seis componentes bien delimitados. Cada uno tiene una responsabilidad única y se comunica solo con sus vecinos directos.

| Componente | Responsabilidad | Se comunica con | Hilo/Proceso |
|---|---|---|---|
| **CameraCapture** | Conectar al RTSP, leer frames crudos, manejar reconexión | FrameQueue | `threading.Thread` dedicado |
| **DetectionPipeline** | Ejecutar YOLOv8n + tracker + lógica de cruce de línea | FrameQueue, EventStore, BroadcastHub, AnnotatedFrameSlot | `threading.Thread` dedicado |
| **EventStore** | Persistir cruces en SQLite, servir consultas de agregación | DetectionPipeline, API REST | Acceso síncrono con WAL mode |
| **MJPEGStreamer** | Servir frames anotados como stream MJPEG a N clientes | AnnotatedFrameSlot | Coroutine async en event loop de FastAPI |
| **BroadcastHub** | Mantener set de WebSocket, distribuir eventos JSON | DetectionPipeline, Frontend | Coroutine async en event loop de FastAPI |
| **API REST** | Endpoints `/api/stats`, `/api/history` | EventStore | Handlers async de FastAPI |

### Diagrama de componentes

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI (uvicorn)                     │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ MJPEGStreamer │   │ BroadcastHub │   │   API REST     │  │
│  │ GET /video    │   │ WS /ws/events│   │ GET /api/stats │  │
│  └──────┬───────┘   └──────┬───────┘   └───────┬────────┘  │
│         │                  │                    │            │
└─────────┼──────────────────┼────────────────────┼────────────┘
          │                  │                    │
   AnnotatedFrameSlot    eventos JSON         consultas SQL
          │                  │                    │
   ┌──────┴──────────────────┴────────────────────┴──────┐
   │              DetectionPipeline (Thread 2)            │
   │  YOLOv8n.track() → centroid tracking → line cross   │
   └──────────────────────┬──────────────────────────────┘
                          │
                    threading.Queue
                     (max ~4 frames)
                          │
   ┌──────────────────────┴──────────────────────────────┐
   │              CameraCapture (Thread 1)                │
   │  cv2.VideoCapture(rtsp://) → read loop              │
   └─────────────────────────────────────────────────────┘
```

## Data Flow

El flujo es estrictamente unidireccional: cámara a pantalla. No hay flujo inverso más allá de configuración inicial.

```
RTSP Camera
    │
    ▼
[CameraCapture Thread]
    │ frame crudo (numpy array)
    ▼
threading.Queue(maxsize=4)  ← si llena, descarta frame más viejo (get_nowait + put)
    │
    ▼
[DetectionPipeline Thread]
    │
    ├──► model.track(frame, persist=True, tracker="bytetrack.yaml")
    │       → detecciones con track_id
    │
    ├──► Lógica de cruce de línea (centroide vs línea virtual)
    │       → evento {track_id, timestamp, direction}
    │
    ├──► Dibujar bounding boxes + línea en frame
    │       → frame anotado
    │
    ├──► AnnotatedFrameSlot ← último frame anotado (sobrescritura, no cola)
    │       → MJPEGStreamer lo lee cuando el cliente pide
    │
    ├──► EventStore.insert(evento)
    │       → SQLite write
    │
    └──► BroadcastHub.notify(evento)
            → asyncio.call_soon_threadsafe() para cruzar de thread a event loop
                → cada WebSocket recibe JSON
```

### Puntos clave del flujo

1. **AnnotatedFrameSlot** no es una cola: es una variable compartida protegida con `threading.Lock`. El streamer MJPEG siempre lee el último frame disponible. No tiene sentido acumular frames viejos para un stream en vivo.

2. **threading.Queue(maxsize=4)** entre captura y detección: si la detección es más lenta que la captura (lo será, YOLOv8n en CPU tarda ~30-80 ms por frame), la cola descarta frames viejos para que la detección siempre trabaje con material reciente. Patrón: `try: q.get_nowait() except Empty: pass` antes de `q.put(frame)`.

3. **Cruce thread-to-async**: el DetectionPipeline vive en un thread Python estándar pero necesita notificar al BroadcastHub que vive en el event loop asyncio. Se usa `loop.call_soon_threadsafe(hub.dispatch, event)` para encolar la notificación de forma segura.

## Thread Model

### Por qué threads y no asyncio puro ni multiprocessing

| Alternativa | Veredicto | Razón |
|---|---|---|
| **asyncio task para captura** | NO | `cv2.VideoCapture.read()` es bloqueante puro (C++). No hay versión async. Bloquearía el event loop. |
| **asyncio.to_thread para detección** | POSIBLE pero peor | Funciona, pero el thread pool de asyncio es compartido. Un worker de detección permanente consumiría un slot del pool indefinidamente. Un thread dedicado es más explícito. |
| **multiprocessing** | NO para v1 | Serializar frames numpy entre procesos (pickle/shared memory) añade complejidad seria. Solo tiene sentido si necesitas paralelismo real en múltiples cores. Con una sola cámara y YOLOv8n, un thread dedicado basta — el GIL se libera durante las operaciones de OpenCV y la inferencia de ONNX/PyTorch. |
| **threading.Thread dedicado** | SI | OpenCV y PyTorch/ONNX liberan el GIL durante operaciones pesadas. Dos threads dedicados (captura + detección) permiten que la captura no se bloquee esperando la inferencia. El event loop de FastAPI queda libre para servir HTTP/WS. |

### Mapa de hilos en ejecución

```
Thread principal (asyncio event loop - uvicorn)
    ├── FastAPI routes (async handlers)
    ├── MJPEGStreamer (async generator con yield)
    ├── BroadcastHub (async, gestiona WebSocket connections)
    └── API REST handlers

Thread "capture" (daemon=True)
    └── while running:
            ret, frame = cap.read()
            queue.put(frame)  # con descarte si llena

Thread "detection" (daemon=True)
    └── while running:
            frame = queue.get()
            results = model.track(frame, ...)
            # procesar cruces, anotar frame, notificar
```

### Arranque y parada

Usar los eventos `lifespan` de FastAPI (no los deprecados `on_event`):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arrancar threads
    capture_thread.start()
    detection_thread.start()
    yield
    # Señalar parada
    stop_event.set()
    capture_thread.join(timeout=5)
    detection_thread.join(timeout=5)
```

El `threading.Event` llamado `stop_event` se comparte con ambos threads para señalar parada limpia.

## Lógica de cruce de línea

### Algoritmo recomendado: centroide + dirección respecto a línea

YOLOv8 con `model.track()` ya asigna IDs persistentes (BoT-SORT o ByteTrack). No necesitas implementar tu propio tracker. La lógica de conteo se reduce a:

1. Para cada detección con `track_id`, calcular el centroide del bounding box: `cx = (x1+x2)/2, cy = (y1+y2)/2`.
2. Definir una línea virtual como `y = LINE_Y` (horizontal) o como dos puntos `(x1,y1)-(x2,y2)` para líneas arbitrarias.
3. Mantener un diccionario `prev_side: dict[int, str]` que recuerda en qué lado de la línea estaba cada track_id en el frame anterior.
4. En cada frame: calcular el lado actual. Si `prev_side[track_id]` era "arriba" y ahora es "abajo" (o viceversa), registrar un cruce.
5. Marcar el track_id como "ya contado" para no contarlo dos veces si oscila cerca de la línea.

```python
def check_crossing(track_id: int, cy: float, line_y: float, prev: dict, counted: set) -> bool:
    if track_id in counted:
        return False
    side = "above" if cy < line_y else "below"
    if track_id in prev and prev[track_id] != side:
        counted.add(track_id)
        prev[track_id] = side
        return True
    prev[track_id] = side
    return False
```

### Elección de tracker

Usar **ByteTrack** (`tracker="bytetrack.yaml"`). Es más ligero que BoT-SORT (no necesita modelo ReID) y suficiente para una escena fija con una cámara. BoT-SORT brilla en escenas con oclusiones fuertes y re-apariciones, pero consume más CPU.

**Confianza:** MEDIUM. Basado en documentación oficial de Ultralytics y comparativas comunitarias. La elección real depende de la escena específica de la cámara; se puede cambiar con un solo parámetro.

## MJPEG Streaming

### Patrón correcto con FastAPI

```python
from fastapi.responses import StreamingResponse

async def mjpeg_generator():
    while True:
        frame = frame_slot.get_latest()  # lee último frame anotado
        if frame is None:
            await asyncio.sleep(0.03)
            continue
        _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg.tobytes()
            + b"\r\n"
        )
        await asyncio.sleep(0.033)  # ~30 fps máximo

@app.get("/video")
async def video_feed():
    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
```

### Consideraciones clave

- **Backpressure**: el `await asyncio.sleep(0.033)` limita a ~30 fps y cede control al event loop. Sin esto, un cliente lento podría acumular frames en el buffer de envío del socket.
- **Desconexión de cliente**: cuando el navegador cierra la pestaña, el `yield` lanza `GeneratorExit` o `ClientDisconnect`. FastAPI/Starlette lo maneja automáticamente cancelando la coroutine.
- **Múltiples clientes**: cada cliente que hace GET a `/video` obtiene su propia instancia del generador. Todos leen del mismo `frame_slot`, así que no hay duplicación de trabajo en detección.
- **Calidad JPEG**: 70 es buen balance para LAN. Subir a 85 si se nota artefacto en los bounding boxes.

## WebSocket Broadcast

### Patrón ConnectionManager

```python
class BroadcastHub:
    def __init__(self):
        self.connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.connections.add(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self.connections.discard(ws)

    async def broadcast(self, message: dict):
        async with self._lock:
            dead = []
            for ws in self.connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.connections.discard(ws)
```

### Cruce thread-to-async para el dispatch

Desde el DetectionPipeline (thread normal) hacia el BroadcastHub (asyncio):

```python
# En DetectionPipeline, al detectar un cruce:
loop.call_soon_threadsafe(
    asyncio.ensure_future,
    hub.broadcast({"type": "crossing", "count": total, "timestamp": ts})
)
```

Esto encola de forma thread-safe una coroutine en el event loop de FastAPI. No bloquea el thread de detección.

**Confianza:** HIGH. Patrón estándar documentado en la stdlib de Python y en múltiples referencias de FastAPI.

## SQLite Schema

### Esquema recomendado

```sql
-- Tabla principal de eventos
CREATE TABLE crossings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id    INTEGER NOT NULL,
    timestamp   TEXT NOT NULL,  -- ISO 8601: '2026-04-16T14:23:01'
    direction   TEXT NOT NULL,  -- 'in' o 'out'
    confidence  REAL            -- confianza de la detección YOLO
);

-- Índice para consultas de agregación por hora (el más frecuente)
CREATE INDEX idx_crossings_ts ON crossings(timestamp);

-- Vista materializada manual para conteo diario rápido (opcional, se puede calcular)
-- Para v1, las queries directas con strftime son suficientes.
```

### Queries clave

```sql
-- Personas hoy
SELECT COUNT(*) FROM crossings
WHERE timestamp >= date('now', 'start of day');

-- Histograma por hora (últimas 24h)
SELECT strftime('%H', timestamp) AS hour, COUNT(*) AS count
FROM crossings
WHERE timestamp >= datetime('now', '-24 hours')
GROUP BY hour
ORDER BY hour;

-- Serie temporal para gráfico (últimos 7 días, por hora)
SELECT strftime('%Y-%m-%d %H:00', timestamp) AS bucket,
       COUNT(*) AS count
FROM crossings
WHERE timestamp >= datetime('now', '-7 days')
GROUP BY bucket
ORDER BY bucket;
```

### Configuración de conexión

```python
import sqlite3

conn = sqlite3.connect("detections.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")       # lecturas concurrentes sin bloqueo
conn.execute("PRAGMA synchronous=NORMAL")     # equilibrio durabilidad/velocidad
conn.execute("PRAGMA busy_timeout=5000")      # esperar 5s si hay lock
```

`check_same_thread=False` es necesario porque el thread de detección escribe y los handlers async de FastAPI leen. WAL mode permite lectura concurrente con escritura sin conflictos.

**Nota sobre TEXT vs INTEGER para timestamps**: TEXT con ISO 8601 es más legible y las funciones `strftime()` de SQLite trabajan directamente con ese formato. Para este volumen de datos (decenas o cientos de eventos por día) no hay diferencia de rendimiento.

**Confianza:** HIGH. Patrones estándar de SQLite bien documentados.

## Build Order

El orden de construcción sigue las dependencias reales: no puedes mostrar algo que no has capturado, ni contar algo que no has detectado.

```
Fase 1: CameraCapture + MJPEG raw (sin detección)
    │   Validar: ¿se ve el stream en el navegador?
    │   Riesgo: problemas de conexión RTSP, codecs
    ▼
Fase 2: DetectionPipeline (YOLOv8n) + bounding boxes en MJPEG
    │   Validar: ¿se ven las cajas sobre personas?
    │   Riesgo: rendimiento CPU, calidad de detección
    ▼
Fase 3: Tracking + línea virtual + EventStore (SQLite)
    │   Validar: ¿cuenta correctamente los cruces?
    │   Riesgo: doble conteo, IDs inestables
    ▼
Fase 4: API REST + WebSocket broadcast
    │   Validar: ¿los endpoints devuelven datos correctos?
    │   Riesgo: sincronización thread/async
    ▼
Fase 5: Frontend dashboard (HTML + Chart.js + video embed)
    │   Validar: ¿se actualiza en tiempo real?
    │   Riesgo: mínimo, es consumo de APIs ya probadas
    ▼
Fase 6: Configuración centralizada + hardening
        Validar: ¿arranca con un comando y se recupera de fallos?
```

### Justificación del orden

- **Fase 1 primero** porque si el RTSP no funciona, nada más importa. Validar la conexión a la cámara es el riesgo técnico más alto y más barato de resolver temprano.
- **Fase 2 antes de 3** porque el tracking (Fase 3) depende de tener detecciones funcionales. No tiene sentido implementar conteo si no detectas personas.
- **Fase 4 antes de 5** porque el frontend solo consume APIs. Construir APIs primero permite probar con curl/Postman antes de invertir en UI.
- **Fase 6 al final** porque la configuración y el hardening son transversales y no bloquean funcionalidad.

## Failure Modes

| Fallo | Síntoma | Impacto | Mitigación |
|---|---|---|---|
| **Cámara desconectada** | `cap.read()` devuelve `(False, None)` o se cuelga | Sin frames, stream MJPEG muestra último frame o nada | Implementar timeout con `cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)`. Bucle de reconexión con backoff exponencial (1s, 2s, 4s, max 30s). Servir imagen estática "Sin señal" mientras reconecta. |
| **`cap.read()` se cuelga sin retornar** | Thread de captura bloqueado indefinidamente | Todo el pipeline se para | Leer frames en sub-thread con timeout: `threading.Timer` que llama a `cap.release()` si `read()` no retorna en 10s. Alternativa: usar `cv2.CAP_PROP_OPEN_TIMEOUT_MSEC` y `cv2.CAP_PROP_READ_TIMEOUT_MSEC`. |
| **YOLO demasiado lento** | Queue de frames se llena, descarta frames | Se pierde cobertura temporal, posibles cruces no detectados | Ya mitigado por diseño: la cola descarta frames viejos. Reducir resolución de entrada (`imgsz=320` en lugar de 640). Procesar 1 de cada N frames. |
| **SQLite bloqueado** | `sqlite3.OperationalError: database is locked` | Eventos de cruce se pierden | WAL mode + `busy_timeout=5000` debería resolver. Si persiste: encolar escrituras en un buffer en memoria y flush periódico. |
| **WebSocket client se desconecta sin cerrar** | `send_json` lanza excepción | Si no se captura, el broadcast loop se rompe | El `try/except` en `broadcast()` detecta clientes muertos y los elimina del set. |
| **Memoria creciente por tracks acumulados** | `prev_side` y `counted` crecen indefinidamente | Leak de memoria lento | Limpiar tracks no vistos en los últimos N frames. Purgar `counted` periódicamente (cada 5 minutos o al superar 1000 entradas). ByteTrack ya recicla IDs internamente. |
| **Múltiples clientes MJPEG saturan red** | Cada cliente consume ~1-3 Mbps en LAN | Latencia sube para todos | Limitar número máximo de clientes MJPEG (ej. 5). Reducir calidad JPEG o fps para clientes adicionales. En LAN con Gigabit esto rara vez es problema. |

### Estrategia general de resiliencia

El sistema debe funcionar en modo degradado: si la cámara cae, el dashboard muestra estadísticas históricas y un mensaje "Sin señal". Si la detección se atrasa, el stream sigue mostrando frames (sin boxes). Cada componente falla independientemente sin tumbar los demás.

## Patrones a seguir

### Patrón 1: Shared Frame Slot (no Queue) para MJPEG
**Qué:** El último frame anotado se almacena en una variable compartida protegida por Lock, no en una cola.
**Por qué:** Los clientes MJPEG siempre quieren el frame más reciente. Una cola acumularía latencia.
**Cuándo:** Siempre que tengas un productor rápido y múltiples consumidores que solo necesitan "lo último".

### Patrón 2: Descarte activo en la cola captura-detección
**Qué:** Antes de insertar un frame, vaciar la cola si está llena.
**Por qué:** Evita que la detección procese frames de hace 2 segundos cuando la cámara ya muestra otra cosa.
**Cuándo:** Siempre que el consumidor sea más lento que el productor y la frescura importa más que la completitud.

### Patrón 3: call_soon_threadsafe para cruce thread/async
**Qué:** Usar `loop.call_soon_threadsafe()` para encolar trabajo desde un thread hacia el event loop asyncio.
**Por qué:** Es la única forma segura de interactuar con el event loop desde otro thread.
**Cuándo:** Siempre que un thread de background necesite notificar a código async.

## Anti-patrones a evitar

### Anti-patrón 1: asyncio para operaciones OpenCV
**Qué:** Poner `cv2.VideoCapture.read()` o `model.predict()` dentro de una coroutine async.
**Por qué:** Son operaciones bloqueantes de C++. Congelan el event loop, bloqueando todos los endpoints HTTP y WebSocket.
**En su lugar:** Threads dedicados.

### Anti-patrón 2: Queue sin límite entre captura y detección
**Qué:** `threading.Queue()` sin `maxsize`.
**Por qué:** Si la detección es más lenta (siempre lo será en CPU), la cola crece indefinidamente consumiendo RAM.
**En su lugar:** `Queue(maxsize=4)` con descarte activo.

### Anti-patrón 3: Un thread por cliente MJPEG
**Qué:** Crear un thread nuevo por cada GET `/video`.
**Por qué:** Innecesario y escala mal. La detección es el cuello de botella, no el streaming.
**En su lugar:** Todos los clientes leen del mismo frame slot vía generadores async independientes.

## Fuentes

- [FastAPI StreamingResponse docs](https://fastapi.tiangolo.com/advanced/custom-response/)
- [FastAPI Concurrency and async/await](https://fastapi.tiangolo.com/async/)
- [FastAPI WebSockets docs](https://fastapi.tiangolo.com/advanced/websockets/)
- [Ultralytics YOLO Multi-Object Tracking](https://docs.ultralytics.com/modes/track/)
- [FastAPI MJPEG async multi-client example](https://github.com/HamzaYslmn/Fastapi-Async-MJPEG-Stream)
- [FastAPI issue #2956: StreamingResponse for multiple clients](https://github.com/fastapi/fastapi/issues/2956)
- [OpenCV RTSP error handling forum](https://forum.opencv.org/t/error-handling-for-rtsp-stream/17962)
- [SQLite time series best practices](https://moldstud.com/articles/p-handling-time-series-data-in-sqlite-best-practices)
- [YOLOv8 line crossing counting](https://learnopencv.com/yolov8-object-tracking-and-counting-with-opencv/)
- [Managing WebSocket clients in FastAPI](https://hexshift.medium.com/managing-multiple-websocket-clients-in-fastapi-ce5b134568a2)
