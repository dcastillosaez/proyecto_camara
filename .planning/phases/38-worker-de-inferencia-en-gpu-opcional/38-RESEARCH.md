# Fase 38: Worker de inferencia en GPU (opcional) — Research

**Investigado:** 2026-09-08
**Dominio:** Selección de dispositivo de inferencia (CUDA/CPU) sobre tres motores heterogéneos — Ultralytics/PyTorch, insightface/ONNXRuntime y ONNXRuntime directo
**Confianza global:** ALTA — casi todo se verificó ejecutando el `.venv` real del proyecto y leyendo el código fuente de las versiones instaladas, no de memoria

<user_constraints>
## User Constraints (de 38-CONTEXT.md)

### Decisiones bloqueadas

**Dependencias**
- Esta fase **NO toca `requirements.txt` ni el `.venv`.** Se implementa la lógica de detección, selección, cableado y fallback; la instalación real de `torch` con CUDA y de `onnxruntime-gpu` queda fuera de alcance.
- Consecuencia aceptada: **el criterio de éxito 3 del ROADMAP (FPS de detección ≥3× respecto a CPU, medido y documentado) no se puede cerrar en esta fase.** Se planifica el arnés de medición y se deja el número real como pendiente explícito, documentado en el cierre de fase y en REQUIREMENTS.md. No se inventa ni se estima la cifra.
- El entorno actual confirma la restricción: `torch 2.11.0+cpu` y `onnxruntime 1.28.0` con providers `['AzureExecutionProvider', 'CPUExecutionProvider']`. La máquina tiene una NVIDIA RTX 2070 SUPER (8 GB, driver 591.86), así que el trabajo es verificable más adelante sin cambiar de hardware.

**Backends soportados**
- **Solo CUDA, con fallback a CPU.** DirectML queda fuera, pese a que el criterio 1 del ROADMAP lo menciona: no es verificable en esta máquina y duplicaría la matriz de pruebas sin aportar nada comprobable.
- El selector debe quedar **extensible**: añadir `DmlExecutionProvider` u otro proveedor más adelante debe ser añadir una entrada, no reescribir la lógica.

**Configuración**
- Un ajuste explícito en `backend/config.py` con tres valores: `auto` (default, detecta), `cpu` (fuerza CPU, comportamiento idéntico a Fase 37) y `cuda` (fuerza GPU y falla ruidosamente si no está disponible, para diagnóstico).
- El default `auto` debe comportarse exactamente como hoy en una máquina sin GPU.
- Sigue vigente la regla del proyecto: nada de credenciales ni rutas absolutas en configuración, y validadores en el mismo estilo que `yolo_model_path`/`reid_model_path`.

**Detección de disponibilidad**
- La sonda debe ser **barata y no lanzar**: importar/consultar y devolver un booleano, nunca romper el arranque si falta el paquete o el driver.
- Se sondea una sola vez por proceso (el patrón `@lru_cache` de `config.py` ya es el idioma del proyecto), no en cada frame ni en cada construcción de motor.

**Fallback y observabilidad**
- Un fallo de inicialización en GPU cae a CPU **sin abortar el arranque**, deja traza del motivo real (no un `except: pass`) y emite `DEGRADED_MODE` por el camino ya existente en el proyecto.
- El log de arranque debe decir, por motor, qué dispositivo quedó activo.
- El dispositivo efectivo debe ser observable desde fuera, en la línea de lo que ya expone `/api/v2/cameras/{id}/health`.

**Batching multi-cámara (criterio 6 del ROADMAP)**
- Opcional y **desactivado por defecto**. Si el análisis del planner concluye que no aporta con un solo flujo real y que añade latencia o acoplamiento, se documenta la decisión de no implementarlo en vez de añadir complejidad muerta — la regla final de CLAUDE.md manda sobre el criterio.

### Claude's Discretion
- Dónde vive el selector de dispositivo (módulo nuevo vs. ampliación de uno existente).
- Firma exacta de la API de selección y cómo se inyecta en los tres motores.
- Estructura del arnés de benchmark y si se marca como test o como script.
- Reparto en sub-tareas del PLAN.

### Deferred Ideas (FUERA DE ALCANCE)
- Instalación de `torch` CUDA y `onnxruntime-gpu`, y medición real del ≥3× (criterio 3). Requiere decisión posterior sobre `requirements-gpu.txt` vs. `.venv` principal.
- Soporte DirectML (`DmlExecutionProvider`) para GPUs AMD/Intel.
- Batching multi-cámara en GPU si el planner concluye que no aporta hoy.
- Cuantización/TensorRT o export a engine optimizado.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Descripción (REQUIREMENTS.md:295-296) | Soporte de esta investigación |
|----|---------------------------------------|-------------------------------|
| SCALE-11 | La GPU se detecta automáticamente y se usa si está disponible, con fallback limpio a CPU | Q1/Q2/Q3/Q4 — sonda barata verificada (`torch.cuda.is_available()` sobre build `+cpu`), forma correcta de fijar dispositivo en los tres motores, y el hallazgo crítico de que ONNXRuntime **hace fallback silencioso** (no lanza), lo que obliga a verificar `session.get_providers()` a posteriori |
| SCALE-12 | Sin GPU, el comportamiento del sistema es idéntico al de la ruta CPU | Q1 (pitfall `CUDA_VISIBLE_DEVICES`), Pitfall 1 y 2 — la ruta CPU debe seguir **sin pasar `device` a Ultralytics** y sin cambiar la lista de providers; cualquier otra cosa altera el comportamiento observable |

Nota de trazabilidad: el criterio 3 del ROADMAP (≥3× FPS) queda **abierto por decisión de alcance**, no por descuido. SCALE-11/SCALE-12 sí se pueden cerrar en esta fase; el ≥3× requiere el stack GPU instalado.
</phase_requirements>

## Summary

El proyecto tiene hoy tres motores de inferencia clavados a CPU por tres mecanismos distintos, y cada uno falla de forma distinta cuando le pides GPU sin tenerla. Ultralytics valida y **lanza** (`ValueError`, o `AssertionError` desde `torch.Tensor.to`). ONNXRuntime **no lanza nunca**: emite un `UserWarning`, descarta el provider que no puede usar y sigue en CPU como si nada — verificado ejecutando el runtime instalado. Y insightface añade una capa más: aunque le pases `providers=[...CUDA...]`, su `prepare(ctx_id=-1)` llama a `session.set_providers(['CPUExecutionProvider'])` y te devuelve a CPU en silencio. Esa asimetría es el núcleo técnico de la fase: no existe un "intenta GPU y captura la excepción" que funcione para los tres.

La consecuencia de diseño es clara. El selector debe devolver una *intención* (`cuda` / `cpu`), cada adaptador debe traducirla a su dialecto, y después de construir cada motor hay que **leer el dispositivo efectivo** y compararlo con el pedido. Para ONNX eso es `session.get_providers()[0]`; para Ultralytics es `model.device` (o `predictor.device`). Esa comparación es la que dispara el `DEGRADED_MODE`, no un `try/except`.

Hay además un efecto secundario de Ultralytics que puede romper SCALE-12 de forma no evidente: `select_device("cpu")` escribe `os.environ["CUDA_VISIBLE_DEVICES"] = ""` a nivel de **proceso** (`ultralytics/utils/torch_utils.py:214`), lo que cegaría también al CUDA EP de ONNXRuntime construido después. La forma segura de forzar CPU en Ultralytics no es pasar `device="cpu"` sino no pasar nada — que es exactamente lo que hace hoy `backend/detector.py:31` y lo que SCALE-12 pide conservar. Para la ruta CUDA, `model.to("cuda:0")` es la vía correcta: verificado que **no cambia `id(self._model)`**, así que el contrato documentado en `detector.py:59-81` (`set_classes` en caliente sin recargar el modelo) sigue intacto.

**Recomendación principal:** un módulo nuevo `backend/inference/device.py` con una función `@lru_cache` `resolve_device(mode) -> DeviceChoice` (intención + motivo) y tres adaptadores finos —uno por motor— que traducen la intención, verifican el dispositivo efectivo tras construir y publican `device_requested` / `device_effective` / `fallback_reason` como atributos legibles. Sin batching multi-cámara (ver Q7).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Sonda de disponibilidad de GPU | Proceso backend (módulo puro, sin I/O) | — | Es una consulta a librerías ya importadas; no pertenece a ningún worker ni al event loop |
| Resolución `auto`/`cpu`/`cuda` → dispositivo | Configuración + módulo selector | — | `Settings` aporta la intención; el selector la cruza con el entorno. Una sola vez por proceso (`@lru_cache`), como `get_settings()` |
| Traducción a Ultralytics (`.to()`) | `backend/detector.py` (adaptador de YOLO) | — | `PersonDetector` ya es el único punto del código que conoce la API de ultralytics (docstring de `face/engine.py:8`) |
| Traducción a ONNXRuntime (lista de `providers`) | `backend/perception/{face,reid}/engine.py` | — | Ambos son "thin adapters" declarados; el orden de providers vive donde se construye la sesión |
| Verificación del dispositivo efectivo | Cada adaptador de motor | — | Solo el adaptador puede leer `session.get_providers()` / `model.device` |
| Emisión de `DEGRADED_MODE` por fallback | `backend/pipeline/factory.py` (por cámara) y `backend/main.py` (servicios compartidos) | `backend/events/engine.py` | Los motores no conocen el `EventEngine`; quien los construye sí. Precedente exacto: `factory.py:104-106` |
| Exposición del dispositivo efectivo | `CameraPipeline.stats()` → `/api/v2/cameras/{id}/health` | `backend/api/v2/cameras.py:137` | El endpoint ya hace `**pipeline.stats()`; añadir una clave no toca la capa web |
| Calentamiento (warm-up) del modelo | Constructor del motor (hilo de arranque) | — | Nunca en el event loop (invariante 6) ni dentro del bucle caliente del worker |

## Standard Stack

No hay stack nuevo. Esta fase se implementa **con lo que ya está instalado**, por decisión del usuario. La tabla documenta las versiones verificadas contra las que hay que programar.

### Core (ya instalado, verificado hoy en `.venv`)

| Librería | Versión | Papel en esta fase | Verificación |
|----------|---------|--------------------|--------------|
| `ultralytics` | 8.4.38 | Motor YOLO; expone `.to(device)` y `device=` por llamada | `[VERIFIED: .venv/Scripts/python.exe -c "import ultralytics; print(ultralytics.__version__)"]` |
| `torch` | 2.11.0**+cpu** | Sonda `torch.cuda.is_available()`; backend de ultralytics | `[VERIFIED: torch.__version__ == '2.11.0+cpu', torch.version.cuda is None]` |
| `onnxruntime` | 1.28.0 (**build CPU**) | Motor de ArcFace y OSNet | `[VERIFIED: ort.get_available_providers() == ['AzureExecutionProvider', 'CPUExecutionProvider']]` |
| `insightface` | 1.0.1 | `FaceAnalysis`; envuelve ONNXRuntime y añade su propia semántica de `ctx_id` | `[VERIFIED: insightface.__version__]` |

### Hardware presente pero no utilizable todavía

| Elemento | Estado | Nota |
|----------|--------|------|
| NVIDIA GeForce RTX 2070 SUPER, 8192 MiB, driver 591.86 | Física, presente | `[ASSUMED]` — dato aportado en el brief de la fase, no re-verificado con `nvidia-smi` en esta sesión |
| `onnxruntime-gpu` | **No instalado** | ORT 1.27+ requiere CUDA 13.0 + cuDNN 9.x `[CITED: onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html]` |
| `torch` con CUDA | **No instalado** (build `+cpu`) | Diferido |

### Alternativas consideradas

| En vez de | Se podría usar | Trade-off |
|-----------|----------------|-----------|
| `torch.cuda.is_available()` como sonda | `nvidia-smi` por subproceso | Detecta la GPU física aunque el stack Python no la pueda usar — **peor**: informaría "hay GPU" y luego todo caería a CPU. La pregunta útil no es "¿hay GPU?" sino "¿puede este proceso usarla?" |
| `torch.cuda.is_available()` | `ort.get_available_providers()` | Son sondas de **motores distintos**. Se necesitan las dos: torch/ultralytics y ONNXRuntime pueden estar en estados diferentes (p. ej. `onnxruntime-gpu` instalado y `torch+cpu`). El selector debe exponer disponibilidad **por familia de motor**, no un único booleano |
| `model.to(device)` en Ultralytics | `device=` en cada llamada a `predict()` | Funciona (`engine/model.py:528` reconstruye el predictor si cambia `args.device`) pero paga la comparación en cada frame y deja la fuente de verdad repartida. `.to()` una vez, en el constructor, es más simple |
| Pasar `device="cpu"` explícito a Ultralytics | No pasar nada (estado actual) | **Pasar `"cpu"` es activamente peor**: `select_device` escribe `CUDA_VISIBLE_DEVICES=""` en el proceso (ver Pitfall 1) |

**Instalación:** ninguna. Comando de verificación de que el entorno no cambió:

```bash
.venv/Scripts/python.exe -c "import torch, onnxruntime as ort; print(torch.__version__, ort.get_available_providers())"
```

## Architecture Patterns

### Diagrama de flujo — resolución de dispositivo en el arranque

```text
Settings.inference_device  ("auto" | "cpu" | "cuda")
            │
            ▼
   resolve_device(mode)            ← @lru_cache, una vez por proceso
            │
            ├── mode == "cpu"  ──────────────► DeviceChoice(torch="cpu", onnx="cpu",
            │                                                reason="forzado por configuración")
            │
            ├── mode == "cuda" ── sonda ──┬── disponible ──► DeviceChoice(cuda, cuda)
            │                             └── NO ──────────► ERROR RUIDOSO (arranque falla)
            │
            └── mode == "auto" ── sonda ──┬── torch CUDA? ──► torch="cuda:0" / "cpu"
                                          └── ORT CUDA EP? ─► onnx="cuda"   / "cpu"
            │
            ▼
   ┌────────┴─────────────────────────────────────────────┐
   │                                                       │
   ▼                          ▼                            ▼
PersonDetector            FaceEngine                   ReIDEngine
(ultralytics)             (insightface+ORT)            (ORT directo)
   │                          │                            │
   │ .to("cuda:0")            │ providers=[CUDA,CPU]       │ providers=[CUDA,CPU]
   │ o NADA (cpu)             │ + prepare(ctx_id=0|-1)     │
   │                          │                            │
   ▼                          ▼                            ▼
VERIFICAR                 VERIFICAR                    VERIFICAR
model.device          models[*].session                sess.get_providers()[0]
                        .get_providers()[0]
   │                          │                            │
   └──────────────┬───────────┴────────────────────────────┘
                  │
                  ▼
         ¿efectivo != pedido?
                  │
         ┌────────┴────────┐
         │ SÍ              │ NO
         ▼                 ▼
  log.warning(motivo)   log.info("motor X en <device>")
  event_engine
    .degraded_mode()
         │
         └───► EventBus ──► SQLite + WebSocket ──► dashboard

  Estado efectivo publicado en CameraPipeline.stats()
                            └──► GET /api/v2/cameras/{id}/health
```

### Estructura propuesta

```text
backend/
  inference/               # NUEVO paquete
    __init__.py
    device.py              # DeviceChoice + resolve_device() + sondas
  detector.py              # +device en __init__, +device_effective
  perception/
    face/engine.py         # +device, providers calculados, ctx_id derivado
    reid/engine.py         # +device, providers calculados
  config.py                # +inference_device (enum auto|cpu|cuda)
  api/v2/config_schema.py  # +FieldDef obligatorio (ver Pitfall 6)
  pipeline/
    factory.py             # emite DEGRADED_MODE por motor degradado
    manager.py             # stats() expone devices
```

Alternativa razonable si el planner prefiere no crear paquete nuevo: `backend/pipeline/device.py`. **Argumento en contra:** `tests/test_architecture.py:129` (`test_pipeline_modules_do_not_import_fastapi`) y el resto de tests de arquitectura tratan `backend/pipeline/` como "cosas que corren en hilos de worker"; el selector es configuración pura resuelta en el arranque y no encaja ahí. Argumento a favor de `backend/inference/`: los tres motores viven en sitios distintos (`detector.py`, `perception/face/`, `perception/reid/`) y ninguno es "dueño" natural del selector.

### Patrón 1: intención resuelta una vez, traducida por adaptador

**Qué:** el selector no sabe nada de `providers` ni de `ctx_id`. Devuelve un objeto pequeño con la decisión y el motivo; cada adaptador traduce.

**Por qué:** es exactamente el patrón de la Fase 37 (`database_url` vacío = SQLite, con valor = esa URL; el punto de decisión es único y los call sites no cambian de firma). También es lo que hace la extensibilidad a DirectML barata: añadir una entrada al mapeo intención→providers.

```python
# backend/inference/device.py  (esbozo — la firma exacta es discreción del planner)
from dataclasses import dataclass
from functools import lru_cache

@dataclass(frozen=True)
class DeviceChoice:
    torch_device: str | None   # None = no pasar device a ultralytics (ruta CPU intacta)
    onnx_providers: tuple[str, ...]
    reason: str                # texto para el log y para el payload de DEGRADED_MODE

# Orden: preferido primero, CPUExecutionProvider SIEMPRE al final.
# Añadir DirectML mañana = añadir una entrada aquí, no reescribir la lógica.
_ONNX_PROVIDERS = {
    "cuda": ("CUDAExecutionProvider", "CPUExecutionProvider"),
    "cpu":  ("CPUExecutionProvider",),
}

@lru_cache(maxsize=None)
def resolve_device(mode: str) -> DeviceChoice: ...
```

### Patrón 2: sonda barata, sin lanzar, sin importar de más

**Qué:** `torch.cuda.is_available()` para la familia torch; `"CUDAExecutionProvider" in ort.get_available_providers()` para la familia ONNX.

**Coste medido** `[VERIFIED: ejecución local]`:
- `torch.cuda.is_available()` sobre build `+cpu`: devuelve `False` sin lanzar; primera llamada `0.0000 s`, 10 000 llamadas en `0.0019 s`.
- `ort.get_available_providers()`: 1000 llamadas en `0.80 ms`.

Ambas son gratis. El `@lru_cache` no es por coste, es por **estabilidad**: garantiza que los tres motores vean la misma decisión aunque algo mute el entorno entre construcciones (ver Pitfall 1).

**Sobre "¿se puede sondear sin importar torch?"** (Q4): sí técnicamente, pero no aporta. `backend/detector.py:8` hace `from ultralytics import YOLO`, y ultralytics importa torch en cadena; medido, `import torch` cuesta **1,79 s** y ya se paga sí o sí en el arranque `[VERIFIED]`. Importar torch dentro de `device.py` no añade coste real. Lo que sí hay que evitar es hacer el import a nivel de módulo si `device.py` se importa desde sitios que hoy no arrastran torch — un `import torch` diferido dentro de la función, envuelto en `try/except ImportError`, cumple el requisito de "no romper el arranque si falta el paquete".

### Patrón 3: verificar el efectivo, no confiar en la ausencia de excepción

```python
# Tras construir la sesión ONNX
effective = self._sess.get_providers()[0]        # p.ej. 'CPUExecutionProvider'
self.device_requested = requested                 # 'cuda'
self.device_effective = _short(effective)         # 'cpu'
if self.device_effective != self.device_requested:
    self.fallback_reason = (
        f"ONNXRuntime descartó {requested}: providers disponibles = "
        f"{ort.get_available_providers()}"
    )
    logger.warning("ReIDEngine: %s", self.fallback_reason)
```

### Anti-patrones a evitar

- **`try: construir_en_gpu() except: construir_en_cpu()`** — no funciona para ONNXRuntime, que nunca lanza. Daría un falso "GPU OK" permanente.
- **Pasar `device="cpu"` a Ultralytics en la ruta CPU** — muta `CUDA_VISIBLE_DEVICES` del proceso (Pitfall 1) y cambia el comportamiento observable respecto a la Fase 37 (SCALE-12).
- **Sondear en cada frame o en cada construcción de motor** — contradice la decisión de CONTEXT.md y añade ruido; `@lru_cache`.
- **Mover la construcción de los motores dentro de las factorías del `WorkerSupervisor`** — `manager.py:220-226` y el docstring de `factory.py:10-16` documentan explícitamente que `ReIDEngine`, la galería y la FSM viven **fuera** de la factoría para no recargar el ONNX en cada reinicio. En GPU ese error sería mucho más caro: recargaría pesos y reservaría VRAM en cada reinicio del worker.
- **Un único booleano `gpu_available`** — enmascara el caso real y probable de "torch con CUDA pero `onnxruntime` build CPU" (o al revés). La disponibilidad es por familia de motor.

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por qué |
|----------|--------------|------------------|---------|
| Saber si hay GPU usable | Parseo de `nvidia-smi` o de variables de entorno | `torch.cuda.is_available()` + `ort.get_available_providers()` | Responden la pregunta correcta ("¿puede *este proceso* usarla?"), no "¿existe hardware?" |
| Fallback de provider en ONNX | Bucle propio "prueba CUDA, si falla prueba CPU" | Lista ordenada de `providers` con `CPUExecutionProvider` al final | ORT ya hace el fallback; el bucle propio no detectaría nada porque no hay excepción que capturar |
| Validar `auto`/`cpu`/`cuda` | `if valor not in (...)` disperso | `FieldDef(type="enum", enum_values=(...))` + validador pydantic | El proyecto ya valida enums en un solo sitio: `backend/api/v2/config.py:118-120` y `camera_driver` en `config_schema.py:78-83` |
| Emitir el evento de degradación | Nuevo canal/log especial | `event_engine.degraded_mode(now, reason)` | Ya existe (`events/engine.py:183-184`) y ya se usa desde un hilo (`factory.py:104-106`) |
| Publicar desde un hilo al bus | `asyncio.run_coroutine_threadsafe` a mano | `bus.publish_threadsafe()` | `events/bus.py:129-132` usa `call_soon_threadsafe`; es el puente oficial de los workers |

**Idea clave:** el trabajo real de esta fase no es "activar la GPU" — es **detectar con fiabilidad que la GPU no se activó**. Las librerías ya intentan usar GPU solas; ninguna te avisa bien cuando no lo consigue.

## Preguntas de investigación — respuestas con evidencia

### Q1 — Ultralytics: `YOLO(...)`, `.to(device)` o `device=` por llamada

**Respuesta: `.to(device)` en el constructor para la ruta CUDA; NO pasar nada para la ruta CPU.**

Evidencia:

1. **`YOLO.__init__` no acepta `device`.** Firma real: `def __init__(self, model, task=None, verbose=False)` `[VERIFIED: .venv/Lib/site-packages/ultralytics/engine/model.py:81-84]`. La opción "en el constructor" tal como se plantea en CONTEXT.md no existe; lo más cercano es `.to()` inmediatamente después.

2. **`.to()` NO cambia la identidad del objeto.** `Model._apply()` hace `self = super()._apply(fn)` (que en `nn.Module` devuelve `self`), pone `self.predictor = None` y `self.overrides["device"] = self.device` `[VERIFIED: engine/model.py:845-869]`. Comprobado empíricamente con el modelo real del proyecto:

   ```
   id before 1530984980576  device cpu
   id after to(cpu) 1530984980576  same obj True  overrides cpu <class 'torch.device'>
   ```

   `[VERIFIED: ejecución local con yolo26n.pt]`. **El contrato de `detector.py:59-81` queda intacto**: `id(self._model)` no cambia, no hace falta reconstruir `PersonDetector`, y el `WorkerSupervisor` no ve ninguna parada (el riesgo que documenta `detector.py:70-72`).

3. **`.to()` invalida el predictor cacheado** (`self.predictor = None`, línea 867) — eso es lo correcto: la siguiente inferencia reconstruye el predictor sobre el dispositivo nuevo. Coste: una reconstrucción, en el arranque, no en el bucle caliente.

4. **`overrides["device"]` queda como `torch.device`, no como str** — verificado arriba. Eso importa porque `select_device` hace *early return* cuando recibe un `torch.device`: `if isinstance(device, torch.device) or str(device).startswith(...): return device` `[VERIFIED: ultralytics/utils/torch_utils.py:163]`. Es decir, tras `.to()`, las llamadas siguientes a `predict()` **no vuelven a pasar por la validación ni por la mutación de entorno** de `select_device`. Es la ruta limpia.

5. **`device=` por llamada también funciona**, pero es peor: `engine/model.py:528` compara `self.predictor.args.device != args.get("device", ...)` en **cada** `predict()` y reconstruye el predictor si difiere. Funciona, cuesta una comparación por frame, y deja la fuente de verdad repartida entre config y call site.

6. **Interacción con `yolo26n.pt` / `end2end=True`:** verificado que el modelo cargado tiene `end2end=True` `[VERIFIED: getattr(m.model,'end2end') == True]`. El `end2end` se aplica en `predictor.setup_model()` **antes** de construir el `AutoBackend` (`engine/predictor.py:395-400`), y el dispositivo se aplica en la construcción del `AutoBackend` (`device=select_device(...)`, línea 402). Son pasos independientes: mover el modelo a CUDA no toca la ruta NMS-free. **No hay interacción problemática.** La ausencia de NMS, de hecho, elimina el post-proceso en CPU que suele ser el cuello de botella al pasar a GPU.

7. **Interacción con `set_classes`:** ninguna. `classes` se aplica en el post-proceso de cada llamada, no en la construcción del modelo (ya documentado en `detector.py:62-65` y verificado en 27-RESEARCH). `.to()` no toca `self._classes`.

8. **Fallo ruidoso en modo `cuda`:** `m.to('cuda')` sobre un build `+cpu` lanza `AssertionError: Torch not compiled with CUDA enabled` `[VERIFIED: ejecución local]`. Ojo, **no** es `ValueError` ni `RuntimeError`: el `except` del modo `auto` debe capturar `Exception`, no un tipo concreto.
   Por la vía `select_device('cuda')` el error sí es `ValueError: Invalid CUDA 'device=0' requested. ... torch.cuda.is_available(): False` `[VERIFIED: ejecución local]`. Dos rutas, dos excepciones distintas — otra razón para capturar `Exception` y quedarse con `repr(exc)` como `reason`.

**Riesgo abierto:** `Model._apply()` empieza con `self._check_is_pytorch_model()` `[VERIFIED: engine/model.py:866]`, que lanza si el modelo no es PyTorch. `backend/config.py:46` **permite `.onnx` en `yolo_model_path`** (`_MODEL_PATH_ALLOWED_SUFFIXES = {".pt", ".onnx"}`). Con un YOLO exportado a ONNX, `.to()` reventaría. El plan debe guardar la llamada (`try/except` o comprobar el sufijo) — es un caso soportado por la configuración aunque el default sea `.pt`.

### Q2 — ONNXRuntime: providers, fallback y detección de disponibilidad

**Hallazgo crítico verificado: ONNXRuntime 1.28.0 NO lanza cuando el provider no está disponible. Ni al crear la sesión, ni en la primera inferencia. Descarta el provider y sigue.**

Prueba ejecutada contra un modelo ONNX real (`~/.insightface/models/buffalo_s/det_500m.onnx`) en el `.venv` del proyecto:

```
ort.InferenceSession(p, providers=['CUDAExecutionProvider','CPUExecutionProvider'])
  → created in 0.20s
  → effective providers: ['CPUExecutionProvider']
  → UserWarning: Specified provider 'CUDAExecutionProvider' is not in available provider names.
                 Available providers: 'AzureExecutionProvider, CPUExecutionProvider'

ort.InferenceSession(p, providers=['CUDAExecutionProvider'])   # sin CPU en la lista
  → ['CPUExecutionProvider']                                    # tampoco lanza

session.set_providers(['CUDAExecutionProvider'])
  → get_providers() == ['CPUExecutionProvider']                 # tampoco lanza
```

`[VERIFIED: ejecución local, onnxruntime 1.28.0]`

Consecuencias directas para el plan:

- **La lista correcta es `["CUDAExecutionProvider", "CPUExecutionProvider"]`** — preferido primero, CPU siempre al final. El fallback es automático y fiable. Confirmado también por el default de insightface, que usa exactamente esa lista `[VERIFIED: insightface/model_zoo/model_zoo.py:70-71]`.
- **La sonda "sin lanzar" es `"CUDAExecutionProvider" in ort.get_available_providers()`.** Distingue exactamente lo que pide el brief: `get_available_providers()` lista lo que **este build** puede usar (aquí: `['AzureExecutionProvider','CPUExecutionProvider']`), mientras que `get_all_providers()` lista los que ORT *conoce* en abstracto (incluye `CUDAExecutionProvider`, `TensorrtExecutionProvider`, `DmlExecutionProvider`...) `[VERIFIED: ambos ejecutados localmente]`. **Usar `get_all_providers()` sería el bug clásico** — devolvería `True` siempre.
- **`get_available_providers()` no cubre el segundo caso** ("está listado pero falla al inicializar" — típico de `onnxruntime-gpu` instalado sin las DLL de CUDA/cuDNN, o con versión incompatible). En ese caso ORT registra el fallo, cae a CPU y **tampoco lanza**. La **única** forma fiable de saber qué pasó de verdad es `session.get_providers()` **después** de construir la sesión, y comparar con lo pedido. Esto no es opcional: es el mecanismo que dispara `DEGRADED_MODE`.
- **El `UserWarning` no sirve como señal programática.** Depende del filtro de warnings del proceso y el proyecto ya usa `-W ignore` en algunos contextos.

Escenario relevante para el futuro (deferred): ORT 1.27+ requiere **CUDA 13.0 + cuDNN 9.x** `[CITED: onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html]`. La RTX 2070 SUPER es Turing (SM 7.5), arquitectura que CUDA 13 mantiene `[ASSUMED — no verificado en esta sesión]`. Cuando llegue el momento de instalar, esa comprobación va primero.

### Q3 — insightface / FaceAnalysis: providers y `ctx_id`

**Respuesta: hay que cambiar DOS cosas a la vez. Cambiar solo `providers` no hace nada.**

Cómo se propaga hoy:

1. `FaceAnalysis.__init__(name, root, allowed_modules, **kwargs)` pasa `**kwargs` tal cual a `model_zoo.get_model(onnx_file, **kwargs)` `[VERIFIED: insightface/app/face_analysis.py:41,48]`. Por eso `providers=["CPUExecutionProvider"]` en `backend/perception/face/engine.py:67` funciona.
2. `get_model` extrae `providers = kwargs.get('providers', get_default_providers())` y construye `PickableInferenceSession(onnx_file, providers=..., provider_options=...)` `[VERIFIED: model_zoo/model_zoo.py:94-96, 40]`. `PickableInferenceSession` hereda de `onnxruntime.InferenceSession` (línea 22), así que aplica todo lo de Q2 — incluido el fallback silencioso.
3. **`prepare(ctx_id)` puede deshacer la elección.** `FaceAnalysis.prepare` llama a `model.prepare(ctx_id, ...)` de cada sub-modelo `[VERIFIED: face_analysis.py:70-74]`, y ambos sub-modelos que este proyecto carga hacen lo mismo:

   ```python
   # insightface/model_zoo/arcface_onnx.py:61-63
   def prepare(self, ctx_id, **kwargs):
       if ctx_id < 0:
           self.session.set_providers(['CPUExecutionProvider'])
   ```
   ```python
   # insightface/model_zoo/retinaface.py:133-135   (SCRFD, el detector)
   def prepare(self, ctx_id, **kwargs):
       if ctx_id < 0:
           self.session.set_providers(['CPUExecutionProvider'])
   ```
   `[VERIFIED: fuente instalada]`

**Cómo degrada hoy `backend/perception/face/engine.py`:** doblemente clavado a CPU y de forma correcta para la Fase 37 —
- `engine.py:67` → `providers=["CPUExecutionProvider"]`
- `engine.py:70` → `self._app.prepare(ctx_id=-1, det_size=det_size)` → `set_providers(['CPUExecutionProvider'])`

Y la degradación por fallo: `engine.py:62-64` devuelve con `_available=False` y un `logger.warning` si `insightface` no está instalado; `engine.py:72-73` captura `Exception` con `logger.exception` (no un `except: pass`) y deja `_available=False`. **Ese contrato ya cumple lo que pide CONTEXT.md** ("deja traza del motivo real"); lo que falta es distinguir "no disponible" de "disponible pero en CPU cuando pedí GPU".

**Cambio necesario para GPU:** `providers = choice.onnx_providers` **y** `ctx_id = 0 if cuda else -1`. Si se cambia solo `providers`, `prepare(ctx_id=-1)` fuerza CPU y el sistema reportaría GPU sin usarla. Verificación posterior:

```python
det = self._app.models["detection"].session.get_providers()[0]
rec = self._app.models["recognition"].session.get_providers()[0]
```

**Aviso:** `ArcFaceONNX.prepare` con `ctx_id >= 0` **no hace nada** (el `if` es la única sentencia). O sea, en la ruta CUDA la elección de dispositivo la determina exclusivamente `providers`. Correcto, pero conviene tenerlo claro: `ctx_id=0` no "enciende" la GPU, solo *deja de apagarla*.

**Nota lateral:** `FaceAnalysis.__init__` imprime a stdout (`print('find model: ...')`, `print(f'Applied providers: {session._providers}...')` en `model_zoo.py:41`) — ya ocurre hoy, no es una regresión, pero si el plan quiere el "log por motor" limpio no debe depender de esos `print`.

### Q4 — Torch/CUDA: sonda barata y segura

`torch.cuda.is_available()` sobre un build `+cpu` es **seguro y prácticamente gratis**:

```
import torch                     1.79 s      (ya se paga: ultralytics lo importa)
first is_available()             0.0000 s → False
10 000 llamadas                  0.0019 s
torch.cuda.device_count()        0
```
`[VERIFIED: ejecución local]`

No lanza. Lo que **sí lanza** es `torch.cuda.get_device_name(0)`: `AssertionError: Torch not compiled with CUDA enabled` `[VERIFIED]`. Si el log de arranque quiere mostrar el nombre de la GPU (buen detalle para el criterio 1), esa llamada va dentro de un `try/except`, siempre después de comprobar `is_available()`.

**¿Se puede sondear sin importar torch?** Sí — pero no aporta, porque `backend/detector.py:8` (`from ultralytics import YOLO`) ya arrastra torch en cualquier arranque real del backend. La recomendación práctica: `import torch` **diferido dentro de la función de sonda**, envuelto en `try/except ImportError` que devuelva `False`. Así el módulo `device.py` es importable y testeable sin torch (útil para los dobles de la Q-validación), cumple "nunca romper el arranque si falta el paquete", y no añade coste medible al arranque real.

### Q5 — Dónde se emite `DEGRADED_MODE` hoy y camino exacto desde un fallo de init de GPU

**Un único emisor real hoy** `[VERIFIED: grep en backend/ y tests/]`:

```python
# backend/pipeline/factory.py:104-106
def _on_recording_failure(message: str) -> None:
    logger.error("RecordingWorker failure (%s): %s", camera_id, message)
    event_engine.degraded_mode(datetime.datetime.now(), reason=message)
```

que baja a:

```python
# backend/events/engine.py:183-184
def degraded_mode(self, now: datetime.datetime, reason: str) -> None:
    self._publish(EventType.DEGRADED_MODE, ts=now, severity=Severity.WARNING,
                  payload={"reason": reason})
```

y `_publish` termina en `self._bus.publish_threadsafe(event)` `[VERIFIED: events/engine.py:80]`, que usa `loop.call_soon_threadsafe(self._enqueue, event)` `[VERIFIED: events/bus.py:129-132]`. Es decir: **es seguro llamarlo desde cualquier hilo y también desde el arranque** (el evento queda encolado y se entrega cuando el loop lo procese). `EventType.DEGRADED_MODE` está en el catálogo con `Severity.WARNING` por defecto `[VERIFIED: events/types.py:46,53]`.

`WorkerSupervisor` **no** emite el evento: solo loguea y expone `degraded` (`supervisor.py:9-10` lo dice explícitamente — "emitirlo como evento tipado DEGRADED_MODE llega en la Fase 19"; `supervisor.py:109-111` expone la propiedad).

**Camino exacto para un fallo de init de GPU — hay un problema de orden que el plan debe resolver:**

| Motor | Dónde se construye | ¿Hay `EventEngine` disponible ahí? |
|-------|--------------------|-------------------------------------|
| `PersonDetector` (YOLO) | `factory.py:73-79` | **NO** — el `EventEngine` de esa cámara se crea justo después, en `factory.py:81` |
| `ReIDEngine` | `manager.py:226`, dentro de `CameraPipeline.__init__` | SÍ — `event_engine` llega como parámetro |
| `FaceEngine` | `recognizer.py:98`, dentro de `PersonRecognizer.__init__` | **NO** — pero `PersonRecognizer` se construye en `main.py:531`, y el `EventEngine` de proceso ya existe desde `main.py:476` |

Dos opciones limpias:

- **(a) Reordenar** `factory.py` para crear `event_engine` (línea 81) antes que `detector` (línea 73). Cambio de 8 líneas, sin efectos secundarios aparentes — `EventEngine(bus, camera_id, latency_tracker)` no depende del detector.
- **(b) Recomendada — no reordenar nada:** cada motor guarda `device_requested` / `device_effective` / `fallback_reason` como atributos públicos, y **quien construye** emite el evento después. En `factory.py`, tras la línea 81, un bucle sobre los motores construidos; en `main.py`, tras construir `recognizer` (línea 531), usando el `event_engine` de la línea 476. Ventaja: los motores no aprenden nada del sistema de eventos (siguen siendo "thin adapters"), y el mismo atributo sirve para el log de arranque, para el evento y para `/health` — una sola fuente de verdad, tres consumidores.

**Ojo con la deduplicación:** con N cámaras, N `PersonDetector` y N `ReIDEngine` fallarían igual, y se emitirían 2N eventos `DEGRADED_MODE` idénticos en el arranque. `degraded_mode()` **no** tiene el latch que sí tiene `camera_offline()` (`engine.py:171-175` comprueba `self._camera_offline` antes de publicar). Recomendación: emitir **una vez por proceso** para el fallback de dispositivo — es una condición global del entorno, no de una cámara. El `@lru_cache` de `resolve_device()` da el punto natural para ese "una vez".

### Q6 — Cómo se expone hoy la salud y dónde encaja el dispositivo efectivo

Cadena actual `[VERIFIED]`:

```python
# backend/api/v2/cameras.py:137-154
@router.get("/{camera_id}/health")
async def camera_health(request: Request, camera_id: str):
    ...
    return {
        **asdict(pipeline.health),          # CaptureHealth (manager.py:268-270)
        "capture_fps": pipeline.get_fps(),
        "detection_fps": pipeline.get_detection_fps(),
        "broker_stats": pipeline.broker.stats(),
        **pipeline.stats(),                  # ← punto de extensión
    }
```

```python
# backend/pipeline/manager.py:424-436
def stats(self) -> dict:
    out = {"workers": ..., "degraded": ..., "broker": ...}
    if self.detection:   out["detection"]   = self.detection.stats
    if self.streaming:   out["streaming"]   = self.streaming.stats
    if self.recognition: out["recognition"] = self.recognition.stats
    return out
```

**Encaje recomendado:** una clave nueva `"devices"` en `CameraPipeline.stats()`, sin tocar la capa web:

```json
"devices": {
  "requested": "auto",
  "yolo":   {"effective": "cpu", "fallback_reason": null},
  "face":   {"effective": "cpu", "fallback_reason": null},
  "reid":   {"effective": "cpu", "fallback_reason": null}
}
```

Un diccionario anidado bajo una clave nueva es aditivo: no rompe ningún consumidor del endpoint (`asdict(pipeline.health)` y las claves existentes no cambian). El precedente exacto es `estimated_cpu_pct`, añadido en la Fase 36 al listado de cámaras (`cameras.py:126-127`).

**Cuidado:** `FaceEngine` vive dentro de `PersonRecognizer`, que es un servicio **compartido entre cámaras** (`factory.py:15-16`: "El `recognizer` SÍ se comparte"). Reportarlo dentro de `stats()` de cada cámara repetiría el mismo dato N veces. Es aceptable (es informativo y N es pequeño), pero si el planner prefiere, el dispositivo de `face` puede ir en el `/api/health` de proceso (`main.py:880`) en vez de por cámara. Decisión de discreción; documentarla.

### Q7 — Batching multi-cámara en GPU (criterio 6)

**Recomendación: NO implementarlo. Documentar la decisión con argumento técnico.** CONTEXT.md autoriza expresamente esta salida y la regla final de CLAUDE.md la respalda.

Argumentos, todos anclados en el código actual:

1. **Cada cámara tiene su propio broker, su propio hilo y su propio modelo.** `CameraPipeline.__init__` crea `self.broker = FrameBroker()` por cámara (`manager.py:96`) y `factory.py:73` construye un `PersonDetector` nuevo por cámara — con el comentario explícito de que "nunca se comparte un modelo YOLO entre pipelines" (`factory.py:10-11`). Batchear exige lo contrario: **un** modelo compartido alimentado por **un** collector que lea de N brokers. Es un rediseño del punto más sensible del pipeline, no una opción configurable.

2. **Rompe el invariante 2 de CLAUDE.md** ("cada worker consume del broker a su ritmo"). Un lote necesita un punto de encuentro: o esperas a que N cámaras tengan frame, o cierras el lote por timeout. Lo primero acopla la latencia de cada cámara a la de la más lenta; lo segundo mete un temporizador nuevo en la ruta caliente. Ambas cosas añaden latencia a un sistema cuya prioridad declarada es "baja latencia".

3. **Cada cámara tiene su propio `AdaptiveRate` con su propio escalón** (`rate.py:26`, `STEPS = (12.0, 8.0, 5.0, 3.0)`), y desde la Fase 36 además un techo externo por reparto de CPU (`rate.set_external_cap`, `manager.py`). Dos cámaras a 12 y 3 FPS no forman lotes: el batcher tendría que ignorar o coordinar la política de ritmo que la Fase 18 y la 36 construyeron a propósito.

4. **Con el hardware real no hay nada que ganar.** Hoy hay **una** cámara: el lote sería de tamaño 1, es decir, el código actual con una capa de indirección encima. Y con varias, YOLO26n a 640 px en una 2070 SUPER está muy lejos de saturar la GPU a 8 FPS por cámara; el cuello estaría en decodificación RTSP y en el pre/post-proceso, que el batching no toca.

5. **Es explícitamente diferible.** CONTEXT.md ya lo lista en `Deferred Ideas`.

**Cómo cerrar el criterio 6 sin implementarlo:** el criterio pide que el batching sea "opcional y desactivable". Con la decisión documentada, el estado por defecto y único es "desactivado", lo que satisface la parte verificable. El PLAN debe dejar constancia escrita (en el SUMMARY de fase y en el cierre) de que es una **decisión razonada**, con estas cinco razones y con la condición de reapertura: *más de 3 cámaras simultáneas y utilización de GPU medida por encima del 70 %*.

### Q8 — Riesgos y pitfalls concretos

Ver la sección siguiente. Los cuatro que pregunta el brief: memoria (Pitfall 5), warm-up (Pitfall 3), hilos vs contexto CUDA (Pitfall 4), y equivalencia de la ruta CPU (Pitfalls 1 y 2).

## Common Pitfalls

### Pitfall 1 — `select_device("cpu")` envenena el proceso entero (rompe SCALE-12)

**Qué pasa:** pasar `device="cpu"` a Ultralytics escribe una variable de entorno **global del proceso**.

```python
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # force torch.cuda.is_available() = False
```
`[VERIFIED: ultralytics/utils/torch_utils.py:214]`

Reproducido localmente:

```
before CVD= None
select_device('cpu')  -> cpu   CVD= ''
select_device('')     -> cpu   CVD= ''     ← ya no se recupera
```
`[VERIFIED: ejecución local]`

**Por qué importa:** con `CUDA_VISIBLE_DEVICES=""`, cualquier motor construido **después** en el mismo proceso ve cero GPUs — incluido el `CUDAExecutionProvider` de ONNXRuntime. Si el plan construye `PersonDetector` en CPU (factory.py:73) antes que `ReIDEngine` (manager.py:226), la ruta GPU de ReID quedaría muerta sin ninguna traza que lo explique.

**Cómo evitarlo (tres capas):**
1. **Nunca pasar `"cpu"` a Ultralytics.** La ruta CPU debe seguir sin pasar `device` — es lo que hace hoy `detector.py:31` y lo que SCALE-12 exige conservar.
2. Si hiciera falta forzar, usar `.to("cpu")`, que va por `nn.Module.to` y **no** llama a `select_device` — verificado: tras `m.to('cpu')`, `CVD= None` `[VERIFIED]`.
3. `resolve_device()` con `@lru_cache` fija la decisión **antes** de construir el primer motor, así ningún motor decide en función de un entorno ya mutado por otro.

**Señal de alarma:** `torch.cuda.is_available()` devuelve `True` en la sonda y `False` más tarde en el mismo proceso.

### Pitfall 2 — "auto" no significa lo mismo para los tres motores hoy

`select_device("")` (lo que se usa hoy, al no pasar `device`) hace `if not cpu and not mps and torch.cuda.is_available(): # prefer GPU if available` `[VERIFIED: torch_utils.py:240]`. **Ultralytics ya usa la GPU automáticamente si torch la ve.** Los dos motores ONNX, en cambio, están literalmente clavados (`face/engine.py:67`, `reid/engine.py:49`).

Implicación para SCALE-12: en la máquina actual (`torch+cpu`), `auto` debe producir **exactamente el comportamiento de hoy**, y eso significa **no cambiar nada** en la ruta de Ultralytics cuando la decisión es CPU: ni `.to("cpu")`, ni `device=`, ni nada. Cero diff de comportamiento. Un test debe fijar esto (ver Validation Architecture).

### Pitfall 3 — La primera inferencia en GPU hunde el `AdaptiveRate` durante decenas de segundos

**Qué pasa:** `AdaptiveRate.observe()` **siembra la media móvil con el primer valor**:

```python
self._avg_latency = (latency if self._avg_latency == 0.0
                     else self._ALPHA * latency + (1 - self._ALPHA) * self._avg_latency)
```
`[VERIFIED: backend/pipeline/rate.py:81-83]`

Con `_DOWN_STREAK = 3`, `_UP_STREAK = 10`, `_ALPHA = 0.2` y `STEPS = (12, 8, 5, 3)` (`rate.py:26-32`), una primera latencia anómala arrastra el sistema hacia abajo y tarda mucho en volver: bajar de 12 a 3 FPS son 3 observaciones; subir de 3 a 12 son **30 observaciones holgadas** más el tiempo que la EMA tarde en decaer.

**Magnitud del problema:** medido en CPU con el modelo real del proyecto, la primera inferencia cuesta **203 ms** frente a **89 ms** en caliente — 2,3× `[VERIFIED: ejecución local, yolo26n.pt, 1280x720, imgsz=640]`. En GPU el arranque en frío es bastante peor (creación del contexto CUDA, carga de cuDNN, selección de algoritmos): del orden de segundos `[ASSUMED — no medible sin stack GPU]`.

**Cómo evitarlo:** una inferencia de calentamiento con un frame sintético (`np.zeros((h, w, 3), np.uint8)`) en el constructor del motor, **antes** de que el `DetectionWorker` arranque, y por tanto sin llamar a `rate.observe()`. Lo mismo para `ReIDEngine` (un crop de ceros) y `FaceEngine` (un frame de ceros; ya está probado que devuelve lista vacía sin lanzar — `tests/test_face_engine.py::TEST_detect_returns_empty_on_blank_frame`).

**Cuidado:** el warm-up añade tiempo al arranque. En CPU sería ~200 ms por motor, aceptable. Debe ser condicional al dispositivo elegido, o hacerse siempre (más simple y hace la ruta CPU marginalmente mejor, pero **cambia el arranque** respecto a la Fase 37 — si se quiere equivalencia estricta, solo en la ruta CUDA).

### Pitfall 4 — Hilos y contexto CUDA

Los workers son **hilos** (`detection.py:112-116`, `threading.Thread(target=self._loop, ...)`), y el invariante 5 de CLAUDE.md prohíbe `await` en ellos. Eso no cambia con GPU: nada de lo que se añade es asíncrono.

Lo que sí hay que respetar:

- **Construir los motores fuera de las factorías del supervisor.** Ya está así y está documentado: `manager.py:220-226` explica que `ReIDEngine` y la galería viven fuera porque "el `WorkerSupervisor` re-ejecuta la factoría en cada reinicio del worker [...] y recargaría el ONNX cada vez". Con GPU ese error pasaría de "lento" a "fuga de VRAM": cada reinicio reservaría memoria nueva. **No mover nada.**
- El contexto CUDA primario es por proceso y compartido entre hilos; PyTorch inferencia y `InferenceSession.run()` son seguros desde varios hilos `[ASSUMED — conocimiento general de CUDA/ORT, no verificado en esta sesión por falta de stack GPU]`. El diseño actual (un modelo por cámara, un hilo por worker) no crea contención nueva.
- **`ort.SessionOptions.intra_op_num_threads = 1`** (`reid/engine.py:46-47`) se eligió para no robarle cores al `DetectionWorker`. Con CUDA EP ese ajuste pasa a ser irrelevante (solo afecta a los nodos que caigan en CPU) pero **no molesta**. No tocarlo: cambiarlo alteraría la ruta CPU.

### Pitfall 5 — Memoria de 8 GB con tres modelos

Los tres modelos son pequeños: YOLO26n (~5,3 MB en disco `[VERIFIED: ls yolo26n.pt]`), `det_500m.onnx` 2,4 MB, `w600k_mbf.onnx` 13 MB, OSNet x0.25 (~3 MB) `[VERIFIED: ls ~/.insightface/models/buffalo_s]`. Los pesos no son el problema.

Lo que consume es el **overhead fijo por runtime**: contexto CUDA de PyTorch, caching allocator, y el arena de memoria del CUDA EP de ONNXRuntime. Del orden de cientos de MB a ~1,5 GB en total `[ASSUMED — no medible sin stack GPU]`. En 8 GB con una cámara sobra margen.

El riesgo real es **multi-cámara**: N cámaras → N instancias de `PersonDetector` y N de `ReIDEngine`, cada una con sus propios buffers de trabajo. Escala linealmente. Con la política actual (un modelo por cámara, por diseño explícito de la Fase 36) conviene documentar un techo orientativo y dejarlo como comprobación del checkpoint con GPU real, no inventarlo aquí.

**Mitigación disponible sin código nuevo:** `ort.SessionOptions` ya se usa en `reid/engine.py:40-47`; si hiciera falta acotar VRAM, `provider_options` del CUDA EP (`gpu_mem_limit`, `arena_extend_strategy`) es el punto de extensión. **No implementarlo ahora** — es optimización especulativa sin medición, justo lo que prohíbe CLAUDE.md.

### Pitfall 6 — Añadir un campo a `Settings` sin tocar `config_schema.py` rompe la suite

`tests/test_config_schema.py:24-26`:

```python
def TEST_all_fields_covers_every_settings_attribute():
    ...
    assert keys == set(Settings.model_fields)
```
`[VERIFIED]`

Es una igualdad de conjuntos: cualquier campo nuevo en `Settings` **debe** tener su `FieldDef`. La Fase 37 ya tropezó con esto y lo dejó escrito en su PLAN (`37-.../PLAN.md`, sección 1). Además `TEST_no_field_has_empty_hint` exige `hint` no vacío.

Forma exacta del campo nuevo, siguiendo el precedente de `camera_driver` (`config_schema.py:78-83`):

```python
FieldDef(
    key="inference_device", env="INFERENCE_DEVICE", label="Dispositivo de inferencia",
    hint="'auto' detecta la GPU y cae a CPU si no está disponible; 'cpu' fuerza CPU; "
         "'cuda' exige GPU y falla el arranque si no la hay (para diagnóstico).",
    type="enum", default="auto", enum_values=("auto", "cpu", "cuda"),
    applies="restart_server",
)
```

`applies="restart_server"`: cambiar de dispositivo exige recargar los tres modelos; no hay ruta en caliente y el módulo solo señaliza, no reinicia nada (`config_schema.py:15-19`).

### Pitfall 7 — `except` demasiado estrecho en el fallback de Ultralytics

Como se vio en Q1, la misma condición ("pediste CUDA y no hay") produce `AssertionError` por la vía `.to("cuda")` y `ValueError` por la vía `select_device("cuda")` `[VERIFIED: ambas ejecutadas localmente]`. Y si faltara torch entero, sería `ImportError`. El `except Exception` con `logger.exception` es el patrón correcto y **ya es el idioma del proyecto** (`face/engine.py:72-73`, `reid/engine.py:65-66`). Lo que CONTEXT.md prohíbe es el `except: pass`, no el `except Exception` con traza.

### Pitfall 8 — `yolo_model_path` puede ser `.onnx`

`config.py:46` acepta `.pt` **y** `.onnx`. `Model._apply()` (y por tanto `.to()`) empieza con `self._check_is_pytorch_model()`, que lanza sobre un modelo ONNX `[VERIFIED: ultralytics/engine/model.py:866]`. El default es `.pt` (`config.py:40`), pero la configuración permite lo otro. Guardar la llamada, y si el modelo no es PyTorch registrar un aviso y quedarse en la ruta actual — un YOLO ONNX seguiría el camino de providers, no el de `.to()`, y eso queda **fuera de alcance** de esta fase.

## Code Examples

### Sondas verificadas (las dos, no una)

```python
# Familia torch / ultralytics
def _torch_cuda_available() -> bool:
    try:
        import torch                       # diferido: el módulo es importable sin torch
        return bool(torch.cuda.is_available())
    except Exception:                      # ImportError, y cualquier fallo de driver
        return False

# Familia ONNXRuntime
def _ort_cuda_available() -> bool:
    try:
        import onnxruntime as ort
        # get_available_providers(): lo que ESTE build puede usar.
        # get_all_providers(): lo que ORT conoce en abstracto — NO sirve como sonda.
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False
```
`[VERIFIED: ambas ejecutadas en el .venv del proyecto; ver la diferencia get_available/get_all en Q2]`

### Ruta CPU: no tocar nada (SCALE-12)

```python
# backend/detector.py — el cambio debe ser estrictamente aditivo
self._model = YOLO(model_path)                       # línea 31, sin cambios
if device is not None and device.startswith("cuda"):  # SOLO en la ruta CUDA
    self._model.to(device)                            # id(self._model) NO cambia
# Ruta CPU: no se llama a .to(), no se pasa device= a predict(). Cero diff.
```

### Verificación del dispositivo efectivo por motor

```python
# ONNX (reid/engine.py y ambos sub-modelos de face/engine.py)
effective = self._sess.get_providers()[0]

# Ultralytics
effective = str(self._model.device)     # 'cpu' | 'cuda:0'
```
`[VERIFIED: get_providers() ejecutado localmente; model.device leído del código y comprobado ('cpu')]`

### Emisión del evento, una vez por proceso

```python
# backend/pipeline/factory.py — tras crear event_engine (línea 81)
for name, engine in (("yolo", detector), ("reid", ...)):
    if engine.fallback_reason:
        event_engine.degraded_mode(
            datetime.datetime.now(),
            reason=f"{name}: {engine.fallback_reason}",
        )
```
Mismo patrón que `factory.py:104-106`. Recordar la deduplicación de Q5: con N cámaras esto emite N veces la misma condición global.

## Runtime State Inventory

Fase de código y configuración; no hay renombrados ni migraciones. Aun así, tres estados de runtime son relevantes:

| Categoría | Encontrado | Acción |
|-----------|-----------|--------|
| Datos almacenados | Ninguno. El dispositivo de inferencia no se persiste ni forma parte de ningún esquema. Los embeddings de `persons.db` y de la galería ReID **no cambian de formato** al calcularse en GPU (mismo modelo, mismos 512D L2-normalizados) — aunque sí pueden diferir en los últimos bits (ver Validation Architecture) | Ninguna |
| Configuración de servicio en vivo | La tabla `app_config` (`ConfigRepo`) puede sobrescribir cualquier campo de `Settings` en runtime, con precedencia sobre `.env` (`config_schema.py:10-13`). Un `inference_device` guardado ahí ganaría al `.env` | Ninguna hoy (campo nuevo, sin filas). Documentar la precedencia en el `hint` |
| Estado registrado en el SO | `CUDA_VISIBLE_DEVICES` **no** está puesta hoy (`CVD= None` verificado antes de importar ultralytics). Ultralytics la escribe si se le pasa `device="cpu"` — ver Pitfall 1 | No pasar `"cpu"` a ultralytics |
| Secretos / variables de entorno | `INFERENCE_DEVICE` sería una variable nueva, **sin valor sensible**. Ningún secreto afectado | `secret=False` en el `FieldDef` |
| Artefactos de build | Ninguno. No hay `.egg-info`, no cambia `requirements.txt`, no se recompila nada | Ninguna |

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|-------------|---------------|-----------|---------|----------|
| `torch` | Sonda CUDA, motor YOLO | ✓ | 2.11.0**+cpu** | — (la ruta CPU es el default) |
| `torch` con CUDA | Ruta GPU de YOLO | ✗ | — | CPU (automático). **Bloquea el criterio 3, ya aceptado** |
| `onnxruntime` | ArcFace, OSNet | ✓ | 1.28.0, build CPU | — |
| `onnxruntime-gpu` | Ruta GPU de ArcFace/OSNet | ✗ | — | CPU (automático y silencioso, ver Q2) |
| `ultralytics` | Motor YOLO | ✓ | 8.4.38 | — |
| `insightface` | FaceAnalysis | ✓ | 1.0.1 | `FaceEngine.available=False` (ya existe) |
| GPU NVIDIA RTX 2070 SUPER | Ruta GPU | ✓ física, ✗ utilizable desde Python | driver 591.86 | — |
| `models/reid/osnet_x0_25_msmt17_dyn.onnx` | Tests de ReID | ✗ **ausente** `[VERIFIED: ls models/ → no existe]` | — | `tests/test_reid_engine.py` hace `pytest.skip` (por diseño, ver su docstring). **Los tests nuevos de ReID deben seguir esa política: skip, nunca fallo** |
| `~/.insightface/models/buffalo_s` | Tests de FaceEngine | ✓ presente (5 `.onnx`) | — | insightface autodescarga |

**Dependencias ausentes que bloquean:** ninguna para SCALE-11/SCALE-12. La única cosa bloqueada es el criterio 3 del ROADMAP, ya diferido por decisión del usuario.

**Nota importante:** el fichero del modelo ReID **no está en disco**. Cualquier test nuevo que construya un `ReIDEngine` real debe usar el mismo `pytest.skip` que `tests/test_reid_engine.py:28-35`, o trabajar con dobles.

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|-----------|-------|
| Framework | pytest + pytest-asyncio (`asyncio_mode = auto`) |
| Fichero de config | `pytest.ini` (raíz del repo) |
| **Convención de nombres** | **`python_functions = TEST_*`** — las funciones de test se llaman `def TEST_xxx()`, en mayúsculas. Verificado en `tests/test_reid_engine.py:46`, `tests/test_face_engine.py:31`, `tests/test_detector.py`. (`tests/test_architecture.py` usa minúsculas y se recoge igual solo porque `fnmatch` es case-insensitive en Windows — **no imitar eso**) |
| Marcador relevante | `@pytest.mark.perf` para tests que miden latencia con márgenes estrechos |
| Comando rápido | `.venv/Scripts/python.exe -m pytest tests/test_<fichero>.py -q` |
| Suite completa | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90 s; 852 passed / 15 skipped tras la Fase 37) |

### Cómo validar CADA criterio de éxito sin GPU

| # | Criterio del ROADMAP | Estrategia sin GPU | Comando |
|---|---------------------|--------------------|---------|
| 1 | GPU detectada automáticamente con log claro | `monkeypatch` de las dos sondas (`_torch_cuda_available`, `_ort_cuda_available`) a `True`/`False` y aserción sobre el `DeviceChoice` devuelto y sobre `caplog`. Cuatro combinaciones: torch sí/no × ORT sí/no. **Limpiar el `@lru_cache`** entre casos (`resolve_device.cache_clear()`) | `pytest tests/test_inference_device.py -q` |
| 2 | Los tres motores usan el proveedor adecuado | `PersonDetector`: con el `MagicMock` de `YOLO` ya existente (`tests/test_detector.py:35-39`), afirmar que `.to()` **se llamó con "cuda:0"** en modo cuda y **no se llamó en absoluto** en modo cpu. `FaceEngine`/`ReIDEngine`: `monkeypatch` de `ort.InferenceSession` / `FaceAnalysis` capturando el kwarg `providers` y, en face, el `ctx_id` de `prepare()` | `pytest tests/test_detector.py tests/test_face_engine.py tests/test_reid_engine.py -q` |
| 3 | FPS ≥3× con GPU | **NO VERIFICABLE.** Se entrega el arnés de medición (script o test `@pytest.mark.perf` con `pytest.skip` si `not cuda_available`) y la cifra queda pendiente documentada | `pytest -m perf -q` → skip |
| 4 | Sin GPU, comportamiento idéntico a la Fase 37 | **El test más importante.** (a) Con `inference_device="cpu"` y con `"auto"` sin GPU, `PersonDetector._model.to` **nunca se llama** y `predict` **no recibe** kwarg `device`. (b) `providers == ["CPUExecutionProvider"]` exacto (lista de un elemento, no `[CUDA, CPU]`). (c) `ctx_id == -1`. (d) `os.environ.get("CUDA_VISIBLE_DEVICES")` sigue siendo `None` tras construir el detector. (e) La suite completa pasa sin regresiones | `pytest tests/ -q` |
| 5 | Fallo de init de GPU → CPU + `DEGRADED_MODE` | Doble del motor que reporta `device_requested="cuda"`, `device_effective="cpu"`, `fallback_reason="..."`. Aserción de que `event_engine.degraded_mode` se llamó **una vez** con la razón real. Precedente de test: el que cubre `_on_recording_failure` | `pytest tests/test_manager.py tests/test_event_engine.py -q` |
| 6 | Batching opcional y desactivable | Sin código → sin test. Verificación **documental** en el SUMMARY de la fase con las cinco razones de Q7 y la condición de reapertura | — |

### Mapa requisito → test

| Req | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|-----|----------------|------|----------------------|----------|
| SCALE-11 | `auto` elige CUDA cuando ambas sondas dicen sí | unit | `pytest tests/test_inference_device.py -k auto_prefers_cuda -q` | ❌ Wave 0 |
| SCALE-11 | `auto` cae a CPU cuando la sonda dice no, sin lanzar | unit | `pytest tests/test_inference_device.py -k auto_falls_back -q` | ❌ Wave 0 |
| SCALE-11 | `cuda` forzado sin GPU falla ruidosamente | unit | `pytest tests/test_inference_device.py -k cuda_forced_raises -q` | ❌ Wave 0 |
| SCALE-11 | Disponibilidad **por familia** (torch sí / ORT no y viceversa) | unit | `pytest tests/test_inference_device.py -k mixed -q` | ❌ Wave 0 |
| SCALE-11 | ONNX: fallback detectado comparando `get_providers()` con lo pedido | unit | `pytest tests/test_reid_engine.py -k fallback -q` | ❌ Wave 0 |
| SCALE-11 | Face: `providers` **y** `ctx_id` coherentes (uno sin el otro = CPU) | unit | `pytest tests/test_face_engine.py -k device -q` | ❌ Wave 0 |
| SCALE-11 | El fallback emite `DEGRADED_MODE` con el motivo real | unit | `pytest tests/test_manager.py -k degraded_device -q` | ❌ Wave 0 |
| SCALE-11 | `/api/v2/cameras/{id}/health` incluye `devices` | integración | `pytest tests/test_cameras_api.py -k health -q` | ⚠️ existe el fichero, falta el caso |
| SCALE-12 | Ruta CPU: `.to()` nunca se llama | unit | `pytest tests/test_detector.py -k cpu_path_untouched -q` | ❌ Wave 0 |
| SCALE-12 | Ruta CPU: `providers` es exactamente `["CPUExecutionProvider"]` | unit | `pytest tests/test_reid_engine.py -k cpu_providers -q` | ❌ Wave 0 |
| SCALE-12 | `CUDA_VISIBLE_DEVICES` no se muta al construir en CPU | unit | `pytest tests/test_detector.py -k no_env_mutation -q` | ❌ Wave 0 |
| SCALE-12 | Cobertura 1:1 `Settings` ↔ `config_schema` con el campo nuevo | unit | `pytest tests/test_config_schema.py -q` | ✅ existe (fallará hasta añadir el `FieldDef`) |
| SCALE-12 | Sin regresión en la suite | full | `pytest tests/ -q` | ✅ existe |

### Frecuencia de muestreo

- **Por commit de tarea:** `pytest tests/test_inference_device.py tests/test_detector.py tests/test_face_engine.py tests/test_reid_engine.py -q`
- **Por merge de wave:** añadir `tests/test_config_schema.py tests/test_manager.py tests/test_cameras_api.py tests/test_architecture.py`
- **Puerta de fase:** suite completa en verde (referencia: 852 passed / 15 skipped tras la Fase 37) antes de `/gsd-verify-work`

### Wave 0 — huecos

- [ ] `tests/test_inference_device.py` — fichero nuevo; cubre SCALE-11 (sondas, resolución, extensibilidad del mapeo de providers)
- [ ] Fixture/helper compartido para limpiar el `@lru_cache` de `resolve_device` entre tests (patrón equivalente al de `get_settings.cache_clear()`; comprobar si `tests/conftest.py` ya lo hace para `Settings`)
- [ ] Dobles de `ort.InferenceSession` que devuelvan `get_providers()` controlado — necesarios porque el modelo ReID **no está en disco** y porque no hay CUDA EP para probar el camino real
- [ ] Doble de `insightface.app.FaceAnalysis` que capture `providers` y `ctx_id`
- [ ] Nada de framework nuevo: pytest + `monkeypatch` + `unittest.mock` ya cubren todo

**Riesgo de validación a declarar:** ningún test de esta fase demuestra que la GPU **funcione**. Demuestran que la *lógica de decisión, cableado y detección de fallback* es correcta. La comprobación de que la ruta CUDA produce resultados correctos y más rápidos es un **checkpoint manual pendiente**, igual que los checkpoints con cámara real de las Fases 17/18.

## Project Constraints (de CLAUDE.md)

Directivas aplicables que el plan debe cumplir:

| Directiva | Impacto en esta fase |
|-----------|----------------------|
| "No añadir dependencias sin necesidad" | Cero dependencias nuevas. Ya alineado con la decisión del usuario |
| Invariante 5: "Ningún hilo hace `await`" | Nada de lo añadido es asíncrono. `tests/test_architecture.py:58` lo protege |
| Invariante 6: "Ninguna corrutina ejecuta inferencia" | El warm-up va en el constructor (hilo de arranque), **nunca** en un endpoint. `test_architecture.py:79` protege `detect`/`embed` en corrutinas — el warm-up llama a `self._model(...)` directamente, así que **verificar que la lista `INFERENCE_CALLS` (`test_architecture.py:16-19`) no lo marque** |
| Invariante 2: "Cada worker consume del broker a su ritmo" | Razón principal para no implementar batching (Q7) |
| "Medir latencia/FPS reales antes de optimizar" | Prohíbe inventar el ≥3× y prohíbe `gpu_mem_limit`/TensorRT especulativos |
| "No crear estado global oculto" | El `@lru_cache` de `resolve_device` es caché explícita, mismo idioma que `get_settings()`. Lo que **sí** es estado global oculto y hay que evitar: `CUDA_VISIBLE_DEVICES` (Pitfall 1) |
| "Nunca exponer credenciales" | `inference_device` no es secreto; `secret=False`, `type="enum"` |
| "Preferir cambios pequeños y verificables" | Reparto sugerido: (1) selector + tests, (2) cableado YOLO, (3) cableado ONNX ×2, (4) observabilidad + `DEGRADED_MODE`, (5) config schema + arnés + documentación |
| Regla final: "cambio mínimo" | Respalda la decisión de no implementar batching y de no tocar `intra_op_num_threads` |
| Python 3.12, Windows 11, `.venv/Scripts/python.exe` | Todos los comandos verificados en ese entorno |

## State of the Art

| Enfoque antiguo | Enfoque actual | Cuándo cambió | Impacto |
|-----------------|----------------|---------------|---------|
| ORT lanzaba al pedir un provider no disponible | ORT avisa con `UserWarning` y descarta el provider en silencio | Desde ORT ~1.10; confirmado en 1.28.0 | **Invalida el patrón `try/except` para detectar fallback.** Hay que comparar `get_providers()` con lo pedido |
| `onnxruntime-gpu` con CUDA 12.x | ORT 1.27+ exige **CUDA 13.0 + cuDNN 9.x**; 1.21-1.26 usaban CUDA 12.8 | ORT 1.27 | Relevante para el trabajo diferido: instalar el `onnxruntime-gpu` equivocado da fallback silencioso a CPU, no un error `[CITED: onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html]` |
| YOLO con NMS en post-proceso CPU | YOLO26 es `end2end=True` (NMS-free) | Modelo actual del proyecto (D-03) | Elimina el post-proceso CPU que suele limitar la ganancia real al pasar a GPU. Buena noticia para el criterio 3 |

**Obsoleto / a no usar:**
- `ort.get_all_providers()` como sonda de disponibilidad — devuelve la lista teórica, incluye `CUDAExecutionProvider` incluso en un build CPU. Verificado.
- Instalar `onnxruntime` y `onnxruntime-gpu` en el mismo entorno — problema conocido de conflicto de paquetes `[ASSUMED — la documentación oficial consultada no lo menciona; relevante solo para el trabajo diferido]`.

## Assumptions Log

| # | Afirmación | Sección | Riesgo si es falsa |
|---|-----------|---------|---------------------|
| A1 | La GPU es una RTX 2070 SUPER de 8 GB con driver 591.86 | Standard Stack | Bajo — dato del brief, no re-verificado con `nvidia-smi`. Solo afecta a la planificación del trabajo diferido |
| A2 | La primera inferencia en CUDA cuesta del orden de segundos | Pitfall 3 | Medio — si fuera despreciable, el warm-up sobraría. Como el warm-up es barato y la ruta CPU ya mide 2,3× de penalización en frío, el riesgo de implementarlo de más es mínimo |
| A3 | El overhead de VRAM de los tres runtimes ronda 1-1,5 GB | Pitfall 5 | Bajo con una cámara. **Medio con N cámaras** — hay que medirlo en el checkpoint con GPU real antes de fijar un techo |
| A4 | El contexto CUDA es seguro entre hilos con el diseño actual (un modelo por cámara) | Pitfall 4 | Medio — es conocimiento general de CUDA/ORT, no verificable aquí. Si fuera falso, aparecería como corrupción o cuelgue en el checkpoint con GPU |
| A5 | CUDA 13 mantiene el soporte de Turing (SM 7.5) | Standard Stack | Medio — si fuera falso, `onnxruntime-gpu` 1.28 no serviría en esta máquina y habría que fijar ORT ≤ 1.26 (CUDA 12.8). **Verificar antes de instalar nada** |
| A6 | `onnxruntime` y `onnxruntime-gpu` conviven mal en el mismo entorno | State of the Art | Bajo — solo afecta al trabajo diferido; la doc oficial consultada no lo confirma |

## Open Questions

1. **¿Dónde reportar el dispositivo de `FaceEngine`?**
   - Lo que sabemos: `PersonRecognizer` (y su `FaceEngine`) es un servicio **compartido** entre cámaras (`factory.py:15-16`), pero el endpoint natural para exponer el dispositivo es por cámara.
   - Lo que no está claro: si duplicar el dato en cada cámara es aceptable o si conviene un sitio de proceso.
   - Recomendación: duplicarlo en `stats()` por simplicidad (N es pequeño y es informativo), **o** exponerlo en `/api/health` (`main.py:880`). Decisión de discreción del planner; documentarla en el PLAN.

2. **¿Reordenar `factory.py` o propagar el motivo por atributo?**
   - Lo que sabemos: `PersonDetector` se construye antes que su `EventEngine` (líneas 73 y 81). El reorden parece seguro.
   - Recomendación: **no reordenar** (opción (b) de Q5). Mantiene a los motores ignorantes del sistema de eventos y da una sola fuente de verdad para log + evento + `/health`.

3. **¿El warm-up también en la ruta CPU?**
   - Lo que sabemos: cuesta ~200 ms por motor en CPU y mejoraría marginalmente el arranque.
   - Lo que no está claro: si eso viola la equivalencia estricta que exige SCALE-12.
   - Recomendación: **solo en la ruta CUDA.** SCALE-12 pide comportamiento idéntico, y "idéntico" incluye la secuencia de arranque.

4. **¿Qué hace exactamente el modo `cuda` forzado cuando falla?**
   - CONTEXT.md dice "falla ruidosamente [...] para diagnóstico". No queda dicho si eso es abortar el arranque del proceso o dejar la cámara en `FAILED`.
   - Recomendación: **abortar el arranque con excepción y mensaje claro.** Es un modo de diagnóstico explícito; degradar silenciosamente en él anularía su propósito. Y ya hay precedente: los validadores de `Settings` (`config.py:47-53`) abortan el arranque ante configuración inválida.

## Sources

### Primarias (confianza ALTA — verificadas ejecutando o leyendo código instalado)

- `.venv` del proyecto: `torch 2.11.0+cpu`, `onnxruntime 1.28.0`, `ultralytics 8.4.38`, `insightface 1.0.1`
- `ultralytics/engine/model.py:81-84` (firma de `__init__`), `:528-537` (reconstrucción del predictor por cambio de device), `:845-869` (`_apply` / `.to()`)
- `ultralytics/engine/predictor.py:395-415` (`setup_model`, `select_device`, `end2end`)
- `ultralytics/utils/torch_utils.py:136` (`select_device`), `:163` (early return con `torch.device`), `:214` y `:221` (`CUDA_VISIBLE_DEVICES`), `:240` (preferencia automática de GPU)
- `insightface/app/face_analysis.py:41,48,70-74`; `insightface/model_zoo/model_zoo.py:22,40,70-71,94-96`; `insightface/model_zoo/arcface_onnx.py:61-63`; `insightface/model_zoo/retinaface.py:133-135`
- Ejecuciones locales: providers efectivos de ORT con provider ausente; `set_providers` con provider ausente; `id()` de `YOLO` antes/después de `.to()`; `CUDA_VISIBLE_DEVICES` tras `select_device('cpu')`; excepciones de `to('cuda')` y `select_device('cuda')`; latencia primera vs. caliente de YOLO26n; coste de las dos sondas
- Código del proyecto citado con fichero y línea a lo largo del documento

### Secundarias (confianza MEDIA)

- `[CITED: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html]` — matriz CUDA/cuDNN por versión de ORT. La página **no** documenta el comportamiento de fallback ni el conflicto de paquetes; eso se verificó localmente

### Terciarias (confianza BAJA — marcadas como `[ASSUMED]`)

- Coste de la primera inferencia en CUDA, overhead de VRAM, seguridad de hilos con contexto CUDA, soporte de Turing en CUDA 13, conflicto `onnxruntime` / `onnxruntime-gpu`. Todas listadas en el Assumptions Log

## Metadata

**Desglose de confianza:**
- Stack estándar: **ALTA** — no hay stack nuevo; versiones verificadas ejecutando el `.venv`
- Arquitectura y puntos de integración: **ALTA** — cada punto citado con fichero y línea del repo
- Comportamiento de las librerías: **ALTA** — leído del código fuente instalado y verificado con ejecuciones reales, no de memoria
- Pitfalls de la ruta CPU (1, 2, 6, 7, 8): **ALTA** — reproducidos localmente
- Pitfalls de la ruta GPU (3 parcial, 4, 5): **MEDIA/BAJA** — no verificables sin stack GPU; marcados en el Assumptions Log
- Recomendación sobre batching: **ALTA** — el argumento se apoya en invariantes y código del proyecto, no en suposiciones sobre hardware

**Fecha de investigación:** 2026-09-08
**Válido hasta:** ~2026-10-08 (30 días). Se invalida antes si se instala `torch` CUDA u `onnxruntime-gpu`: en ese momento hay que re-verificar el comportamiento de fallback con el CUDA EP realmente presente, que es el caso que hoy no se puede probar.
