# Phase 38: Worker de inferencia en GPU (opcional) - Context

**Gathered:** 2026-09-08
**Status:** Ready for planning
**Source:** Discusión directa con el usuario (2 preguntas de alcance, sin discuss-phase)

<domain>
## Phase Boundary

Última fase del roadmap v2.0. El objetivo es que el pipeline aproveche una GPU cuando
exista, sin degradar ni alterar la ruta CPU actual (SCALE-11, SCALE-12).

Tres piezas de código:

1. **Detección y selección de dispositivo**: un punto único que decide el dispositivo
   efectivo (CUDA o CPU) a partir de configuración explícita más sondeo del entorno, con
   log claro de qué se eligió y por qué.
2. **Cableado a los tres motores de inferencia**: YOLO (`backend/detector.py`, vía
   Ultralytics), ArcFace (`backend/perception/face/engine.py`, `insightface` +
   `onnxruntime`) y OSNet/ReID (`backend/perception/reid/engine.py`, `onnxruntime`
   directo). Hoy los tres están clavados a CPU: los dos motores ONNX pasan
   `providers=["CPUExecutionProvider"]` literal y `PersonDetector` nunca pasa `device`.
3. **Fallback y degradación**: si la inicialización en GPU falla, se cae a CPU
   automáticamente, se emite `DEGRADED_MODE` y el sistema sigue operando.

Fuera de esta fase: cualquier cambio que altere el comportamiento observable cuando no
hay GPU. La ruta CPU debe quedar byte a byte equivalente a la de la Fase 37.

</domain>

<decisions>
## Implementation Decisions

### Dependencias (decisión del usuario)
- **Esta fase NO toca `requirements.txt` ni el `.venv`.** Se implementa la lógica de
  detección, selección, cableado y fallback; la instalación real de `torch` con CUDA y
  de `onnxruntime-gpu` queda fuera de alcance.
- Consecuencia aceptada: **el criterio de éxito 3 del ROADMAP (FPS de detección ≥3×
  respecto a CPU, medido y documentado) no se puede cerrar en esta fase.** Se planifica
  el arnés de medición y se deja el número real como pendiente explícito, documentado
  en el cierre de fase y en REQUIREMENTS.md. No se inventa ni se estima la cifra.
- El entorno actual confirma la restricción: `torch 2.11.0+cpu` y
  `onnxruntime 1.28.0` con providers `['AzureExecutionProvider', 'CPUExecutionProvider']`.
  La máquina tiene una NVIDIA RTX 2070 SUPER (8 GB, driver 591.86), así que el trabajo
  es verificable más adelante sin cambiar de hardware.

### Backends soportados (decisión del usuario)
- **Solo CUDA, con fallback a CPU.** DirectML queda fuera, pese a que el criterio 1 del
  ROADMAP lo menciona: no es verificable en esta máquina y duplicaría la matriz de
  pruebas sin aportar nada comprobable.
- El selector debe quedar **extensible**: añadir `DmlExecutionProvider` u otro proveedor
  más adelante debe ser añadir una entrada, no reescribir la lógica.

### Configuración
- Un ajuste explícito en `backend/config.py` con tres valores: `auto` (default,
  detecta), `cpu` (fuerza CPU, comportamiento idéntico a Fase 37) y `cuda` (fuerza GPU
  y falla ruidosamente si no está disponible, para diagnóstico).
- El default `auto` debe comportarse exactamente como hoy en una máquina sin GPU.
- Sigue vigente la regla del proyecto: nada de credenciales ni rutas absolutas en
  configuración, y validadores en el mismo estilo que `yolo_model_path`/`reid_model_path`.

### Detección de disponibilidad
- La sonda debe ser **barata y no lanzar**: importar/consultar y devolver un booleano,
  nunca romper el arranque si falta el paquete o el driver.
- Se sondea una sola vez por proceso (el patrón `@lru_cache` de `config.py` ya es el
  idioma del proyecto), no en cada frame ni en cada construcción de motor.

### Fallback y observabilidad
- Un fallo de inicialización en GPU cae a CPU **sin abortar el arranque**, deja traza
  del motivo real (no un `except: pass`) y emite `DEGRADED_MODE` por el camino ya
  existente en el proyecto.
- El log de arranque debe decir, por motor, qué dispositivo quedó activo.
- El dispositivo efectivo debe ser observable desde fuera, en la línea de lo que ya
  expone `/api/v2/cameras/{id}/health`.

### Batching multi-cámara (criterio 6 del ROADMAP)
- Opcional y **desactivado por defecto**. Si el análisis del planner concluye que no
  aporta con un solo flujo real y que añade latencia o acoplamiento, se documenta la
  decisión de no implementarlo en vez de añadir complejidad muerta — la regla final de
  CLAUDE.md manda sobre el criterio.

### Decisiones cerradas tras 38-RESEARCH.md (2026-09-08)

Estas cuatro las abrió el research con recomendación; quedan cerradas aquí y el planner
no debe reabrirlas:

1. **Detección de fallback en onnxruntime por comparación, no por excepción.**
   ONNXRuntime 1.28 no lanza cuando falta el provider: emite `UserWarning`, lo descarta
   y sigue en CPU. La única forma fiable de saber qué quedó activo es comparar
   `session.get_providers()` con lo solicitado. Nada de `try/except` como sonda.

2. **La ruta CPU sigue sin pasar `device` en absoluto.**
   `select_device("cpu")` de Ultralytics escribe `os.environ["CUDA_VISIBLE_DEVICES"] = ""`
   a nivel de proceso, lo que cegaría también al CUDA EP de onnxruntime construido
   después. Con dispositivo efectivo CPU, `backend/detector.py` debe quedar exactamente
   como hoy (`detector.py:31`, sin `.to()`). Esto es lo que protege SCALE-12.

3. **El device se propaga a `PersonDetector` por atributo, sin reordenar `factory.py`.**
   Hoy el `PersonDetector` se construye en `factory.py:73`, antes que su `EventEngine`
   en la 81, así que en el momento del fallo de GPU todavía no hay a quién emitirle
   `DEGRADED_MODE`. Se guarda el resultado de la selección y se emite cuando el
   `EventEngine` ya existe. Reordenar el factory es más riesgo que beneficio.

4. **Warm-up solo en GPU, nunca en CPU.**
   `AdaptiveRate.observe()` siembra la EMA con la primera medida (`rate.py:81-83`), y la
   primera inferencia cuesta 203 ms frente a 89 ms en caliente; en frío la GPU hundiría
   el ritmo durante decenas de segundos. Añadir warm-up también en CPU cambiaría el
   comportamiento de la ruta por defecto y rompería SCALE-12.

5. **Modo `cuda` forzado que no puede cumplirse aborta el arranque.**
   Es un modo de diagnóstico: si el usuario pide CUDA explícitamente y no hay CUDA, el
   sistema falla ruidosamente en vez de degradar en silencio. Precedente: los
   `@field_validator` de `Settings` ya abortan el arranque ante configuración inválida.
   El fallback silencioso a CPU es exclusivo del modo `auto`.

6. **Batching multi-cámara (criterio 6 del ROADMAP): NO se implementa.**
   El research lo desaconseja con cinco razones ancladas en código (broker y modelo por
   cámara por diseño explícito de la Fase 36, invariante 2 del CLAUDE.md, `AdaptiveRate`
   independiente por cámara, y lote de tamaño 1 hoy). Se documenta la decisión y su
   condición de reapertura en el cierre de fase. El criterio se cumple por la vía de
   "opcional y desactivable": desactivado permanentemente y justificado.

7. **El campo nuevo de `Settings` debe registrarse también en `config_schema`.**
   `tests/test_config_schema.py:24-26` exige igualdad de conjuntos entre
   `Settings.model_fields` y `config_schema.all_fields()`. El `FieldDef` va con
   `type="enum"` y `enum_values=("auto","cpu","cuda")`.

8. **`insightface` necesita `providers` Y `ctx_id` a la vez.**
   Con `ctx_id < 0`, `arcface_onnx.py:61-63` y `retinaface.py:133-135` hacen
   `set_providers(['CPUExecutionProvider'])` y deshacen la elección en silencio.

### Claude's Discretion
- Dónde vive el selector de dispositivo (módulo nuevo vs. ampliación de uno existente).
- Firma exacta de la API de selección y cómo se inyecta en los tres motores.
- Estructura del arnés de benchmark y si se marca como test o como script.
- Reparto en sub-tareas del PLAN.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Alcance y requisitos
- `.planning/ROADMAP.md` § Phase 38 — goal, dependencias y los 6 criterios de éxito
- `.planning/REQUIREMENTS.md` — SCALE-11 (detección automática + fallback limpio) y
  SCALE-12 (sin GPU, comportamiento idéntico)
- `propuesta_mejora/SPEC_v2.md` § Phase 38 — ficheros afectados según el spec
- `.planning/STATE.md` — estado real de fases, decisiones y cifra vigente de la suite

### Código que se toca
- `backend/detector.py` — `PersonDetector`, construye `YOLO(model_path)` sin `device`
- `backend/perception/face/engine.py:67` — `providers=["CPUExecutionProvider"]` literal
- `backend/perception/reid/engine.py:49` — `providers=["CPUExecutionProvider"]` literal
- `backend/config.py` — `Settings` (pydantic-settings + `@lru_cache`), validadores
- `backend/pipeline/detection.py` — worker de detección
- `backend/pipeline/supervisor.py` — reinicio y modo degradado (`DEGRADED_MODE`)

### Reglas del proyecto
- `CLAUDE.md` — invariantes del pipeline (1-10), stack cerrado, criterios de diseño
- `tests/test_architecture.py` — barrera contra `await`/inferencia en el sitio equivocado
- Fase 37 (`.planning/phases/37-backends-opcionales-postgresql-redis/PLAN.md`) — patrón
  vigente de "backend opcional con default de primera clase intacto"

</canonical_refs>

<specifics>
## Specific Ideas

- El patrón de la Fase 37 es el molde exacto: una ruta alternativa opcional que se
  activa por configuración y deja la ruta por defecto intacta y de primera clase.
- La sustitución de `providers=["CPUExecutionProvider"]` por una lista calculada es el
  cambio mecánico central; el orden de la lista es el que decide el fallback en
  `onnxruntime` (proveedor preferido primero, `CPUExecutionProvider` siempre al final).
- Ultralytics acepta `device` tanto en construcción como por llamada; hay que elegir uno
  y ser coherente, teniendo en cuenta que `set_classes`/reconfiguración en caliente ya
  asume que el modelo no se recarga (ver `backend/detector.py:60-65`).
- Los tests nuevos deben pasar **sin GPU**: se prueba la lógica de selección y el
  fallback con dobles, no la inferencia acelerada real.

</specifics>

<deferred>
## Deferred Ideas

- Instalación de `torch` CUDA y `onnxruntime-gpu`, y medición real del ≥3× (criterio 3).
  Requiere decisión posterior sobre `requirements-gpu.txt` vs. `.venv` principal.
- Soporte DirectML (`DmlExecutionProvider`) para GPUs AMD/Intel.
- Batching multi-cámara en GPU si el planner concluye que no aporta hoy.
- Cuantización/TensorRT o export a engine optimizado.

</deferred>
