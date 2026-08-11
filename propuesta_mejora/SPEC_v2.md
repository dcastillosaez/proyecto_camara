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
| `propuesta_mejora/SPEC_v2.md` (este) | **Referencia técnica**: arquitectura objetivo, decisiones técnicas, contratos de módulo, modelo de datos, catálogo de eventos; en §9, ficheros y riesgos por fase |
| `.planning/ROADMAP.md` § v2.0 | **Plan**: fases GSD 17-38 con goal, dependencias, requisitos y criterios de éxito |
| `.planning/STATE.md` | **Estado**: qué fase está completa, cuál falta y qué checkpoints quedan pendientes |
| `.planning/REQUIREMENTS.md` § v2 | **Trazabilidad**: requisitos con ID estable referenciados por cada fase |

Cada fase de la sección 9, combinada con su entrada en `ROADMAP.md` § Phase Details v2.0, es directamente convertible en `.planning/phases/NN-nombre/NN-01-PLAN.md` sin diseño adicional.

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

Goal, dependencias, requisitos y criterios de éxito de cada fase: ver
`.planning/ROADMAP.md` § Phase Details v2.0. Aquí solo lo que ese
documento no cubre — ficheros afectados y riesgos con su mitigación.

## Phase 17 — Frame Broker y Capture Worker 🔴

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

**Ficheros:**
- Crear: `backend/pipeline/detection.py`, `tracking.py`, `streaming.py`, `recording.py`
- Modificar: `backend/detector.py` (interfaz `infer(frame) -> Detections` pura), `backend/tracker.py` (exponer `TrackState`)
- Tests: `tests/test_adaptive_rate.py`, `tests/test_workers_isolation.py`

**Riesgos:**
- *Tracking degradado al bajar el FPS de detección.* → ByteTrack necesita `frame_rate` coherente; se pasa el FPS **efectivo** de detección, no el de captura. Criterio: la métrica de IDs perdidos por minuto no empeora respecto a v1.2.

---

## Phase 19 — Event Engine, Rule Engine y esquema de datos v2 🔴

**Ficheros:**
- Crear: `backend/events/{types,engine,bus,rules}.py`, `backend/storage/{models,repositories,migrations}.py`, `config/rules.yaml`
- Modificar: `backend/database.py` (delega en `storage/`), `backend/notifier.py` (pasa a ser una *acción*, no un decisor), `backend/main.py`
- Tests: `tests/test_event_engine.py`, `tests/test_rule_engine.py`, `tests/test_migrations.py`

**Riesgos:**
- *Migración destructiva.* → Backup automático de `events.db` antes de migrar + test que ejecuta la migración dos veces y comprueba idempotencia.
- *`notifier.py` tiene lógica de decisión hoy.* → Se traslada a reglas equivalentes en `rules.yaml`, y se verifica que las alertas actuales siguen disparándose igual.

---

## Phase 20 — Grabación con pre/post-buffer y metadatos 🔴

**Ficheros:**
- Crear: `backend/pipeline/prebuffer.py` (`RingFrameBuffer`)
- Modificar: `backend/pipeline/recording.py`, `backend/recorder.py` (retirada), `backend/gdrive.py` (cola + reintentos)
- Tests: `tests/test_prebuffer.py`, `tests/test_recording_metadata.py`, `tests/test_upload_retry.py`

**Riesgos:**
- *Consumo de RAM.* → JPEG-encoded (ADR-07) + límite duro de frames en el deque + métrica `prebuffer_bytes`.
- *Escritura de clips bloqueando el worker.* → El ensamblado del clip se hace en un hilo dedicado con su propia cola.

---

## Phase 21 — Observabilidad y latencia end-to-end 🟡

**Ficheros:**
- Crear: `backend/observability/{metrics,latency}.py`
- Modificar: todos los workers (instrumentación), `backend/api/v2/metrics.py`
- Tests: `tests/test_metrics.py`, `tests/test_latency.py`

**Riesgo:** *sobre-instrumentación en el bucle caliente.* → Los histogramas se actualizan una vez por frame procesado, nunca por detección individual.

---

## Phase 22 — Deuda de seguridad y gestión de memoria 🔴

**Ficheros:**
- Crear: `scripts/migrate_embeddings.py`, `tests/test_memory_bounds.py`
- Modificar: `backend/recognizer.py`, `backend/config.py`, `backend/api/v2/*`

**Riesgo:** *la prueba de 8 h es lenta para CI.* → Se ejecuta como job manual/nocturno; en CI corre una versión de 10 min con reloj acelerado.

---

# FASE B — INTELIGENCIA ARTIFICIAL (fases 23-27)

## Phase 23 — Migración a InsightFace/ArcFace con quality gating 🟠

**Puerta de entrada (bloqueante):** spike de 1 día que verifica `pip install insightface onnxruntime` y una inferencia real en el entorno Windows del proyecto. Si falla, se activa el plan B de ADR-02 antes de continuar. *(Superada — ver 23-CONTEXT.md.)*

**Ficheros:**
- Crear: `backend/perception/face/{engine,quality,index}.py`, `scripts/fetch_models.py`, `scripts/reenroll.py`
- Modificar: `backend/recognizer.py` (reducido a orquestación), `requirements.txt`
- Tests: `tests/test_face_engine.py`, `tests/test_face_quality.py`, `tests/test_identity_index.py`

**Riesgos:**
- *Instalación en Windows.* → Puerta de entrada arriba + plan B documentado.
- *Pérdida de identidades enroladas.* → El re-enrolamiento es obligatorio y se ejecuta antes de retirar dlib; se conserva `data/persons.db` renombrada como respaldo.

---

## Phase 24 — Identidad temporal: votación y máquina de estados 🟠

**Ficheros:**
- Crear: `backend/perception/face/identity.py`
- Modificar: `backend/perception/face/engine.py`, `backend/events/engine.py`
- Tests: `tests/test_temporal_voting.py`, `tests/test_identity_state_machine.py`

**Riesgo:** *latencia de confirmación percibida.* → El evento `PERSON_RECOGNIZED` se emite al confirmar, pero la UI muestra el candidato con estado "verificando…" desde el primer voto.

---

## Phase 25 — Re-identificación de personas (ReID) 🟠

**Ficheros:**
- Crear: `backend/perception/reid/{engine,gallery}.py`
- Modificar: `backend/pipeline/tracking.py`, `backend/events/engine.py`
- Tests: `tests/test_reid_engine.py`, `tests/test_track_gallery.py`

**Riesgo:** *fusiones erróneas de identidad son peores que no fusionar.* → Umbral conservador por defecto (0.7) y flag `REID_INHERIT_IDENTITY` que permite ejecutar ReID en modo solo-observación (registra la decisión sin aplicarla) durante el rodaje.

---

## Phase 26 — Análisis de comportamiento 🟡

**Ficheros:**
- Crear: `backend/perception/behavior.py`
- Modificar: `backend/pipeline/tracking.py`, `config/rules.yaml`
- Tests: `tests/test_behavior_analyzer.py`

**Fuera de alcance explícito:** detección de caídas (requiere pose) → backlog v2.1.

---

## Phase 27 — Multi-clase y contexto de escena 🟡

**Ficheros:**
- Crear: `backend/perception/objects.py`, `backend/api/v2/context.py`
- Modificar: `backend/detector.py`, `backend/perception/behavior.py`
- Tests: `tests/test_object_events.py`, `tests/test_scene_context.py`

**Riesgo:** *falsos `OBJECT_LEFT` con mobiliario fijo.* → Lista de exclusión por zona + requisito de que el objeto haya *aparecido* (no estar presente desde el arranque).

---

# FASE C — PRODUCTO (fases 28-34)

## Phase 28 — Refactor del frontend a módulos ES 🟠

**Ficheros:**
- Crear: `frontend/css/*.css`, `frontend/js/**` (según §8.2)
- Modificar: `frontend/index.html`, `backend/main.py` (mount estático)
- Tests: smoke E2E manual (Playwright llega en la Fase 34)

**Riesgo:** *refactor grande sin red de seguridad de tests.* → Se hace **antes** de añadir vistas nuevas y con checklist explícita de paridad. Es la única fase de la milestone cuyo criterio principal es "no cambiar nada visible".

---

## Phase 29 — Vista de operaciones 🟠

**Ficheros:** `frontend/js/views/operations.js`, `components/videoCanvas.js`, `alertCenter.js`, `css/layout.css`; `backend/api/v2/ws.py`.

---

## Phase 30 — Event Timeline y centro de alertas 🟠

**Ficheros:** `frontend/js/views/timeline.js`, `components/eventCard.js`; `backend/api/v2/{events,timeline}.py`.

**Riesgo:** *coste de miniaturas.* → Se generan en el momento del evento (Fase 20), no bajo demanda; se sirven con cache headers.

---

## Phase 31 — Vista de analítica 🟡

**Ficheros:** `frontend/js/views/analytics.js`; `backend/api/v2/analytics.py`; `scripts/seed_events.py` (datos sintéticos para benchmark).

---

## Phase 32 — Vista de cámara y configuración visual 🟠

**Ficheros:** `frontend/js/views/{camera,settings}.js`; `backend/api/v2/config.py`, `backend/storage/repositories.py`.

**Riesgo:** *config runtime y `.env` divergentes.* → Precedencia única y explícita + la UI muestra el origen efectivo de cada valor.

---

## Phase 33 — Editores visuales de zonas, líneas y reglas 🟠

**Ficheros:** `frontend/js/components/{zoneEditor,ruleEditor}.js`; `backend/api/v2/{zones,lines,rules}.py`.

---

## Phase 34 — Tests E2E e integración del pipeline 🟡

**Ficheros:** `tests/integration/test_pipeline_e2e.py`, `tests/e2e/*.spec.js`, `playwright.config.js`, `.github/workflows/*.yml`.

---

# FASE D — ESCALABILIDAD (fases 35-38)

## Phase 35 — CameraManager y `camera_id` transversal 🟡

**Ficheros:** `backend/pipeline/manager.py`, `backend/storage/migrations.py`, `backend/api/v2/cameras.py`.

---

## Phase 36 — Multi-cámara en runtime y UI 🟡

**Ficheros:** `frontend/js/views/{operations,settings}.js`, `components/cameraGrid.js`; `backend/api/v2/cameras.py`.

**Riesgo:** *CPU insuficiente para N cámaras.* → `AdaptiveRate` global con presupuesto compartido: al añadir cámaras, el FPS de detección por cámara se reparte automáticamente.

---

## Phase 37 — Backends opcionales: PostgreSQL y Redis 🟡

**Ficheros:** `backend/storage/repositories.py`, `backend/events/bus.py`, `docs/scaling.md`.

---

## Phase 38 — Worker de inferencia en GPU (opcional) 🟡

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
