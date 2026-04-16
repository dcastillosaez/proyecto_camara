# Domain Pitfalls

**Domain:** RTSP stream capture + YOLOv8 person detection + FastAPI MJPEG streaming + SQLite dashboard
**Researched:** 2026-04-16

## Critical Pitfalls

Errores que provocan reescrituras o problemas graves de rendimiento/estabilidad.

---

### Pitfall 1: Buffer RTSP acumulativo — el vídeo se retrasa progresivamente

**What goes wrong:** `cv2.VideoCapture.read()` consume frames de un buffer interno. Si el procesamiento (YOLO) tarda más que el intervalo entre frames, el buffer crece y el vídeo muestra imágenes de hace 10, 30, 60 segundos o más. El retraso solo aumenta con el tiempo y nunca se recupera.

**Why it happens:** OpenCV usa un buffer de frames por defecto (normalmente 5). Si no vacías el buffer al ritmo de la cámara (25-30 fps), cada `read()` devuelve el frame más antiguo del buffer, no el más reciente. YOLOv8n en CPU tarda 30-80ms por frame, así que solo procesas 12-30 fps. El excedente se acumula.

**Consequences:** El dashboard muestra vídeo con decenas de segundos de retraso. Las detecciones y conteos se asocian a timestamps incorrectos. El usuario cree que ve el presente pero ve el pasado.

**Warning signs:**
- El reloj de la cámara (si es visible) no coincide con la hora real
- Al mover algo frente a la cámara, tarda varios segundos en aparecer en el dashboard
- El uso de memoria del proceso crece lentamente

**Prevention:**
1. Hilo dedicado de captura que llama `grab()` en bucle continuo a máxima velocidad, descartando frames viejos
2. Compartir solo el último frame capturado con el hilo de procesamiento (patrón productor-consumidor con variable compartida, no cola)
3. Configurar `cv2.VideoCapture.set(cv2.CAP_PROP_BUFFERSIZE, 1)` aunque no todas las plataformas lo respetan
4. Usar `cap.grab()` para vaciar el buffer y `cap.retrieve()` solo cuando necesites el frame

**Detection:** Medir diferencia entre `time.time()` y el timestamp del frame procesado. Si supera 1 segundo, hay acumulación.

**Phase:** Fase 1 (captura RTSP). Es el primer problema que aparecerá y bloquea todo lo demás.

**Confidence:** HIGH (documentado extensamente en foros de OpenCV y en la comunidad de Ultralytics)

---

### Pitfall 2: VideoCapture.read() se cuelga indefinidamente al perder conexión RTSP

**What goes wrong:** Si la cámara Tapo se reinicia, pierde red o cambia de IP, `cv2.VideoCapture.read()` puede bloquearse indefinidamente. No hay timeout por defecto. El hilo de captura muere silenciosamente o se queda congelado sin lanzar excepción.

**Why it happens:** OpenCV no tiene mecanismo robusto de timeout para RTSP en Python. Los timeouts que se añadieron en versiones recientes no están expuestos completamente en opencv-python. La función `read()` espera datos TCP que nunca llegan.

**Consequences:** El dashboard deja de actualizarse sin ningún error visible. El proceso consume recursos sin hacer nada útil. Solo se descubre cuando alguien mira el dashboard y ve la imagen congelada.

**Warning signs:**
- El frame timestamp deja de actualizarse
- El hilo de captura ya no produce frames nuevos
- No hay errores en logs pero tampoco hay actividad

**Prevention:**
1. Ejecutar la captura en un hilo con watchdog: si no se recibe frame en N segundos (por ejemplo 10), destruir el `VideoCapture` y crear uno nuevo
2. Usar `cap.grab()` con verificación de retorno booleano en lugar de `cap.read()` directo
3. Implementar lógica de reconexión con backoff exponencial (2s, 4s, 8s, max 30s)
4. Loguear cada intento de reconexión y cada éxito/fracaso
5. Considerar `os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;5000000"` (microsegundos) para limitar el timeout de apertura

**Detection:** Hilo monitor que comprueba cada 5 segundos si el timestamp del último frame es reciente.

**Phase:** Fase 1 (captura RTSP). Debe resolverse junto con el buffer.

**Confidence:** HIGH (issue #22677 de OpenCV confirma el problema)

---

### Pitfall 3: StreamingResponse de FastAPI no detecta desconexión del cliente

**What goes wrong:** Cuando un navegador cierra la pestaña del stream MJPEG, el generador de StreamingResponse sigue ejecutándose en el servidor. Con 5 pestañas abiertas y cerradas, hay 5 generadores zombi consumiendo CPU y memoria, codificando JPEGs que nadie recibe.

**Why it happens:** FastAPI/Starlette no cancela automáticamente el generador cuando el cliente se desconecta. El generador solo falla cuando intenta escribir al socket cerrado, pero en implementaciones ingenuas el yield del generador nunca detecta esa escritura fallida.

**Consequences:** Fuga de memoria proporcional al número de conexiones históricas. CPU desperdiciada codificando JPEGs. En pocas horas el servidor se vuelve lento. En equipos con poca RAM puede acabar en crash.

**Warning signs:**
- El uso de CPU crece con cada pestaña que se abre, pero no baja cuando se cierra
- El número de hilos/corrutinas activas solo sube
- `top` o `htop` muestra uso de CPU mayor al esperado

**Prevention:**
1. Verificar `await request.is_disconnected()` periódicamente dentro del generador
2. Envolver el generador en un try/except que capture `asyncio.CancelledError` y `ConnectionResetError`
3. Usar el patrón `cancel_on_disconnect` documentado por la comunidad FastAPI
4. Limitar el número máximo de clientes simultáneos del stream
5. Registrar conexiones activas y limpiar recursos al salir del generador (bloque `finally`)

**Detection:** Endpoint `/health` que reporte número de streams activos. Si supera el número de pestañas abiertas, hay fuga.

**Phase:** Fase 2 (streaming MJPEG). Implementar la detección de desconexión desde el principio, no como fix posterior.

**Confidence:** HIGH (issue #1342 y discussion #7572 de FastAPI)

---

### Pitfall 4: Conteo doble — contar detecciones por frame en vez de tracking + line crossing

**What goes wrong:** La implementación ingenua cuenta "cuántas personas detecto en este frame" y suma al total. Resultado: una persona parada frente a la cámara durante 1 minuto se cuenta como 1800 personas (30 fps x 60 segundos). O bien, una persona que camina lentamente se cuenta 50+ veces.

**Why it happens:** YOLOv8 es un detector, no un tracker. Cada frame es independiente. Sin tracking, no hay forma de saber si la persona del frame 100 es la misma que la del frame 99.

**Consequences:** Las estadísticas del dashboard son completamente inútiles. Los conteos pueden ser órdenes de magnitud mayores que la realidad. Pierde toda la credibilidad del sistema.

**Warning signs:**
- Conteos absurdamente altos (miles de personas en una hora en un pasillo)
- Los conteos fluctúan dramáticamente con la velocidad de movimiento
- Personas estáticas generan conteos continuos

**Prevention:**
1. Usar ByteTrack (integrado en Ultralytics) para asignar IDs persistentes entre frames: `model.track(frame, tracker="bytetrack.yaml")`
2. Implementar línea virtual de cruce: solo contar cuando el centroide de un track cruza la línea
3. Mantener un set de IDs ya contados para no contar dos veces el mismo track
4. Definir dirección de cruce si se necesita distinguir entrada/salida
5. NO intentar implementar tracking propio — usar ByteTrack o BoT-SORT que ya vienen con Ultralytics

**Detection:** Validar manualmente: poner una persona frente a la cámara 30 segundos y verificar que el conteo es 1, no 900.

**Phase:** Fase 3 (detección + conteo). Es el requisito central del proyecto.

**Confidence:** HIGH (documentado en Ultralytics docs y múltiples tutoriales de conteo)

---

### Pitfall 5: Mezclar primitivas de threading y asyncio

**What goes wrong:** El hilo de captura OpenCV usa `threading.Lock` para proteger el frame compartido. El endpoint async de FastAPI intenta adquirir ese lock desde una corrutina. Se produce un deadlock o bloqueo del event loop.

**Why it happens:** `threading.Lock.acquire()` es bloqueante y detiene el event loop de asyncio. Una corrutina que llama a un lock de threading congela todas las demás corrutinas hasta que el lock se libere. Al revés, usar `asyncio.Lock` desde un hilo normal tampoco funciona porque requiere un event loop.

**Consequences:** El servidor FastAPI deja de responder a todas las peticiones (no solo la del stream). El dashboard se congela. Parece un crash pero no hay error en logs.

**Warning signs:**
- El servidor deja de responder periódicamente durante fracciones de segundo
- Las respuestas HTTP tienen latencia variable e impredecible
- `asyncio` warnings sobre corrutinas que tardan demasiado

**Prevention:**
1. Para compartir el frame entre hilo de captura y FastAPI: usar una variable simple protegida con `threading.Lock`, pero en el lado de FastAPI acceder mediante `asyncio.to_thread()` o `run_in_executor()`
2. Alternativa más limpia: el hilo de captura escribe el frame en una variable atómica (en Python, asignar una referencia a un objeto es thread-safe por el GIL), y el endpoint simplemente lee la referencia sin lock
3. Nunca llamar a `threading.Lock.acquire()` directamente desde una función `async def`
4. Si necesitas notificaciones, usar `asyncio.Event` en el lado async y `threading.Event` en el lado de threads, con un bridge entre ambos

**Detection:** Loguear el tiempo que tarda cada iteración del generador MJPEG. Si hay picos de >100ms sin razón, hay contención de locks.

**Phase:** Fase 2 (cuando se conecte la captura con el streaming). Definir el patrón de comunicación entre hilos desde el principio.

**Confidence:** HIGH (documentado en la documentación oficial de FastAPI sobre concurrencia)

---

## Moderate Pitfalls

---

### Pitfall 6: YOLOv8 lento en CPU por no optimizar el pipeline

**What goes wrong:** La inferencia tarda 200-500ms por frame en vez de los 30-50ms esperados para YOLOv8n. El dashboard va a 2-5 fps, inutilizable.

**Why it happens:** Varios errores acumulativos:
- Usar imagen a 640x640 cuando 320x320 es suficiente para detección de personas a distancias cortas
- Cargar el modelo en cada frame con `YOLO("yolov8n.pt")` en vez de cargarlo una vez
- Ejecutar inferencia en TODOS los frames en vez de cada N frames
- No usar `stream=True` que evita post-procesamiento innecesario
- No exportar a ONNX/OpenVINO que duplica-triplica el rendimiento en CPU

**Warning signs:**
- FPS por debajo de 10 en el dashboard
- Uso de CPU al 100% constante en un solo core
- El vídeo se ve como slideshow

**Prevention:**
1. Cargar el modelo UNA vez al inicio: `model = YOLO("yolov8n.pt")`
2. Reducir resolución de entrada: `model.track(frame, imgsz=320)` si la escena lo permite
3. Procesar cada 2-3 frames y reutilizar las detecciones del último frame procesado para los intermedios
4. Exportar a ONNX: `model.export(format="onnx")` y luego usar el `.onnx` para inferencia
5. Para CPU Intel: exportar a OpenVINO para 2-4x speedup
6. Usar `stream=True` en el predict/track para reducir overhead

**Detection:** Medir y loguear `model.track()` time en cada llamada. Debe ser <80ms para YOLOv8n en CPU moderno.

**Phase:** Fase 3 (detección). Optimizar desde el primer momento, no como fix posterior.

**Confidence:** HIGH (benchmarks disponibles en docs de Ultralytics y OpenVINO)

---

### Pitfall 7: SQLite "database is locked" en FastAPI multihilo

**What goes wrong:** Múltiples requests concurrentes intentan escribir en SQLite simultáneamente. Se producen errores `sqlite3.OperationalError: database is locked` que pierden eventos de detección.

**Why it happens:** SQLite solo permite un escritor a la vez. Uvicorn con workers o threads puede generar escrituras concurrentes. Sin WAL mode ni busy_timeout, el segundo escritor falla inmediatamente en vez de esperar.

**Consequences:** Eventos de detección perdidos. Estadísticas incompletas. Errores intermitentes difíciles de reproducir.

**Warning signs:**
- Errores "database is locked" esporádicos en logs
- Los conteos del dashboard no cuadran con lo observado en el vídeo
- Los errores aumentan en horas de mayor actividad

**Prevention:**
1. Activar WAL mode al crear la conexión: `PRAGMA journal_mode=WAL`
2. Configurar busy_timeout: `PRAGMA busy_timeout=5000`
3. Usar UNA sola conexión de escritura (patrón writer thread/queue) o un pool muy pequeño
4. Cada hilo/request debe tener su propia conexión de lectura
5. Configurar `check_same_thread=False` si se comparte conexión entre hilos, pero preferir conexiones por hilo
6. Para este proyecto (volumen bajo, un solo escritor real), lo más simple: un único hilo de escritura con cola de eventos

**Detection:** Buscar "database is locked" en los logs del servidor.

**Phase:** Fase 4 (persistencia en SQLite). Configurar WAL y busy_timeout desde la primera migración.

**Confidence:** HIGH (documentación oficial de SQLite y múltiples posts en la comunidad FastAPI)

---

### Pitfall 8: Autenticación RTSP de la Tapo C220 — cuenta de cámara vs cuenta Tapo

**What goes wrong:** El desarrollador usa su email y contraseña de la cuenta Tapo/TP-Link en la URL RTSP. La conexión falla con 401 Unauthorized. O bien, la conexión funciona unos días y luego deja de funcionar sin cambiar nada.

**Why it happens:** Las cámaras Tapo requieren crear una cuenta de cámara separada (usuario + contraseña) desde la app Tapo, distinta de la cuenta de TP-Link/Tapo. Esta cuenta se configura en Ajustes > Avanzado > Cuenta de cámara. Además, actualizaciones de firmware o reinicios pueden resetear esta cuenta.

**Consequences:** Horas de debugging de un problema que parece de red pero es de credenciales. Frustración innecesaria al inicio del proyecto.

**Warning signs:**
- Error 401 al conectar con `cv2.VideoCapture("rtsp://user:pass@192.168.1.132:554/stream1")`
- La conexión funcionaba ayer y hoy no, sin cambiar código
- La cámara responde a ping pero no al stream RTSP

**Prevention:**
1. Crear la cuenta de cámara desde la app Tapo ANTES de empezar a programar
2. Formato correcto: `rtsp://CAMERA_USER:CAMERA_PASS@192.168.1.132:554/stream1` (alta calidad) o `/stream2` (baja calidad)
3. Guardar credenciales en archivo de configuración (.env), no hardcodeadas
4. Documentar el proceso de creación de cuenta de cámara en el README
5. Fijar IP estática de la cámara en el router para evitar cambios de IP
6. Tras actualizar firmware de la cámara, verificar que la cuenta RTSP sigue activa

**Detection:** Probar la URL RTSP con VLC antes de escribir código Python.

**Phase:** Fase 0 / pre-requisito. Verificar antes de escribir una sola línea de código.

**Confidence:** HIGH (documentación oficial de TP-Link y múltiples reportes en la comunidad)

---

## Minor Pitfalls

---

### Pitfall 9: MJPEG en el navegador acumula retraso por frames encolados en el frontend

**What goes wrong:** Aunque el servidor envíe frames al ritmo correcto, el navegador (especialmente con `<img>` tag apuntando al endpoint MJPEG) puede acumular un buffer interno. Tras varios minutos, el vídeo tiene 2-5 segundos de retraso respecto al tiempo real.

**Why it happens:** El protocolo MJPEG sobre HTTP es un multipart stream. Algunos navegadores bufferean el contenido del response body. Si el navegador no puede renderizar tan rápido como llegan los frames (por ejemplo, pestaña en background), se acumulan.

**Prevention:**
1. Limitar el framerate del stream MJPEG a 10-15 fps (suficiente para un dashboard, reduce carga)
2. En el generador del servidor, usar siempre el frame más reciente disponible, nunca una cola
3. Añadir headers anti-cache: `Cache-Control: no-cache, no-store`, `Pragma: no-cache`
4. Considerar fallback: si el navegador detecta retraso, recargar la imagen periódicamente con JavaScript
5. Alternativa avanzada: usar `<canvas>` con fetch periódico de JPEG individuales en vez de stream MJPEG continuo

**Phase:** Fase 5 (dashboard frontend). Monitorizar durante testing.

**Confidence:** MEDIUM (el comportamiento varía entre navegadores)

---

### Pitfall 10: No separar la detección del streaming — todo en un solo loop

**What goes wrong:** Un único bucle hace captura + YOLO + encoding JPEG + envío al navegador. Si YOLO tarda 80ms, el stream está limitado a 12 fps. Si hay 3 clientes, YOLO se ejecuta 3 veces por frame.

**Why it happens:** Es la implementación más intuitiva: un endpoint que lee frame, detecta, dibuja bounding boxes y lo envía. Pero no escala ni siquiera a 2 clientes.

**Prevention:**
1. Arquitectura de 3 hilos/componentes independientes:
   - Hilo de captura: lee frames al ritmo de la cámara
   - Hilo de procesamiento: ejecuta YOLO cada N frames, actualiza detecciones
   - Endpoints de streaming: leen el último frame anotado y lo sirven a N clientes
2. El frame anotado (con bounding boxes dibujados) se comparte como variable compartida
3. N clientes leen el mismo frame anotado sin multiplicar la inferencia

**Phase:** Fase 2-3 (diseño de arquitectura). Definir esta separación antes de escribir el código de detección.

**Confidence:** HIGH (patrón estándar en todos los proyectos de streaming + AI)

---

## Phase-Specific Warnings

| Phase | Pitfall probable | Mitigación |
|-------|-----------------|------------|
| Fase 0 (setup) | #8 Credenciales Tapo incorrectas | Crear cuenta de cámara y probar con VLC antes de codificar |
| Fase 1 (captura RTSP) | #1 Buffer acumulativo, #2 Cuelgue en desconexión | Hilo de captura dedicado con drain de buffer y watchdog |
| Fase 2 (streaming MJPEG) | #3 Fuga de generadores, #5 Deadlock threading/async | Detección de desconexión y patrón de comunicación entre hilos |
| Fase 3 (detección YOLO) | #4 Doble conteo, #6 Rendimiento lento | ByteTrack + línea virtual, optimización desde el inicio |
| Fase 4 (persistencia) | #7 SQLite locked | WAL mode + busy_timeout + writer único |
| Fase 5 (dashboard) | #9 Retraso acumulado en navegador | Limitar fps del stream, headers anti-cache |
| Todas las fases | #10 Arquitectura monolítica | Separar captura, procesamiento y streaming desde el inicio |

---

## Sources

- [OpenCV Forum: Delay in VideoCapture because of buffer](https://forum.opencv.org/t/delay-in-videocapture-because-of-buffer/2755)
- [OpenCV Issue #22677: VideoCapture.read() permanently stuck](https://github.com/opencv/opencv/issues/22677)
- [FastAPI Issue #1342: Stop streaming response when client disconnects](https://github.com/fastapi/fastapi/issues/1342)
- [FastAPI Discussion #7572: Stop streaming response](https://github.com/fastapi/fastapi/discussions/7572)
- [Jason Cameron: Stop Burning CPU on Dead FastAPI Streams](https://jasoncameron.dev/posts/fastapi-cancel-on-disconnect)
- [Ultralytics Docs: Object Counting](https://docs.ultralytics.com/guides/object-counting/)
- [Ultralytics Issue #13902: Increase inference speed](https://github.com/ultralytics/ultralytics/issues/13902)
- [FastAPI Docs: Concurrency and async/await](https://fastapi.tiangolo.com/async/)
- [DataSci Ocean: FastAPI Race Conditions with Global Variables](https://datasciocean.com/en/other/fastapi-race-condition/)
- [SQLite concurrent writes and "database is locked"](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/)
- [TP-Link FAQ: RTSP/ONVIF protocols](https://www.tapo.com/us/faq/724/)
- [TP-Link Support: View Tapo Camera Using RTSP/ONVIF](https://www.tp-link.com/us/support/faq/2680/)
- [go2rtc Issue #1801: Tapo Camera RTSP username/password error](https://github.com/AlexxIT/go2rtc/issues/1801)
