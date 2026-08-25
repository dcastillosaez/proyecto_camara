# Requirements: Tapo Dashboard

**Defined:** 2026-04-16
**Core Value:** Ver en tiempo real cuántas personas han pasado frente a la cámara y a qué horas hay más actividad, con el vídeo en vivo, reconocimiento facial y grabación automática integrados en el mismo panel.

## v1 Requirements

### Captura de video

- [x] **CAP-01**: El sistema captura el stream RTSP de `rtsp://192.168.1.132:554/stream1` en un hilo dedicado sin acumular buffer
- [x] **CAP-02**: El sistema se reconecta automáticamente al stream RTSP si la cámara cae o la red se interrumpe (backoff exponencial)
- [x] **CAP-03**: El sistema retransmite el vídeo en vivo al navegador vía MJPEG con latencia < 2 s en LAN

### Detección de personas

- [x] **DET-01**: El sistema detecta personas en cada frame usando YOLOv8n con confianza configurable (default 0.45)
- [x] **DET-02**: Los bounding boxes de las personas detectadas se dibujan sobre el frame MJPEG visible en el dashboard
- [x] **DET-03**: El nivel de confianza de cada detección se muestra en el overlay del bounding box
- [x] **DET-04**: La detección se ejecuta en un hilo separado al de captura para no bloquear el stream

### Conteo de personas

- [x] **CNT-01**: El sistema asigna IDs persistentes a cada persona mediante ByteTrack (supervision) para evitar dobles conteos
- [x] **CNT-02**: El sistema cuenta cruces de una línea virtual configurable usando supervision LineZone
- [x] **CNT-03**: Cada cruce registra timestamp y dirección (entrada/salida) en SQLite

### Persistencia de datos

- [x] **DB-01**: La base de datos SQLite almacena todos los eventos de cruce con timestamp (WAL mode habilitado)
- [x] **DB-02**: Los accesos a SQLite son asíncronos (aiosqlite) para no bloquear el event loop de FastAPI
- [x] **DB-03**: El sistema recupera los eventos históricos correctamente tras reinicio

### API y tiempo real

- [x] **API-01**: El endpoint `GET /api/stats` devuelve: total de personas hoy, conteo por hora de las últimas 24 h
- [x] **API-02**: El endpoint `GET /api/events` devuelve los últimos 50 eventos con timestamp, dirección y nombre de persona
- [x] **API-03**: El WebSocket `WS /ws` emite en tiempo real cada evento de cruce con: timestamp, total del día, último conteo horario
- [x] **API-04**: El endpoint `GET /video_feed` sirve el stream MJPEG con correcto cierre al desconectar el cliente

### Dashboard web

- [x] **UI-01**: El dashboard muestra el vídeo en directo con bounding boxes en tiempo real
- [x] **UI-02**: El dashboard muestra el contador total de personas del día actual, actualizado en tiempo real vía WebSocket
- [x] **UI-03**: El dashboard muestra un histograma de barras con la actividad por hora de las últimas 24 h (Chart.js)
- [x] **UI-04**: El dashboard muestra una tabla con los últimos eventos de cruce (hora, dirección, nombre de persona)
- [x] **UI-05**: El dashboard usa modo oscuro por defecto y es legible desde cualquier dispositivo de la LAN
- [x] **UI-06**: El dashboard muestra un indicador de estado de conexión a la cámara (online / reconectando)

### Configuración

- [x] **CFG-01**: Todas las variables configurables se gestionan desde un fichero `.env` con validación al arrancar (pydantic-settings)
- [x] **CFG-02**: El sistema arranca con un único comando: `uvicorn backend.main:app`

### Reconocimiento facial

- [x] **FR-01**: Endpoint `POST /api/enroll_face` registra un rostro con nombre; acepta imagen subida o frame actual de la cámara
- [x] **FR-02**: Cada detección de rostro se compara contra la BD de rostros enrolados (distancia euclidiana, tolerancia 0.55); se asigna nombre si coincide
- [x] **FR-03**: Los eventos de cruce registran el nombre de la persona identificada (o null si desconocida)

### Grabación y almacenamiento en nube

- [x] **REC-01**: Cuando se detecta actividad, comienza grabación .mp4 (mp4v) en `data/clips/`
- [x] **REC-02**: La grabación termina `recording_tail_secs` (default 5 s) después de que no hay personas en frame
- [x] **REC-03**: Cada clip finalizado se sube automáticamente a la carpeta «Grabaciones Tapo» en Google Drive vía OAuth2; el archivo local se elimina tras upload exitoso
- [x] **REC-04**: Si el upload falla, se reintenta con backoff exponencial (hasta 3 intentos); si todos fallan se marca como `failed` en BD

## v2 Requirements

### Análisis avanzado

- **ANLZ-01**: Heatmap de actividad por hora del día y día de la semana
- **ANLZ-02**: Exportación de histórico a CSV
- **ANLZ-03**: Thumbnail de la última detección guardado en disco

### Configuración avanzada

- **CFG-03**: Posición de la línea virtual ajustable desde la interfaz web sin reiniciar
- **CFG-04**: Ajuste del umbral de confianza YOLO desde la interfaz web

## Out of Scope

| Feature | Razón |
|---------|-------|
| Notificaciones push / alertas | Fuera del alcance de v1; el dashboard es observacional |
| Autenticación de usuarios | Dashboard local de red privada, sin exposición pública |
| Acceso remoto / túnel | Diseño exclusivamente para LAN |
| Múltiples cámaras | Una cámara en v1; multi-cámara requiere refactor de arquitectura |
| WebRTC | MJPEG es suficiente para LAN y elimina complejidad de señalización |

## Traceability

| Requirement | Phase | Status | Tests |
|-------------|-------|--------|-------|
| CAP-01 | Phase 2 | ✓ Complete | TEST_069, TEST_070 |
| CAP-02 | Phase 2 | ✓ Complete | TEST_071, TEST_072 |
| CAP-03 | Phase 2 | ✓ Complete | TEST_075, TEST_076 |
| DET-01 | Phase 3 | ✓ Complete | TEST_030, TEST_031, TEST_033 |
| DET-02 | Phase 3 | ✓ Complete | TEST_037, TEST_039 |
| DET-03 | Phase 3 | ✓ Complete | TEST_031, TEST_037 |
| DET-04 | Phase 3 | ✓ Complete | TEST_077 |
| CNT-01 | Phase 4 | ✓ Complete | TEST_054, TEST_055, TEST_082 |
| CNT-02 | Phase 4 | ✓ Complete | TEST_080, TEST_081, TEST_057 |
| CNT-03 | Phase 4 | ✓ Complete | TEST_058, TEST_084 |
| DB-01 | Phase 5 | ✓ Complete | TEST_011, TEST_058, TEST_029 |
| DB-02 | Phase 5 | ✓ Complete | TEST_061, TEST_023 |
| DB-03 | Phase 5 | ✓ Complete | TEST_058, TEST_060 |
| API-01 | Phase 6 | ✓ Complete | TEST_011, TEST_012, TEST_013 |
| API-02 | Phase 6 | ✓ Complete | TEST_015, TEST_016, TEST_023 |
| API-03 | Phase 6 | ✓ Complete | TEST_077 |
| API-04 | Phase 6 | ✓ Complete | TEST_075, TEST_076 |
| UI-01 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-02 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-03 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-04 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-05 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| UI-06 | Phase 7 | ✓ Complete | — (frontend, sin test automatizado) |
| CFG-01 | Phase 8 | ✓ Complete | TEST_000, TEST_001, TEST_002, TEST_003, TEST_004 |
| CFG-02 | Phase 8 | ✓ Complete | TEST_077 |
| FR-01 | Phase 9 | ✓ Complete | TEST_066, TEST_067, TEST_068 |
| FR-02 | Phase 9 | ✓ Complete | TEST_062, TEST_063, TEST_064 |
| FR-03 | Phase 9 | ✓ Complete | TEST_058, TEST_059, TEST_060 |
| REC-01 | Phase 10 | ✓ Complete | TEST_040, TEST_041 |
| REC-02 | Phase 10 | ✓ Complete | TEST_040, TEST_042 |
| REC-03 | Phase 10 | ✓ Complete | TEST_044, TEST_045 |
| REC-04 | Phase 10 | ✓ Complete | TEST_046, TEST_047 |

**Coverage:**
- v1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0
- Complete: 31/31

---
*Requirements defined: 2026-04-16*
*Last updated: 2026-04-19 — v1.0 completo, todas las fases implementadas*

---

## v2 Requirements — Milestone v2.0 (Plataforma de Video Analytics)

**Definidos:** 2026-08-07
**Origen:** `propuesta_mejora/mejoras_inmediatas.md` + `propuesta_mejora/vulnerabilidades.md`
**Especificación:** `propuesta_mejora/SPEC_v2.md`
**Nota de nomenclatura:** los prefijos `CLIP-`, `OPS-` y `SET-` sustituyen a `REC-`, `UI-` y `CFG-` en v2 para no colisionar con los IDs de v1, que permanecen inmutables.

### Pipeline de vídeo (PIPE)

- [x] **PIPE-01**: La captura RTSP publica siempre el último frame disponible y nunca bloquea esperando a un consumidor
- [x] **PIPE-02**: Cada consumidor tiene su propio slot de frame; un consumidor lento solo se pierde frames a sí mismo
- [x] **PIPE-03**: El worker de captura contiene únicamente captura, reescalado y publicación — sin detección, reconocimiento, zonas ni heatmap
- [x] **PIPE-04**: Detección, streaming y grabación corren como workers independientes que fallan y se reinician de forma aislada
- [x] **PIPE-05**: El fallo de un worker emite `DEGRADED_MODE` y no detiene el resto del pipeline
- [x] **PIPE-06**: Ningún hilo ejecuta `await` y ninguna corrutina ejecuta inferencia
- [x] **PIPE-07**: Toda estructura con crecimiento potencial (tracks, votos, cachés, estados de zona) tiene política de expiración verificada

### Detección adaptativa (DET, continúa v1)

- [x] **DET-05**: El FPS de inferencia es independiente del de captura y se reduce automáticamente cuando la latencia de inferencia supera el presupuesto configurado

### Motor de eventos (EVT)

- [x] **EVT-01**: El sistema emite eventos tipados de un catálogo cerrado (personas, identidad, comportamiento, objetos, sistema)
- [x] **EVT-02**: Un único objeto `Event` viaja al bus, a la persistencia y al WebSocket — un contrato, tres consumidores
- [x] **EVT-03**: Las detecciones no se persisten fila a fila; se agregan por minuto en `detection_stats`
- [x] **EVT-04**: Todo evento persistido incluye `camera_id`, severidad y contexto suficiente para reconstruirlo sin el frame original
- [x] **EVT-05**: El WebSocket v2 multiplexa canales (`event`, `metrics`, `tracks`, `system`) sobre una única conexión

### Motor de reglas (RULE)

- [x] **RULE-01**: Las reglas se definen en YAML validado por esquema, con condiciones de evento, zona, horario y umbrales
- [x] **RULE-02**: Las acciones soportadas son grabar, capturar, notificar, telegram, webhook, log, subir a Drive y marcar flag
- [x] **RULE-03**: Cada regla tiene debounce configurable por `(regla, cámara, identidad)`
- [x] **RULE-04**: Una regla inválida se desactiva con un error legible sin impedir el arranque del sistema
- [x] **RULE-05**: Una regla puede probarse contra el histórico reciente antes de activarse *(cerrado en Fase 33, checkpoint 33-14: `POST /api/v2/rules/{id}/test` verificado con servidor real)*

### Persistencia v2 (DB, continúa v1)

- [x] **DB-10**: El esquema separa `cameras`, `persons`, `face_embeddings`, `tracks`, `events`, `detection_stats`, `recordings`, `zones`, `lines`, `rules`, `app_config` y `system_metrics`
- [x] **DB-11**: Las migraciones son idempotentes, se ejecutan al arrancar y registran la versión de esquema
- [x] **DB-12**: Antes de cada migración destructiva se genera una copia de seguridad de la base de datos
- [x] **DB-13**: El histórico de `crossing_events` se conserva íntegro como eventos `LINE_CROSSED`
- [x] **DB-14**: Existen los índices necesarios para que las consultas de timeline y analítica sobre 100.000 eventos respondan en menos de 500 ms

### Grabación de clips (CLIP)

- [x] **CLIP-01**: Cada clip incluye un pre-buffer configurable anterior al evento que lo dispara
- [x] **CLIP-02**: Cada clip incluye un post-buffer configurable posterior a la última detección
- [x] **CLIP-03**: El pre-buffer se mantiene en RAM dentro de un presupuesto configurado y medible
- [x] **CLIP-04**: Cada grabación registra duración, tamaño, checksum SHA-256, miniatura, motivo, evento origen, persona y zona
- [x] **CLIP-05**: La miniatura se genera en el momento del evento y se sirve por API
- [x] **CLIP-06**: La retención local y la subida a la nube son políticas independientes y configurables
- [x] **CLIP-07**: Los fallos de subida se reintentan con backoff desde una cola persistente sin bloquear el pipeline

### Observabilidad (OBS)

- [x] **OBS-01**: El sistema expone métricas en formato Prometheus y en JSON para el dashboard
- [x] **OBS-02**: Se contabilizan frames descartados por suscriptor, reconexiones RTSP y antigüedad del último frame
- [x] **OBS-03**: Se miden los FPS reales de captura, detección, tracking, reconocimiento y ReID por separado
- [x] **OBS-04**: Se mide la latencia de inferencia por etapa como histograma
- [x] **OBS-05**: Se mide la latencia end-to-end desde la captura del frame hasta el envío del evento por WebSocket
- [x] **OBS-06**: Se monitorizan profundidad de colas, tracks activos, cola de subida, fallos de subida, tamaño de BD y espacio libre en disco

### Seguridad v2 (SEC)

- [x] **SEC-15**: No existe uso de `pickle` en código de producción; la migración de embeddings legacy es un script explícito de un solo uso
- [x] **SEC-16**: La ruta del modelo YOLO se valida por extensión y contención dentro del directorio del proyecto; un valor inválido aborta el arranque con mensaje claro

### Reconocimiento facial (FACE)

- [x] **FACE-01**: Los embeddings faciales se generan con ArcFace (512D, L2-normalizado) sobre ONNXRuntime
- [x] **FACE-02**: Las caras se alinean por landmarks antes de generar el embedding
- [x] **FACE-03**: Se descartan las caras que no superan los umbrales de tamaño, nitidez y pose, registrando el motivo del descarte
- [x] **FACE-04**: La búsqueda de identidad sobre 1.000 personas se resuelve en menos de 5 ms
- [x] **FACE-05**: Existe un procedimiento de re-enrolamiento masivo desde las imágenes de la galería que reporta identidades migradas y fallidas
- [x] **FACE-06**: `dlib` y `face-recognition` dejan de ser dependencias del proyecto
- [x] **FACE-07**: Una identidad solo se confirma tras N votos coherentes en una ventana deslizante
- [x] **FACE-08**: Cada track tiene un estado de identidad explícito: UNKNOWN, CANDIDATE, CONFIRMED o TEMPORARILY_LOST
- [x] **FACE-09**: Una visita de una persona conocida genera un único evento de reconocimiento, no uno por frame
- [x] **FACE-10**: La pérdida y recuperación de un track no crea identidades duplicadas
- [x] **FACE-11**: El reconocimiento se dispara por evento (track nuevo, confianza baja, revalidación vencida), no ciegamente cada N frames

### Re-identificación (REID)

- [x] **REID-01**: Se genera un embedding de apariencia por track mediante OSNet en ONNX
- [x] **REID-02**: Un track nuevo puede heredar la identidad de un track cerrado recientemente si la similitud supera el umbral y no hay conflicto con un track activo
- [x] **REID-03**: Una persona identificada que deja de mostrar la cara conserva su identidad
- [x] **REID-04**: El coste de ReID está acotado a una inferencia por track cada N segundos

### Comprensión de escena (BEH)

- [x] **BEH-01**: El sistema detecta merodeo con umbrales de tiempo y desplazamiento configurables
- [x] **BEH-02**: El sistema detecta carrera e inmovilidad prolongada
- [x] **BEH-03**: El sistema detecta aglomeración a partir de un número configurable de tracks simultáneos
- [x] **BEH-04**: El sistema emite entrada y salida de zona por track con tiempo de permanencia
- [x] **BEH-05**: Cada evento de comportamiento incluye las magnitudes que lo justifican
- [x] **BEH-06**: Las clases detectadas son configurables más allá de "persona" (bicicleta, coche, moto, mochila, maleta)
- [x] **BEH-07**: El sistema detecta objetos abandonados y objetos retirados
- [x] **BEH-08**: El sistema expone un resumen de contexto de escena: hora, zona, personas totales, conocidas, desconocidas y nivel de actividad
- [x] **BEH-09**: El nivel de actividad se calcula contra la media móvil histórica de esa franja horaria

### Interfaz de operaciones (OPS)

- [ ] **OPS-01**: La lógica del frontend vive en módulos ES separados por responsabilidad, no en `index.html`
- [ ] **OPS-02**: Ningún módulo de frontend supera las 300 líneas
- [ ] **OPS-03**: La modularización mantiene paridad funcional completa con v1.2 y no introduce build step
- [ ] **OPS-04**: La pantalla principal responde sin scroll a: si el sistema está bien, qué ocurre ahora y si ha pasado algo importante
- [ ] **OPS-05**: El overlay de detecciones se dibuja sobre canvas alimentado por WebSocket, sin re-renderizar el stream MJPEG
- [ ] **OPS-06**: La reconexión del WebSocket es automática y visible sin recargar la página
- [x] **OPS-07**: Los eventos se presentan como línea temporal con hora, severidad, descripción, zona y miniatura
- [x] **OPS-08**: Cada evento ofrece acciones directas: ver vídeo, ver captura, marcar como persona y descartar
- [x] **OPS-09**: Los filtros de eventos se resuelven en servidor con paginación por cursor
- [x] **OPS-10**: Un evento nuevo aparece en la interfaz en menos de un segundo
- [x] **OPS-11**: El centro de alertas agrupa alertas activas, muestra qué regla las disparó y permite silenciarlas
- [x] **OPS-12**: Existe una vista de analítica con personas por hora, ocupación por zona y heatmap
- [x] **OPS-13**: La analítica muestra ranking de personas por visitas y tendencia frente al periodo anterior
- [x] **OPS-14**: Las agregaciones se calculan en base de datos, no en el navegador
- [x] **OPS-15**: La analítica es exportable a CSV y JSON en el rango visible
- [ ] **OPS-16**: Existe una vista de cámara con live view y salud en tiempo real (FPS, latencia, CPU, RAM, estado RTSP)
- [ ] **OPS-17**: Los ajustes rápidos de detección y grabación son accesibles desde la vista de cámara
- [ ] **OPS-18**: La configuración se edita desde la interfaz mediante un árbol de secciones
- [ ] **OPS-19**: Los parámetros que requieren reinicio están claramente señalizados frente a los que se aplican en caliente
- [ ] **OPS-20**: Cada sección de configuración permite restaurar los valores por defecto
- [x] **OPS-21**: Las zonas se dibujan, editan y borran directamente sobre el vídeo con coordenadas independientes de la resolución *(cerrado en Fase 33, checkpoint 33-14)*
- [x] **OPS-22**: Las líneas de conteo se dibujan sobre el vídeo con indicación visual de dirección *(cerrado en Fase 33, checkpoint 33-14)*
- [x] **OPS-23**: Las zonas tienen tipo (conteo, restringida, exclusión) y horario propio *(cerrado en Fase 33, checkpoint 33-14)*
- [x] **OPS-24**: Las reglas se componen desde formularios en la interfaz, sin editar YAML *(cerrado en Fase 33, checkpoint 33-14)*

### Configuración runtime (SET)

- [x] **SET-01**: La configuración operativa se persiste en base de datos y es editable en caliente
- [x] **SET-02**: La precedencia es configuración runtime > `.env` > valor por defecto del código, documentada y testeada
- [x] **SET-03**: Todo parámetro tiene rango validado en servidor con mensaje de error legible
- [x] **SET-04**: Todo cambio de configuración queda auditado como evento con su diff

### Testing v2 (TEST)

- [ ] **TEST-01**: Existe un test de integración del pipeline completo con fuente RTSP sintética, ejecutable en CI sin cámara real
- [ ] **TEST-02**: Playwright cubre los escenarios críticos de frontend: vídeo, cámara offline, reconexión WS, evento nuevo, filtros, clips, modales, PTZ, alertas y editor de zonas
- [ ] **TEST-03**: La suite completa se ejecuta en menos de 5 minutos
- [ ] **TEST-04**: CI ejecuta unit e integración en cada push y E2E en cada pull request
- [ ] **TEST-05**: La cobertura de los paquetes `events`, `pipeline` y `perception` supera el 80%

### Escalabilidad (SCALE)

- [ ] **SCALE-01**: El pipeline de una cámara está encapsulado en una clase instanciable N veces
- [ ] **SCALE-02**: `camera_id` está presente y es obligatorio en todas las tablas con dimensión de cámara
- [ ] **SCALE-03**: Todos los endpoints v2 aceptan `camera_id`, con valor por defecto cuando solo hay una cámara
- [ ] **SCALE-04**: Parar o reiniciar una cámara no afecta a las demás ni al servidor
- [ ] **SCALE-05**: Se pueden añadir y configurar cámaras desde la interfaz sin reiniciar el servidor
- [ ] **SCALE-06**: Existe vista mosaico multi-cámara y selector de cámara en la vista de operaciones
- [ ] **SCALE-07**: Zonas, líneas y reglas son propias de cada cámara, con posibilidad de reglas globales
- [ ] **SCALE-08**: El presupuesto de CPU se reparte automáticamente entre cámaras y la interfaz advierte al superarlo
- [ ] **SCALE-09**: Todo el acceso a datos pasa por repositorios, permitiendo cambiar de SQLite a PostgreSQL sin tocar la lógica
- [ ] **SCALE-10**: El bus de eventos tiene implementación in-process por defecto y una alternativa distribuida opcional
- [ ] **SCALE-11**: La GPU se detecta automáticamente y se usa si está disponible, con fallback limpio a CPU
- [ ] **SCALE-12**: Sin GPU, el comportamiento del sistema es idéntico al de la ruta CPU

### Fuera de alcance v2.0 (backlog v2.1)

- Detección de caídas mediante estimación de pose
- Reconocimiento de matrículas (ALPR)
- Búsqueda semántica de eventos en lenguaje natural
- PWA / app móvil offline
- Federación multi-sitio
- Índice vectorial `hnswlib` (solo si el número de identidades supera 20.000)

### Cobertura v2

| Bloque | Requisitos | Fases |
|--------|-----------|-------|
| A — Robustez | PIPE (7), DET-05, EVT (5), RULE (5), DB (5), CLIP (7), OBS (6), SEC (2) | 17-22 |
| B — IA | FACE (11), REID (4), BEH (9) | 23-27 |
| C — Producto | OPS (24), SET (4), TEST (5) | 28-34 |
| D — Escalabilidad | SCALE (12) | 35-38 |

- Requisitos v2 totales: **107**
- Mapeados a fases: **107**
- Sin mapear: **0**
- Completados: **49/107** (bloque A completo incluido RULE-05, cerrado en Fase 33; OPS-21..OPS-24 cerrados en Fase 33; FACE-01..06 de la Fase 23 completos en código, verificación con datos reales pendiente — checkpoint 23-02 Task 4)

---
*Requisitos v2 definidos: 2026-08-07*
*Especificación de referencia: propuesta_mejora/SPEC_v2.md*
