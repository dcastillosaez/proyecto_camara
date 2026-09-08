# Phase 38: Worker de inferencia en GPU (opcional) - Pattern Map

**Mapped:** 2026-09-08
**Files analyzed:** 6 (1 nuevo, 5 modificados)
**Analogs found:** 6 / 6

**Nota de precisión sobre 38-CONTEXT.md:** el fichero cita `backend/detector.py —
DetectorYOLO`. La clase real en `backend/detector.py` se llama `PersonDetector`
(no existe `DetectorYOLO` en el repo — verificado con grep). El planner debe usar
`PersonDetector`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/inference/device.py` (nuevo, ubicación a discreción) | utility / config-derived selector | request-response (llamada síncrona, una vez por proceso) | `backend/events/bus.py:247-255` (`create_event_bus`) + `backend/config.py:420-423` (`get_settings`) | role-match (factoría de decisión única + cache de proceso) |
| `backend/config.py` (campo nuevo `inference_device`) | config | CRUD (validación de settings) | `backend/config.py:42-54` (`validate_yolo_model_path`) | exact (mismo estilo `@field_validator`) |
| `backend/detector.py` (`PersonDetector.__init__`) | service/wrapper de inferencia | request-response | `backend/perception/reid/engine.py:36-50` (`ReIDEngine.__init__`, try/except degradando) | role-match (constructor que decide backend de ejecución) |
| `backend/perception/face/engine.py:59-73` (`FaceEngine.__init__`) | service/wrapper de inferencia | request-response | (self-analog, ya usa `providers=` hardcoded — es el punto exacto a tocar) | exact |
| `backend/perception/reid/engine.py:36-50` (`ReIDEngine.__init__`) | service/wrapper de inferencia | request-response | (self-analog, ya usa `providers=` hardcoded — es el punto exacto a tocar) | exact |
| `backend/pipeline/factory.py` (cableado del device a los 3 motores) | factory/wiring | CRUD (construcción) | `backend/pipeline/factory.py:73-79` (`PersonDetector(...)` ya construido aquí a partir de `settings`) | exact |
| `backend/events/engine.py` (uso de `degraded_mode`) | event-driven | event-driven | `backend/pipeline/factory.py:104-106` (`_on_recording_failure` → `event_engine.degraded_mode(...)`) | exact |
| `backend/api/v2/cameras.py` (`camera_health`, campo nuevo) | route/controller | request-response | `backend/api/v2/cameras.py:137-154` (`camera_health`) | exact |
| `tests/test_device_selection.py` (nuevo) | test | request-response | `tests/test_reid_engine.py:73-97` + `tests/test_face_engine.py:64-74` (dobles con `monkeypatch`) | exact |
| `tests/integration/test_gpu_inference.py` (nuevo, opcional) | test | event-driven (skip condicional) | `tests/integration/test_redis_bus.py:1-28` (`TEST_REDIS_URL` + `pytestmark = pytest.mark.skipif`) | exact |
| arnés de benchmark FPS GPU vs CPU | test/perf | batch (medición repetida) | `tests/test_detector.py:222-269` (`real_detector`/`bench_frame` + `@pytest.mark.perf`) | exact |

## Pattern Assignments

### 1. Selector de dispositivo (pieza nueva)

**Analogía estructural — punto único de decisión por configuración:**
`backend/events/bus.py:247-255`
```python
def create_event_bus(
    settings, loop: asyncio.AbstractEventLoop | None = None
) -> EventBusBase:
    """Fabrica del bus segun configuracion (Fase 37, SCALE-10): `redis_url` vacio
    (default) mantiene el comportamiento in-process de siempre; con valor, usa
    RedisBus. Unico punto de decision -- main.py no necesita saber cual es cual."""
    if settings.redis_url:
        return RedisBus(settings.redis_url, loop=loop)
    return InProcessBus(loop=loop)
```
Copiar: la forma — una función pura `settings -> valor decidido`, sin estado oculto,
con docstring que documenta "único punto de decisión" para que el resto del código
no vuelva a ramificar por configuración. Aplicado a la Fase 38: una función que reciba
`settings.inference_device` (`"auto"/"cpu"/"cuda"`) + el resultado de la sonda barata
y devuelva el dispositivo efectivo (y, para los motores ONNX, la lista de providers
ordenada).

**Análogo del "sondeo barato, cacheado, que no lanza":**
`backend/config.py:420-423`
```python
@lru_cache
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
```
Copiar: el idioma `@lru_cache` sobre una función de cero argumentos para que el
sondeo (p. ej. `torch.cuda.is_available()` u `onnxruntime.get_available_providers()`)
se ejecute una sola vez por proceso, tal como pide 38-CONTEXT.md ("el patrón
`@lru_cache` de config.py ya es el idioma del proyecto"). NO copiar `get_settings`
en sí — es un singleton de `Settings`, no del selector; el selector es una función
propia, también decorada con `@lru_cache`.

**Análogo de "sondeo que nunca lanza, degrada a False/CPU":**
`backend/perception/face/engine.py:59-73` y `backend/perception/reid/engine.py:36-50`
(ver más abajo) — el patrón `try/except Exception: logger.exception(...); return`
dejando `available=False` es el molde para que la sonda de CUDA nunca aborte el
arranque si falta el driver o el paquete.

**Qué NO copiar:** `RedisBus` falla ruidosamente si Redis no está disponible (no hay
fallback automático a `InProcessBus` en runtime, solo en la fábrica según config) —
ese es el comportamiento correcto para `inference_device="cuda"` forzado ("falla
ruidosamente para diagnóstico", CONTEXT.md), pero NO para `"auto"`, donde el fallback
a CPU debe ser automático y silencioso salvo por el log.

---

### 2. Ajuste de configuración nuevo (`auto`/`cpu`/`cuda`)

**Analogía exacta de validador — mismo estilo, mismo sitio:**
`backend/config.py:40-54`
```python
yolo_model_path: str = "yolo26n.pt"

@field_validator("yolo_model_path")
@classmethod
def validate_yolo_model_path(cls, v: str) -> str:
    p = Path(v)
    if p.suffix.lower() not in _MODEL_PATH_ALLOWED_SUFFIXES:
        raise ValueError(
            f"yolo_model_path extension {p.suffix!r} not allowed. "
            f"Allowed: {sorted(_MODEL_PATH_ALLOWED_SUFFIXES)}"
        )
    resolved = p.resolve() if p.is_absolute() else (_PROJECT_ROOT / p).resolve()
    if not resolved.is_relative_to(_PROJECT_ROOT):
        raise ValueError(f"yolo_model_path must be inside the project directory: {resolved}")
    return v
```
Copiar: `@field_validator("inference_device") @classmethod` + `raise ValueError(...)`
con el conjunto de valores permitidos citado en el mensaje de error, exactamente
como aquí se cita `sorted(_MODEL_PATH_ALLOWED_SUFFIXES)`. Definir una constante
module-level tipo `_INFERENCE_DEVICE_ALLOWED = {"auto", "cpu", "cuda"}` junto a
`_MODEL_PATH_ALLOWED_SUFFIXES` (línea 9).

**Qué NO copiar:** no hay precedente de `Literal["auto", "cpu", "cuda"]` en
`Settings` — el único uso de `typing.Literal` en el repo es
`backend/ptz.py:5,67` (`direction: Literal["up", "down", "left", "right"]`), que es
un modelo Pydantic de **request body** (`PTZCommand`), no de `Settings`. Los campos
de tipo enumerado existentes en `Settings` (`camera_driver: str = "tapo"`,
`upload_min_severity: str = "warning"`) son `str` libres, documentados por
comentario, sin `@field_validator` que verifique el conjunto — es decir, **no hay
un enum validado en `Settings` hoy**; el molde de validación viene de
`yolo_model_path`/`reid_model_path` (validan contenido, no pertenencia a un set),
así que el planner puede usar `Literal["auto", "cpu", "cuda"]` como tipo de campo
(pydantic ya valida la pertenencia automáticamente sin `@field_validator` manual)
o replicar el patrón manual — cualquiera de las dos es coherente con el proyecto,
pero `Literal` en el campo es más simple y aprovecha pydantic-settings sin código
adicional.

---

### 3. Cableado del dispositivo a los tres motores

**Cómo reciben hoy su configuración — verificado línea a línea:**

a) `PersonDetector` (`backend/detector.py:23-35`) recibe todo por **parámetros del
constructor**, nunca lee `Settings` directamente:
```python
def __init__(
    self,
    model_path: str = "yolov8n.pt",
    confidence: float = 0.45,
    classes: list[int] | None = None,
    label: str = "person",
    imgsz: int = 640,
) -> None:
    self._model = YOLO(model_path)
```
Quien traduce `Settings` a estos parámetros es `backend/pipeline/factory.py:73-79`:
```python
detector = PersonDetector(
    model_path=settings.yolo_model_path,
    confidence=settings.yolo_confidence,
    classes=services.active_classes,
    label=settings.detection_label,
    imgsz=settings.yolo_imgsz,
)
```
Copiar exactamente este patrón: añadir un parámetro `device: str | None = None` (o
el tipo que decida el selector) a `PersonDetector.__init__`, pasado a `YOLO(model_path)`
o a la llamada de inferencia — CONTEXT.md ya advierte elegir uno de los dos sitios de
Ultralytics y ser coherente con `set_classes` (`detector.py:60-65`, que asume que el
modelo no se recarga). En `factory.py` añadir `device=resolve_device(settings)` (o el
nombre que tenga la función del selector) junto a las demás líneas `settings.xxx`.

b) `FaceEngine` (`backend/perception/face/engine.py:59-70`) construye el proveedor
**hardcodeado dentro del propio motor**, no recibe `device`/`providers` como parámetro:
```python
def __init__(self, model_name: str = "buffalo_s", det_size: tuple[int, int] = (320, 320)) -> None:
    ...
    self._app = FaceAnalysis(
        name=model_name, providers=["CPUExecutionProvider"],
        allowed_modules=self._ALLOWED_MODULES,
    )
    self._app.prepare(ctx_id=-1, det_size=det_size)
```
Y se construye sin argumentos en `backend/recognizer.py:98`: `self._engine = FaceEngine()`.
`PersonRecognizer` (que envuelve `FaceEngine`) se construye en `backend/main.py:531-538`
con parámetros de `settings.face_*`, pero **hoy no le pasa nada relacionado con
providers**. El cableado más limpio y menos invasivo: añadir `providers: list[str] | None
= None` al constructor de `FaceEngine` (con default `["CPUExecutionProvider"]` para no
tocar la ruta CPU) y propagarlo por `PersonRecognizer.__init__` → `FaceEngine(providers=...)`,
y desde `main.py:531` pasar el resultado del selector.

c) `ReIDEngine` (`backend/perception/reid/engine.py:36,48-50`) recibe `model_path` e
`intra_op_threads` por constructor, y también tiene `providers=["CPUExecutionProvider"]`
**hardcodeado**:
```python
def __init__(self, model_path: str, intra_op_threads: int = 1) -> None:
    ...
    self._sess = ort.InferenceSession(
        model_path, sess_options=so, providers=["CPUExecutionProvider"]
    )
```
Se construye en `backend/pipeline/manager.py:226`: `self.reid_engine = ReIDEngine(reid_model_path)`,
dentro de `CameraPipeline.__init__` a partir de un parámetro `reid_model_path` que a su
vez viene de `factory.py:147` (`reid_model_path=settings.reid_model_path`). Mismo patrón
a replicar: añadir `providers: list[str] | None = None` al constructor de `ReIDEngine`,
propagarlo como parámetro nuevo de `CameraPipeline.__init__` (junto a `reid_model_path`)
y desde `factory.py` pasar `providers=resolve_onnx_providers(settings)`.

**Regla de orden de providers (ya la fija CONTEXT.md, no inventar otra):** "el orden de
la lista es el que decide el fallback en `onnxruntime` (proveedor preferido primero,
`CPUExecutionProvider` siempre al final)" — así que la función del selector para los
motores ONNX debe devolver algo como `["CUDAExecutionProvider", "CPUExecutionProvider"]`
o `["CPUExecutionProvider"]`, nunca solo el proveedor elegido.

**Qué NO copiar:** ninguno de los tres motores lee `Settings`/`get_settings()`
directamente — los tres reciben todo por parámetros explícitos del constructor,
resueltos en `factory.py`/`main.py`. Mantener esa disciplina: el selector se llama
en `factory.py`/`main.py` (o en el módulo del selector, cacheado), nunca dentro de
`FaceEngine`/`ReIDEngine`/`PersonDetector`.

---

### 4. Degradación con `DEGRADED_MODE`

**Firma exacta y quién la emite hoy:**
`backend/events/engine.py:183-184` (`EventEngine.degraded_mode`):
```python
def degraded_mode(self, now: datetime.datetime, reason: str) -> None:
    self._publish(EventType.DEGRADED_MODE, ts=now, severity=Severity.WARNING, payload={"reason": reason})
```
`EventType.DEGRADED_MODE` está en `backend/events/types.py:46` y su severidad
(`Severity.WARNING`) en `backend/events/types.py:53`.

**Análogo exacto de "fallo de init de componente opcional → sigue degradado":**
`backend/pipeline/factory.py:104-106`:
```python
def _on_recording_failure(message: str) -> None:
    logger.error("RecordingWorker failure (%s): %s", camera_id, message)
    event_engine.degraded_mode(datetime.datetime.now(), reason=message)
```
Copiar: la firma `logger.error(...)` seguido de `event_engine.degraded_mode(datetime.datetime.now(),
reason=<motivo real>)` — nunca un `except: pass`, tal como exige CONTEXT.md
("deja traza del motivo real"). Para la Fase 38, el punto de emisión natural es donde
se resuelve el fallback GPU→CPU (en el selector o en el wiring de `factory.py`/`main.py`,
tras capturar la excepción real de inicialización en GPU), con `reason` describiendo
qué motor y por qué falló (p. ej. `"CUDA init failed for YOLO: <exc>"`).

**Segundo análogo de degradación silenciosa sin evento (motores ONNX/insightface):**
`backend/perception/reid/engine.py:64-66` y `backend/perception/face/engine.py:72-73`
usan `logger.exception(...)` + `self._available = False` pero **no** emiten
`DEGRADED_MODE` — degradan localmente y el llamador (`PersonRecognizer._available`,
`CameraPipeline.reid_enabled`) decide qué hacer. Distinguir: la degradación GPU→CPU
de la Fase 38 sí debe emitir `DEGRADED_MODE` (lo pide CONTEXT.md explícitamente),
a diferencia de "modelo ausente" que ya es un modo soportado sin evento. No mezclar
ambos caminos — el fallback de dispositivo es un evento observable de arranque, no
una ausencia silenciosa de funcionalidad.

**Qué NO copiar:** `EventEngine.camera_offline`/`camera_recovered` (`events/engine.py:171-181`)
usan flags de instancia (`self._camera_offline`) para no republicar el mismo evento en
cada frame — no aplica aquí porque el fallback de dispositivo ocurre una sola vez en
el arranque del proceso (ya cacheado por `@lru_cache` en el selector), así que no hace
falta deduplicar.

---

### 5. Exposición en `/api/v2/cameras/{id}/health`

**Cómo se añade hoy un campo nuevo — patrón exacto:**
`backend/api/v2/cameras.py:137-154`:
```python
@router.get("/{camera_id}/health")
@limiter.limit(V2_RATE_LIMIT)
async def camera_health(request: Request, camera_id: str):
    """CaptureWorker health for one camera, plus FrameBroker subscriber stats."""
    if _camera_manager is None:
        raise HTTPException(status_code=503, detail="Pipeline v2 no activo")
    pipeline = _camera_manager.get(camera_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {
        **asdict(pipeline.health),
        "capture_fps": pipeline.get_fps(),
        "detection_fps": pipeline.get_detection_fps(),
        "broker_stats": pipeline.broker.stats(),
        **pipeline.stats(),
    }
```
Y `pipeline.stats()` en `backend/pipeline/manager.py:424-436`:
```python
def stats(self) -> dict:
    out: dict[str, Any] = {
        "workers": self.worker_status(),
        "degraded": self.degraded,
        "broker": self.broker.stats(),
    }
    if self.detection:
        out["detection"] = self.detection.stats
    ...
    return out
```
Y `DetectionWorker.stats` (`backend/pipeline/detection.py:130-136`):
```python
@property
def stats(self) -> dict:
    return {
        "frames_processed": self._frames_processed,
        "exceptions": self._exceptions,
        **self._rate.stats,
    }
```
Copiar: el dispositivo efectivo NO se calcula en el endpoint — se calcula una vez
(vía el selector cacheado) y se expone como un campo más del `dict` que ya devuelve
`DetectionWorker.stats` (p. ej. `"device": self._detector_device` o similar, guardado
en `__init__` del worker o leído directamente del detector). El endpoint ya lo
recogería solo con `**pipeline.stats()` sin tocar `cameras.py`, siguiendo exactamente
el mismo camino por el que hoy `frames_processed`/`exceptions` llegan al JSON de
`/health`.

**Qué NO copiar:** no crear una ruta nueva (`/api/v2/cameras/{id}/device` o similar)
— CONTEXT.md pide exponerlo "en la línea de lo que ya expone" el health existente,
no un endpoint nuevo.

---

### 6. Tests con dobles para capacidad ausente

**Convención de nombres verificada:** `pytest.ini:2` — `python_functions = TEST_*`
(mayúsculas, no `test_*`). Todo test nuevo debe seguir `TEST_*`, salvo
`tests/test_architecture.py` que usa `test_*` porque son invariantes de arquitectura,
no comportamiento (y así queda fuera de la colección `TEST_*`... realmente pytest
colecciona ambos si `python_functions` no excluye `test_*`; en la práctica el repo
mezcla ambos estilos por convención, no por configuración — usar `TEST_*` para
tests de comportamiento nuevos, como hace el resto de `tests/*.py`).

**Análogo exacto — "modelo/paquete ausente degrada sin lanzar", con `monkeypatch`:**
`tests/test_reid_engine.py:73-97`:
```python
def TEST_reid_engine_degrades_gracefully():
    """Sin modelo, available=False y embed() devuelve None, nunca lanza."""
    broken = ReIDEngine("no/such/path.onnx")
    assert broken.available is False
    assert broken.embed(np.zeros((10, 10, 3), dtype=np.uint8)) is None
    assert broken.embed(None) is None


def TEST_reid_engine_rejects_fixed_batch(monkeypatch):
    import backend.perception.reid.engine as engine_module

    class _FakeIO:
        def __init__(self, name, shape):
            self.name = name
            self.shape = shape

    class _FakeSession:
        def __init__(self, *a, **kw): ...
        def get_inputs(self):  return [_FakeIO("input", [16, 3, 256, 128])]
        def get_outputs(self): return [_FakeIO("output", [16, 512])]

    monkeypatch.setattr(engine_module.ort, "InferenceSession", _FakeSession)
    assert ReIDEngine("cualquier.onnx").available is False
```
`tests/test_face_engine.py:64-74`:
```python
def TEST_engine_unavailable_degrades_gracefully(monkeypatch):
    """If the underlying model fails to load, detect()/embed() return empty/None, never raise."""
    import backend.perception.face.engine as engine_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated model load failure")

    monkeypatch.setattr(engine_module, "FaceAnalysis", _boom)
    broken = FaceEngine()
    assert broken.available is False
    assert broken.detect(np.zeros((10, 10, 3), dtype=np.uint8)) == []
```
Copiar exactamente este molde para los tests del selector: `monkeypatch.setattr` sobre
el símbolo importado en el módulo del selector (p. ej. `monkeypatch.setattr(device_module,
"torch", None)` o sobre una función interna que envuelva `torch.cuda.is_available`/
`onnxruntime.get_available_providers`) para simular "CUDA no disponible", "paquete no
instalado" y "driver presente pero falla al inicializar" como tres casos `TEST_*`
independientes, cada uno afirmando que el resultado cae a CPU sin lanzar.

**Análogo de integración real opcional, con `skipif` por variable de entorno:**
`tests/integration/test_redis_bus.py:1-28`:
```python
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not TEST_REDIS_URL,
    reason="TEST_REDIS_URL no definida -- requiere un Redis real, ver docstring del modulo",
)
```
Copiar esta forma para un test de integración GPU real (si se decide escribirlo):
`pytest.mark.skipif(not torch.cuda.is_available(), reason=...)` o una variable de
entorno equivalente, viviendo en `tests/integration/`, fuera de la suite por defecto
— igual que Redis, no hay GPU real en CI.

**Qué NO copiar:** no usar `unittest.mock.patch` como decorador de clase — el repo
usa `monkeypatch` (fixture de pytest) de forma consistente en estos dos ficheros;
mantener esa elección para coherencia de estilo.

---

### 7. Arnés de benchmark/medición de FPS

**Ya existe un arnés reutilizable de metodología, con salvedades:**
`tests/test_detector.py:216-269` (`TEST_multiclass_latency_under_15_percent`,
fixtures `real_detector`/`bench_frame`):
```python
@pytest.fixture(scope="module")
def real_detector() -> PersonDetector:
    if not _BUS_JPG.exists():
        pytest.skip(f"{_BUS_JPG} ausente — no se puede medir latencia real")
    return PersonDetector(model_path="yolo26n.pt", confidence=0.45)

@pytest.fixture(scope="module")
def bench_frame() -> np.ndarray:
    img = cv2.imread(str(_BUS_JPG))
    ...
    return cv2.resize(img, (1280, 720))

@pytest.mark.perf
def TEST_multiclass_latency_under_15_percent(real_detector, bench_frame):
    """... Se mide el p50, no un maximo ni una sola llamada ...
    Las dos configuraciones se miden INTERCALADAS ... para repartir la deriva
    de carga de la maquina por igual entre ambas muestras."""
```
Y `tests/test_reid_engine.py:54` (`TEST_reid_latency_under_20ms`) usa la misma
metodología de p50 para el motor ONNX.

Y el marcador está registrado en `pytest.ini:4-8`:
```ini
markers =
    perf: mide latencia real con margenes estrechos -- excluir de runs con
        cobertura (el trazado linea a linea de coverage.py infla el tiempo
        de las rutas con mucho glue Python, como la inferencia de YOLO, y
        puede colar una regresion falsa).
```

**Se reutiliza, no se inventa desde cero.** El arnés de la Fase 38 (CPU vs GPU) debe:
- Vivir como test `@pytest.mark.perf`, igual que `TEST_multiclass_latency_under_15_percent`.
- Medir p50 sobre N repeticiones, no una sola llamada (mismo argumento de jitter).
- Ir con `skipif`/`pytest.skip` si no hay GPU disponible en la máquina que corre el
  test — como hace `real_detector` cuando falta `bus.jpg` — porque CONTEXT.md ya
  fija que el número real (criterio 3, ≥3×) **no se puede cerrar en esta fase** sin
  `torch` CUDA instalado: el test debe quedar preparado y saltarse limpiamente, no
  fallar ni inventar una cifra.
- El patrón "intercalar las dos medidas" (CPU/CUDA) en vez de medir en bloques
  seguidos es directamente aplicable — mismo argumento de deriva de carga que ya
  documenta `test_detector.py:244-251`.

**Qué NO copiar:** no existe ningún script en `scripts/` (`fetch_models.py`,
`soak_test.py`, etc.) dedicado a benchmark de FPS — `soak_test.py` es un test de
resistencia/estabilidad, no de latencia comparada. No crear un script nuevo si el
test `@pytest.mark.perf` ya cubre la necesidad; CONTEXT.md deja "estructura del
arnés... test o script" a discreción del planner, pero el precedente más fuerte
del repo es el test, no el script.

---

### 8. `tests/test_architecture.py` — invariantes que el código nuevo debe respetar

Fichero completo revisado (`tests/test_architecture.py:1-183`). Invariantes activos:

1. **`test_no_await_in_worker_threads`** — ningún método usado como `target=` de
   `threading.Thread` en `backend/pipeline/**` puede contener `await`/`async for`/
   `async with`. Si el selector de dispositivo se llama desde dentro de un worker
   (p. ej. `DetectionWorker`), debe seguir siendo código síncrono — el selector en
   sí ya lo es (sondeo síncrono + `@lru_cache`), así que no hay riesgo si se llama
   directamente; sí lo habría si alguien intentara envolverlo en una corrutina y
   luego usarlo como target de un hilo.

2. **`test_no_inference_in_coroutines`** — ninguna corrutina (`async def`) puede
   **llamar** (`ast.Call`) a una función cuyo nombre esté en
   `INFERENCE_CALLS = {"detect_sv", "detect", "embed", "process_crop",
   "process_crop_scored", "identify_or_register"}`. Implicación directa para la
   Fase 38: si el wiring del selector queda en `main.py` (que sí tiene código
   `async`), está permitido invocar `PersonDetector(...)`/`FaceEngine(...)`/
   `ReIDEngine(...)` (son constructores, no estos nombres), pero **no** se debe
   llamar `.detect(...)`/`.embed(...)` desde una corrutina para "verificar que el
   device funciona" en el arranque — si se necesita una inferencia de sondeo real
   (no solo `torch.cuda.is_available()`), debe ir en `asyncio.to_thread(...)`,
   igual que el resto del pipeline.

3. **`test_capture_worker_stays_pure`** — `backend/pipeline/capture.py` no puede
   contener las cadenas `yolo/detector/recogn/zone/heatmap/tracker` (case-insensitive).
   El selector de dispositivo NO debe importarse ni referenciarse desde
   `capture.py` bajo ningún concepto — CaptureWorker es agnóstico a IA por diseño
   (invariante 1 de CLAUDE.md).

4. **`test_no_pickle_in_backend`** — ninguna línea de `backend/**/*.py` puede
   contener la palabra `pickle`. No aplica directamente, pero si el selector
   serializa algo para cache/log, no usar pickle.

5. **`test_pipeline_modules_do_not_import_fastapi`** — ningún módulo bajo
   `backend/pipeline/**` puede importar `fastapi`/`starlette`. Si el selector vive
   en `backend/pipeline/` (una de las opciones a discreción del planner), no puede
   importar nada de la capa web — coherente con que hoy `factory.py`/`manager.py`
   ya evitan esa importación.

6. **`test_raw_sql_text_stays_in_storage_module`** — no aplica a la Fase 38 (sin SQL).

**Implicación de nomenclatura para el módulo/función del selector:** evitar nombrar
la función pública del selector `detect` o `embed` a secas (colisionaría con
`INFERENCE_CALLS` si alguna vez se llamara desde una corrutina) — usar un nombre
distintivo como `resolve_device`/`select_device`/`get_inference_device`, que además
es más claro semánticamente y evita cualquier falso positivo futuro en
`test_no_inference_in_coroutines`.

## Shared Patterns

### "Backend opcional con default de primera clase intacto" (Fase 37, molde declarado)
**Fuente:** `backend/events/bus.py:247-255` (`create_event_bus`) y
`backend/database.py:83-98` (`_get_engine`)
**Aplica a:** el selector de dispositivo y el cableado a los 3 motores
```python
# events/bus.py
if settings.redis_url:
    return RedisBus(settings.redis_url, loop=loop)
return InProcessBus(loop=loop)

# database.py
if settings.database_url:
    _engine = create_async_engine(settings.database_url)
else:
    ...
    _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
```
Regla a replicar: valor vacío/`"auto"` con sonda negativa → comportamiento IDÉNTICO
al actual (CPU), sin ramas nuevas visibles en el resto del código; el punto de
decisión es único y explícito.

### Degradación observable vía evento tipado
**Fuente:** `backend/events/engine.py:183-184` + `backend/pipeline/factory.py:104-106`
**Aplica a:** el fallback GPU→CPU en el arranque
```python
def degraded_mode(self, now: datetime.datetime, reason: str) -> None:
    self._publish(EventType.DEGRADED_MODE, ts=now, severity=Severity.WARNING, payload={"reason": reason})
```
```python
def _on_recording_failure(message: str) -> None:
    logger.error("RecordingWorker failure (%s): %s", camera_id, message)
    event_engine.degraded_mode(datetime.datetime.now(), reason=message)
```

### Motores que degradan localmente sin lanzar (`available: bool`)
**Fuente:** `backend/perception/face/engine.py:59-77` y
`backend/perception/reid/engine.py:36-70`
**Aplica a:** cómo deben comportarse `FaceEngine`/`ReIDEngine`/`PersonDetector` si
`providers=["CUDAExecutionProvider", ...]` falla al inicializar sesión — capturar
`Exception`, `logger.exception(...)`, dejar el objeto en un estado usable (CPU)
en vez de propagar.

## No Analog Found

Ninguna pieza de la Fase 38 queda sin analog razonable en el repo — el repo no
tiene GPU/CUDA hoy, pero el molde de "backend opcional" (Fase 37) y el de
"motor con degradación local" (Fase 23/25, ArcFace/OSNet) cubren estructuralmente
las tres piezas nuevas. La única cifra que el repo no puede proveer es el número
real de FPS con GPU (fuera de alcance, documentado en 38-CONTEXT.md).

## Metadata

**Analog search scope:** `backend/config.py`, `backend/detector.py`,
`backend/perception/face/engine.py`, `backend/perception/reid/engine.py`,
`backend/pipeline/factory.py`, `backend/pipeline/manager.py`,
`backend/pipeline/detection.py`, `backend/events/bus.py`, `backend/events/engine.py`,
`backend/database.py`, `backend/api/v2/cameras.py`, `backend/main.py`,
`tests/test_reid_engine.py`, `tests/test_face_engine.py`, `tests/test_detector.py`,
`tests/integration/test_redis_bus.py`, `tests/test_architecture.py`, `pytest.ini`
**Files scanned:** ~18 ficheros leídos con `Read`/`Grep` (sin releer rangos)
**Pattern extraction date:** 2026-09-08
