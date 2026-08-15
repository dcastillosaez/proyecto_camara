# Phase 25: Re-identificación de personas (ReID) — Research

**Researched:** 2026-08-13
**Domain:** Embeddings de apariencia (OSNet/ONNX) + continuidad de identidad sin cara visible
**Confidence:** HIGH (modelo, latencia e integración verificados ejecutando código real en este equipo; el umbral 0.7 sigue siendo MEDIUM/LOW)

---

<user_constraints>
## User Constraints (from 25-CONTEXT.md)

### Locked Decisions

**Contratos (de SPEC_v2.md §5.6 — locked)**

```python
class ReIDEngine:
    def embed(self, person_crop: np.ndarray) -> np.ndarray:  # 512D normalizado

class TrackGallery:
    """Mantiene continuidad de identidad cuando la cara no es visible."""
    def update(self, track_id: int, emb: np.ndarray, identity: int | None) -> None
    def resolve(self, track_id: int, emb: np.ndarray) -> tuple[int | None, float]:
        """Si un track nuevo se parece a un track reciente con identidad, la hereda."""
```

**ADR-04 (locked)**
- Modelo: `osnet_x0_25` exportado a ONNX, ~2.2M parámetros, diseñado para ReID de
  personas, CPU-friendly. Se descarta `torchreid` completo (arrastra PyTorch).
- Política: ReID se calcula 1 vez cada N frames/segundos por track, no por frame.

**Política de herencia (SPEC §5.6 — locked)**
Un track nuevo hereda identidad de un track cerrado hace **< 15 s** si la similitud
ReID es **> 0.7** **y** no hay conflicto con otro track activo que ya tenga esa
identidad. Umbral conservador deliberado (SPEC §9 Riesgo): una fusión errónea de
identidad es peor que no fusionar.

**Parámetros por defecto (locked, configurables vía `backend/config.py`)**
- `reid_inherit_window_secs = 15.0`
- `reid_similarity_threshold = 0.7`
- `reid_interval_secs = 2.0`
- `reid_inherit_identity: bool = False` (flag `REID_INHERIT_IDENTITY` — modo
  solo-observación por defecto)

**Restricciones de arquitectura (de CLAUDE.md — no negociables)**
- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- El estado compartido de tracks vive en `TrackRegistry`; no duplicar fuente de verdad
  con la que ya escribe `IdentityStateMachine`.
- Toda estructura con crecimiento potencial necesita política de expiración con test
  que la verifique.
- Cambio mínimo: no reescribir `IdentityStateMachine`; ReID es una vía de recuperación
  **adicional**, no un reemplazo de `_claim_lost`.

### Claude's Discretion

Las 3 preguntas que CONTEXT.md dejó abiertas para RESEARCH (integración,
origen del ONNX, worker) — resueltas más abajo con evidencia ejecutada.

### Deferred Ideas (OUT OF SCOPE)

- Activar `REID_INHERIT_IDENTITY=true` por defecto → cuando haya datos reales
  de falsos positivos. La fase entrega el mecanismo y el flag, no la decisión.
- Comportamiento (merodeo, carrera, aglomeración) → Fase 26.
- Multi-clase/objetos → Fase 27.
- Cualquier cambio a `TemporalVoter` / la votación facial.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Descripción (verbatim de REQUIREMENTS.md §REID) | Research Support |
|----|--------------------------------------------------|------------------|
| REID-01 | Se genera un embedding de apariencia por track mediante OSNet en ONNX | Modelo verificado: `osnet_x0_25_msmt17.onnx`, salida `(N, 512)` float32, cargado y ejecutado con `onnxruntime 1.28.0` en este Windows. Ver §Environment Availability y §Blocker resuelto. |
| REID-02 | Un track nuevo puede heredar la identidad de un track cerrado recientemente si la similitud supera el umbral y no hay conflicto con un track activo | `TrackGallery.resolve()` + reutilización de `IdentityStateMachine._claim_lost` (identity.py:161-179). Ver §Pattern 1 y §Q1. |
| REID-03 | Una persona identificada que deja de mostrar la cara conserva su identidad | Nuevo método `on_reid_result()` en la FSM que entra por la rama UNKNOWN y produce `IdentityTransition(..., emits=False)` — mismo mecanismo que ya evita el segundo `PERSON_RECOGNIZED` (identity.py:195-211). |
| REID-04 | El coste de ReID está acotado a una inferencia por track cada N segundos | `TrackGallery.needs_embedding(track_id, now)` con `reid_interval_secs`, espejo exacto de `IdentityStateMachine.needs_recognition()` (identity.py:381-404). Ver §Q4. |
</phase_requirements>

---

## Summary

La fase es viable y el riesgo técnico principal ya está **resuelto en esta sesión**, no
diferido a una puerta bloqueante: el modelo existe, se descarga, carga y ejecuta en este
equipo Windows con el `onnxruntime` que ya está en `requirements.txt`, y cumple el
criterio 1 con margen (**4,97 ms p50 de inferencia; 5,50 ms p50 de `embed()` completo
con preprocesado**, frente a los 20 ms exigidos). Pero el fichero ONNX público **tiene el
eje de batch fijado a 16**, no dinámico: usado tal cual, una sola inferencia cuesta
**84,5 ms** y falla el criterio 1. La solución verificada es reescribir el eje de batch a
dinámico con el paquete `onnx` (ya presente como dependencia transitiva de `insightface`),
lo que da un modelo **numéricamente idéntico** (`max|Δ| = 0.0`) y batch 1.

La pregunta de integración tiene una respuesta forzada por el código, no de gusto:
`IdentityStateMachine._claim_lost()` es el **único** sitio que borra la entrada
`TEMPORARILY_LOST` de `_states`. Si la herencia por apariencia se resolviera en el worker
sin pasar por la FSM, esa entrada sobreviviría y `on_tick()` (identity.py:425-449) emitiría
más tarde un `IDENTITY_LOST` espurio para una persona que en realidad nunca se perdió. Por
tanto ReID debe entrar **por la FSM**, mediante un método nuevo y aditivo
`on_reid_result()` que reutilice `_claim_lost` y que **no** vote en el `TemporalVoter`.

El worker es `RecognitionWorker`, no uno nuevo: la FSM está documentada como
*single-thread sin lock* (identity.py:130) y meterle un segundo hilo obligaría a añadir un
lock, es decir, a reescribirla — justo lo que CONTEXT prohíbe. El coste añadido es
despreciable (~11 ms/s a 2 FPS, ~1 % de un core).

**Recomendación principal:** `ReIDEngine` (ONNX batch-dinámico, degradación graciosa como
`FaceEngine`) + `TrackGallery` (dominio puro, reloj inyectado, TTL + cota dura) +
`IdentityStateMachine.on_reid_result()` aditivo + cableado en `RecognitionWorker` y
`manager.py`, con el flag `reid_inherit_identity` decidiendo **en el worker** (no en la
gallery) si la herencia se aplica o solo se registra.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Inferencia OSNet sobre crop de persona | Percepción (`backend/perception/reid/engine.py`) | — | Mismo tier y mismo patrón que `FaceEngine`; adaptador fino sobre ONNXRuntime, sin conocimiento de tracks ni reloj |
| Memoria de embeddings de tracks recientes + resolución de candidato | Dominio puro (`backend/perception/reid/gallery.py`) | — | Igual que `TemporalVoter`/`IdentityStateMachine`: sin `time`, sin hilos, sin I/O; reloj como parámetro |
| Decisión de estado de identidad (heredar o no) | Dominio puro (`backend/perception/face/identity.py`) | — | Único dueño de `_states`; `_claim_lost` ya existe y solo él sabe borrar la entrada `TEMPORARILY_LOST` |
| Ejecución periódica, selección de track y throttling | Worker hilo (`backend/pipeline/recognition.py`) | — | Es quien ya posee el ciclo de vida de la FSM tras la Fase 24 y el único escritor de identidad en `TrackRegistry` |
| Construcción/propiedad de engine y gallery | Cableado (`backend/pipeline/manager.py`) | `backend/main.py` | Fuera de la factoría del supervisor, igual que `identity_fsm` (manager.py:122-135) |
| Publicación del evento | Eventos (`backend/events/engine.py`) | — | `emit_identity` ya traduce `IdentityTransition` → `EventType`; **no requiere cambios** |
| Descarga y preparación del modelo | Build/ops (`scripts/fetch_models.py`) | — | SPEC §4.3 ya lo anticipa; el runtime no debe descargar nada |

---

## Blocker resuelto en research: el ONNX de OSNet

CONTEXT preguntaba si hacía falta una "puerta de entrada bloqueante" como la de la Fase 23.
**La puerta se ha ejecutado durante este research**, con evidencia reproducible.

### Origen real del fichero

| Fuente | URL | Estado |
|--------|-----|--------|
| `kornia/osnet` (org. Kornia AI) | `https://huggingface.co/kornia/osnet/resolve/main/osnet_x0_25_msmt17.onnx` | **Descargado, 907 169 bytes** `[VERIFIED: curl 200 + sha256]` |
| `anriha/osnet_x0_25_msmt17` (licencia MIT) | `https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/osnet_x0_25_msmt17.onnx` | **Descargado, 907 169 bytes — byte-idéntico al anterior** `[VERIFIED: sha256 coincidente]` |
| `kaiyangzhou/osnet` (autor de OSNet, licencia MIT) | `https://huggingface.co/kaiyangzhou/osnet` | Solo `.pth`/`.pyth` (PyTorch). **No publica ONNX** `[VERIFIED: HF API siblings]` |

**sha256 = `e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277`** (idéntico en las
dos fuentes). Dato de confianza extra: el repo de Kornia guarda junto al ONNX un motor
TensorRT llamado `osnet-reid-e78604f4-trt10.3.0.30-sm87.engine` — los 8 primeros hex del
sha256 del ONNX, es decir, Kornia usa este mismo fichero como su modelo ReID canónico
`[VERIFIED: listado de ficheros de kornia/osnet]`. Kornia envuelve boxmot
(`kornia/contrib/boxmot_tracker.py`) `[VERIFIED: github code search]`, y el export procede
de la cadena boxmot/torchreid.

Recomendación: usar **`kornia/osnet` como fuente primaria** (organización con nombre y
mantenimiento, no una cuenta personal) y `anriha` como espejo documentado, verificando
siempre el sha256. No usar `pip install boxmot` ni `torchreid`: ambos arrastran PyTorch,
lo que ADR-04 descarta explícitamente.

### Verificación ejecutada en este equipo

```
onnxruntime 1.28.0            (ya instalado, requirements.txt: onnxruntime>=1.19)
onnx        1.22.0            (ya instalado — Required-by: insightface)
input   'input'  [16, 3, 256, 128]  tensor(float)
output  'output' [16, 512]          tensor(float)
```

| Medición (Windows 11, CPU, `CPUExecutionProvider`) | Resultado |
|---|---|
| Inferencia con el modelo original, batch fijo 16 | p50 **84,5 ms** por llamada → **5,28 ms/crop si van los 16 llenos**, pero **84,5 ms si solo se usa 1** |
| Inferencia batch 16, `intra_op_num_threads=1` | p50 187,5 ms |
| Tras reescribir el eje batch a dinámico — **batch 1** | p50 **4,97 ms** |
| Batch 1, `intra_op_num_threads=1` (worker educado) | p50 **12,16 ms**, p95 12,82 ms |
| `embed()` completo (resize + BGR→RGB + normalize + infer + L2) sobre un crop 180×70 | p50 **5,50 ms**, p95 29,88 ms, max 53,9 ms |
| Equivalencia numérica original ↔ reescrito | `max |Δ| = 0.0` (bit-idéntico) |
| Norma L2 de la salida cruda | ~52,4 → **el modelo NO devuelve embeddings normalizados** |

**Implicaciones directas para el plan:**

1. **El eje batch fijo a 16 es un blocker real, no teórico.** `dim_value: 16`, no un
   símbolo — por eso `SessionOptions.add_free_dimension_override_by_name("batch", 1)` **no
   sirve**: solo actúa sobre dimensiones simbólicas `[VERIFIED: dim0 impreso como
   dim_value:16 + comportamiento de ORT observado]`. Sin reescritura, criterio 1 falla por
   4x.
2. La reescritura es trivial y no necesita PyTorch:
   ```python
   m = onnx.load(src)
   for t in list(m.graph.input) + list(m.graph.output):
       d = t.type.tensor_type.shape.dim[0]
       d.ClearField("dim_value")
       d.dim_param = "batch"
   onnx.save(m, dst)
   ```
3. `onnx` está hoy en el venv **solo como transitiva de `insightface`**. Si el proyecto la
   usa directamente, debe declararse: **añadir `onnx>=1.16` a `requirements.txt`**
   (regla de dependencias explícitas). Hacer la reescritura en `scripts/fetch_models.py`
   (una vez, offline) evita que `onnx` sea dependencia de *runtime*.
4. `ReIDEngine` debe **normalizar L2 la salida** para cumplir "512D normalizado" del
   contrato SPEC — igual que `FaceEngine.embed` hace `raw / np.linalg.norm(raw)`
   (engine.py:106).
5. **Criterio 1 debe medirse como mediana (p50) con warmup**, no como máximo: el p95 de
   `embed()` sube a ~30 ms por jitter del planificador de Windows en una máquina
   compartida. Un test que asserte "< 20 ms" sobre una sola llamada será flaky.

**No hace falta una puerta bloqueante separada**, pero el plan **sí** debe incluir una tarea
de Wave 0 que reproduzca esto *dentro del repo* (`scripts/fetch_models.py` + smoke test de
`ReIDEngine`), porque el spike se ejecutó en un scratchpad, no en el árbol del proyecto.

---

## Discrepancias entre SPEC/ADR y la realidad medida

Esto es lo que el planner debe corregir respecto a los documentos de entrada.

| # | Documento dice | Realidad verificada | Acción para el plan |
|---|----------------|---------------------|---------------------|
| D-1 | ADR-04: "`osnet_x0_25`, **~2,2M parámetros**" | 907 KB en float32 ⇒ **~0,22M parámetros**. Los 2,2M son los de `osnet_x1_0`, no del `x0_25`. `[VERIFIED: tamaño del fichero]` | No cambia la decisión (el modelo elegido es aún más barato de lo que ADR-04 creía). Corregir la cifra si se reescribe el ADR; no bloquea. |
| D-2 | SPEC §4.3: "`osnet_x0_25_msmt17.onnx` — **~9 MB**" | **907 KB** `[VERIFIED]` | Ídem. La cifra de 9 MB corresponde a `osnet_x1_0`. |
| D-3 | SPEC §5.6: `resolve(self, track_id, emb) -> tuple[int\|None, float]` | Sin `now` no puede aplicar la ventana de 15 s, y sin el set de identidades activas no puede detectar el conflicto exigido por REID-02. | **Ampliar la firma**: `resolve(track_id, emb, now, active_identities)`. Precedente exacto de la Fase 24: SPEC §5.5 mostraba `on_face_result(track_id, person_id, score)` y el código real es `on_face_result(track_id, person_id, score, now)` (identity.py:181-183) por la regla de reloj inyectado. |
| D-4 | SPEC §5.6: `update(self, track_id, emb, identity) -> None` | Necesita `now` para el TTL. | `update(track_id, emb, identity, now)`. Mismo motivo. |
| D-5 | SPEC §9 Phase 25: "Modificar: `backend/pipeline/tracking.py`" | `TrackRegistry` **ya tiene todo lo necesario**: `frame_ids()` (tracking.py:113), `set_identity()` (117), `set_identity_state()` (124), `snapshot()` (91). Ningún campo nuevo hace falta para REID-01..04. | **No tocar `tracking.py`** salvo que se decida exponer `reid_similarity` para la UI del bloque C — eso no lo pide ningún requisito de esta fase. |
| D-6 | SPEC §9 Phase 25: "Modificar: `backend/events/engine.py`" | `emit_identity` (engine.py:180-217) y `_identity_event_type` (164-178) ya cubren el caso: una transición `→ CONFIRMED` con `emits=False` no publica nada, que es exactamente lo que la herencia por ReID necesita. | **No tocar `events/engine.py`.** |
| D-7 | SPEC §9 no lista `identity.py`, `recognition.py`, `manager.py`, `config.py`, `main.py` | Los cinco necesitan cambios (ver §Ficheros reales). | La Fase 24 encontró la misma clase de omisión (`24-06-SUMMARY.md`). Usar la lista de abajo, no la de SPEC §9. |
| D-8 | CONTEXT: "no reescribir `IdentityStateMachine`" | La integración correcta exige **añadir un método** a `IdentityStateMachine`. | Añadir `on_reid_result()` es *aditivo*, no una reescritura: no toca `on_face_result`, ni `_claim_lost`, ni el `TemporalVoter`. Justificación técnica en §Q1 (el bug del `IDENTITY_LOST` espurio). Marcar como desviación consciente y justificada. |

---

## Preguntas de CONTEXT resueltas

### Q1 — ¿Dónde se integra `TrackGallery.resolve()` con `IdentityStateMachine`?

**Respuesta: dentro de la FSM, mediante un método público nuevo `on_reid_result()` que
reutiliza `_claim_lost`. El worker calcula el embedding y resuelve el candidato; la FSM
decide y transiciona.**

Trazado del código real:

1. `_claim_lost(person_id, now)` (identity.py:161-179) recorre `_states`, encuentra la
   entrada `TEMPORARILY_LOST` con ese `person_id` dentro de `lost_ttl`, y hace
   **`del self._states[tid]` + `self._voter.reset(tid)`**. Está indexado por `person_id`,
   que es exactamente lo que `TrackGallery.resolve()` devuelve.
2. `on_tick(now)` (identity.py:425-449) recorre `_states` y, para toda entrada
   `TEMPORARILY_LOST` con `now - lost_at > lost_ttl`, emite
   `IdentityTransition(TEMPORARILY_LOST → UNKNOWN, emits=True)`.
3. `_identity_event_type` (events/engine.py:170-178) traduce
   `TEMPORARILY_LOST → UNKNOWN` a **`EventType.IDENTITY_LOST`**.

**Consecuencia decisiva:** si la herencia por apariencia se hiciera solo en el worker
(`registry.set_identity(new_tid, pid, name)` sin tocar la FSM), la entrada vieja seguiría
en `_states`, y 30 s después `on_tick` emitiría un `IDENTITY_LOST` de una persona que el
sistema tiene delante y ya reetiquetada. Ese evento va marcado `severity` por catálogo y
alimenta `rules.yaml`. Sólo `_claim_lost` limpia esa entrada, y es privado. **La vía del
worker está descartada por el código, no por preferencia estética.**

Forma recomendada (aditiva, sin tocar nada existente):

```python
def on_reid_result(
    self, track_id: int, person_id: int | None, similarity: float, now: float
) -> IdentityTransition | None:
    """Segunda via de recuperacion de identidad: apariencia, sin cara visible (Fase 25).

    NO vota en el TemporalVoter: la votacion es facial y la Fase 25 no la toca.
    Solo actua sobre tracks sin evidencia facial propia; un track CANDIDATE con
    votacion en curso o CONFIRMED nunca es secuestrado por apariencia.
    """
    if person_id is None:
        return None
    st = self._states.get(track_id)
    if st is not None and st.state is not IdentityState.UNKNOWN:
        return None                       # la cara manda; ReID no interfiere
    if st is not None and self._voter.matched_votes(track_id) > 0:
        return None                       # ya hay evidencia facial de este track
    if not self._claim_lost(person_id, now):
        return None                       # nadie perdido con esa identidad
    st = self._states.setdefault(track_id, _TrackIdentity())
    st.state = IdentityState.CONFIRMED
    st.person_id = person_id
    st.confidence = similarity
    st.failed_revalidations = 0
    st.last_revalidation_at = now
    st.last_face_at = now                 # evita que on_tick lo purgue por rancio
    st.recognized_emitted = True
    return IdentityTransition(
        track_id, IdentityState.UNKNOWN, IdentityState.CONFIRMED,
        person_id=person_id, confidence=similarity,
        votes=0, window=self._voter.window,
        emits=False,                      # misma visita: no hay 2o PERSON_RECOGNIZED
    )
```

`emits=False` es lo que da el criterio 3 ("conserva su `person_id` **sin `UNKNOWN_PERSON`
intermedio**"): copia exacta del comportamiento de la rama facial `_claim_lost`
(identity.py:201-211).

⚠️ **Ojo con `st.last_face_at`**: si no se refresca, `on_tick` puede borrar el estado por
rancio (`now - st.last_face_at > stale_ttl`, identity.py:454). Y `needs_recognition()`
(identity.py:404) usa el mismo campo: fijarlo a `now` hace que el track recién heredado no
pida inferencia facial inmediata, lo cual es correcto — pero significa que un track heredado
por apariencia **no revalidará con cara hasta `revalidate_after` (120 s)**. Es el
comportamiento deseado (barato) pero debe quedar escrito en el plan y cubierto por un test,
porque es la palanca que decide cuánto tiempo puede vivir una herencia errónea sin
corregirse.

### Q2 — ¿De dónde sale `osnet_x0_25.onnx`?

Resuelto arriba (§Blocker resuelto). Resumen: **Hugging Face `kornia/osnet`**, 907 169
bytes, sha256 `e78604f4...`, MIT (según el espejo `anriha`), descargado y ejecutado en este
equipo. Requiere reescritura del eje batch. `scripts/fetch_models.py` (que SPEC §4.3 ya
anticipa y que **aún no existe** en `scripts/`) debe: descargar → verificar sha256 →
reescribir batch → guardar en `models/reid/` → ser idempotente.

`models/` **no está en `.gitignore`** hoy; SPEC §4.3 dice que debe estarlo. Añadirlo.

### Q3 — ¿Qué worker ejecuta la inferencia ReID?

**Respuesta: `RecognitionWorker`. No crear un worker nuevo.**

Evidencia:

| Argumento | Fuente en el código |
|---|---|
| La FSM es explícitamente single-thread sin lock | `identity.py:130` — *"Un solo hilo (RecognitionWorker._loop), por eso no hay lock."* Un segundo hilo escribiendo en `_states` obligaría a añadir un lock ⇒ reescritura prohibida por CONTEXT. |
| `RecognitionWorker` es ya el único escritor de identidad en el registry | `tracking.py:41-44` y `recognition.py:10-13`. Un worker ReID escribiendo `set_identity` rompería esa regla explícita. |
| Presupuesto de CPU sobrado | Worker fijo a 2 FPS (`manager.py:141-142`, `AdaptiveRate(2.0, 2.0, 2.0)`). Una inferencia ReID de ~5,5 ms por tick ⇒ **~11 ms/s ≈ 1,1 % de un core**. Cara: 15-40 ms (`STATE.md`). |
| Coste de un worker nuevo | Nueva suscripción al `FrameBroker` (1 slot más de fan-out), nuevo hilo, nueva entrada en `WorkerSupervisor`, nueva rama de reinicio en `manager.py`. Todo para 1 % de un core. |

**Matiz importante:** la inferencia ReID **no** debe pasar por `_next_candidate()`. Ese
método filtra por `needs_recognition()` (recognition.py:200), y el caso que ReID tiene que
cubrir — persona de espaldas, `TEMPORARILY_LOST`, o `UNKNOWN` en backoff de 120 s — es
precisamente donde `needs_recognition()` puede decir *no*. ReID necesita su propia selección
de candidato, con su propio gate (§Q4).

**Igualmente importante:** **no llamar a `self._rate.observe(reid_latency)`**. Ese
`AdaptiveRate` está fijado (`min=max=2.0` ⇒ `_steps` de un solo escalón, `rate.py:38`), así
que no cambiaría el FPS, pero sí contaminaría `avg_latency` en `stats` (`rate.py:98-104`),
que se publica en `/api/v2/cameras/{id}/health` vía `manager.py:261`. Instrumentar solo con
`_metrics.inference_latency_seconds.labels(stage="reid")` — la etiqueta ya está prevista en
el catálogo (`observability/metrics.py:79-82`) y `reid_fps` ya existe como gauge
(`metrics.py:76-78`).

### Q4 — Throttling: "máximo 1 inferencia ReID cada 2 s por track"

Mecanismos de throttling que ya existen en el módulo, y por qué ninguno sirve tal cual:

| Mecanismo | Granularidad | ¿Sirve? |
|---|---|---|
| `AdaptiveRate.should_process(now)` (`rate.py:57-64`) | Global del worker (2 FPS) | No — es por worker, no por track |
| `IdentityStateMachine.needs_recognition(tid, now)` (`identity.py:381-404`) | Por track, pero basada en `last_face_at`/`revalidate_after` (facial) | No — reutilizarla mezclaría dos relojes distintos en el mismo campo |
| `_min_track_age` (`recognition.py:64`, default 0.5 s) | Por track, pero es un mínimo de edad, no un intervalo | Parcial — sí conviene reutilizarlo como filtro previo |

**Recomendación:** poner el gate **en `TrackGallery`**, no en la FSM ni en el worker:

```python
def needs_embedding(self, track_id: int, now: float) -> bool:
    """Espejo exacto de IdentityStateMachine.needs_recognition (FACE-11): criterio 5."""
    e = self._entries.get(track_id)
    return e is None or (now - e.last_embedded_at) >= self._interval
```

Razones: (a) el timestamp por track vive donde ya vive el dato por track — cero fuentes de
verdad nuevas; (b) misma forma y misma convención de reloj inyectado que
`needs_recognition()`, así que el revisor no tiene que aprender un patrón nuevo; (c) el
criterio 5 se puede testear en aislamiento sobre la gallery, sin hilos, y además end-to-end
sobre el worker contando llamadas al engine mockeado — igual que
`TEST_inference_budget_drops_on_unconfirmed_track` mide el criterio 6 de la Fase 24
(`test_recognition_worker.py:329-358`).

**Cota agregada:** el worker debe elegir **como mucho un track por tick** para ReID (mismo
`min(tracks, key=first_seen)` de `_next_candidate`, recognition.py:203). A 2 FPS de tick y
`reid_interval_secs=2.0`, eso sostiene hasta **4 tracks concurrentes** a su ritmo pleno;
con más tracks, el intervalo efectivo por track se degrada por encima de 2 s — degradación
segura (menos coste, no más), pero debe documentarse en el plan.

### Q5 — Cómo se testea un `*Engine` de ONNXRuntime sin cámara ni modelo real

El repo tiene **dos** patrones vivos y hay que usar los dos, cada uno en su sitio:

| Patrón | Ejemplo real | Cuándo usarlo aquí |
|---|---|---|
| **Modelo real, imagen real del propio paquete** | `tests/test_face_engine.py` construye `FaceEngine()` de verdad y usa `skimage.data.astronaut()` como única fixture facial, "fetched at test time rather than stored as a repo asset" (test_face_engine.py:1-29) | `tests/test_reid_engine.py`: shape 512D, norma L2 = 1, latencia p50 < 20 ms (criterio 1) |
| **Motor mockeado con `MagicMock`** | `tests/test_recognition_worker.py:85-87` — `recognizer = MagicMock(); recognizer.available = True; recognizer.process_crop_scored.return_value = _face(...)` | Todo `tests/test_track_gallery.py` y todos los tests de worker/FSM: **vectores sintéticos, nunca imágenes** |
| **Degradación graciosa** | `test_face_engine.py:64-75` monkeypatchea `FaceAnalysis` para que reviente y comprueba `available is False` y que nada lanza | `TEST_reid_engine_unavailable_degrades_gracefully`: fichero ONNX ausente ⇒ `available is False`, `embed()` devuelve `None` |

⚠️ **Trampa medida, crítica para los tests:** con entradas de ruido aleatorio, el coseno
entre dos embeddings **independientes** sale **0,991** — el modelo colapsa fuera de
distribución. Un test de `TrackGallery` alimentado con crops de `np.random` "demostraría"
que todo se parece a todo y no probaría nada. Por eso **`test_track_gallery.py` debe usar
vectores 512D construidos a mano** (p. ej. `e_a = normalize(np.eye(512)[0] + 0.05*ruido)`),
donde el coseno es controlable y el umbral 0.7 es una frontera real.

Para CI: si `models/reid/*.onnx` no está presente, `tests/test_reid_engine.py` debe hacer
`pytest.skip`, no fallar. Precedente relevante: `test_face_engine.py` **no** hace skip
porque `insightface` autodescarga; aquí no hay autodescarga, así que el skip es necesario y
la nota del cierre de la Fase 24 sobre el desajuste del CI Linux (`python_functions =
TEST_*` en `pytest.ini`) aplica igual.

### Q6 — Política de expiración de `TrackGallery`

Aritmética de memoria: 512 × float32 = **2 KB por entrada** (numpy por defecto usaría
float64 = 4 KB ⇒ **forzar `astype(np.float32)`**). Una entrada por `track_id`, y ByteTrack
nunca reutiliza ids (`identity.py:104-105`, `identity.py:163-165`) ⇒ crecimiento sin cota si
no se poda.

Doble guarda, calcada de la que ya usa la FSM (`lost_ttl` + `stale_ttl` en
`on_tick`, identity.py:426-457):

1. **TTL por tiempo:** `prune(now)` borra entradas con
   `now - last_seen > reid_inherit_window_secs` (15 s). Un track visible refresca
   `last_seen` en cada `update()` (≤ 2 s), así que nunca se cae estando en pantalla; si se
   cayera por competencia con otros tracks, el único efecto es que pierde su sitio en la
   galería y se vuelve a añadir. Sin daño.
2. **Cota dura:** `max_entries` (sugerido **256**, LRU por `last_seen`) como "seguro de
   vida" para el caso en que nadie llame a `prune()` a tiempo — exactamente el razonamiento
   del comentario de `identity.py:450-453`.

Techo de memoria: 256 × 2 KB = **512 KB**. Con 15 s de ventana y una escena realista de
esta cámara, la ocupación esperada es de unidades de entradas.

Test obligatorio en `tests/test_memory_bounds.py`, con la forma exacta de
`TEST_temporal_voter_bounded` (test_memory_bounds.py:95-100): bucle de 10 000 track_ids,
`assert len(gallery._entries) <= 256`.

**Dónde se llama a `prune()`:** en `RecognitionWorker._sync_identity()`
(recognition.py:220-238), que ya es el punto de mantenimiento periódico de la FSM y ya
recibe `now`. No inventar un segundo bucle de mantenimiento.

### Q7 — `REID_INHERIT_IDENTITY=false` (modo solo-observación)

**El flag vive en el worker, no en `TrackGallery`.**

`TrackGallery.resolve()` calcula **siempre** el candidato real y devuelve
`(person_id, similarity)`. El worker decide:

```python
pid, sim = self._gallery.resolve(tid, emb, now, active_identities)
if pid is not None:
    self._reid_matches += 1
    logger.info("ReID: track %d -> person %d (sim %.3f, inherit=%s)",
                tid, pid, sim, self._reid_inherit)
    if self._reid_inherit:
        t = self._fsm.on_reid_result(tid, pid, sim, now)
        ...
```

Por qué así y no con el flag dentro de la gallery:

- Si `resolve()` devolviera `(None, sim)` en modo observación, **se pierde justo el dato que
  se quiere auditar** (qué identidad se habría heredado). El propósito del modo es medir la
  tasa de falsos positivos.
- La gallery se queda como dominio puro sin ramas de política de producto — misma disciplina
  que `TemporalVoter`/`IdentityStateMachine`, que no conocen `Event` ni configuración.
- El modo observación recorre **exactamente el mismo camino** hasta el punto de decisión
  (engine → gallery → candidato), con un solo `if` de diferencia. Eso es lo que hace la
  auditoría creíble.

**Canal de auditoría sin endpoints nuevos:** añadir contadores a
`RecognitionWorker.stats` (recognition.py:101-108) — `reid_inferences`, `reid_matches`,
`reid_inherited`, `reid_conflicts` — que ya salen por `manager.py:261` →
`/api/v2/cameras/{id}/health`. Para el criterio 4 ("tasa de falsos positivos documentada"),
loguear cada match con `track_id`, `person_id` y `similarity` a nivel INFO.

---

## Standard Stack

### Core

| Librería | Versión | Propósito | Por qué es el estándar |
|----------|---------|-----------|------------------------|
| `onnxruntime` | **1.28.0 instalada** (requirements: `>=1.19`) | Runtime CPU de OSNet | Ya en el proyecto desde la Fase 23; ADR-04 y SPEC §4.3 lo dan por el runtime de OSNet. Verificado cargando este modelo `[VERIFIED: ejecución local]` |
| `onnx` | **1.22.0 instalada** (transitiva de `insightface`) | Reescritura del eje batch fijo | Única forma sin PyTorch de convertir el export de batch 16 a batch dinámico `[VERIFIED: ejecución local]` |
| `numpy` | ya presente | Embeddings, coseno | ADR-03 ya fija numpy + `np.dot` para similitud, sin base vectorial |
| `opencv-python` | ya presente | `cv2.resize` + `cvtColor` del preprocesado | Ya es el estándar del repo para imagen |

**No añadir:** `torch`, `torchreid`, `boxmot`, `kornia`, `faiss`, `hnswlib`. ADR-04 descarta
PyTorch explícitamente; ADR-03 descarta bases vectoriales por debajo de 20 000 identidades.

### Instalación

```bash
# Único cambio en requirements.txt (si la reescritura del batch vive en el repo):
onnx>=1.16
```

**Verificación de versión ejecutada:**
```
onnxruntime 1.28.0   [VERIFIED: import en .venv del proyecto]
onnx        1.22.0   [VERIFIED: pip show onnx -> Required-by: insightface]
```

### Alternativas consideradas

| En vez de | Se podría usar | Trade-off |
|---|---|---|
| Reescribir el batch con `onnx` | Usar el modelo tal cual con batch 16 relleno | 84,5 ms/crop ⇒ **falla el criterio 1** `[VERIFIED]` |
| Reescribir el batch con `onnx` | `add_free_dimension_override_by_name` | **No aplica**: el eje es `dim_value: 16` (literal), no simbólico `[VERIFIED]` |
| `osnet_x0_25_msmt17` | `person_reid_youtu` de OpenCV Zoo (`opencv/person_reid_youtureid`, Apache-2.0) | Fuente aún más reputada y también 512D, pero **desvía de ADR-04**. Guardar como plan B si el ONNX de OSNet desapareciera de HF. |
| `osnet_x0_25_msmt17` | `osnet_x1_0` (el de los ~2,2M params que ADR-04 describe) | 10x más grande y más lento; el `x0_25` ya cumple el criterio 1 con margen. Mantener `x0_25`. |

---

## Architecture Patterns

### Diagrama de flujo (dentro de `RecognitionWorker._loop`, un solo hilo)

```
                 FrameBroker.subscribe("recognition")   [ya existe]
                              │  frame (latest-frame, sin cola)
                              ▼
                   ┌──────────────────────┐
                   │ _maybe_prune(now)    │  (existente)
                   │ _sync_identity(now)  │  (existente) ── + gallery.prune(now)
                   └──────────┬───────────┘
                              ▼
                   rate.should_process(now)?   2 FPS fijo
                       no ──► siguiente frame
                       │ sí
        ┌──────────────┴───────────────────────────────┐
        ▼                                              ▼
  VÍA FACIAL (Fase 24, intacta)               VÍA APARIENCIA (Fase 25, nueva)
  _next_candidate(now)                        _next_reid_candidate(now)
    filtro: fsm.needs_recognition()             filtro: gallery.needs_embedding()
        │                                            │  + edad >= min_track_age
        ▼                                            ▼
  recognizer.process_crop_scored(crop, tid)    ReIDEngine.embed(person_crop)  ~5,5 ms
        │  (person_id, score)                        │  512D L2-normalizado
        ▼                                            ▼
  fsm.on_face_result(tid,pid,score,now)        gallery.update(tid, emb,
        │                                             fsm.identity_of(tid)[0], now)
        │                                            │
        │                                            ▼
        │                                      gallery.resolve(tid, emb, now,
        │                                                      active_identities)
        │                                            │  (person_id|None, sim)
        │                                            ▼
        │                                      reid_inherit_identity?
        │                                       no ──► log + contador (auditoría)
        │                                       │ sí
        │                                       ▼
        │                                 fsm.on_reid_result(tid,pid,sim,now)
        │                                       │  reutiliza _claim_lost()
        └───────────────┬───────────────────────┘
                        ▼  IdentityTransition | None
          registry.set_identity_state() / set_identity()      [existente]
                        ▼
          event_engine.emit_identity(t, ...)                  [existente, sin cambios]
                        │  emits=False en herencia ⇒ 0 eventos nuevos
                        ▼
                 EventBus ──► WebSocket / SQLite
```

### Estructura de ficheros

```
backend/perception/reid/
├── __init__.py        # nuevo (el paquete face/ tiene el suyo)
├── engine.py          # ReIDEngine — adaptador ONNXRuntime, patrón FaceEngine
└── gallery.py         # TrackGallery — dominio puro, reloj inyectado
scripts/
└── fetch_models.py    # nuevo: descarga + sha256 + reescritura de batch, idempotente
models/reid/           # nuevo, gitignored
└── osnet_x0_25_msmt17_dyn.onnx
```

### Pattern 1 — `ReIDEngine`: adaptador fino con degradación graciosa

**Qué:** copiar literalmente el contrato de `FaceEngine` (perception/face/engine.py):
`available` como propiedad, `try/except` en `__init__` con `logger.exception`, y métodos
que devuelven `None`/`[]` en vez de lanzar cuando el motor no está.

**Cuándo:** siempre en esta capa. Es lo que permite que el sistema arranque sin
`models/reid/` presente.

```python
# Fuente: patrón de backend/perception/face/engine.py:59-106 (verificado en el repo)
class ReIDEngine:
    """Embeddings de apariencia 512D con osnet_x0_25 (MSMT17) sobre ONNXRuntime CPU.

    Degrada como FaceEngine: sin modelo, available=False y embed() devuelve None.
    """

    INPUT_HW = (256, 128)                                   # H, W del export ONNX
    _MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(3, 1, 1)
    _STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(3, 1, 1)

    def __init__(self, model_path: str, intra_op_threads: int = 1) -> None:
        self._available = False
        self._sess = None
        try:
            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # 1 hilo: el worker comparte CPU con YOLO. Medido: 12,2 ms p50 vs
            # 5,0 ms sin limite -- sigue por debajo de los 20 ms del criterio 1
            # y no le roba cores al DetectionWorker.
            so.intra_op_num_threads = intra_op_threads
            so.inter_op_num_threads = intra_op_threads
            self._sess = ort.InferenceSession(
                model_path, sess_options=so, providers=["CPUExecutionProvider"]
            )
            self._in = self._sess.get_inputs()[0].name
            self._out = self._sess.get_outputs()[0].name
            batch_dim = self._sess.get_inputs()[0].shape[0]
            if isinstance(batch_dim, int) and batch_dim != 1:
                # El export publico viene con batch FIJO 16: una inferencia
                # suelta costaria 84 ms en vez de 5. scripts/fetch_models.py
                # reescribe ese eje; si no se hizo, mejor deshabilitar que
                # arrastrar 84 ms por track cada 2 s.
                logger.error("ReIDEngine: modelo con batch fijo %s — ejecutar "
                             "scripts/fetch_models.py", batch_dim)
                return
            self._available = True
        except Exception:
            logger.exception("ReIDEngine: fallo al cargar %s", model_path)

    @property
    def available(self) -> bool:
        return self._available

    def embed(self, person_crop: np.ndarray) -> np.ndarray | None:
        """512D L2-normalizado. None si el motor no esta o el crop es vacio."""
        if not self._available or person_crop is None or person_crop.size == 0:
            return None
        h, w = self.INPUT_HW
        x = cv2.resize(person_crop, (w, h), interpolation=cv2.INTER_LINEAR)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = (np.transpose(x, (2, 0, 1)) - self._MEAN) / self._STD
        raw = self._sess.run([self._out], {self._in: x[None]})[0][0]
        # El modelo NO normaliza: norma cruda medida ~52. SPEC §5.6 exige 512D
        # normalizado, y el coseno de TrackGallery lo da por hecho.
        return (raw / np.linalg.norm(raw)).astype(np.float32)
```

Preprocesado **verificado contra la implementación de referencia de boxmot**
(`boxmot/reid/backends/base_backend.py:49-50, 174-201` y
`boxmot/reid/core/preprocessing.py:11-19`): `cv2.resize` a `(W=128, H=256)` con
`INTER_LINEAR`, `BGR2RGB`, `/255.0`, media `(0.485, 0.456, 0.406)`, desviación
`(0.229, 0.224, 0.225)`, y L2-normalización de la salida `[VERIFIED: código fuente de
boxmot vía gh api]`.

### Pattern 2 — `TrackGallery`: dominio puro con reloj inyectado

**Qué:** ni `import time`, ni hilos, ni I/O, ni `Event`. Todos los métodos que dependen del
reloj reciben `now: float` monotónico. Es la regla explícita de
`backend/perception/face/identity.py:1-12`.

```python
# Fuente: patrón de backend/perception/face/identity.py (verificado en el repo)
@dataclass
class _GalleryEntry:
    emb: np.ndarray                  # float32, 512D, L2-normalizado
    person_id: int | None
    last_seen: float
    last_embedded_at: float


class TrackGallery:
    """Continuidad de identidad por apariencia (SPEC_v2.md §5.6, REID-02/03/04).

    Dominio puro: sin reloj propio, sin hilos, sin I/O. Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock — igual que IdentityStateMachine.
    """

    def __init__(self, inherit_window: float = 15.0, similarity_threshold: float = 0.7,
                 interval: float = 2.0, max_entries: int = 256) -> None: ...

    def needs_embedding(self, track_id: int, now: float) -> bool: ...
    def update(self, track_id, emb, identity, now) -> None: ...
    def resolve(self, track_id, emb, now, active_identities: set[int]
                ) -> tuple[int | None, float]: ...
    def prune(self, now: float, frame_ids: set[int]) -> None: ...
```

Reglas de `resolve()` (las cuatro condiciones de REID-02, en este orden):

1. Candidatos = entradas con `person_id is not None`, `tid != track_id`,
   **`tid not in frame_ids`** (track cerrado, no uno que está delante ahora mismo).
2. Frescura: `now - last_seen <= inherit_window` (15 s).
3. Similitud: `float(emb @ e.emb)` — coseno directo, ambos ya normalizados (ADR-03: `np.dot`,
   sin base vectorial). Se toma el máximo.
4. **Conflicto:** si `person_id in active_identities` (identidades que la FSM tiene ahora
   mismo en `CONFIRMED` sobre tracks visibles) ⇒ devolver `(None, sim)`. Esto es lo que
   impide fusionar dos personas cuando la "perdida" en realidad sigue en pantalla.

`active_identities` sale del worker: recorrer `registry.frame_ids()` y quedarse con
`fsm.identity_of(tid)[0]` no nulo (identity.py:154-159 devuelve identidad solo si
`CONFIRMED` — exactamente la semántica que hace falta).

### Anti-patrones a evitar

- **Meter el resultado de ReID en `on_face_result()`.** Ese método llama a
  `self._voter.vote(track_id, person_id, score)` (identity.py:186): un voto de apariencia
  contaminaría la votación facial y rompería la restricción de CONTEXT y los parámetros
  medidos de FACE-07.
- **Resolver la herencia solo en el worker sin pasar por la FSM.** Deja huérfana la entrada
  `TEMPORARILY_LOST` y produce un `IDENTITY_LOST` espurio 30 s después (§Q1).
- **Un worker ReID separado.** Obliga a poner un lock en `IdentityStateMachine` (§Q3).
- **Umbral 0.7 aplicado sobre el coseno de embeddings *sin normalizar*.** El modelo devuelve
  norma ~52; sin normalizar, el "coseno" no está en [-1,1] y el umbral no significa nada.
- **Guardar los embeddings como float64.** Duplica la memoria de la galería por nada.
- **Persistir `reid_embedding` en la tabla `tracks`.** SPEC §7 lo contempla en el esquema,
  pero ningún requisito REID-01..04 lo pide, y `tracks` ni siquiera se escribe hoy desde el
  pipeline. Fuera de alcance.

---

## Don't Hand-Roll

| Problema | No construyas | Usa en su lugar | Por qué |
|---|---|---|---|
| Herencia de identidad tras perder el track | Un mapa propio `person_id → track_id` en el worker | `IdentityStateMachine._claim_lost()` (identity.py:161-179) | Es el único que borra la entrada `TEMPORARILY_LOST` y evita el `IDENTITY_LOST` espurio; duplicarlo crea dos fuentes de verdad sobre `_states` |
| Idempotencia del evento de reconocimiento | Un flag "ya emití" en el worker | `IdentityTransition.emits=False` + `emit_identity` (events/engine.py:196-197) | La guarda ya vive en la FSM y está testeada por FACE-09 |
| Detección de "el track desapareció" | Comparar `last_seen` a mano | `TrackRegistry.frame_ids()` (tracking.py:113) | `active_ids()` tiene TTL de 30 s; usarlo fue el bug D-05 que costó un plan entero en la Fase 24 |
| Batching / batch dinámico del ONNX | Un pool de sesiones o padding manual a 16 | Reescribir el eje con `onnx` en `fetch_models.py` | Verificado bit-idéntico y 17x más rápido para batch 1 |
| Similitud vectorial | Distancia euclídea a mano, kd-tree, FAISS | `emb_a @ emb_b` con vectores normalizados | ADR-03: con N pequeño el producto escalar es < 1 ms; FAISS/hnswlib no entran hasta N > 20 000 |
| Preprocesado del crop | Inventar el resize/normalización | Los valores exactos de boxmot (§Pattern 1) | Usar otra normalización degrada silenciosamente la calidad de los embeddings: no falla, solo empeora |
| Descarga del modelo en runtime | `urllib` dentro de `ReIDEngine.__init__` | `scripts/fetch_models.py` idempotente (SPEC §4.3) | Un arranque no debe depender de la red; el precedente de `insightface` (autodescarga) es la excepción, no la regla |
| Ritmo de inferencia | Un contador de frames | `TrackGallery.needs_embedding(tid, now)` + `AdaptiveRate` existente | El repo ya decidió "por tiempo transcurrido, determinista y testeable con reloj simulado" (rate.py:16-18) |

**Idea clave:** casi todo lo que esta fase necesita ya existe y está testeado; el trabajo
real es un motor ONNX de ~80 líneas, una galería de ~90 y **un método** en la FSM. Cualquier
plan que sea mucho más grande que eso está reimplementando la Fase 24.

---

## Common Pitfalls

### Pitfall 1 — El eje batch fijo a 16 (el que se lleva la fase por delante)
**Qué falla:** `ReIDEngine.embed()` lanza `InvalidArgument: Got: 1 Expected: 16`; si alguien
"lo arregla" rellenando a 16, la latencia pasa de 5 a 84 ms y el criterio 1 falla por 4x.
**Por qué pasa:** el export público fija `dim_value: 16` en entrada y salida.
**Cómo evitarlo:** reescritura en `fetch_models.py` + guarda en `ReIDEngine.__init__` que
detecta batch fijo ≠ 1 y se deshabilita con `logger.error` claro.
**Señal temprana:** `sess.get_inputs()[0].shape[0] == 16`.

### Pitfall 2 — El umbral 0.7 puede no discriminar entre dos personas reales
**Qué falla:** dos personas distintas con ropa parecida se fusionan — exactamente el
criterio 4.
**Medición hecha en esta sesión** (imágenes reales de `skimage.data`, coseno sobre
embeddings normalizados):

| Par | Coseno |
|---|---|
| astronaut ↔ astronaut espejada | 0,976 |
| astronaut ↔ astronaut oscurecida (−40 de brillo) | 0,963 |
| astronaut ↔ astronaut recortada | 0,934 |
| astronaut ↔ **astronaut con el tono desplazado 60°** ("otra ropa") | **0,481** |
| astronaut ↔ coffee (contenido no relacionado) | 0,683 |
| astronaut oscurecida ↔ coffee | **0,713** ⚠️ |
| astronaut ↔ rocket | 0,254 |

Lectura: la **misma** persona con cambios de pose/iluminación queda holgadamente por encima
de 0,9 — el 0,7 es seguro por ese lado. Pero contenido **completamente no relacionado** ya
roza 0,71, y OSNet es fuertemente cromático (el cambio de tono hunde la similitud a 0,48).
Dos personas reales, ambas con abrigo oscuro, estarán mucho más cerca entre sí que una
persona y una taza de café.
**Cómo evitarlo:** el flag `reid_inherit_identity=False` por defecto **no es opcional** —
es el mecanismo por el que se mide la tasa real antes de activarlo. Loguear cada match con
la similitud para poder construir el histograma del criterio 4.
**Confianza:** `[VERIFIED: medición ejecutada]` para las cifras; `[ASSUMED]` para la
extrapolación a pares de personas reales — nadie ha medido eso todavía en este proyecto.

### Pitfall 3 — Ruido aleatorio da coseno 0,99
**Qué falla:** un test que usa `np.random` como "crop de persona" da similitud 0,991 entre
dos ruidos independientes y pasa (o falla) por motivos que no tienen nada que ver con ReID.
**Por qué pasa:** entradas fuera de distribución colapsan a una dirección común del espacio
de embeddings. La similitud media de las 9 imágenes probadas con su centroide es 0,775.
**Cómo evitarlo:** `test_track_gallery.py` con **vectores** sintéticos controlados;
`test_reid_engine.py` con imágenes reales de `skimage.data`, nunca ruido.
`[VERIFIED: medición ejecutada]`

### Pitfall 4 — El `IDENTITY_LOST` espurio
**Qué falla:** 30 s después de una herencia por ReID hecha fuera de la FSM, se emite
`IDENTITY_LOST` para alguien que está delante de la cámara. Si `rules.yaml` engancha ese
evento, dispara una alerta falsa.
**Por qué pasa:** `on_tick` (identity.py:432-449) expira las entradas `TEMPORARILY_LOST`
huérfanas.
**Cómo evitarlo:** siempre pasar por `on_reid_result()` → `_claim_lost()`.
**Señal temprana:** un test que confirme por ReID, avance el reloj `lost_ttl + ε`, ejecute
`on_tick(now)` y asserte `transitions == []`.

### Pitfall 5 — El track heredado no se refresca y `on_tick` lo borra
**Qué falla:** un track confirmado por apariencia desaparece de `_states` al superar
`stale_ttl = lost_ttl + revalidate_after * 3` (identity.py:426) si `last_face_at` se quedó
en 0.0.
**Cómo evitarlo:** `on_reid_result` fija `st.last_face_at = now`. Consecuencia deliberada:
la revalidación facial de ese track se pospone `revalidate_after` (120 s). Documentarlo.

### Pitfall 6 — Contaminar `AdaptiveRate` con la latencia de ReID
**Qué falla:** `avg_latency` en `/api/v2/cameras/{id}/health` deja de significar "latencia
facial" y mezcla dos etapas.
**Cómo evitarlo:** solo `_metrics.inference_latency_seconds.labels(stage="reid").observe()`
(la etiqueta ya existe, metrics.py:79-82) y `_metrics.reid_fps` (metrics.py:76-78). Nunca
`self._rate.observe()`.

### Pitfall 7 — `test_architecture.py` ya vigila el nombre `embed`
**Qué falla:** `INFERENCE_CALLS` incluye literalmente `"embed"`
(test_architecture.py:15-18), y `test_no_inference_in_coroutines` recorre **todo**
`backend/`. Cualquier `await`-context que llame a `ReIDEngine.embed(...)` rompe la suite.
**Cómo evitarlo:** `embed()` solo se invoca desde `RecognitionWorker._loop` (hilo). Esto es
una ventaja: el invariante ya cubre ReID sin tocar el test.
**Ojo adicional:** `test_pipeline_modules_do_not_import_fastapi` y
`test_capture_worker_stays_pure` prohíben la subcadena `"recogn"` en `capture.py` — no
mover nada de ReID allí.

### Pitfall 8 — `models/` no está en `.gitignore`
**Qué falla:** un `git add -A` mete 900 KB de binario en el repo.
**Cómo evitarlo:** añadir `models/` a `.gitignore` en la misma tarea que crea
`fetch_models.py`. `[VERIFIED: .gitignore leído — no contiene models/]`

---

## Code Examples

### Selección del candidato ReID en el worker

```python
# Fuente: patrón de RecognitionWorker._next_candidate (recognition.py:184-203)
def _next_reid_candidate(self, now: float):
    """Track mas antiguo que toca re-embeber ahora, o None.

    Deliberadamente NO usa fsm.needs_recognition(): el caso que ReID cubre
    (persona de espaldas, TEMPORARILY_LOST, UNKNOWN en backoff de 120 s) es
    justo donde ese gate dice que no. El unico limite es reid_interval_secs
    (criterio 5) y min_track_age.
    """
    tracks = [
        ts for ts in self._registry.snapshot().values()
        if (now - ts.first_seen) >= self._min_track_age
        and self._gallery.needs_embedding(ts.track_id, now)
    ]
    if not tracks:
        return None
    return min(tracks, key=lambda ts: ts.first_seen)
```

### Identidades activas para la comprobación de conflicto (REID-02)

```python
# Fuente: TrackRegistry.frame_ids (tracking.py:113) + IdentityStateMachine.identity_of
#         (identity.py:154-159, devuelve identidad solo si CONFIRMED)
def _active_identities(self) -> set[int]:
    out: set[int] = set()
    for tid in self._registry.frame_ids():
        pid, _ = self._fsm.identity_of(tid)
        if pid is not None:
            out.add(pid)
    return out
```

### `scripts/fetch_models.py` — descarga idempotente + reescritura del batch

```python
# SPEC_v2.md §4.3 anticipa este script; hoy no existe en scripts/.
OSNET = ModelSpec(
    url="https://huggingface.co/kornia/osnet/resolve/main/osnet_x0_25_msmt17.onnx",
    mirror="https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/"
           "osnet_x0_25_msmt17.onnx",
    sha256="e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277",
    size=907_169,
    dest=Path("models/reid/osnet_x0_25_msmt17_dyn.onnx"),
)

def _to_dynamic_batch(src: Path, dst: Path) -> None:
    """El export publico fija dim0=16 en entrada y salida. ORT rechaza batch 1
    y una llamada rellena a 16 cuesta 84 ms en vez de 5. Reescribir el eje da
    un grafo bit-identico (verificado: max|delta| = 0.0) con batch dinamico."""
    import onnx
    m = onnx.load(str(src))
    for t in list(m.graph.input) + list(m.graph.output):
        d = t.type.tensor_type.shape.dim[0]
        d.ClearField("dim_value")
        d.dim_param = "batch"
    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(m, str(dst))
```

### Parámetros de configuración (patrón de la Fase 24)

```python
# Fuente: bloque "--- Identidad temporal (Fase 24 ...)" de backend/config.py:137-147
# --- Re-identificacion por apariencia (Fase 25 — REID-01..REID-04) ---
# Defaults de SPEC_v2.md §5.6 / ADR-04. reid_inherit_window_secs es MAS CORTA
# que identity_lost_ttl_secs (30 s) a proposito: la apariencia es menos fiable
# que la votacion facial y debe caducar antes.
reid_enabled: bool = True
reid_model_path: str = "models/reid/osnet_x0_25_msmt17_dyn.onnx"
reid_inherit_window_secs: float = 15.0
reid_similarity_threshold: float = 0.7
reid_interval_secs: float = 2.0
reid_inherit_identity: bool = False      # REID_INHERIT_IDENTITY: solo-observacion
reid_max_gallery_entries: int = 256
```

`reid_model_path` puede reutilizar `validate_yolo_model_path` (config.py:39-51) casi
literalmente: `_MODEL_PATH_ALLOWED_SUFFIXES` **ya incluye `.onnx`** (config.py:9) y la
contención dentro del proyecto (SEC-16) aplica igual. Añadir también un
`@model_validator` que verifique `0 < reid_similarity_threshold <= 1.0`,
`reid_inherit_window_secs > 0` y `reid_interval_secs > 0`, siguiendo
`validate_identity_params` (config.py:183-199).

---

## Ficheros reales de la fase (sustituye a SPEC §9)

| Fichero | Acción | Motivo |
|---|---|---|
| `backend/perception/reid/__init__.py` | Crear | Paquete nuevo |
| `backend/perception/reid/engine.py` | Crear | `ReIDEngine` |
| `backend/perception/reid/gallery.py` | Crear | `TrackGallery` |
| `backend/perception/face/identity.py` | **Modificar** (aditivo) | `on_reid_result()` — no listado en SPEC §9; justificación en §Q1/D-8 |
| `backend/pipeline/recognition.py` | **Modificar** | Cablear engine + gallery, `_next_reid_candidate`, contadores, `gallery.prune` en `_sync_identity` |
| `backend/pipeline/manager.py` | **Modificar** | Construir engine y gallery **fuera** de `_make_recognition` (manager.py:122-135) e inyectarlos; nuevos kwargs `reid_*` |
| `backend/config.py` | **Modificar** | 7 parámetros + validadores |
| `backend/main.py` | **Modificar** | Pasar `settings.reid_*` a `camera_manager.add()` (main.py:413-437) |
| `scripts/fetch_models.py` | Crear | Descarga + sha256 + reescritura del batch (SPEC §4.3) |
| `requirements.txt` | **Modificar** | `onnx>=1.16` explícito |
| `.gitignore` | **Modificar** | `models/` |
| `backend/pipeline/tracking.py` | **No tocar** | Ya tiene todo (D-5) |
| `backend/events/engine.py` | **No tocar** | Ya traduce la transición (D-6) |
| `tests/test_reid_engine.py` | Crear | Criterio 1 |
| `tests/test_track_gallery.py` | Crear | Criterios 2 y 4 |
| `tests/test_identity_state_machine.py` | **Modificar** | `on_reid_result` + no-`IDENTITY_LOST`-espurio |
| `tests/test_recognition_worker.py` | **Modificar** | Criterios 3 y 5 end-to-end + modo solo-observación |
| `tests/test_memory_bounds.py` | **Modificar** | Cota de `TrackGallery` |
| `tests/test_config.py` | **Modificar** | Validadores nuevos |

---

## State of the Art

| Enfoque antiguo | Enfoque actual | Cuándo cambió | Impacto |
|---|---|---|---|
| `torchreid` + PyTorch para extraer features | ONNX exportado + `onnxruntime` CPU | Export ONNX en torchreid desde ~ago 2022 | Permite ReID sin PyTorch — la base de ADR-04 |
| Modelos ReID solo en Google Drive del autor | Hugging Face Hub (`kornia/osnet`, `kaiyangzhou/osnet`) | 2023-2025 | Descarga scriptable, con hash verificable |
| ReID por frame | ReID cada N s por track | Práctica estándar en trackers CPU (boxmot, DeepSORT) | Es la política de ADR-04 y el criterio 5 |

**Nota de obsolescencia:** el ONNX disponible usa **opset 10 / IR 6** — antiguo, pero
`onnxruntime 1.28.0` lo carga sin advertencias `[VERIFIED]`. No hay export más moderno
publicado; no merece la pena re-exportar (haría falta PyTorch).

---

## Assumptions Log

| # | Claim | Sección | Riesgo si es falso |
|---|---|---|---|
| A1 | El umbral 0,7 discrimina entre dos **personas reales** distintas en esta cámara | Pitfall 2, criterio 4 | Fusiones erróneas de identidad. **Mitigado por diseño**: `reid_inherit_identity=False` por defecto. La fase entrega el mecanismo de medida, no la garantía. |
| A2 | La ventana de 15 s y el intervalo de 2 s son adecuados para esta escena | Parámetros locked | Bajo — son configurables y los fija CONTEXT como decisión de producto |
| A3 | Un solo track ReID por tick (≤4 tracks concurrentes a ritmo pleno) basta para esta cámara | §Q4 | Con >4 personas simultáneas, el intervalo efectivo por track supera 2 s. Degradación segura (menos coste), pero el criterio 5 sigue cumpliéndose |
| A4 | La licencia del ONNX es MIT (declarada en el espejo `anriha`; `kornia/osnet` no declara licencia en su model card) | §Blocker resuelto | Bajo — OSNet upstream es MIT (`kaiyangzhou/osnet`, license: mit). Confirmar si el proyecto necesita rigor de licencias |
| A5 | `intra_op_num_threads=1` es la mejor configuración frente a compartir CPU con YOLO | Pattern 1 | Medido: 12,2 ms vs 5,0 ms. Ambos por debajo de 20 ms. Si se prefiere latencia, quitar el límite. Decisión reversible de una línea |

---

## Open Questions (RESOLVED)

> Las 3 preguntas quedaron cerradas antes de planificar — los 6 `PLAN.md` siguen la
> recomendación de cada una (verificado por `gsd-plan-checker`).

1. **¿Cuál es la tasa real de falsos positivos con dos personas de ropa parecida?**
   **RESOLVED:** no bloquea la fase. El criterio 4 se cierra con (a) un test
     determinista sobre vectores sintéticos (25-03) que demuestra que el umbral y la
     comprobación de conflicto funcionan, y (b) un checkpoint manual con cámara real
     (25-06) que documenta el histograma de similitudes — mismo formato que los 6
     checkpoints abiertos de fases anteriores (`STATE.md`).
   - Lo que sabemos: la misma persona da ≥0,93; contenido no relacionado llega a 0,71.
   - Lo que falta: pares de personas reales de esta cámara.

2. **¿Dónde vive el modelo, `models/reid/` o `data/`?**
   **RESOLVED:** `models/reid/` + entrada en `.gitignore`, como dice SPEC — implementado
   en 25-01.
   - SPEC §4.3 dice `models/reid/`; `.gitignore` no lo contempla y `insightface` usa
     `~/.insightface/models/`.

3. **¿Se persiste `reid_embedding` en la tabla `tracks`?**
   **RESOLVED:** no, en esta fase — ningún plan lo hace.
   - SPEC §7 lo tiene en el esquema; ningún requisito REID-01..04 lo pide y el pipeline
     no escribe `tracks` hoy.

---

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|---|---|---|---|---|
| `onnxruntime` | `ReIDEngine` | ✓ | 1.28.0 | — |
| `onnx` | Reescritura del batch | ✓ (transitiva de `insightface`) | 1.22.0 | Declararla explícita en `requirements.txt` |
| `numpy`, `opencv-python` | Preprocesado, coseno | ✓ | ya en el proyecto | — |
| `scikit-image` | Fixture de imagen real en tests | ✓ | ya en `requirements.txt` | — |
| Red HTTPS a `huggingface.co` | `scripts/fetch_models.py` | ✓ (HTTP 200 verificado) | — | Espejo `anriha` documentado |
| `osnet_x0_25_msmt17.onnx` | REID-01 | ✓ descargado y ejecutado | 907 169 B, sha256 `e78604f4…` | Plan B: `opencv/person_reid_youtureid` (desvía de ADR-04) |
| `models/reid/` en el repo | Runtime | ✗ (no existe aún) | — | `ReIDEngine.available=False` ⇒ ReID no-op, sistema intacto |
| GPU | — | no aplica | — | CPU verificada suficiente |

**Sin dependencias que bloqueen.** El único artefacto ausente es el propio fichero de modelo,
y el plan lo produce con `scripts/fetch_models.py`.

---

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|---|---|
| Framework | `pytest>=7.0` + `pytest-asyncio>=0.24` (`asyncio_mode = auto`) |
| Config file | `pytest.ini` — **`python_functions = TEST_*`** (los tests nuevos deben llamarse `TEST_*`; los `test_*` heredados siguen recogiéndose por el prefijo de fichero) |
| Quick run | `.venv/Scripts/python.exe -m pytest tests/test_track_gallery.py tests/test_reid_engine.py -q` |
| Full suite | `.venv/Scripts/python.exe -m pytest tests/ -q` (377/377 hoy, ~90 s) |

### Mapa requisito → test

| Req | Criterio ROADMAP | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|---|---|---|---|---|---|
| REID-01 | 1 | `embed()` devuelve 512D, norma L2 = 1 | unit | `pytest tests/test_reid_engine.py -k embedding_is_512d_l2_normalized -q` | ❌ Wave 0 |
| REID-01 | 1 | p50 de `embed()` < 20 ms con warmup (≥30 iters) | perf | `pytest tests/test_reid_engine.py -k latency_under_20ms -q` | ❌ Wave 0 |
| REID-01 | — | Sin modelo ⇒ `available is False`, `embed()` → `None` | unit | `pytest tests/test_reid_engine.py -k degrades_gracefully -q` | ❌ Wave 0 |
| REID-01 | — | Modelo con batch fijo ≠ 1 ⇒ `available is False` (Pitfall 1) | unit | `pytest tests/test_reid_engine.py -k rejects_fixed_batch -q` | ❌ Wave 0 |
| REID-02 | 2 | Hereda con `sim > 0.7` y `< 15 s`; no hereda con `sim = 0.65`; no hereda pasados 16 s | unit | `pytest tests/test_track_gallery.py -k inherit -q` | ❌ Wave 0 |
| REID-02 | 2 | **No** hereda si la identidad está en un track activo (conflicto) | unit | `pytest tests/test_track_gallery.py -k conflict -q` | ❌ Wave 0 |
| REID-02 | — | `on_reid_result` no toca tracks `CANDIDATE`/`CONFIRMED` ni vota en el voter | unit | `pytest tests/test_identity_state_machine.py -k reid -q` | ❌ Wave 0 |
| REID-02 | — | Tras heredar por ReID, `on_tick` **no** emite `IDENTITY_LOST` (Pitfall 4) | unit | `pytest tests/test_identity_state_machine.py -k reid_no_spurious_identity_lost -q` | ❌ Wave 0 |
| REID-03 | 3 | Persona confirmada → sin cara 10 s → reaparece con `track_id` nuevo → `person_id` conservado y **exactamente 1** `PERSON_RECOGNIZED`, **0** `UNKNOWN_PERSON` | integración | `pytest tests/test_recognition_worker.py -k reid_recovers_identity_without_face -q` | ❌ Wave 0 |
| REID-04 | 5 | ≤1 llamada a `engine.embed` por track cada 2 s (motor mockeado, contando llamadas) | integración | `pytest tests/test_recognition_worker.py -k reid_inference_budget -q` | ❌ Wave 0 |
| REID-04 | — | `TrackGallery` acotada tras 10 000 track_ids | unit | `pytest tests/test_memory_bounds.py -k track_gallery_bounded -q` | ❌ Wave 0 |
| — | 4 | Dos vectores distintos no se fusionan; histograma de similitudes logueado | unit + checkpoint manual | `pytest tests/test_track_gallery.py -k does_not_merge -q` + checkpoint con cámara real | ❌ Wave 0 |
| — | — | `reid_inherit_identity=False` ⇒ `resolve` sí calcula, la FSM **no** cambia de estado, el contador sí sube | integración | `pytest tests/test_recognition_worker.py -k observation_only -q` | ❌ Wave 0 |
| — | — | Validadores de `reid_*` rechazan valores fuera de rango | unit | `pytest tests/test_config.py -k reid -q` | ❌ Wave 0 |
| — | — | La suite de arquitectura sigue verde (`embed` fuera de corrutinas) | arquitectura | `pytest tests/test_architecture.py -q` | ✅ existe |

### Frecuencia de muestreo

- **Por commit de tarea:** `pytest tests/test_track_gallery.py tests/test_reid_engine.py tests/test_identity_state_machine.py -q`
- **Por merge de wave:** `pytest tests/test_recognition_worker.py tests/test_memory_bounds.py tests/test_architecture.py tests/test_config.py -q`
- **Puerta de fase:** suite completa verde (≥377 + los nuevos) antes de `/gsd-verify-work`

### Huecos de Wave 0

- [ ] `tests/test_reid_engine.py` — REID-01, criterio 1. Necesita el modelo en
      `models/reid/`; si falta ⇒ `pytest.skip`, nunca fallo.
- [ ] `tests/test_track_gallery.py` — REID-02, criterios 2 y 4. **Vectores sintéticos, no
      imágenes** (Pitfall 3).
- [ ] `scripts/fetch_models.py` — prerrequisito de `test_reid_engine.py`.
- [ ] Fixture compartida de embeddings deterministas (vectores 512D con coseno conocido);
      puede vivir en el propio `test_track_gallery.py`, `tests/conftest.py` solo si la usa
      más de un fichero.
- No hace falta instalar framework: `pytest`/`pytest-asyncio` ya están.

---

## Security Domain

### Categorías ASVS aplicables

| Categoría ASVS | Aplica | Control estándar |
|---|---|---|
| V2 Autenticación | no | La fase no toca autenticación |
| V3 Gestión de sesión | no | — |
| V4 Control de acceso | no | Sin endpoints nuevos |
| V5 Validación de entrada | **sí** | `reid_model_path` validado con el patrón `validate_yolo_model_path` (config.py:39-51): extensión en `_MODEL_PATH_ALLOWED_SUFFIXES` y contención dentro de `_PROJECT_ROOT` (SEC-16). Umbrales validados con `@model_validator`. |
| V6 Criptografía | **sí (integridad)** | **sha256 obligatorio** del ONNX descargado en `fetch_models.py`. Un modelo ONNX es un grafo ejecutable: descargarlo sin verificar hash desde un repo de terceros es una cadena de suministro sin control. Hash conocido: `e78604f4ccda49b8f41cd0f8f7303800ce75d2361895ebb0729513c1bf53d277` |
| V12 Ficheros | **sí** | Escritura solo bajo `models/`; `mkdir(parents=True)` con ruta derivada de constante, no de entrada de usuario |
| V14 Configuración | **sí** | `reid_inherit_identity=False` por defecto = *fail-safe*: sin decisión explícita del operador, ReID no altera identidades |

### Amenazas conocidas para este stack

| Patrón | STRIDE | Mitigación estándar |
|---|---|---|
| Modelo ONNX manipulado en el hub | Tampering | Verificación sha256 + tamaño exacto; espejo secundario con el mismo hash |
| Descarga en runtime desde el proceso servidor | Tampering / DoS | La descarga vive en `scripts/`, nunca en `ReIDEngine.__init__` |
| Path traversal vía `REID_MODEL_PATH` en `.env` | Tampering | Validador de contención en `_PROJECT_ROOT` (SEC-16, ya existe) |
| Fusión errónea de identidad (atribuir a persona A la actividad de B) | Spoofing / Repudiation | Umbral conservador 0,7 + comprobación de conflicto + `REID_INHERIT_IDENTITY=false` por defecto + log de auditoría por match |
| Crecimiento sin cota de la galería de embeddings | DoS | TTL de 15 s + `max_entries=256` + test de cota (invariante de la Fase 22) |
| `pickle` en la carga del modelo | Tampering | No aplica: ONNX es protobuf, no pickle. `test_no_pickle_in_backend` (test_architecture.py:117-124) sigue verde |

---

## Sources

### Primarias (HIGH)
- **Código del repo, leído en esta sesión:** `backend/perception/face/identity.py`,
  `backend/pipeline/recognition.py`, `backend/pipeline/tracking.py`,
  `backend/pipeline/manager.py`, `backend/pipeline/rate.py`,
  `backend/perception/face/engine.py`, `backend/events/engine.py`, `backend/config.py`,
  `backend/observability/metrics.py`, `backend/main.py`, `tests/test_architecture.py`,
  `tests/test_recognition_worker.py`, `tests/test_face_engine.py`,
  `tests/test_memory_bounds.py`, `tests/conftest.py`, `pytest.ini`, `requirements.txt`,
  `.gitignore`
- **Ejecución local (spikes de esta sesión):** descarga del ONNX desde dos fuentes,
  `sha256sum`, carga en `onnxruntime 1.28.0`, latencias batch 1/16 con y sin límite de
  hilos, reescritura del eje batch con `onnx 1.22.0`, verificación bit a bit, matriz de
  similitudes coseno sobre imágenes reales de `skimage.data`
- `boxmot` — `boxmot/reid/backends/base_backend.py`, `boxmot/reid/backends/onnx_backend.py`,
  `boxmot/reid/core/preprocessing.py` (vía GitHub API): valores exactos de preprocesado
- Hugging Face API — listados de ficheros y metadatos de `kornia/osnet`,
  `anriha/osnet_x0_25_msmt17`, `kaiyangzhou/osnet`
- `propuesta_mejora/SPEC_v2.md` §4.3, §5.6, §7, §8.4, ADR-03, ADR-04, §9 Phase 25
- `.planning/ROADMAP.md` § Phase 25; `.planning/REQUIREMENTS.md` § REID;
  `.planning/STATE.md`; `.planning/phases/25-.../25-CONTEXT.md`

### Secundarias (MEDIUM)
- `https://huggingface.co/anriha/osnet_x0_25_msmt17` — licencia MIT, tamaño del fichero
- `https://kaiyangzhou.github.io/deep-person-reid/MODEL_ZOO` — familia OSNet, pesos MSMT17
- WebSearch (verificado después contra la ejecución local): input `1×3×256×128`, salida 512

### Terciarias (LOW)
- Blog `prometeo.blog` sobre ReID multi-cámara en Jetson — mencionaba preprocesado sin
  desviación estándar; **contradicho** por el código de boxmot, que sí normaliza. Se ha
  usado el código, no el blog.

---

## Metadata

**Desglose de confianza:**
- Stack y modelo: **HIGH** — descargado, hasheado, cargado y cronometrado en este equipo
- Integración con la FSM: **HIGH** — deducida del código real; el argumento del
  `IDENTITY_LOST` espurio es trazable línea a línea
- Elección de worker: **HIGH** — el comentario de `identity.py:130` y el presupuesto medido
  no dejan alternativa razonable
- Latencia (criterio 1): **HIGH** para el p50; **MEDIUM** para el p95 en máquina cargada
- Umbral 0,7 y criterio 4: **MEDIUM/LOW** — medido con imágenes reales pero **no** con pares
  de personas reales. Es el riesgo abierto de la fase, y el flag existe justo por eso
- Expiración de la galería: **HIGH** — patrón copiado de estructuras ya testeadas

**Fecha:** 2026-08-13
**Válido hasta:** ~2026-09-13 (30 días). Vigilar solo que `kornia/osnet` siga publicando el
fichero; el sha256 permite detectar cualquier cambio.
