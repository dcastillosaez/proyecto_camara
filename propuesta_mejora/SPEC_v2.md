# SPEC v2.0 — Tapo Dashboard → Plataforma de Video Analytics

**Documento:** Especificación técnica de referencia
**Origen:** `propuesta_mejora/mejoras_inmediatas.md` (25 puntos) + `propuesta_mejora/vulnerabilidades.md`
**Fecha:** 2026-08-07
**Estado del proyecto:** v1.2 completa (16/16 fases GSD)
**Milestone objetivo:** v2.0 — fases 17 a 38

---

## 0. Cómo usar este documento

| Documento | Rol |
|-----------|-----|
| `propuesta_mejora/SPEC_v2.md` (este) | **Referencia**: arquitectura objetivo, decisiones técnicas, contratos de módulo, modelo de datos, catálogo de eventos, detalle ejecutable por fase |
| `.planning/ROADMAP.md` § v2.0 | **Gestión**: fases GSD 17-38 con dependencias y criterios de éxito |
| `.planning/REQUIREMENTS.md` § v2 | **Trazabilidad**: requisitos con ID estable referenciados por cada fase |

Cada fase de la sección 9 es directamente convertible en `.planning/phases/NN-nombre/NN-01-PLAN.md` sin diseño adicional.

**Regla de oro del milestone:** ninguna fase puede romper la funcionalidad v1.2 en producción. Todo cambio estructural entra detrás de un flag de configuración con default = comportamiento v1, y el flag se invierte a default v2 solo cuando la fase pasa su verificación.

---

## 1. Estado actual (inventario real del repositorio)

### 1.1 Backend

| Fichero | LOC | Responsabilidad actual | Deuda identificada |
|---------|-----|------------------------|--------------------|
| `backend/main.py` | 722 | FastAPI app, ~30 endpoints, WebSocket, broadcast, watchdog, purga, middleware | Dios-objeto: routing + orquestación + ciclo de vida mezclados |
| `backend/stream.py` | 534 | `RTSPStream`: captura, drain, detección, tracking, zonas, heatmap, capturas, hilo de reconocimiento | **Núcleo del acoplamiento**: 8 responsabilidades en una clase |
| `backend/recognizer.py` | 551 | `PersonRecognizer`: dlib/face-recognition, SQLite propia (`data/persons.db`), caché por tracker_id | dlib HOG + 128D + distancia euclídea; sin quality gating; sin votación temporal; `pickle.loads` legacy vivo |
| `backend/database.py` | 416 | SQLAlchemy async: `CrossingEvent`, `Zone`, `Capture`, `Recording` | Sin `camera_id`; sin separación detection/event; sin tabla `events` genérica |
| `backend/main.py` (API) | — | `/api/stats`, `/api/events`, `/api/health`, `/api/zones`, `/api/heatmap`, `/api/alerts/*`, `/api/recordings`, `/ptz/*`, `/camera/*` | Sin versionado; sin `/api/v2` |
| `backend/notifier.py` | 191 | Telegram + webhook + cooldown | Lógica de "cuándo alertar" hardcodeada, no basada en reglas |
| `backend/recorder.py` | 126 | `ClipRecorder`: graba al detectar, cierra tras `recording_tail_secs` | **Sin pre-buffer**: se pierden los segundos previos al evento |
| `backend/tracker.py` | 134 | `PersonTracker`: ByteTrack + `LineZone` | Correcto; falta exponer estado de track para ReID |
| `backend/detector.py` | 69 | `PersonDetector`: YOLO26n/YOLOv8n | Correcto; falta política adaptativa por FPS |
| `backend/config.py` | 156 | `Settings` pydantic-settings, ~55 claves | Crece sin agrupación; sin config runtime editable desde UI |
| `backend/camera.py` / `ptz.py` / `gdrive.py` / `auth.py` / `ssl_utils.py` | 198/126/140/80/103 | Correctos | `gdrive.py` sin cola de reintentos persistente |

### 1.2 Frontend

```
frontend/
├── index.html   1843 LOC  ← TODA la lógica del dashboard
└── app.js          2 LOC  ← "Lógica del dashboard incluida en index.html"
```

Es el mayor bloqueante de la Fase C: no se puede añadir Event Timeline, Analítica y Configuración visual sobre un único fichero de 1843 líneas.

### 1.3 Seguridad — estado real frente a `vulnerabilidades.md`

Verificado contra el código actual:

| # | Vulnerabilidad | Estado real | Acción v2 |
|---|----------------|-------------|-----------|
| 1 | `pickle` en BD de personas | 🟡 **Parcial** — `recognizer.py:485` mantiene `pickle.loads` para migrar blobs legacy | Fase 22: eliminar la ruta pickle por completo tras migración explícita |
| 2 | Upload sin validación | 🟢 Corregido (`_ALLOWED_IMAGE_TYPES`, `main.py:567`) | Añadir límite de bytes explícito |
| 3 | CORS | 🟢 Corregido (`CORSMiddleware`, `main.py:312`) | — |
| 4 | Credenciales en `CAMERA_URL` | 🟢 Corregido (`build_rtsp_url`) | — |
| 5 | WS tokens sin TTL | 🟢 Corregido (`_purge_expired_tokens`) | — |
| 6 | `YOLO_MODEL_PATH` sin validar | 🔴 **Pendiente** | Fase 22 |
| 7 | Rate limiting | 🟢 Corregido (`slowapi`) | Extender a endpoints v2 |
| 8 | Certificado sin SAN | 🟢 Corregido (`_build_san_entries`) | — |
| 9 | Headers de seguridad | 🟢 Corregido (`SecurityHeadersMiddleware`) | — |
| 10 | `limit` sin cota | 🟢 Corregido (`le=500`) | — |
| 11 | `name` sin longitud | 🟢 Corregido (`max_length=100`) | — |
| 12 | Logs con credenciales | 🟢 Corregido (`mask_rtsp_url`) | — |
| 13 | Permisos clave SSL | 🟢 Corregido (`_restrict_key_permissions`) | — |
| 14 | SRI en Chart.js | 🟢 Corregido (`integrity=sha384-...`) | Mantener al modularizar el frontend |

**Conclusión:** el punto 15 de la propuesta se reduce a 2 ítems reales (#1 residual y #6) más el hardening de la superficie nueva que introduce v2. No requiere una fase completa; se resuelve en la Fase 22 junto con la limpieza de memoria.

---

## 2. Arquitectura objetivo

### 2.1 Vista de capas

```
┌─────────────────────────────────────────────────────────────┐
│                       CAPTURE LAYER                         │
│  CaptureWorker (1 por cámara) → FrameBroker (latest-frame)   │
└───────────────────────────┬─────────────────────────────────┘
                            │  fan-out sin bloqueo
      ┌─────────────┬───────┴────────┬──────────────┐
      ▼             ▼                ▼              ▼
┌───────────┐ ┌───────────┐   ┌────────────┐ ┌────────────┐
│ Detection │ │ Recording │   │ Streaming  │ │  Metrics   │
│  Worker   │ │  Worker   │   │  Worker    │ │  Sampler   │
└─────┬─────┘ └───────────┘   └────────────┘ └────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER                      │
│  Tracker (ByteTrack) → TrackRegistry                     │
│      ├── FaceWorker    (InsightFace/ArcFace + quality)   │
│      ├── ReIDWorker    (OSNet embedding)                 │
│      └── BehaviorWorker(loitering, dirección, velocidad) │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│                      EVENT ENGINE                        │
│  Detecciones + estado de tracks → eventos tipados        │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│                       RULE ENGINE                        │
│  rules.yaml → match(evento, contexto) → acciones         │
└───────┬───────────────┬───────────────┬──────────────────┘
        ▼               ▼               ▼
   Alertas          Grabación        Persistencia
   (notifier)       (recorder)       (SQLite)
        └───────────────┴───────────────┘
                        ▼
              EventBus → WebSocket → OPERATIONS UI
```

### 2.2 Invariantes de diseño (no negociables)

1. **La captura nunca espera a la IA.** `CaptureWorker` escribe siempre el último frame y descarta el anterior si nadie lo consumió.
2. **Ningún worker bloquea a otro.** Toda comunicación entre workers es por cola acotada con política de descarte explícita.
3. **Perder frames > acumular latencia.** Colas de frames con `maxsize=1`; colas de eventos con `maxsize` amplio pero acotado.
4. **I/O externo (Drive, Telegram, webhook) nunca está en el camino crítico.** Cola persistente + reintentos con backoff.
5. **Detección ≠ Evento.** Las detecciones son datos volátiles agregables; los eventos son hechos persistentes.
6. **Todo dato con dimensión de cámara lleva `camera_id`** desde la Fase 19, aunque solo haya una cámara.
7. **La configuración runtime es un dato, no un fichero.** `.env` define el arranque; la configuración operativa vive en BD y se edita desde la UI.

### 2.3 Modelo de concurrencia

| Componente | Mecanismo | Motivo |
|------------|-----------|--------|
| CaptureWorker | `threading.Thread` (bloqueante en `cap.read()`) | OpenCV libera el GIL en I/O |
| FrameBroker | `threading.Lock` + slot único por suscriptor | Coste O(1), sin copias innecesarias |
| Detection/Face/ReID Worker | `threading.Thread` (numpy/ONNX liberan GIL) | Inferencia libera el GIL |
| Recording Worker | `threading.Thread` | `cv2.VideoWriter` es bloqueante |
| EventEngine | `asyncio.Queue` en el loop de FastAPI | Consume eventos y hace I/O async (BD, WS) |
| Puente hilo → asyncio | `asyncio.run_coroutine_threadsafe` / `loop.call_soon_threadsafe` | Único punto de cruce permitido |
| Uploads (Drive) | `ThreadPoolExecutor(max_workers=2)` + cola en BD | Reintentos sin bloquear |

**Regla:** un hilo nunca hace `await`; una corrutina nunca hace inferencia.

---

## 3. Decisiones técnicas (ADR resumidos)

### ADR-01 — FrameBroker con slot por suscriptor, no cola compartida
**Decisión:** cada suscriptor tiene su propio slot de 1 frame protegido por lock; el productor sobreescribe.
**Alternativas descartadas:** `queue.Queue(maxsize=1)` por suscriptor (coste de sincronización mayor y semántica de `put_nowait`+`get_nowait` más frágil); cola compartida (un consumidor lento roba frames a otro).
**Consecuencia:** un consumidor lento solo se pierde frames a sí mismo. Métrica `dropped_frames` por suscriptor.

### ADR-02 — InsightFace (ArcFace, modelo `buffalo_s`) sobre ONNXRuntime CPU
**Decisión:** sustituir `face-recognition`/dlib por `insightface` con `onnxruntime`.
**Motivo:** ArcFace 512D supera ampliamente al embedding 128D de dlib en condiciones de CCTV (ángulo, iluminación, escala). El detector SCRFD incluido es mejor que HOG en caras pequeñas.
**Riesgo:** `insightface` requiere compilación en Windows en algunas versiones. **Mitigación:** fijar `onnxruntime` y usar wheels precompiladas; la Fase 23 empieza con un spike de instalación como criterio de salida bloqueante. Si falla, plan B = `onnxruntime` directo con modelo ArcFace exportado (`w600k_r50.onnx`) sin el paquete `insightface`.
**Migración:** los embeddings 128D de dlib **no son compatibles** con ArcFace 512D. Requiere re-enrolamiento desde las imágenes originales de `data/gallery/`. La Fase 23 incluye un script de re-enrolamiento masivo.

### ADR-03 — Índice vectorial en memoria, no base vectorial externa
**Decisión:** matriz numpy `(N, 512)` normalizada + producto escalar (`np.dot`) para similitud coseno.
**Motivo:** con N < 5.000 identidades el coste es < 1 ms. Introducir FAISS/Qdrant/Milvus es complejidad operacional sin beneficio.
**Umbral de revisión:** si N > 20.000, migrar a `hnswlib` (single-file, sin servidor).

### ADR-04 — ReID con OSNet vía ONNX
**Decisión:** `osnet_x0_25` exportado a ONNX (embedding 512D), inferido sobre los crops de persona.
**Motivo:** ~2.2M parámetros, diseñado para ReID de personas, ejecutable en CPU. Alternativas (`torchreid` completo) arrastran PyTorch.
**Política:** ReID se calcula 1 vez cada N frames por track, no por frame.

### ADR-05 — Reglas en YAML con esquema validado por Pydantic, no DSL propio
**Decisión:** `config/rules.yaml` cargado y validado con modelos Pydantic; editable desde la UI y persistido en la tabla `rules`.
**Motivo:** legible, versionable, y la validación Pydantic da errores claros. Un DSL propio o `eval()` es innecesario y peligroso.

### ADR-06 — SQLite se mantiene; se separa el esquema
**Decisión:** seguir con SQLite/WAL. Las detecciones **no** se persisten fila a fila: se agregan en memoria y se vuelcan como `detection_stats` por minuto.
**Motivo:** a 8 FPS de detección, persistir cada detección son ~700k filas/día. Los eventos son ~decenas/día.
**Puerta a PostgreSQL:** Fase 37, opcional, tras abstraer el acceso en un repositorio.

### ADR-07 — Pre-buffer en RAM con `collections.deque`
**Decisión:** buffer circular de `pre_buffer_secs × recording_fps` frames JPEG-encoded en RAM.
**Motivo:** almacenar frames BGR crudos a 720p son ~2.7 MB/frame; 10 s a 15 FPS = 400 MB. Encodeados a JPEG q=85 son ~120 KB/frame → **18 MB**. Aceptable.
**Consecuencia:** el `RecordingWorker` decodifica el pre-buffer al escribir el clip. Coste puntual, no en el camino crítico.

### ADR-08 — Frontend: ES modules nativos, sin build step
**Decisión:** dividir `index.html` en módulos ES6 (`<script type="module">`) servidos estáticamente.
**Motivo:** el proyecto prohíbe build step. Los ES modules nativos funcionan en todos los navegadores objetivo y permiten separar responsabilidades sin bundler.
**Consecuencia:** los módulos se sirven desde `/static/js/*.js`; hay que añadir `StaticFiles` mount y mantener SRI en las dependencias CDN.

### ADR-09 — Versionado de API: `/api/v2/*` conviviendo con `/api/*`
**Decisión:** los endpoints nuevos y los que cambian de forma van bajo `/api/v2`. Los `/api/*` v1 se mantienen hasta la Fase 34.
**Motivo:** permite migrar el frontend fase a fase sin big bang.

### ADR-10 — Métricas en formato Prometheus, expuestas en `/metrics`
**Decisión:** `prometheus-client` con registry propio; el dashboard consume `/api/v2/metrics` (JSON) y el endpoint `/metrics` queda disponible para scraping.
**Motivo:** evita reinventar contadores/histogramas y abre la puerta a Grafana sin trabajo extra.

---

## 4. Stack: adiciones y cambios

### 4.1 Dependencias nuevas

| Paquete | Versión | Fase | Propósito |
|---------|---------|------|-----------|
| `insightface` | >=0.7.3 | 23 | Detección + alineación + ArcFace |
| `onnxruntime` | >=1.19 | 23 | Runtime CPU para ArcFace y OSNet |
| `prometheus-client` | >=0.21 | 21 | Métricas |
| `PyYAML` | >=6.0 | 19 | Carga de `rules.yaml` |
| `playwright` | >=1.48 | 34 | Tests E2E de frontend (dev) |
| `pytest-asyncio` | >=0.24 | 19 | Tests del EventEngine (dev) |
| `hnswlib` | >=0.8 | opcional | Solo si N identidades > 20.000 |

### 4.2 Dependencias a retirar

| Paquete | Fase | Sustituto |
|---------|------|-----------|
| `face-recognition` | 23 (retirada real en 24) | `insightface` |
| `dlib` | 23 | (transitiva de la anterior) |

**Nota Windows:** `dlib` es precisamente la dependencia más problemática de instalar en Windows. Retirarla simplifica el arranque en máquinas nuevas.

### 4.3 Modelos a descargar

| Modelo | Tamaño | Ubicación |
|--------|--------|-----------|
| `buffalo_s` (SCRFD + ArcFace) | ~90 MB | `models/insightface/` |
| `osnet_x0_25_msmt17.onnx` | ~9 MB | `models/reid/` |
| `yolo26n.pt` | ya presente | raíz |

Añadir `models/` a `.gitignore` y un script `scripts/fetch_models.py` idempotente.
---

## 5. Contratos de módulo

Estructura de directorios objetivo del backend:

```
backend/
├── main.py                  # solo: app factory, montaje de routers, lifespan
├── config.py                # Settings de arranque (.env)
├── pipeline/
│   ├── __init__.py
│   ├── broker.py            # FrameBroker, Frame
│   ├── capture.py           # CaptureWorker
│   ├── detection.py         # DetectionWorker (+ política adaptativa)
│   ├── tracking.py          # TrackRegistry (envuelve PersonTracker)
│   ├── streaming.py         # StreamingWorker (MJPEG)
│   ├── recording.py         # RecordingWorker (+ pre/post buffer)
│   └── manager.py           # CameraPipeline, CameraManager
├── perception/
│   ├── face/
│   │   ├── engine.py        # FaceEngine (InsightFace)
│   │   ├── quality.py       # FaceQualityAssessor
│   │   ├── index.py         # IdentityIndex (matriz numpy)
│   │   └── identity.py      # IdentityStateMachine, TemporalVoter
│   ├── reid/
│   │   ├── engine.py        # ReIDEngine (OSNet ONNX)
│   │   └── gallery.py       # TrackGallery (continuidad de tracks)
│   └── behavior.py          # BehaviorAnalyzer
├── events/
│   ├── types.py             # EventType, Event (Pydantic)
│   ├── engine.py            # EventEngine
│   ├── bus.py               # EventBus (pub/sub async)
│   └── rules.py             # RuleEngine, Rule, Action
├── storage/
│   ├── models.py            # SQLAlchemy declarative
│   ├── repositories.py      # EventRepo, RecordingRepo, PersonRepo, ...
│   └── migrations.py        # migraciones idempotentes
├── observability/
│   ├── metrics.py           # registry Prometheus + helpers
│   └── latency.py           # trazado end-to-end
├── api/
│   ├── v1/                  # routers actuales (compatibilidad)
│   └── v2/                  # routers nuevos
└── ... (auth.py, ssl_utils.py, gdrive.py, notifier.py, ptz.py, camera.py)
```

### 5.1 `pipeline/broker.py`

```python
@dataclass(slots=True)
class Frame:
    camera_id: str
    seq: int                  # monotónico por cámara
    captured_at: float        # time.monotonic() en el momento de cap.read()
    wall_clock: datetime      # timestamp real para eventos
    image: np.ndarray         # BGR, tamaño de proceso

class FrameBroker:
    """Fan-out latest-frame. Un slot por suscriptor; el productor sobreescribe."""

    def subscribe(self, name: str) -> "Subscription": ...
    def publish(self, frame: Frame) -> None:
        """Nunca bloquea. Incrementa dropped[name] si el slot estaba lleno."""
    def stats(self) -> dict[str, dict[str, int]]:
        """{name: {"delivered": int, "dropped": int, "last_seq": int}}"""

class Subscription:
    def get(self, timeout: float | None = None) -> Frame | None:
        """Devuelve el frame más reciente no consumido, o None si timeout."""
    def close(self) -> None: ...
```

**Criterios verificables:** `publish` es O(1) y no bloquea nunca (test con suscriptor que duerme 1 s); `stats()["detector"]["dropped"] > 0` cuando el consumidor va más lento que el productor.

### 5.2 `pipeline/capture.py`

```python
class CaptureWorker:
    """Reemplaza el _capture_loop de RTSPStream. SOLO captura."""

    def __init__(self, camera_id: str, rtsp_url: str, broker: FrameBroker,
                 process_size: tuple[int, int], reconnect_backoff: Backoff): ...
    def start(self) -> None: ...
    def stop(self, timeout: float = 5.0) -> None: ...
    @property
    def health(self) -> CaptureHealth:
        """fps, reconnects, last_frame_age, connected, native_resolution"""
```

Responsabilidades **eliminadas** respecto a `RTSPStream`: detección, tracking, zonas, heatmap, capturas de galería, reconocimiento. Todo eso migra a workers.

### 5.3 `pipeline/detection.py`

```python
class AdaptiveRate:
    """Decide si procesar el frame actual según el FPS objetivo y la carga real."""
    def __init__(self, target_fps: float, min_fps: float, max_fps: float): ...
    def should_process(self, now: float) -> bool: ...
    def observe(self, latency: float) -> None:
        """Baja el FPS efectivo si la latencia de inferencia sube."""

class DetectionWorker:
    def __init__(self, sub: Subscription, detector: PersonDetector,
                 tracks: TrackRegistry, rate: AdaptiveRate, sink: Callable): ...
```

**Política de FPS objetivo** (configurable, defaults):

| Etapa | FPS objetivo | Nota |
|-------|--------------|------|
| Captura | nativo (~15-25) | limitado por la cámara |
| Detección | 8 | `AdaptiveRate` lo baja a `min_fps=3` bajo carga |
| Tracking | igual que detección | ByteTrack se actualiza solo con detecciones |
| Reconocimiento facial | 2 | + disparo por evento (track nuevo / confianza baja / revalidación) |
| ReID | 1 por track cada 2 s | |

### 5.4 `perception/face/`

```python
@dataclass
class FaceCandidate:
    bbox: tuple[int, int, int, int]
    kps: np.ndarray            # 5 landmarks
    det_score: float
    quality: FaceQuality

@dataclass
class FaceQuality:
    size_px: int               # lado menor del bbox
    blur: float                # varianza del laplaciano
    yaw: float; pitch: float; roll: float
    brightness: float
    passed: bool
    reason: str | None         # "too_small" | "blurry" | "extreme_pose" | ...

class FaceQualityAssessor:
    def assess(self, crop: np.ndarray, kps: np.ndarray) -> FaceQuality: ...

class FaceEngine:
    def detect(self, frame: np.ndarray) -> list[FaceCandidate]: ...
    def embed(self, frame: np.ndarray, cand: FaceCandidate) -> np.ndarray:
        """Alineación por landmarks + ArcFace. Devuelve 512D L2-normalizado."""

class IdentityIndex:
    """Matriz (N, 512) normalizada. Similitud = producto escalar."""
    def add(self, person_id: int, emb: np.ndarray) -> None: ...
    def search(self, emb: np.ndarray, top_k: int = 3) -> list[tuple[int, float]]: ...
    def rebuild(self) -> None: ...
```

**Umbrales por defecto** (configurables):

| Parámetro | Default | Efecto |
|-----------|---------|--------|
| `face_min_size_px` | 60 | descarta caras lejanas |
| `face_max_blur` | 100.0 | varianza laplaciano mínima |
| `face_max_yaw_deg` | 40 | descarta perfiles extremos |
| `face_match_threshold` | 0.45 | similitud coseno mínima para candidato |
| `face_confirm_threshold` | 0.55 | similitud para voto fuerte |

### 5.5 Máquina de estados de identidad

```
                  ┌─────────┐
       ┌─────────►│ UNKNOWN │◄──────────────┐
       │          └────┬────┘               │
       │  votos         │ match > threshold  │ timeout
       │  insuficientes │                    │ (lost_ttl)
       │          ┌─────▼─────┐              │
       └──────────┤ CANDIDATE │              │
                  └─────┬─────┘        ┌─────┴───────────┐
        N votos coherentes │            │ TEMPORARILY_LOST│
                    ┌─────▼─────┐      └─────▲───────────┘
                    │ CONFIRMED ├────────────┘ track sin cara visible
                    └─────┬─────┘
                          │ re-aparece con match coherente
                          └──────────► CONFIRMED
```

```python
class TemporalVoter:
    """Ventana deslizante de votos por track."""
    def __init__(self, window: int = 8, min_votes: int = 3,
                 min_ratio: float = 0.6): ...
    def vote(self, track_id: int, person_id: int | None, score: float) -> None: ...
    def verdict(self, track_id: int) -> tuple[int | None, float]:
        """(person_id ganador, confianza agregada) o (None, 0.0)"""

class IdentityStateMachine:
    def on_face_result(self, track_id: int, person_id: int | None, score: float) -> Event | None
    def on_track_lost(self, track_id: int) -> Event | None
    def on_tick(self, now: float) -> list[Event]
    def state_of(self, track_id: int) -> IdentityState
```

**Parámetros:** `min_votes=3`, `window=8`, `lost_ttl=30 s`, `revalidate_after=120 s`.

**Criterio de aceptación clave:** con una secuencia de test de 200 frames de una persona conocida, el sistema emite **un solo** `PERSON_RECOGNIZED` (no uno por frame) y **cero** identidades duplicadas tipo `Juan_2`, `Juan_3`.

### 5.6 `perception/reid/`

```python
class ReIDEngine:
    def embed(self, person_crop: np.ndarray) -> np.ndarray:  # 512D normalizado

class TrackGallery:
    """Mantiene continuidad de identidad cuando la cara no es visible."""
    def update(self, track_id: int, emb: np.ndarray, identity: int | None) -> None
    def resolve(self, track_id: int, emb: np.ndarray) -> tuple[int | None, float]:
        """Si un track nuevo se parece a un track reciente con identidad, la hereda."""
```

**Política:** un track nuevo hereda identidad de un track cerrado hace < 15 s si la similitud ReID > 0.7 **y** no hay conflicto con otro track activo con esa identidad.

### 5.7 `perception/behavior.py`

```python
@dataclass
class TrackState:
    track_id: int
    first_seen: float; last_seen: float
    centroid_history: deque[tuple[float, float, float]]   # (t, x, y)
    zones: set[str]
    zone_entry_times: dict[str, float]
    identity: int | None
    identity_state: IdentityState

class BehaviorAnalyzer:
    def analyze(self, tracks: dict[int, TrackState], now: float) -> list[Event]:
        """Emite LOITERING, RUNNING, IMMOBILE, CROWD_DETECTED, ZONE_ENTERED/EXITED,
        DIRECTION_CHANGED según umbrales configurables."""
```

| Comportamiento | Regla | Default |
|----------------|-------|---------|
| `LOITERING` | tiempo en zona > `loiter_secs` y desplazamiento neto < `loiter_radius_px` | 120 s / 80 px |
| `RUNNING` | velocidad media > `run_speed_px_s` durante > 1 s | 350 px/s |
| `IMMOBILE` | desplazamiento < 20 px durante > 60 s | |
| `CROWD_DETECTED` | tracks activos simultáneos >= `crowd_threshold` | 5 |

**Nota de alcance:** "persona cayendo" (detección de caídas) requiere estimación de pose (YOLO-pose) y se declara **fuera del alcance de v2.0**; queda registrado como backlog v2.1 en la sección 11.

---

## 6. Modelo de eventos

### 6.1 Catálogo (`events/types.py`)

```python
class EventType(str, Enum):
    # Personas
    PERSON_ENTERED       = "PERSON_ENTERED"
    PERSON_EXITED        = "PERSON_EXITED"
    LINE_CROSSED         = "LINE_CROSSED"
    ZONE_ENTERED         = "ZONE_ENTERED"
    ZONE_EXITED          = "ZONE_EXITED"
    # Identidad
    PERSON_RECOGNIZED    = "PERSON_RECOGNIZED"
    UNKNOWN_PERSON       = "UNKNOWN_PERSON"
    IDENTITY_LOST        = "IDENTITY_LOST"
    # Comportamiento
    LOITERING            = "LOITERING"
    RUNNING              = "RUNNING"
    IMMOBILE             = "IMMOBILE"
    CROWD_DETECTED       = "CROWD_DETECTED"
    INTRUSION            = "INTRUSION"
    # Objetos (v2.1, definidos aquí para estabilidad del contrato)
    OBJECT_LEFT          = "OBJECT_LEFT"
    OBJECT_REMOVED       = "OBJECT_REMOVED"
    # Sistema
    CAMERA_OFFLINE       = "CAMERA_OFFLINE"
    CAMERA_RECOVERED     = "CAMERA_RECOVERED"
    RECORDING_STARTED    = "RECORDING_STARTED"
    RECORDING_FINISHED   = "RECORDING_FINISHED"
    UPLOAD_FAILED        = "UPLOAD_FAILED"
    CONFIG_CHANGED       = "CONFIG_CHANGED"
    DEGRADED_MODE        = "DEGRADED_MODE"
```

### 6.2 Estructura del evento

```python
class Event(BaseModel):
    id: str                      # uuid4
    type: EventType
    camera_id: str
    ts: datetime                 # wall clock del frame origen
    severity: Literal["info", "warning", "critical"]
    track_id: int | None = None
    person_id: int | None = None
    person_name: str | None = None
    zone_id: str | None = None
    confidence: float | None = None
    bbox: tuple[int, int, int, int] | None = None
    snapshot_path: str | None = None
    recording_id: int | None = None
    payload: dict[str, Any] = {}    # campos específicos del tipo
```

Este objeto es **el mismo** que viaja por el `EventBus`, se persiste en la tabla `events` y se serializa al WebSocket. Un único contrato, tres consumidores.

### 6.3 Mensaje WebSocket v2

```json
{
  "v": 2,
  "kind": "event",
  "data": { "...Event serializado..." }
}
```

Otros `kind`: `"metrics"` (cada 2 s), `"tracks"` (posiciones para overlay, cada 500 ms), `"system"` (cambios de estado del pipeline).

### 6.4 Rule Engine — esquema de `rules.yaml`

```yaml
version: 1
rules:
  - name: intrusion_nocturna
    enabled: true
    when:
      event: PERSON_ENTERED
      zone: jardin
      time_range: "23:00-06:00"
      days: [0,1,2,3,4,5,6]
    debounce_secs: 60
    actions:
      - type: record
        pre_secs: 10
        post_secs: 15
      - type: telegram
        template: "🔴 Intrusión en {zone_id} a las {ts:%H:%M:%S}"
      - type: webhook
        url_ref: alert_webhook_url

  - name: persona_desconocida
    when:
      event: UNKNOWN_PERSON
      min_confidence: 0.5
    debounce_secs: 120
    actions: [ {type: snapshot}, {type: record}, {type: notify} ]

  - name: permanencia_excesiva
    when:
      event: LOITERING
      duration_gte: 120
    actions: [ {type: notify} ]
```

**Acciones soportadas:** `record`, `snapshot`, `notify`, `telegram`, `webhook`, `log`, `upload_drive`, `set_flag`.

**Semántica:**
- Todas las condiciones de `when` son AND.
- `debounce_secs` es por `(rule, camera_id, person_id|track_id)`.
- Si una acción falla, las demás se ejecutan igualmente; el fallo genera un evento `UPLOAD_FAILED`/log.
- Las reglas se evalúan en orden; no hay short-circuit entre reglas (todas las que matchean se disparan).

---

## 7. Modelo de datos v2

### 7.1 Tablas

```sql
cameras(id TEXT PK, name, rtsp_url_ref, enabled, process_w, process_h,
        created_at, last_seen_at)

persons(id INTEGER PK, name, created_at, updated_at, last_seen_at,
        visit_count, notes, enrolled_from)

face_embeddings(id INTEGER PK, person_id FK, embedding BLOB,   -- float32 512D
                model TEXT, quality REAL, source_image, created_at)

tracks(id INTEGER PK, camera_id FK, track_id INT, started_at, ended_at,
       person_id FK NULL, identity_state TEXT, max_confidence REAL,
       reid_embedding BLOB NULL)

events(id TEXT PK, camera_id FK, type TEXT, ts DATETIME, severity TEXT,
       track_id INT NULL, person_id FK NULL, zone_id FK NULL,
       confidence REAL, bbox TEXT, snapshot_path TEXT,
       recording_id FK NULL, payload JSON)

detection_stats(id INTEGER PK, camera_id FK, minute DATETIME,
                detections INT, unique_tracks INT, avg_confidence REAL,
                max_concurrent INT)        -- agregado, NO fila por detección

recordings(id INTEGER PK, camera_id FK, filename, started_at, ended_at,
           duration_s REAL, size_bytes INT, sha256 TEXT, thumbnail_path TEXT,
           trigger_event_id FK NULL, reason TEXT, person_id FK NULL,
           zone_id FK NULL, upload_state TEXT, upload_attempts INT,
           drive_file_id TEXT, local_expires_at DATETIME)

zones(id TEXT PK, camera_id FK, name, polygon JSON, kind TEXT,
      schedule JSON, enabled)

lines(id TEXT PK, camera_id FK, name, start_x_frac, start_y_frac,
      end_x_frac, end_y_frac, enabled)

rules(id TEXT PK, name, enabled, definition JSON, updated_at)

app_config(key TEXT PK, value JSON, updated_at)   -- config runtime editable

system_metrics(id INTEGER PK, camera_id FK NULL, ts DATETIME, metrics JSON)
```

### 7.2 Índices obligatorios

```sql
CREATE INDEX idx_events_ts        ON events(ts DESC);
CREATE INDEX idx_events_type_ts   ON events(type, ts DESC);
CREATE INDEX idx_events_cam_ts    ON events(camera_id, ts DESC);
CREATE INDEX idx_events_person    ON events(person_id, ts DESC);
CREATE INDEX idx_tracks_cam       ON tracks(camera_id, started_at DESC);
CREATE INDEX idx_recordings_cam   ON recordings(camera_id, started_at DESC);
CREATE INDEX idx_detstats_minute  ON detection_stats(camera_id, minute DESC);
```

### 7.3 Migración desde v1

| v1 | v2 | Estrategia |
|----|----|-----------|
| `crossing_events` | `events` con `type=LINE_CROSSED` | Script de migración: 1 fila → 1 evento, `camera_id='cam1'` |
| `zones` | `zones` + `camera_id` | `ALTER TABLE ADD COLUMN camera_id DEFAULT 'cam1'` |
| `captures` | `events` (`snapshot_path`) + `persons` | Conservar tabla, enlazar por `person_id` |
| `recordings` | `recordings` extendida | `ALTER TABLE` con las columnas nuevas, NULL-ables |
| `data/persons.db` (dlib 128D) | `face_embeddings` (ArcFace 512D) | **Re-enrolamiento**: no hay conversión posible entre espacios de embedding |

Las migraciones viven en `storage/migrations.py`, son **idempotentes**, se ejecutan en `lifespan` y se registran en `app_config['schema_version']`. Antes de cada migración destructiva se copia `events.db` a `data/backups/events-{ts}.db`.

---

## 8. API v2 y frontend

### 8.1 Endpoints nuevos (`/api/v2`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/v2/events` | Filtros: `type[]`, `severity`, `person_id`, `zone_id`, `camera_id`, `from`, `to`, `cursor`, `limit<=200`. Paginación por cursor |
| GET | `/api/v2/events/{id}` | Evento + snapshot + clip asociado |
| GET | `/api/v2/timeline` | Eventos agrupados por bloques para el Event Timeline |
| GET | `/api/v2/analytics/summary` | Hoy vs ayer, % variación, hora pico |
| GET | `/api/v2/analytics/hourly` | Serie por hora, filtrable por rango |
| GET | `/api/v2/analytics/occupancy` | Ocupación por zona |
| GET | `/api/v2/analytics/persons` | Ranking de visitas por persona |
| GET | `/api/v2/analytics/heatmap` | Heatmap (ya existe en v1, se versiona) |
| GET | `/api/v2/metrics` | Snapshot JSON de todas las métricas |
| GET | `/metrics` | Exposición Prometheus |
| GET/PUT | `/api/v2/config` | Configuración runtime editable |
| GET/POST/DELETE | `/api/v2/zones` | CRUD con polígonos |
| GET/POST/DELETE | `/api/v2/lines` | CRUD de líneas de conteo |
| GET/POST/PUT/DELETE | `/api/v2/rules` | CRUD de reglas + validación en dry-run |
| POST | `/api/v2/rules/{id}/test` | Evalúa la regla contra los últimos N eventos |
| GET | `/api/v2/cameras` | Lista de cámaras y su salud |
| GET | `/api/v2/cameras/{id}/health` | FPS, latencia, reconexiones, colas |
| GET | `/api/v2/persons` | Personas + estado + última vez vista |
| POST | `/api/v2/persons/{id}/enroll` | Añadir imagen a una identidad existente |
| POST | `/api/v2/persons/merge` | Fusionar dos identidades duplicadas |
| WS | `/api/v2/ws` | Canal unificado (`event`, `metrics`, `tracks`, `system`) |

### 8.2 Estructura del frontend

```
frontend/
├── index.html                 # shell: layout, nav, contenedores; SIN lógica
├── css/
│   ├── base.css               # variables, reset, tipografía
│   ├── layout.css             # grid del centro de operaciones
│   └── components.css         # tarjetas, badges, timeline, modales
└── js/
    ├── app.js                 # bootstrap, router de vistas, estado global
    ├── api.js                 # fetch tipado contra /api/v2, manejo de errores
    ├── websocket.js           # conexión, reconexión con backoff, dispatch
    ├── store.js               # estado observable minimalista (pub/sub)
    ├── views/
    │   ├── operations.js      # vista principal (vídeo + alertas + personas)
    │   ├── timeline.js        # Event Timeline
    │   ├── analytics.js       # gráficas y rankings
    │   ├── camera.js          # live view + salud + ajustes rápidos
    │   ├── recordings.js      # galería de clips
    │   └── settings.js        # configuración visual (árbol)
    └── components/
        ├── videoCanvas.js     # <img> MJPEG + overlay canvas de detecciones
        ├── zoneEditor.js      # dibujo de polígonos/líneas sobre el vídeo
        ├── ruleEditor.js      # editor de reglas
        ├── eventCard.js       # tarjeta de evento con thumbnail y acciones
        ├── alertCenter.js     # panel de alertas
        └── notifications.js   # toasts / Web Push
```

**Restricción:** ES modules nativos (`<script type="module" src="/static/js/app.js">`). Sin bundler, sin framework, sin build step. Chart.js sigue por CDN con SRI.

### 8.3 Layout de la vista de operaciones

```
┌───────────────────────────────────────────────────────────┐
│ ● SISTEMA ONLINE    Cámara 1 ▾    12:43:32     [⚙] [🔔3]  │
├───────────────────────────────┬───────────────────────────┤
│                               │  ALERTAS ACTIVAS          │
│        VIDEO EN DIRECTO       │  🔴 Persona desconocida   │
│        + overlay de tracks    │  🟡 Intrusión zona jardín │
│        + zonas/líneas         │  🟢 Sistema OK            │
│                               ├───────────────────────────┤
│                               │  PERSONAS AHORA      3    │
│                               │  Juan · Ana · Desconocido │
├───────────────────────────────┴───────────────────────────┤
│ ACTIVIDAD HOY   ████▆▆█████████▆▆                         │
├─────────────────────┬─────────────────┬───────────────────┤
│ ENTRADAS  124       │ SALIDAS  119    │ EVENTOS  7        │
└─────────────────────┴─────────────────┴───────────────────┘
```

**Criterio de diseño verificable:** las tres preguntas — *¿está todo bien?*, *¿qué ocurre ahora?*, *¿ha pasado algo importante?* — deben responderse sin scroll ni clics en una pantalla de 1366×768.

### 8.4 Observabilidad — catálogo de métricas

| Métrica | Tipo | Etiquetas |
|---------|------|-----------|
| `capture_fps` | gauge | camera |
| `capture_reconnects_total` | counter | camera |
| `capture_frame_age_seconds` | gauge | camera |
| `frames_dropped_total` | counter | camera, subscriber |
| `detection_fps` / `tracking_fps` / `face_fps` / `reid_fps` | gauge | camera |
| `inference_latency_seconds` | histogram | stage (yolo/face/reid) |
| `queue_depth` | gauge | queue |
| `active_tracks` | gauge | camera |
| `identities_confirmed` / `identities_unknown` | gauge | camera |
| `events_total` | counter | type, severity, camera |
| `recording_queue_depth` / `upload_queue_depth` | gauge | — |
| `upload_failures_total` | counter | reason |
| `database_size_bytes` / `disk_free_bytes` | gauge | — |
| `e2e_latency_seconds` | histogram | stage_pair |

**Latencia end-to-end**: cada `Frame` lleva `captured_at`. Se instrumentan tres puntos — `captured_at → processed_at`, `processed_at → event_emitted_at`, `event_emitted_at → ws_sent_at` — y su suma es la latencia end-to-end publicada.

**Por qué importa:** un sistema puede reportar `FPS = 25` con 15 s de latencia real. `frames_dropped_total` y `capture_frame_age_seconds` son las métricas que delatan esa situación.
---

## 9. Plan de fases ejecutable

22 fases (17-38) en 4 bloques. Cada fase es autónoma, deja el sistema funcionando y tiene criterios de éxito verificables.

Leyenda de prioridad según el ranking de `mejoras_inmediatas.md`: 🔴 crítica · 🟠 alta · 🟡 media.

---

# FASE A — ROBUSTEZ (fases 17-22)

## Phase 17 — Frame Broker y Capture Worker 🔴

**Goal:** la captura RTSP produce frames a ritmo nativo y nunca espera a ningún consumidor.

**Depends on:** nada (primera fase v2).
**Requisitos:** PIPE-01, PIPE-02, PIPE-03.

**Success criteria (verificables):**
1. `backend/pipeline/broker.py` expone `FrameBroker` con `publish()` que jamás bloquea: test con suscriptor que duerme 1 s por frame demuestra que el productor mantiene su FPS.
2. Con 3 suscriptores de velocidades distintas, el lento acumula `dropped > 0` y los rápidos mantienen `dropped == 0`.
3. `CaptureWorker` contiene **solo** captura, reescalado y publicación: `grep -c "YOLO\|recogn\|zone\|heat" backend/pipeline/capture.py` devuelve 0.
4. El stream MJPEG sigue funcionando exactamente igual que en v1.2 (verificación manual en navegador).
5. `GET /api/v2/cameras/cam1/health` devuelve `fps`, `connected`, `reconnects`, `last_frame_age_s`.

**Ficheros:**
- Crear: `backend/pipeline/__init__.py`, `broker.py`, `capture.py`, `manager.py`
- Modificar: `backend/stream.py` (pasa a ser fachada de compatibilidad), `backend/main.py` (lifespan arranca el pipeline)
- Tests: `tests/test_broker.py`, `tests/test_capture_worker.py`

**Contratos clave:** `Frame`, `FrameBroker`, `Subscription`, `CaptureWorker` (§5.1, §5.2).

**Riesgos:**
- *Regresión del MJPEG al cambiar la fuente de frames.* → El `StreamingWorker` se implementa como suscriptor y se compara visualmente antes/después.
- *Fuga de hilos al parar.* → `stop(timeout)` con `join` y test que verifica `threading.active_count()` estable tras 10 ciclos start/stop.

**Flag:** `PIPELINE_V2=false` por defecto; `true` activa el broker. Se invierte al cerrar la fase.

---

## Phase 18 — Workers desacoplados e inferencia adaptativa 🔴

**Goal:** detección, tracking, streaming y grabación corren como workers independientes con FPS objetivo propios.

**Depends on:** 17.
**Requisitos:** PIPE-04, PIPE-05, PIPE-06, DET-05.

**Success criteria:**
1. Existen y arrancan de forma independiente: `DetectionWorker`, `StreamingWorker`, `RecordingWorker`. Matar uno (simulado con excepción) no detiene los demás; el supervisor lo reinicia y emite `DEGRADED_MODE`.
2. Con `detection_target_fps=8` y cámara a 20 FPS, el vídeo se sirve a ~20 FPS y la detección corre a 8±1 FPS medidos.
3. `AdaptiveRate` reduce el FPS de detección cuando la latencia de inferencia supera el presupuesto: test con detector simulado de 300 ms verifica descenso hasta `min_fps`.
4. El uso de CPU medido en reposo con 1 persona en escena baja respecto a v1.2 (medición documentada antes/después).
5. Ningún worker hace `await`; ninguna corrutina hace inferencia (revisión + test de arquitectura con `ast`).

**Ficheros:**
- Crear: `backend/pipeline/detection.py`, `tracking.py`, `streaming.py`, `recording.py`
- Modificar: `backend/detector.py` (interfaz `infer(frame) -> Detections` pura), `backend/tracker.py` (exponer `TrackState`)
- Tests: `tests/test_adaptive_rate.py`, `tests/test_workers_isolation.py`

**Riesgos:**
- *Tracking degradado al bajar el FPS de detección.* → ByteTrack necesita `frame_rate` coherente; se pasa el FPS **efectivo** de detección, no el de captura. Criterio: la métrica de IDs perdidos por minuto no empeora respecto a v1.2.

---

## Phase 19 — Event Engine, Rule Engine y esquema de datos v2 🔴

**Goal:** el sistema deja de razonar en "detecciones" y pasa a emitir eventos tipados evaluados contra reglas.

**Depends on:** 18.
**Requisitos:** EVT-01..EVT-05, RULE-01..RULE-04, DB-10..DB-14.

**Success criteria:**
1. `EventType` cubre los 22 tipos del catálogo (§6.1) y `Event` valida con Pydantic.
2. El `EventBus` entrega el **mismo** objeto `Event` a persistencia, WebSocket y RuleEngine (test de identidad de payload).
3. `rules.yaml` con las 3 reglas de ejemplo carga, valida y dispara: test de integración inyecta un `PERSON_ENTERED` en zona `jardin` a las 23:30 simuladas y verifica que se llama a `record` + `telegram`.
4. Una regla mal formada produce un error de validación legible al arrancar y **no** tumba el servidor: se desactiva esa regla y se emite un log de nivel ERROR.
5. `debounce_secs` funciona: 10 eventos idénticos en 5 s producen 1 sola acción.
6. Las detecciones ya no se persisten fila a fila: tras 10 min de operación, `SELECT COUNT(*) FROM events` es del orden de decenas y `detection_stats` tiene 1 fila por minuto.
7. La migración desde v1 conserva el histórico: `crossing_events` → `events` con `type=LINE_CROSSED` sin pérdida de filas (test de conteo).

**Ficheros:**
- Crear: `backend/events/{types,engine,bus,rules}.py`, `backend/storage/{models,repositories,migrations}.py`, `config/rules.yaml`
- Modificar: `backend/database.py` (delega en `storage/`), `backend/notifier.py` (pasa a ser una *acción*, no un decisor), `backend/main.py`
- Tests: `tests/test_event_engine.py`, `tests/test_rule_engine.py`, `tests/test_migrations.py`

**Riesgos:**
- *Migración destructiva.* → Backup automático de `events.db` antes de migrar + test que ejecuta la migración dos veces y comprueba idempotencia.
- *`notifier.py` tiene lógica de decisión hoy.* → Se traslada a reglas equivalentes en `rules.yaml`, y se verifica que las alertas actuales siguen disparándose igual.

---

## Phase 20 — Grabación con pre/post-buffer y metadatos 🔴

**Goal:** ningún clip empieza después del evento; cada clip es auditable.

**Depends on:** 19.
**Requisitos:** CLIP-01..CLIP-07.

**Success criteria:**
1. Con `pre_buffer_secs=10`, el clip generado por un evento en T contiene imagen desde T-10 s (verificable con timestamp quemado en el frame durante el test).
2. El post-buffer añade `post_buffer_secs` tras la última detección (default 10 s).
3. Cada fila de `recordings` tiene `sha256`, `duration_s`, `size_bytes`, `thumbnail_path`, `trigger_event_id`, `reason`, `upload_state`.
4. La miniatura existe en disco y se sirve por `/api/v2/recordings/{id}/thumbnail`.
5. El uso de RAM del pre-buffer se mantiene por debajo de 40 MB con la configuración por defecto (medido).
6. Política de retención: local 7 días (configurable) / Drive solo eventos con `severity != info`. Los clips no subidos se marcan `upload_state='skipped'`, no `failed`.
7. Un fallo de Drive no bloquea el pipeline: cola persistente en `recordings.upload_state='pending'` con reintentos y backoff; test simula 3 fallos y verifica el 4º intento correcto.

**Ficheros:**
- Crear: `backend/pipeline/prebuffer.py` (`RingFrameBuffer`)
- Modificar: `backend/pipeline/recording.py`, `backend/recorder.py` (retirada), `backend/gdrive.py` (cola + reintentos)
- Tests: `tests/test_prebuffer.py`, `tests/test_recording_metadata.py`, `tests/test_upload_retry.py`

**Riesgos:**
- *Consumo de RAM.* → JPEG-encoded (ADR-07) + límite duro de frames en el deque + métrica `prebuffer_bytes`.
- *Escritura de clips bloqueando el worker.* → El ensamblado del clip se hace en un hilo dedicado con su propia cola.

---

## Phase 21 — Observabilidad y latencia end-to-end 🟡

**Goal:** el sistema es diagnosticable sin adjuntar un depurador.

**Depends on:** 20.
**Requisitos:** OBS-01..OBS-06.

**Success criteria:**
1. `/metrics` expone todas las métricas del catálogo (§8.4) en formato Prometheus.
2. `/api/v2/metrics` devuelve el mismo snapshot en JSON y el dashboard lo pinta.
3. `frames_dropped_total` se incrementa de forma demostrable al ralentizar artificialmente el detector.
4. `e2e_latency_seconds` se calcula desde `Frame.captured_at` hasta el envío por WebSocket, con los tres tramos desglosados.
5. Un test de humo verifica que una latencia inyectada de 2 s aparece reflejada en el percentil 95 de la métrica.
6. La recolección de métricas añade < 2% de CPU (medido comparando con la fase anterior).

**Ficheros:**
- Crear: `backend/observability/{metrics,latency}.py`
- Modificar: todos los workers (instrumentación), `backend/api/v2/metrics.py`
- Tests: `tests/test_metrics.py`, `tests/test_latency.py`

**Riesgo:** *sobre-instrumentación en el bucle caliente.* → Los histogramas se actualizan una vez por frame procesado, nunca por detección individual.

---

## Phase 22 — Deuda de seguridad y gestión de memoria 🔴

**Goal:** cerrar los puntos de seguridad realmente pendientes y garantizar operación 24/7 sin crecimiento de memoria.

**Depends on:** 21.
**Requisitos:** SEC-15, SEC-16, PIPE-07.

**Success criteria:**
1. `grep -rn "pickle" backend/` no devuelve resultados en código de producción. La migración de blobs legacy se hace con un script explícito `scripts/migrate_embeddings.py` ejecutado una vez, no en el camino de carga.
2. `yolo_model_path` se valida: extensión `.pt`/`.onnx` y ruta resuelta contenida en el directorio del proyecto. Un path fuera del proyecto aborta el arranque con mensaje claro.
3. Todos los endpoints `/api/v2` tienen rate limiting y validación de cotas (`limit <= 200`).
4. Prueba de resistencia de 8 h: RSS del proceso estable dentro de ±10% tras la primera hora; `active_tracks`, cachés de reconocimiento y estados de zona no crecen monótonamente.
5. Todas las estructuras con crecimiento potencial (`TrackRegistry`, `TemporalVoter`, `IdentityStateMachine`, cachés de zona/heatmap) tienen política de expiración con test que la verifica.
6. Las colas acotadas nunca crecen sin límite: `queue_depth` acotado en la prueba de 8 h.

**Ficheros:**
- Crear: `scripts/migrate_embeddings.py`, `tests/test_memory_bounds.py`
- Modificar: `backend/recognizer.py`, `backend/config.py`, `backend/api/v2/*`

**Riesgo:** *la prueba de 8 h es lenta para CI.* → Se ejecuta como job manual/nocturno; en CI corre una versión de 10 min con reloj acelerado.

---

# FASE B — INTELIGENCIA ARTIFICIAL (fases 23-27)

## Phase 23 — Migración a InsightFace/ArcFace con quality gating 🟠

**Goal:** el reconocimiento facial usa embeddings ArcFace 512D y descarta caras que no valen la pena procesar.

**Depends on:** 22.
**Requisitos:** FACE-01..FACE-06.

**Puerta de entrada (bloqueante):** spike de 1 día que verifica `pip install insightface onnxruntime` y una inferencia real en el entorno Windows del proyecto. Si falla, se activa el plan B de ADR-02 antes de continuar.

**Success criteria:**
1. `FaceEngine.detect()` + `.embed()` producen embeddings 512D L2-normalizados con `buffalo_s`.
2. `FaceQualityAssessor` rechaza y **etiqueta el motivo** de: caras < 60 px, borrosas (laplaciano < 100), yaw > 40°. Test con imágenes sintéticas de cada caso.
3. `IdentityIndex` resuelve una búsqueda sobre 1.000 identidades en < 5 ms (benchmark en el test).
4. `scripts/reenroll.py` reconstruye todas las identidades desde `data/gallery/` y reporta cuántas se pudieron migrar y cuántas no (por falta de imagen fuente).
5. Sobre un set de validación de al menos 50 recortes reales del propio proyecto, la tasa de aciertos de ArcFace es igual o mejor que la de dlib, con el mismo conjunto de identidades. **Este número se documenta en el SUMMARY de la fase**, no se asume.
6. `dlib` y `face-recognition` desaparecen de `requirements.txt`.

**Ficheros:**
- Crear: `backend/perception/face/{engine,quality,index}.py`, `scripts/fetch_models.py`, `scripts/reenroll.py`
- Modificar: `backend/recognizer.py` (reducido a orquestación), `requirements.txt`
- Tests: `tests/test_face_engine.py`, `tests/test_face_quality.py`, `tests/test_identity_index.py`

**Riesgos:**
- *Instalación en Windows.* → Puerta de entrada arriba + plan B documentado.
- *Pérdida de identidades enroladas.* → El re-enrolamiento es obligatorio y se ejecuta antes de retirar dlib; se conserva `data/persons.db` renombrada como respaldo.

---

## Phase 24 — Identidad temporal: votación y máquina de estados 🟠

**Goal:** una persona es "Juan" tras evidencia coherente, no tras un frame afortunado; y sigue siendo Juan aunque se pierda el track.

**Depends on:** 23.
**Requisitos:** FACE-07..FACE-11.

**Success criteria:**
1. `IdentityStateMachine` implementa los 4 estados de §5.5 con transiciones testeadas una a una.
2. Con una secuencia de 200 frames de una persona conocida se emite **exactamente un** `PERSON_RECOGNIZED`.
3. Con embeddings ruidosos alternando dos identidades, `TemporalVoter` no confirma ninguna (ratio < `min_ratio`) y el track permanece en `CANDIDATE`.
4. Cero identidades duplicadas: en una secuencia con pérdida y recuperación de track, no se crean `person_id` nuevos para la misma persona. Métrica `identities_created_total` = 0 en ese test.
5. Revalidación: tras `revalidate_after=120 s`, un track `CONFIRMED` vuelve a intentar reconocimiento; si falla 3 veces consecutivas, pasa a `TEMPORARILY_LOST` y emite `IDENTITY_LOST`.
6. El reconocimiento se dispara **por evento** (track nuevo, confianza baja, revalidación vencida), no cada N frames a ciegas: el número de inferencias faciales por minuto con 1 persona estática en escena baja al menos un 70% respecto a la Fase 23.

**Ficheros:**
- Crear: `backend/perception/face/identity.py`
- Modificar: `backend/perception/face/engine.py`, `backend/events/engine.py`
- Tests: `tests/test_temporal_voting.py`, `tests/test_identity_state_machine.py`

**Riesgo:** *latencia de confirmación percibida.* → El evento `PERSON_RECOGNIZED` se emite al confirmar, pero la UI muestra el candidato con estado "verificando…" desde el primer voto.

---

## Phase 25 — Re-identificación de personas (ReID) 🟠

**Goal:** el sistema mantiene la identidad cuando la cara no es visible.

**Depends on:** 24.
**Requisitos:** REID-01..REID-04.

**Success criteria:**
1. `ReIDEngine` produce embeddings 512D con `osnet_x0_25` en ONNX, latencia < 20 ms por crop en CPU (medido).
2. `TrackGallery.resolve()` hereda identidad de un track cerrado hace < 15 s con similitud > 0.7, y **no** la hereda si otro track activo ya tiene esa identidad.
3. Escenario de test: persona identificada se gira de espaldas 10 s y vuelve — mantiene el mismo `person_id` sin emitir `UNKNOWN_PERSON` intermedio.
4. Escenario negativo: dos personas distintas con ropa similar no se fusionan (se documenta el umbral elegido y la tasa de falsos positivos en el set de prueba).
5. ReID corre como máximo 1 vez cada 2 s por track: `reid_fps` acotado en métricas.

**Ficheros:**
- Crear: `backend/perception/reid/{engine,gallery}.py`
- Modificar: `backend/pipeline/tracking.py`, `backend/events/engine.py`
- Tests: `tests/test_reid_engine.py`, `tests/test_track_gallery.py`

**Riesgo:** *fusiones erróneas de identidad son peores que no fusionar.* → Umbral conservador por defecto (0.7) y flag `REID_INHERIT_IDENTITY` que permite ejecutar ReID en modo solo-observación (registra la decisión sin aplicarla) durante el rodaje.

---

## Phase 26 — Análisis de comportamiento 🟡

**Goal:** el sistema responde a "¿qué está ocurriendo?", no solo a "¿hay alguien?".

**Depends on:** 25.
**Requisitos:** BEH-01..BEH-05.

**Success criteria:**
1. `BehaviorAnalyzer` emite `LOITERING`, `RUNNING`, `IMMOBILE`, `CROWD_DETECTED`, `ZONE_ENTERED`, `ZONE_EXITED` con los umbrales de §5.7, todos configurables.
2. Test con trayectorias sintéticas: 6 escenarios (merodeo, carrera, inmovilidad, grupo, entrada y salida de zona) producen exactamente el evento esperado y ninguno más.
3. Cada evento de comportamiento incluye en `payload` las magnitudes que lo justifican (`duration_s`, `speed_px_s`, `net_displacement_px`, `track_count`).
4. `TrackState` mantiene un historial acotado (`maxlen`) — no crece con el tiempo de sesión.
5. Los eventos de comportamiento son utilizables como `when.event` en `rules.yaml` sin cambios en el RuleEngine.

**Ficheros:**
- Crear: `backend/perception/behavior.py`
- Modificar: `backend/pipeline/tracking.py`, `config/rules.yaml`
- Tests: `tests/test_behavior_analyzer.py`

**Fuera de alcance explícito:** detección de caídas (requiere pose) → backlog v2.1.

---

## Phase 27 — Multi-clase y contexto de escena 🟡

**Goal:** capa semántica: además de personas, el sistema entiende objetos y describe el estado de la escena.

**Depends on:** 26.
**Requisitos:** BEH-06..BEH-09.

**Success criteria:**
1. Las clases detectadas son configurables (`yolo_classes`): persona, bicicleta, coche, moto, mochila, maleta. La UI permite activarlas/desactivarlas.
2. `OBJECT_LEFT` se emite cuando un objeto de clase-equipaje permanece inmóvil > `object_left_secs` (default 60 s) sin persona asociada a < `assoc_radius_px`.
3. `OBJECT_REMOVED` se emite cuando un objeto previamente estable desaparece con una persona cerca.
4. `GET /api/v2/analytics/context` devuelve el estado agregado: hora, zona, personas totales, conocidas, desconocidas, nivel de actividad (`low|normal|high` calculado contra la media móvil de 7 días de esa franja horaria).
5. Test: escena sintética con mochila abandonada emite exactamente un `OBJECT_LEFT`; la misma escena con la persona permaneciendo al lado no lo emite.
6. Activar 6 clases en lugar de 1 no incrementa la latencia de inferencia más de un 15% (YOLO detecta todas las clases en la misma pasada; solo cambia el post-proceso).

**Ficheros:**
- Crear: `backend/perception/objects.py`, `backend/api/v2/context.py`
- Modificar: `backend/detector.py`, `backend/perception/behavior.py`
- Tests: `tests/test_object_events.py`, `tests/test_scene_context.py`

**Riesgo:** *falsos `OBJECT_LEFT` con mobiliario fijo.* → Lista de exclusión por zona + requisito de que el objeto haya *aparecido* (no estar presente desde el arranque).

---

# FASE C — PRODUCTO (fases 28-34)

## Phase 28 — Refactor del frontend a módulos ES 🟠

**Goal:** `index.html` deja de contener lógica; el frontend es mantenible.

**Depends on:** 21 (necesita `/api/v2/metrics`); independiente de la Fase B.
**Requisitos:** OPS-01, OPS-02, OPS-03.

**Success criteria:**
1. La estructura de §8.2 existe y `index.html` baja de 1843 a menos de 300 líneas (solo shell + contenedores).
2. `frontend/js/app.js` deja de ser un placeholder de 2 líneas y es el punto de entrada real.
3. Ningún módulo excede 300 líneas; cada uno tiene una responsabilidad declarada en su cabecera.
4. **Paridad funcional total con v1.2**: todas las funciones actuales (vídeo, contadores, histograma, tabla de eventos, filtros, clips, PTZ, zonas, alertas, salud) siguen operativas. Checklist manual firmada en el SUMMARY.
5. FastAPI monta `StaticFiles` para `/static` y el SRI de Chart.js se mantiene.
6. La carga inicial no supera 1 s en LAN (medido en DevTools).

**Ficheros:**
- Crear: `frontend/css/*.css`, `frontend/js/**` (según §8.2)
- Modificar: `frontend/index.html`, `backend/main.py` (mount estático)
- Tests: smoke E2E manual (Playwright llega en la Fase 34)

**Riesgo:** *refactor grande sin red de seguridad de tests.* → Se hace **antes** de añadir vistas nuevas y con checklist explícita de paridad. Es la única fase de la milestone cuyo criterio principal es "no cambiar nada visible".

---

## Phase 29 — Vista de operaciones 🟠

**Goal:** la pantalla principal responde en 3 segundos a las tres preguntas del operador.

**Depends on:** 28.
**Requisitos:** OPS-04, OPS-05, OPS-06.

**Success criteria:**
1. El layout de §8.3 está implementado y es responsive hasta 1366×768 sin scroll.
2. La barra superior refleja el estado real del pipeline (online / degradado / offline) leyendo `/api/v2/cameras`.
3. El panel "Personas ahora" lista las identidades activas con su estado (`CONFIRMED` / `verificando…` / `desconocido`).
4. El overlay sobre el vídeo dibuja bboxes, `track_id`, nombre e identidad, alimentado por el canal `tracks` del WebSocket a 2 Hz — no re-renderiza el `<img>` MJPEG.
5. La reconexión del WebSocket es automática con backoff y la UI lo indica sin recargar la página.
6. Prueba de usuario: un observador no familiarizado identifica correctamente si hay una alerta activa en menos de 3 s.

**Ficheros:** `frontend/js/views/operations.js`, `components/videoCanvas.js`, `alertCenter.js`, `css/layout.css`; `backend/api/v2/ws.py`.

---

## Phase 30 — Event Timeline y centro de alertas 🟠

**Goal:** sustituir la tabla plana por una línea temporal accionable.

**Depends on:** 29.
**Requisitos:** OPS-07..OPS-11.

**Success criteria:**
1. Cada entrada muestra: hora, icono de severidad, descripción legible, zona, miniatura y acciones (`Ver vídeo`, `Ver captura`, `Marcar como persona`, `Descartar`).
2. Filtros combinables por tipo, severidad, persona, zona y rango temporal, resueltos en servidor (`/api/v2/events` con cursor).
3. Scroll infinito con paginación por cursor: 10.000 eventos navegables sin degradación perceptible.
4. Un evento nuevo entrante aparece en el timeline en < 1 s sin recargar.
5. "Marcar como persona" abre el enrolamiento con el crop del evento precargado y, al confirmar, actualiza retroactivamente los eventos de ese track.
6. El centro de alertas agrupa alertas activas, permite silenciar por regla y muestra el motivo (qué regla disparó).

**Ficheros:** `frontend/js/views/timeline.js`, `components/eventCard.js`; `backend/api/v2/{events,timeline}.py`.

**Riesgo:** *coste de miniaturas.* → Se generan en el momento del evento (Fase 20), no bajo demanda; se sirven con cache headers.

---

## Phase 31 — Vista de analítica 🟡

**Goal:** convertir el histórico en información operativa.

**Depends on:** 30.
**Requisitos:** OPS-12..OPS-15.

**Success criteria:**
1. La vista muestra: personas por hora, ocupación por zona (barras), heatmap, ranking de personas por visitas y tendencias (hoy vs ayer con % de variación) y hora más activa.
2. Selector de rango: hoy / 7 días / 30 días / personalizado.
3. Todas las agregaciones se calculan en SQL, no en el navegador: el payload de `/api/v2/analytics/hourly` para 30 días es < 100 KB.
4. Las consultas de analítica sobre 100.000 eventos responden en < 500 ms (benchmark con BD sintética poblada por script).
5. Exportación CSV/JSON del rango visible.

**Ficheros:** `frontend/js/views/analytics.js`; `backend/api/v2/analytics.py`; `scripts/seed_events.py` (datos sintéticos para benchmark).

---

## Phase 32 — Vista de cámara y configuración visual 🟠

**Goal:** operar y configurar el sistema sin tocar `.env`.

**Depends on:** 31.
**Requisitos:** OPS-16..OPS-20, SET-01..SET-04.

**Success criteria:**
1. La vista Cámara muestra live view + FPS, latencia e2e, CPU, RAM, FPS de detector, estado de tracking y estado RTSP, todo desde `/api/v2/metrics`.
2. El árbol de configuración de la propuesta (Cámara / Detección / Tracking / Reconocimiento / Zonas / Reglas / Alertas / Almacenamiento) está implementado.
3. Los cambios se persisten en `app_config` y se aplican **en caliente** cuando el parámetro lo permite; los que requieren reinicio se marcan claramente en la UI.
4. Cada parámetro tiene rango validado en servidor; un valor fuera de rango devuelve 422 con mensaje legible y la UI lo muestra junto al campo.
5. Botón "Restaurar valores por defecto" por sección.
6. Los cambios de configuración quedan auditados: `events` recibe una entrada `CONFIG_CHANGED` con el diff.
7. La precedencia queda documentada y testeada: `app_config` (runtime) > `.env` > default del código.

**Ficheros:** `frontend/js/views/{camera,settings}.js`; `backend/api/v2/config.py`, `backend/storage/repositories.py`.

**Riesgo:** *config runtime y `.env` divergentes.* → Precedencia única y explícita + la UI muestra el origen efectivo de cada valor.

---

## Phase 33 — Editores visuales de zonas, líneas y reglas 🟠

**Goal:** dibujar zonas y componer reglas sin escribir YAML ni fracciones de coordenadas.

**Depends on:** 32.
**Requisitos:** OPS-21..OPS-24, RULE-05.

**Success criteria:**
1. `zoneEditor.js` permite dibujar, mover, editar vértices y borrar polígonos directamente sobre el frame de vídeo, con coordenadas normalizadas (0-1) independientes de la resolución.
2. Igual para líneas de conteo, con indicador visual de dirección entrada/salida.
3. Las zonas soportan tipo (`counting`, `restricted`, `exclusion`) y horario propio.
4. `ruleEditor.js` compone reglas con el esquema de §6.4 mediante formularios; la regla resultante se valida en servidor antes de guardar.
5. `POST /api/v2/rules/{id}/test` evalúa la regla contra los últimos 500 eventos y devuelve cuántos habrían disparado — permite validar antes de activar.
6. Cambiar una zona no requiere reiniciar: el pipeline recarga la configuración de zonas en menos de 1 s.
7. Zonas y líneas dibujadas con la resolución de proceso a 720p siguen siendo correctas si se cambia a 1080p (test de invariancia).

**Ficheros:** `frontend/js/components/{zoneEditor,ruleEditor}.js`; `backend/api/v2/{zones,lines,rules}.py`.

---

## Phase 34 — Tests E2E e integración del pipeline 🟡

**Goal:** una red de seguridad que cubra el camino completo, no solo unidades aisladas.

**Depends on:** 33.
**Requisitos:** TEST-01..TEST-05.

**Success criteria:**
1. Test de integración del pipeline completo con fuente sintética: `FakeRTSP → DetectionWorker (detector mock) → Tracker → EventEngine → RuleEngine → BD → WebSocket`, sin cámara real, ejecutable en CI.
2. Playwright cubre: vídeo visible, cámara offline muestra estado degradado, WebSocket reconecta tras corte, evento nuevo aparece en el timeline, filtros funcionan, clip reproduce, modal abre y cierra, PTZ responde, alerta aparece, editor de zonas guarda.
3. La suite completa (unit + integración + E2E) corre en menos de 5 min.
4. GitHub Actions ejecuta unit + integración en cada push y E2E en cada PR.
5. Cobertura de `backend/events/`, `backend/pipeline/` y `backend/perception/` por encima del 80%.
6. Los endpoints `/api/*` v1 quedan formalmente marcados como deprecados una vez el frontend usa solo v2.

**Ficheros:** `tests/integration/test_pipeline_e2e.py`, `tests/e2e/*.spec.js`, `playwright.config.js`, `.github/workflows/*.yml`.

---

# FASE D — ESCALABILIDAD (fases 35-38)

## Phase 35 — CameraManager y `camera_id` transversal 🟡

**Goal:** el código deja de asumir una única cámara, aunque solo haya una.

**Depends on:** 34.
**Requisitos:** SCALE-01..SCALE-04.

**Success criteria:**
1. `CameraPipeline` encapsula capture + broker + workers de **una** cámara; `CameraManager` gestiona N instancias con arranque/parada independientes.
2. `camera_id` está presente y es NOT NULL en `events`, `tracks`, `detection_stats`, `recordings`, `zones`, `lines`, `system_metrics`.
3. Todos los endpoints v2 aceptan `camera_id` (default: la única cámara si solo hay una).
4. Arrancar dos pipelines contra la misma URL RTSP funciona y produce eventos con `camera_id` distintos (test de integración con fuente sintética duplicada).
5. Parar una cámara no afecta a la otra ni al servidor.
6. Sin cambios visibles para un despliegue de una sola cámara (regresión cero).

**Ficheros:** `backend/pipeline/manager.py`, `backend/storage/migrations.py`, `backend/api/v2/cameras.py`.

---

## Phase 36 — Multi-cámara en runtime y UI 🟡

**Goal:** añadir, configurar y visualizar varias cámaras desde la interfaz.

**Depends on:** 35.
**Requisitos:** SCALE-05..SCALE-08.

**Success criteria:**
1. CRUD de cámaras desde la UI; añadir una cámara la arranca sin reiniciar el servidor.
2. Selector de cámara en la vista de operaciones + vista mosaico con N streams.
3. Cada cámara tiene zonas, líneas y reglas propias; las reglas pueden aplicarse a `camera: "*"`.
4. Presupuesto de recursos: la UI muestra el coste estimado de CPU por cámara y advierte al superar el umbral configurado.
5. La analítica agrega por cámara y en total.
6. Prueba con 2 cámaras simultáneas durante 1 h: sin degradación del FPS por debajo del 80% del valor mono-cámara, o degradación documentada y explicada.

**Ficheros:** `frontend/js/views/{operations,settings}.js`, `components/cameraGrid.js`; `backend/api/v2/cameras.py`.

**Riesgo:** *CPU insuficiente para N cámaras.* → `AdaptiveRate` global con presupuesto compartido: al añadir cámaras, el FPS de detección por cámara se reparte automáticamente.

---

## Phase 37 — Backends opcionales: PostgreSQL y Redis 🟡

**Goal:** permitir escalar el almacenamiento y el bus sin reescribir el código.

**Depends on:** 36.
**Requisitos:** SCALE-09, SCALE-10.

**Success criteria:**
1. El acceso a datos pasa exclusivamente por `storage/repositories.py`: `grep -rn "session\.\|select(" backend/ --exclude-dir=storage` no devuelve nada.
2. Cambiar `DATABASE_URL` a `postgresql+asyncpg://...` funciona sin cambios de código; la suite de tests de repositorio corre contra ambos motores.
3. `EventBus` tiene dos implementaciones intercambiables (`InProcessBus`, `RedisBus`) tras una interfaz común; con Redis desconfigurado el sistema arranca en modo in-process sin error.
4. SQLite sigue siendo el **default** y la ruta soportada de primera clase.
5. Documentado cuándo merece la pena migrar (nº de cámaras, volumen de eventos/día).

**Ficheros:** `backend/storage/repositories.py`, `backend/events/bus.py`, `docs/scaling.md`.

---

## Phase 38 — Worker de inferencia en GPU (opcional) 🟡

**Goal:** aprovechar GPU si existe, sin degradar la ruta CPU.

**Depends on:** 37.
**Requisitos:** SCALE-11, SCALE-12.

**Success criteria:**
1. Detección automática de GPU disponible (CUDA / DirectML) con log claro del dispositivo elegido.
2. YOLO, ArcFace y OSNet usan el proveedor ONNX/torch adecuado según el dispositivo, seleccionable por configuración.
3. Con GPU disponible, el FPS de detección sostenible sube al menos 3× respecto a CPU (medido y documentado).
4. Sin GPU, el comportamiento es **idéntico** al de la Fase 37 (regresión cero).
5. Fallback automático a CPU si la inicialización de GPU falla, emitiendo `DEGRADED_MODE`.
6. Batching opcional de inferencia multi-cámara en GPU, desactivable.

**Ficheros:** `backend/pipeline/detection.py`, `backend/perception/**/engine.py`, `backend/config.py`.

---

## 10. Trazabilidad: 25 puntos → fases

| # | Punto de `mejoras_inmediatas.md` | Fase(s) | Prioridad |
|---|----------------------------------|---------|-----------|
| 1 | Valoración global | — | contexto |
| 2 | Separar el pipeline de vídeo | 17, 18 | 🔴 |
| 3 | Reconocimiento facial InsightFace/ArcFace + calidad + votación temporal + máquina de estados | 23, 24 | 🟠 |
| 4 | Re-Identification (ReID) | 25 | 🟠 |
| 5 | Motor de eventos + reglas | 19 (motor), 33 (editor) | 🔴 |
| 6 | Scene Understanding Layer | 26, 27 | 🟡 |
| 7 | Inferencia adaptativa (FPS por etapa) | 18, 24 | 🟠 |
| 8 | Modelo de persistencia: separar entidades, detections ≠ events | 19 | 🔴 |
| 9 | Grabación robusta: pre/post-buffer, metadatos, retención local+cloud | 20 | 🔴 |
| 10 | Dashboard como centro de operaciones | 29 | 🟠 |
| 11 | Event Timeline | 30 | 🟠 |
| 12 | Pantalla de analítica | 31 | 🟡 |
| 13 | Vista Cámara | 32 | 🟠 |
| 14 | Configuración visual | 32, 33 | 🟠 |
| 15 | Seguridad pendiente (`vulnerabilidades.md`) | 22 | 🔴 |
| 16 | Preparar multi-cámara | 35, 36 | 🟡 |
| 17 | Observabilidad y latencia e2e | 21 | 🟡 |
| 18 | Tests E2E frontend + integración | 34 | 🟡 |
| 19 | Frontend fuera de `index.html` | 28 | 🟠 |
| 20 | Orden de evolución (Fases A-D) | 17-38 | — |
| — | Limpieza de memoria (Fase A, punto 6) | 22 | 🔴 |
| — | Event bus / PostgreSQL / Redis (Fase D) | 37 | 🟡 |
| — | GPU worker (Fase D) | 38 | 🟡 |
| — | Editor de zonas / editor de reglas (Fase C) | 33 | 🟠 |
| — | Centro de alertas (Fase C) | 30 | 🟠 |

**Cobertura: 25/25.** Único elemento explícitamente diferido: detección de caídas (mencionado en el punto 6) → backlog v2.1 por requerir estimación de pose.

---

## 11. Backlog v2.1 (fuera de alcance de este milestone)

- Detección de caídas mediante YOLO-pose.
- Reconocimiento de matrículas (ALPR).
- Búsqueda semántica de eventos en lenguaje natural.
- App móvil / PWA offline.
- Federación multi-sitio.
- Índice vectorial `hnswlib` (solo si N identidades > 20.000).

---

## 12. Riesgos del milestone y mitigaciones

| Riesgo | Impacto | Probabilidad | Mitigación |
|--------|---------|--------------|------------|
| `insightface`/`dlib` no instalan en Windows | Bloquea Fase B completa | Media | Puerta de entrada en Fase 23 + plan B con ONNX puro (ADR-02) |
| Refactor del pipeline introduce regresiones sutiles de vídeo | Alto | Media | Flag `PIPELINE_V2`, verificación visual A/B, fase 17 no añade funcionalidad |
| Pérdida de identidades enroladas al migrar embeddings | Alto | Alta si no se planifica | Re-enrolamiento obligatorio desde `data/gallery/` + respaldo de `persons.db` |
| Refactor del frontend sin tests | Alto | Media | Fase 28 aislada, criterio = paridad funcional, Playwright en Fase 34 |
| CPU insuficiente al sumar ArcFace + ReID + comportamiento | Alto | Media | `AdaptiveRate` con presupuesto global + disparo por evento en lugar de por frame |
| Crecimiento de memoria en operación 24/7 | Alto | Media | Fase 22 con prueba de 8 h y test de cotas en todas las estructuras |
| Migración de esquema corrompe el histórico | Alto | Baja | Backup automático + migraciones idempotentes + test de doble ejecución |
| Alcance excesivo: 22 fases es un milestone largo | Medio | Alta | Cada fase deja el sistema operativo; se puede parar al final de cualquier fase |

---

## 13. Criterios de aceptación del milestone v2.0

El milestone se considera completo cuando **todos** son ciertos:

1. El vídeo en directo mantiene su fluidez con detección, reconocimiento facial, ReID y grabación activos simultáneamente.
2. `frames_dropped_total` y `e2e_latency_seconds` son visibles en el dashboard y la latencia end-to-end mediana en LAN es inferior a 1,5 s.
3. Un evento de intrusión produce un clip que **empieza antes** del evento, con miniatura, checksum y regla de origen registrados.
4. Una persona conocida genera un único `PERSON_RECOGNIZED` por visita, sin identidades duplicadas, y conserva su identidad al girarse de espaldas.
5. Las reglas de alerta se crean y prueban desde la interfaz sin editar ficheros.
6. Las zonas y líneas se dibujan sobre el vídeo desde la interfaz.
7. El operador identifica el estado del sistema y la última alerta en menos de 3 segundos en la vista de operaciones.
8. `grep -rn "pickle" backend/` no devuelve nada; `yolo_model_path` está validado.
9. Una prueba de 8 horas termina con RSS estable y sin colas desbordadas.
10. La suite completa (unit + integración + E2E) pasa en CI en menos de 5 minutos.
11. Añadir una segunda cámara no requiere cambios de código ni reinicio del servidor.
12. `index.html` tiene menos de 300 líneas y ningún módulo JS supera las 300.
