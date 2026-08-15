# Phase 26: Análisis de comportamiento - Research

**Researched:** 2026-08-15
**Domain:** Análisis de trayectorias en tiempo real sobre un pipeline de visión ya desacoplado (Python 3.12, hilos, dominio puro con reloj inyectado)
**Confidence:** HIGH — casi todo se resuelve leyendo el código del propio repo; no hay dependencias externas nuevas ni decisiones de librería

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Umbrales y reglas (SPEC §5.7 — locked):**

| Comportamiento | Regla | Default |
|---|---|---|
| `LOITERING` | tiempo en zona > `loiter_secs` **y** desplazamiento neto < `loiter_radius_px` | 120 s / 80 px |
| `RUNNING` | velocidad media > `run_speed_px_s` durante > 1 s | 350 px/s |
| `IMMOBILE` | desplazamiento < 20 px durante > 60 s | 20 px / 60 s |
| `CROWD_DETECTED` | tracks activos simultáneos >= `crowd_threshold` | 5 |

Todos configurables desde `backend/config.py` (pydantic-settings).

**Hallazgos H-1..H-4 del CONTEXT** (verificados uno a uno en este research — ver
`## Verificación de H-1..H-4`).

**Restricciones de arquitectura (CLAUDE.md — no negociables):**
- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- `TrackRegistry` es la fuente de verdad del estado de tracks; no duplicarla.
- Toda estructura con crecimiento potencial necesita política de expiración con test.
- Reloj inyectado: nada de `time.monotonic()` dentro del dominio puro.
- Cambio mínimo: no reescribir el pipeline de zonas ni el `EventEngine` existentes.

### Claude's Discretion

Las 5 preguntas abiertas que CONTEXT dejó para este research (ventana temporal,
worker anfitrión, dwell time, idempotencia de CROWD, criterio 5) más las 3 del
orquestador (trayectorias sintéticas, payload, dependencia de zonas). Resueltas
todas en `## Respuestas a las preguntas abiertas`.

### Deferred Ideas (OUT OF SCOPE)

- **Detección de caídas** — requiere pose (YOLO-pose) → backlog v2.1.
- **`DIRECTION_CHANGED`** — sin `EventType` ni criterio de éxito → fase aparte.
- **Multi-clase, objetos abandonados y contexto de escena** (BEH-06..BEH-09) → Fase 27.
- **Poblar `config/rules.yaml` con reglas de producción** — la fase debe *demostrar*
  que los eventos son usables (criterio 5), no decidir qué alertas quiere el usuario.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Descripción | Soporte de este research |
|----|-------------|--------------------------|
| BEH-01 | Merodeo con umbrales de tiempo y desplazamiento configurables | Patrón 2 (agregado incremental con ancla) + Q1 + Q8 (fallback sin zonas) + bloque de config |
| BEH-02 | Carrera e inmovilidad prolongada | Patrón 2 (IMMOBILE por span de bbox de posiciones) + Patrón 3 (RUNNING sobre `centroid_history`, que YA cubre 1 s) |
| BEH-03 | Aglomeración a partir de N tracks simultáneos | Patrón 4 (latch de escena, calcado de `camera_offline`) + Q4 |
| BEH-04 | Entrada/salida de zona por track con tiempo de permanencia | Q3 — el trabajo real es añadir `duration_s` al `ZONE_EXITED` que ya emite `EventEngine.process_zone`; `zone_entry_times` está MUERTO |
| BEH-05 | Cada evento incluye las magnitudes que lo justifican | Q7 — `Event.payload` es `dict[str, Any]` y columna `JSON`: cabe sin tocar el modelo. **`duration_s` es nombre obligatorio**, no opcional (Q5) |
</phase_requirements>

---

## Summary

Esta fase no necesita ninguna librería nueva, ningún modelo nuevo y ninguna
decisión de stack. Todo lo que hace falta ya existe en el repo: el catálogo de
eventos completo, el motor de eventos con su patrón de idempotencia, el worker
donde correr, el registro de tracks y dos ejemplos recientes (Fases 24 y 25) del
patrón exacto de "dominio puro + reloj inyectado + estado acotado + traducción a
evento en `EventEngine`". El trabajo es de diseño, no de integración.

El hallazgo central del research **disuelve el problema H-4 en vez de resolverlo**.
CONTEXT plantea la ventana de 120 s como una disyuntiva entre historia propia
submuestreada y ampliar `history_len` del registry. Al derivar las cuatro reglas
sobre el papel resulta que **ninguna de las cuatro necesita historia**: LOITERING e
IMMOBILE se calculan con agregados incrementales O(1) por track (ancla temporal +
caja envolvente de posiciones), CROWD_DETECTED es un contador de escena y RUNNING
solo mira 1 s hacia atrás — ventana que el `centroid_history` actual ya cubre
sobradamente en el peor caso (12,5 s a 12 FPS). El coste de memoria pasa de ~142 KB
por track (opción b, medida) a ~600 B por track (medido), y el criterio 4 del
ROADMAP ("el historial por track está acotado y no crece con el tiempo de sesión")
se vuelve trivialmente cierto y trivialmente testeable.

El segundo hallazgo importante es que **la pregunta de idempotencia de CONTEXT se
queda corta**: se preguntaba solo por `CROWD_DETECTED`, pero LOITERING, RUNNING e
IMMOBILE son igual de continuos. Sin latch, una persona parada 10 minutos delante
de la cámara genera ~4.800 eventos `IMMOBILE` a 8 FPS, cada uno escrito en SQLite y
difundido por WebSocket. El propio docstring de `EventEngine` (`engine.py:3-4`) dice
que ese fue *el* error conceptual de v1. Los cuatro comportamientos necesitan latch
por episodio.

**Primary recommendation:** `BehaviorAnalyzer` como dominio puro en
`backend/perception/behavior.py`, con estado O(1) por track (sin historia propia,
sin tocar `TrackRegistry`), latch por episodio para los cuatro comportamientos,
devolviendo `list[BehaviorFinding]` (nunca `Event`); ejecutado desde
`DetectionWorker._loop` justo después de `_update_zones_and_heat`, que ya calcula la
pertenencia a zonas; traducido a eventos por un `EventEngine.emit_behavior()` calcado
de `emit_identity()`; y `duration_s` como clave obligatoria del payload porque
`RuleEngine` ya la lee para `duration_gte` (`rules.py:88-91`).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reglas de comportamiento (umbral → veredicto) | Dominio puro (`backend/perception/behavior.py`) | — | Sin reloj real, sin I/O, sin `Event`: patrón `identity.py`/`gallery.py` (Fases 24/25) |
| Muestreo por frame de las trayectorias | Hilo de detección (`DetectionWorker._loop`) | — | Único punto que ya tiene `tracked`, la pertenencia a zonas y el `now` monotónico del frame |
| Pertenencia a zonas por track | Hilo de detección (`_update_zones_and_heat`, `detection.py:236-251`) | — | Ya calcula `inside` por zona con `sv.PolygonZone.trigger()`; nadie más lo tiene |
| Traducción veredicto → `Event` tipado | `backend/events/engine.py` | — | Es el único que conoce `camera_id`, reloj de pared y el bus |
| Tiempo de permanencia en zona | `EventEngine.process_zone` | — | Ya es el dueño de `_zone_inside`; meter un segundo dueño duplicaría los eventos |
| Idempotencia (un evento por episodio) | Dominio puro (latch en `BehaviorAnalyzer`) | `EventEngine` (latch de escena) | La FSM de la Fase 24 hace exactamente esto con el flag `emits` |
| Persistencia y difusión | `backend/main.py` (suscriptores del bus) | — | **Cero trabajo**: `_persist_event`/`_broadcast_v2`/`_apply_rules` ya son genéricos por tipo |
| Configuración de umbrales | `backend/config.py` | `manager.py` → `main.py` | Bloque por fase con validador de rango, como `validate_reid_params` |

---

## Verificación de H-1..H-4

Los cuatro hallazgos del CONTEXT son correctos. Dos necesitan matiz.

### H-1 — CONFIRMADO, y además hay más muerto de lo que decía

[VERIFIED: `backend/events/types.py:19-46`] Los 6 tipos existen literalmente:
`ZONE_ENTERED` (24), `ZONE_EXITED` (25), `LOITERING` (31), `RUNNING` (32),
`IMMOBILE` (33), `CROWD_DETECTED` (34). `DIRECTION_CHANGED` **no aparece** en el
fichero. `tests/test_event_types.py:12` congela la lista de nombres del catálogo,
así que añadir un tipo nuevo rompería ese test — otra razón para no tocarlo.

[VERIFIED] `DEFAULT_SEVERITY` (`types.py:49-57`) no asigna severidad a ninguno de
los cuatro comportamientos → todos caerían en `Severity.INFO`.
**Consecuencia no obvia:** `upload_min_severity` vale `"warning"` por defecto
(`config.py:115`, consumido en `recording.py:309`). Subir `LOITERING` o
`CROWD_DETECTED` a `WARNING` en `DEFAULT_SEVERITY` los convertiría automáticamente
en disparadores de subida de clips a Google Drive. Ver `## Open Questions` #1.

### H-2 — CONFIRMADO

[VERIFIED: `backend/pipeline/detection.py:248-251`] `_update_zones_and_heat` llama a
`self._event_engine.process_zone(st["id"], inside, datetime.datetime.now(), captured_at, processed_at)`
una vez por zona y por frame.

[VERIFIED: `backend/events/engine.py:117-138`] `process_zone` hace el diff contra
`self._zone_inside[zone_id]` y emite `ZONE_ENTERED`/`ZONE_EXITED` **sin payload**
(no pasa `payload=` en ninguna de las dos llamadas, líneas 129-137). El evento sale
con `payload={"_emitted_at": ...}` únicamente.

Conclusión de CONTEXT confirmada: implementar zonas dentro de `BehaviorAnalyzer`
duplicaría cada evento. BEH-04 = añadir `duration_s` al `ZONE_EXITED` existente.

### H-3 — CONFIRMADO, y con un matiz que cambia el plan

[VERIFIED: `backend/pipeline/tracking.py:18-34`] `TrackState` real ya tiene
`track_id`, `first_seen`, `last_seen`, `bbox`, `confidence`, `centroid_history`,
`zones`, `zone_entry_times`, `person_id`, `person_name`, `identity_state`.

**Matiz nuevo y relevante** [VERIFIED: `rg "zone_entry_times|\.zones" --include=*.py`
sobre todo el repo]: los campos `zones` (línea 28) y `zone_entry_times` (línea 29)
**son código muerto**. Aparecen exactamente una vez cada uno — en su propia
declaración. Nadie los escribe, nadie los lee, ningún test los toca. Son un
esqueleto que SPEC dejó preparado y que nunca se cableó.

Esto importa porque cambia la respuesta a Q3: no hay que "reutilizar
`zone_entry_times`", hay que decidir si se cablea (segundo dueño de la pertenencia a
zonas, contra el invariante 7 de CLAUDE.md) o se deja muerto y el dato vive donde ya
está el dueño único. Ver Q3.

### H-4 — CONFIRMADO, con dos correcciones importantes

[VERIFIED: `backend/pipeline/tracking.py:27,47,76`] `centroid_history` es
`deque(maxlen=self._history_len)` con `history_len: int = 150` por defecto, y
`manager.py:74` construye `TrackRegistry()` sin argumentos → 150 en producción.
Se rellena en `update_from_detections` (`tracking.py:84`) con `(now, cx, cy)`.

**Corrección 1 — se rellena a FPS de DETECCIÓN, no de captura.**
[VERIFIED: `backend/pipeline/detection.py:158,181`] `_loop` descarta el frame si
`self._rate.should_process(...)` dice que no (línea 158), y solo después llama a
`self._registry.update_from_detections(tracked, now)` (línea 181). El `now` es
`time.monotonic()` medido tras la inferencia (línea 179).

**Corrección 2 — la ventana temporal cubierta no es fija: varía 4x con la carga.**
[VERIFIED: `backend/pipeline/rate.py:26`] `AdaptiveRate.STEPS = (12.0, 8.0, 5.0, 3.0)`
y `config.py:66-68` fija `detection_target_fps=8.0`, `min=3.0`, `max=12.0`. Es decir,
150 muestras cubren:

| FPS efectivo | Ventana real de `centroid_history` |
|---|---|
| 12,0 (holgado) | 12,5 s |
| 8,0 (default) | 18,75 s |
| 5,0 | 30 s |
| 3,0 (degradado) | 50 s |

CONTEXT decía "~19 s"; es correcto para el default, pero el rango real es 12,5–50 s.
**Esto invalida cualquier diseño que cuente muestras en vez de tiempo**: un umbral
expresado en número de frames significaría 60 s o 12,5 s según la carga de CPU del
momento. Todo lo que esta fase mida debe medirse contra el `t` de la tupla, nunca
contra `len(deque)`.

Y la conclusión de CONTEXT se sostiene: 50 s es el máximo absoluto y solo en modo
degradado. LOITERING (120 s) e IMMOBILE (60 s) no se pueden calcular con este
historial **si se calculan escaneando historia**. Ver Q1 para por qué no hay que
calcularlos así.

---

## Respuestas a las preguntas abiertas

### Q1 — ¿Cómo se cubre la ventana temporal de 120 s? → **Con ninguna de las dos opciones: no hace falta historia**

CONTEXT plantea (a) historia propia submuestreada vs (b) ampliar `history_len`.
Medí las dos y luego encontré que la premisa es evitable.

**Coste de memoria medido** [VERIFIED: `sys.getsizeof` recursivo sobre `deque` de
tuplas de 3 `float`, Python 3.12.10 x64, la misma que usa el proyecto]:

| Opción | Estructura | Bytes/track | Ventana cubierta |
|---|---|---|---|
| Actual | `deque(maxlen=150)` de `(t,x,y)` | **22.216 B (21,7 KB)** | 12,5–50 s (variable) |
| (b) ampliar `history_len` a 1000 | `deque(maxlen=1000)` | **145.208 B (141,8 KB)** | 83–333 s |
| (a) historia propia 1 Hz, 120 muestras | `deque(maxlen=120)` | **18.136 B (17,7 KB)** | 120 s fijos |
| (a') historia propia numpy `(120,3) float32` | `np.zeros((120,3),f32)` | 1.568 B (1,5 KB) | 120 s fijos |
| **(c) agregados incrementales O(1)** | dataclass de ~10 `float` | **584 B** | ilimitada |

**Por qué (b) es la peor opción y no solo por memoria.** Multiplica por 6,5x la
memoria de `TrackState` para *todos* los consumidores (`StreamingWorker`,
`RecognitionWorker`, `RecordingWorker`), y **ninguno lee `centroid_history` hoy**
[VERIFIED: el grep de `centroid_history` solo devuelve `tracking.py` y dos tests].
Además `TrackRegistry` **no tiene cota dura de número de tracks**: solo
`prune(now, ttl=30.0)` por TTL (`tracking.py:130-138`), a diferencia de
`TrackGallery._enforce_cap` (`gallery.py:145-158`) o del cap de `_states` de la FSM.
Multiplicar el tamaño por track multiplica también el peor caso de un pico de
tracks. Es exactamente lo que la Fase 22 buscaba evitar.

**Por qué (a) tampoco hace falta.** Derivando las cuatro reglas:

- **IMMOBILE** = "desplazamiento < 20 px durante > 60 s". Se calcula con un *ancla*:
  guarda `(t_ancla, x_ancla, y_ancla)` más la caja envolvente `(min_x,max_x,min_y,max_y)`
  de las posiciones vistas desde el ancla. En cada frame actualiza la caja; si el
  span (`max(max_x-min_x, max_y-min_y)`) supera 20 px, resetea el ancla al punto
  actual. La duración inmóvil es `now - t_ancla`. **4 floats de estado, exacto, O(1).**
- **LOITERING** = "tiempo en zona > 120 s **y** desplazamiento neto < 80 px". Con
  `(t_entrada, x_entrada, y_entrada)` de la zona: duración = `now - t_entrada`,
  desplazamiento neto = `hypot(x - x_entrada, y - y_entrada)`. **3 floats, O(1).**
- **CROWD_DETECTED** = `len(tracks_del_frame) >= 5`. **0 estado por track.**
- **RUNNING** = "velocidad media > 350 px/s durante > 1 s". La ventana es **1 s**, no
  120. El `centroid_history` actual cubre ≥12,5 s **en el peor caso** (12 FPS). No solo
  basta: sobra 12x. Ver Q1-bis abajo.

**Recomendación: opción (c).** `BehaviorAnalyzer` mantiene un `dict[int, _TrackAgg]`
con ~10 floats y 3-4 booleanos de latch por track (584 B medidos), sin ninguna
estructura de longitud variable. `TrackRegistry` no se toca. `centroid_history` se
lee solo para RUNNING, sin copiarlo.

Ventajas concretas frente a (a):
1. El criterio 4 del ROADMAP se cumple por construcción y se testea en una línea
   (`sizeof` del estado no depende de cuántos frames han pasado), en vez de tener que
   probar que un `deque` respeta su `maxlen`.
2. Es inmune a los saltos de `AdaptiveRate`: todo se mide contra `now` en segundos.
   Un submuestreo "1 muestra/s" habría necesitado su propio gate temporal y habría
   perdido resolución justo cuando el FPS cae a 3 (el caso degradado, el peor).
3. No introduce una segunda copia de la trayectoria → no hay riesgo de que diverja de
   `TrackRegistry` (invariante 7 de CLAUDE.md).

**Riesgo asumido y cómo mitigarlo:** el ancla es un agregado, así que el analizador
no puede "mirar atrás" para reevaluar con umbrales nuevos en caliente. Si el operador
cambia `immobile_secs` en runtime (hoy no se puede: la config es `@lru_cache`, se lee
al arrancar), los agregados en curso mantendrían el umbral viejo hasta el siguiente
reset del ancla. Irrelevante en el diseño actual, pero conviene que el planner lo
sepa antes de la Fase 32 (configuración visual).

### Q1-bis — RUNNING sobre `centroid_history`: cómo, exactamente

[CITED: `backend/pipeline/tracking.py:84`] El deque es `(t, x, y)` con `t` monotónico.
Para la ventana de 1 s: recorrer el deque **desde el final hacia atrás** hasta
encontrar la primera muestra con `t <= now - run_window_secs`; eso da el par
`(muestra_antigua, muestra_actual)`. Coste: ~`fps` iteraciones (3-12), no 150.

**Decisión de fórmula — recomendada: desplazamiento NETO / Δt, no longitud de camino.**
La longitud de camino (suma de distancias entre muestras consecutivas) integra el
jitter del bbox de YOLO/ByteTrack: cada frame añade el ruido del centroide, y a más
FPS más ruido acumulado — un track parado daría velocidad creciente con el FPS. El
desplazamiento neto no tiene ese sesgo y coincide con la semántica de "está
corriendo" (una persona que corre se desplaza en línea). [ASSUMED — razonamiento
sobre el jitter, no medido con cámara real en esta sesión]

**Guarda obligatoria:** exigir que el track tenga al menos `run_window_secs` de
historia (`now - centroid_history[0][0] >= run_window_secs`) antes de evaluar. Sin
ella, un track recién creado con 2 muestras separadas 20 ms daría velocidades de
miles de px/s con cualquier movimiento.

### Q2 — ¿Dónde corre `BehaviorAnalyzer`? → **`DetectionWorker`, sin dudarlo, y construido FUERA de la factoría**

**Dónde ejecutarlo.** `DetectionWorker._loop` (`detection.py:153-185`) es el único
sitio que tiene simultáneamente: el `tracked` del frame (línea 164), el registry ya
actualizado (línea 181), la pertenencia a zonas recién calculada
(`_update_zones_and_heat`, línea 182), el `EventEngine` (línea 65) y un `now`
monotónico coherente (línea 179). Colocar la llamada **después** de la línea 182 y
**antes** de `_emit_track_lifecycle` (línea 184) o justo después; el orden entre esas
dos es indiferente porque no comparten estado.

Las alternativas se descartan con evidencia:
- **`RecognitionWorker`** corre a `recognition_target_fps=2.0` (`config.py:69`) → 2
  muestras por segundo. La ventana de RUNNING es 1 s: se quedaría con 2 puntos. Además
  no recibe `tracked` ni la pertenencia a zonas.
- **Bucle de housekeeping** (`housekeeping_secs=60.0`, `config.py:126`) → resolución
  de 60 s, inservible para RUNNING.
- **Worker nuevo** → un cuarto suscriptor del broker que tendría que recalcular
  zonas con `sv.PolygonZone.trigger()` (duplicando la inferencia geométrica) para
  obtener un dato que `DetectionWorker` ya tiene. Contra "cambio mínimo".

**Presupuesto de CPU.** [VERIFIED: micro-benchmark en la máquina del proyecto,
Python 3.12.10, 10 tracks × 100.000 frames del agregado incremental completo incluida
la generación de posiciones] → **12,3 µs por frame para 10 tracks**. El presupuesto
de `AdaptiveRate` es `(1/fps)*0.8` (`rate.py:69`) = **100 ms a 8 FPS**. El analizador
consume el **0,012 %** del presupuesto. Es ruido de medición frente a YOLO.

Además [VERIFIED: `detection.py:170-171`] `self._rate.observe(inference_latency)` se
llama **antes** de la línea 182, con la latencia medida solo alrededor de
`detect_sv` + `tracker.update`. Es decir, el analizador **no contamina** `avg_latency`
ni el control adaptativo — el mismo cuidado que la Fase 25 tuvo con la vía ReID
(decisión registrada en `STATE.md`: "`self._rate.observe()` nunca se llama desde la
vía ReID").

**Dónde CONSTRUIRLO — el punto que se olvida.** [VERIFIED: `manager.py:96-108`]
`DetectionWorker` se construye dentro de la factoría `_make_detection`, que
`WorkerSupervisor` **re-ejecuta en cada reinicio del worker**. Si el
`BehaviorAnalyzer` se instanciara dentro del `DetectionWorker.__init__`, cada
reinicio del detector borraría todas las anclas y latches: una persona que llevara
100 s inmóvil volvería a empezar el contador, y todos los latches se re-armarían
provocando una ráfaga de eventos duplicados justo después de un reinicio.

El repo ya resolvió esto dos veces con el mismo patrón, y lo documenta:
- `manager.py:134-146` — `IdentityStateMachine` fuera de la factoría ("la FSM vive
  FUERA de la factoria: WorkerSupervisor la re-ejecuta en cada reinicio...").
- `manager.py:148-160` — `ReIDEngine`/`TrackGallery` fuera de la factoría, por lo mismo.
- `manager.py:110-118` — `_make_streaming` rescata `clients` del worker anterior.

→ **`self.behavior = BehaviorAnalyzer(...)` en `CameraPipeline.__init__`, junto a
`self.identity_fsm`, y pasado como argumento a `DetectionWorker` dentro de la
factoría.** Esto es prescriptivo, no opcional.

**Manejo de errores.** [CITED: `recognition.py:366-374`, `detection.py:165-168`] El
patrón del repo es envolver la llamada al dominio en `try/except Exception`,
incrementar `self._exceptions` y `logger.exception(...)`, y seguir. El analizador
debe ir envuelto igual: un `ZeroDivisionError` en el cálculo de velocidad no puede
matar el hilo de detección.

### Q3 — ¿Cómo se añade el dwell time a `ZONE_EXITED`? → **En `EventEngine.process_zone`; `zone_entry_times` está muerto y debe seguir muerto**

**Trazado del código real:**
1. `TrackState.zone_entry_times` (`tracking.py:29`) — **cero escritores, cero
   lectores** en todo el repo [VERIFIED por grep]. Igual `TrackState.zones`
   (`tracking.py:28`). Ambos son código muerto desde que se escribió el dataclass.
2. El dueño real de la pertenencia a zonas es doble y ya está establecido:
   `DetectionWorker._zone_states[i]["inside"]` (`detection.py:246`) para las
   estadísticas de la API, y `EventEngine._zone_inside[zone_id]`
   (`engine.py:37,138`) para las transiciones.
3. `process_zone` recibe `now: datetime.datetime` (reloj de pared) más
   `captured_at`/`processed_at` (monotónicos, opcionales).

**Recomendación: `_zone_entry_at: dict[str, dict[int, float]]` dentro de `EventEngine`,
poblado en la rama `entered` y consumido+borrado en la rama `exited` de `process_zone`.**

Razones:
- Es donde ya vive `_zone_inside`. Un solo dueño, un solo diff, cambio de ~8 líneas.
- Cablear `zone_entry_times` en `TrackRegistry` crearía un segundo escritor de estado
  de zona sincronizado a mano con `_zone_inside` — exactamente el "estado global
  oculto" y la "lógica duplicada" que CLAUDE.md prohíbe. Y `TrackRegistry` documenta
  su regla de escritor único (`tracking.py:41-44`).
- La limpieza es automática y demostrable: todo track que desaparece cae en
  `previous - inside_track_ids` → se emite `ZONE_EXITED` → se hace `pop`. El dict
  queda acotado por "tracks dentro de zonas ahora mismo".

**Trampa del reloj — decisión que el planner debe tomar explícitamente.** Restar dos
`datetime.datetime.now()` es sensible a saltos de reloj (NTP, cambio de hora) y
`_update_zones_and_heat` llama a `datetime.datetime.now()` **una vez por zona y por
frame** (`detection.py:250`). Lo monotónico ya está disponible en la firma
(`captured_at`, `processed_at`) pero ambos son `float | None` con default `None`
(`engine.py:122-123`) y `None` en la mayoría de tests. Tres caminos:
  (a) usar `processed_at` cuando no es `None` y caer a la resta de `datetime` si lo es
      — dos caminos de código, difícil de testear;
  (b) añadir un parámetro explícito `now_monotonic: float | None = None` — más limpio
      semánticamente (`captured_at` es un concepto privado de latencia, `engine.py:54-57`),
      pero toca la firma pública;
  (c) restar los `datetime`.
  **Recomendación: (b)**, coherente con la disciplina de reloj inyectado de las
  Fases 24/25. Documentar el fallback cuando llega `None` (no emitir `duration_s`, en
  vez de emitir un valor falso).

**Nombre de la clave: `duration_s`.** Obligatorio, ver Q5.

**Impacto en tests existentes:** `tests/test_event_engine.py:52-65`
(`TEST_zone_transitions`) no inspecciona el payload → sigue verde si el cambio es
puramente aditivo. Es el único test que toca `process_zone`.

### Q4 — Idempotencia → **hace falta para los CUATRO comportamientos, no solo para CROWD**

**El patrón que ya usa el repo**, en dos sabores:
- **Latch booleano de escena** — `EventEngine._camera_offline` (`engine.py:38`) con
  `camera_offline()`/`camera_recovered()` (`engine.py:144-154`): `if self._camera_offline: return`
  al entrar, se pone a `True` al emitir, y el evento inverso lo re-arma. Es el patrón
  exacto que pide `CROWD_DETECTED`.
- **Diff de conjuntos** — `process_tracks` (`engine.py:99-111`) y `process_zone`
  (`engine.py:125-138`): se emite solo sobre `nuevo - anterior`.
- **Flag `emits` en el veredicto del dominio** — `IdentityTransition.emits`
  (`identity.py:45`) + `if not transition.emits: return` (`engine.py:196-197`). Este
  es el más potente: la decisión de si un cambio de estado merece evento vive en el
  dominio puro (donde se puede testear sin bus, sin asyncio y sin reloj real), y
  `EventEngine` solo traduce.

**Por qué se necesita para los cuatro.** LOITERING, RUNNING e IMMOBILE son
condiciones *continuas*, no transiciones: mientras la persona siga parada, la
condición `now - t_ancla > 60` sigue siendo cierta en cada frame. A 8 FPS eso son
**480 eventos por minuto por track**, todos escritos en SQLite por `_persist_event`
(`main.py:276`) y difundidos por WebSocket (`main.py:278`). El docstring de
`EventEngine` (`engine.py:3-4`) lo dice sin rodeos: *"One event per transition, never
per frame — this is the point where v1 failed conceptually."*

**No sirve `debounce_secs` de `rules.yaml`** (`rules.py:50,152-158`): actúa sobre el
*disparo de la regla*, después de que el evento ya se haya persistido y difundido. El
latch tiene que estar en el origen.

**Recomendación:** un flag booleano por `(track_id, comportamiento)` en el estado
O(1) del analizador, más el latch de escena para CROWD. `BehaviorAnalyzer` devuelve un
`BehaviorFinding` **solo en el flanco de subida** (patrón `emits`). Re-armado:
- LOITERING / IMMOBILE: re-armar cuando la condición geométrica deja de cumplirse
  (el ancla se resetea porque la persona se movió).
- RUNNING: re-armar cuando la velocidad cae por debajo del umbral. **Añadir
  histéresis** (p. ej. re-armar por debajo de `0.8 * run_speed_px_s`), porque una
  persona corriendo a exactamente 350 px/s con ruido de bbox oscilaría alrededor del
  umbral y emitiría en cada cruce.
- CROWD: mismo latch con histéresis (`>= crowd_threshold` para armar,
  `< crowd_threshold` — o `<= crowd_threshold - 1` — para re-armar). **No existe
  `CROWD_CLEARED` en el catálogo** [VERIFIED: `types.py:19-46`] y el CONTEXT prohíbe
  añadir tipos, así que el re-armado es silencioso.

**Cota de memoria del latch:** vive dentro del mismo dict por track del analizador →
lo cubre la misma política de expiración. Ver `## Common Pitfalls` #4.

### Q5 — Criterio 5 (`when.event` sin tocar el `RuleEngine`) → **CONFIRMADO, funciona hoy, con una obligación de nombre**

[VERIFIED: `backend/events/rules.py:24-33`] `class When(BaseModel)` declara
`event: EventType`. Pydantic valida contra el **enum completo**, no contra una lista
cerrada aparte. Como los 6 tipos ya están en `EventType` (H-1), una regla con
`event: LOITERING` valida y carga sin tocar una línea de código.

[VERIFIED: `rules.py:72-74`] `_matches` compara `when.event != event.type` →
funciona por igualdad de enum, sin tabla de traducción.

[VERIFIED: `rules.py:105-120`] `load_rules` valida cada regla con
`Rule.model_validate` y, si falla, la desactiva y la registra sin bloquear el
arranque. Un typo en el nombre del evento produce un error de validación con el
mensaje del enum, no un crash.

**`duration_gte` sirve — y ESO IMPONE EL NOMBRE DE LA CLAVE.**
[VERIFIED: `rules.py:88-91`]:
```python
if when.duration_gte is not None:
    duration = event.payload.get("duration_s")
    if duration is None or duration < when.duration_gte:
        return False
```
El `RuleEngine` lee literalmente `payload["duration_s"]`. Por tanto **BEH-05 no puede
llamar a ese campo `duration`, `dwell_s`, `elapsed` ni `secs`**: tiene que ser
`duration_s`, o el criterio 5 se cumple a medias (el evento se puede filtrar por
tipo, pero no por duración). Aplica a `LOITERING`, `IMMOBILE`, `RUNNING` y al
`ZONE_EXITED` de BEH-04.

**Otros filtros que salen gratis:**
- `when.zone` compara contra `event.zone_id` (`rules.py:75-76`) → si `LOITERING` se
  emite con `zone_id` poblado, se puede escribir "merodeo solo en la zona del
  garaje" sin código nuevo.
- `when.payload` hace match exacto de claves arbitrarias (`rules.py:98-101`) → p. ej.
  `payload: {track_count: 8}`. **Ojo:** es igualdad exacta, no `>=`; para
  `CROWD_DETECTED` no sirve como umbral, solo `duration_gte` tiene comparación.
- `when.min_confidence` compara `event.confidence` (`rules.py:85-87`), que es
  `float | None` en `Event`. Los eventos de comportamiento no tienen "confianza"
  natural → dejar `confidence=None` y no usar ese filtro.

**Debounce:** la clave es `(rule.name, camera_id, person_id or track_id)`
(`rules.py:147-150`) → funciona correctamente por track para los eventos de
comportamiento. `CROWD_DETECTED` no tiene `track_id` → cae en la clave `""`, es
decir debounce global por cámara. Correcto para un evento de escena.

**Trabajo real para el criterio 5: cero código.** Un test que construya un
`Rule.model_validate({... "when": {"event": "LOITERING", "duration_gte": 120}})` y
verifique que `RuleEngine.evaluate(evento_loitering)` devuelve el nombre de la regla
lo demuestra. `config/rules.yaml` **no necesita modificarse** (CONTEXT lo difiere
explícitamente) — ver `## Discrepancias con SPEC`.

### Q6 — ¿Cómo se testean trayectorias sintéticas aquí? → **Dos niveles; el nivel 1 no necesita ningún fixture nuevo**

**Nivel 1 (el que cubre el criterio 2): dominio puro, sin `sv.Detections`.**
El patrón lo marcan `tests/test_track_gallery.py` (6,2 KB, 14 tests) y
`tests/test_identity_state_machine.py` (17,8 KB): se instancia la clase de dominio,
se le pasan datos y un `now` inventado, y se comprueba el veredicto. Sin hilos, sin
broker, sin asyncio, sin reloj real. Es determinista y corre en milisegundos.

Una "trayectoria sintética" en ese nivel es simplemente una lista de
`(t, x, y)` generada por un helper local:
```python
def _walk(x0, y0, vx, vy, secs, fps=8.0):
    """Trayectoria rectilínea: devuelve [(t, x, y), ...] a fps constante."""
    n = int(secs * fps)
    return [(i / fps, x0 + vx * i / fps, y0 + vy * i / fps) for i in range(n)]
```
Las seis trayectorias del criterio 2, con los defaults locked:

| # | Evento esperado | Trayectoria |
|---|---|---|
| 1 | `LOITERING` | 130 s dentro de una zona, deriva total < 80 px (p. ej. ±30 px alrededor de un punto) |
| 2 | `RUNNING` | 2 s en línea recta a 400 px/s (> 350) |
| 3 | `IMMOBILE` | 70 s con jitter de ±5 px (span < 20 px) |
| 4 | `CROWD_DETECTED` | 1 frame con 5 tracks simultáneos |
| 5 | `ZONE_ENTERED` | track que aparece fuera y entra en la zona |
| 6 | `ZONE_EXITED` | el mismo track que sale, tras 12 s → `duration_s ≈ 12` |

**"y ninguno más" es la mitad difícil del criterio 2** y hay que planificarlo
explícitamente: la trayectoria 3 (inmóvil 70 s) satisface también el desplazamiento
de LOITERING, y si el track está dentro de una zona más de 120 s emitirá LOITERING
además de IMMOBILE. Las trayectorias deben construirse para aislar: la de IMMOBILE
debe durar < `loiter_secs` o quedar fuera de toda zona. El test debe afirmar sobre
el **conjunto completo** de findings (`assert types == {EventType.IMMOBILE}`), no
sobre la presencia del esperado.

**Nivel 2 (cableado): sí necesita un fixture, y ya existe casi entero.**
`tests/test_detection_worker.py:27-35` define `_tracked(ids)` que construye un
`sv.Detections` con `xyxy` fijo en `[[10,10,50,50]]`. Para mover tracks hace falta
la variante posicional — **y ya está escrita** en el mismo fichero:
`tests/test_detection_worker.py:252` `_tracked_at(boxes, tids)`. El plan debe
reutilizar `_tracked_at`, no escribir un tercer helper.
`tests/test_memory_bounds.py:34-40` tiene además `_fake_tracked(track_id)` con
`SimpleNamespace` — más ligero, sin depender de `supervision`, útil para los tests de
cota de memoria.

**Convención de nombres:** `pytest.ini` fija `python_functions = TEST_*`. En Windows
el matching de pytest es case-insensitive, así que conviven `test_*` (v1.2) y `TEST_*`
(Fases 22-25) — [VERIFIED: `pytest tests/test_track_registry.py --collect-only`
recoge los 11, 7 en minúscula y 4 en mayúscula]. **Los tests nuevos deben usar
`TEST_*`**, como todo lo escrito desde la Fase 22; en Linux/CI los `test_*` dejarían
de recogerse silenciosamente.

**Ficheros de test previstos:**
- `tests/test_behavior_analyzer.py` (nuevo) — dominio puro, criterios 1/2/3.
- `tests/test_event_engine.py` (ampliar) — `duration_s` en `ZONE_EXITED`,
  `emit_behavior`.
- `tests/test_memory_bounds.py` (ampliar) — criterio 4, patrón `TEST_*_bounded`.
- `tests/test_rule_engine.py` (ampliar) — criterio 5.
- `tests/test_config.py` (ampliar) — defaults y validadores de rango.
- `tests/test_detection_worker.py` (ampliar) — cableado, reutilizando `_tracked_at`.

### Q7 — ¿Qué payload lleva hoy un `Event` y caben las magnitudes de BEH-05? → **Caben sin tocar nada**

[VERIFIED: `backend/events/types.py:60-74`] `Event` es un `BaseModel` con
`payload: dict[str, Any] = Field(default_factory=dict)`. Sin `extra="forbid"`, sin
esquema del payload. Campos de primer nivel disponibles y ya rellenables:
`track_id`, `person_id`, `person_name`, `zone_id`, `confidence`, `bbox`,
`snapshot_path`, `recording_id`, `severity`.

[VERIFIED: `backend/events/engine.py:46-66`] `_publish(event_type, ts, captured_at,
processed_at, **fields)` extrae `payload` de `fields`, le añade `_emitted_at` y
opcionalmente `_captured_at`, y pasa el resto como kwargs a `Event(...)`. Es decir:
**cualquier método nuevo de emisión ya tiene la vía abierta** — basta llamar a
`self._publish(EventType.LOITERING, ts=..., track_id=..., zone_id=...,
payload={"duration_s": ..., "net_displacement_px": ...})`.

[VERIFIED: `backend/storage/models.py:102`] La columna es
`payload = Column(JSON, nullable=False, default=dict)` y
`repositories.py:61` hace `payload=event.payload` sin filtrar → las claves nuevas
persisten solas. Sin migración de esquema.

[VERIFIED: `backend/main.py:93`] `_broadcast_v2` serializa con
`event.model_dump_json()` → las claves nuevas llegan al frontend solas.

[VERIFIED: `backend/events/bus.py:61`] `_metrics.events_total.labels(type=..., ...)`
se incrementa en el bus por tipo → los cuatro comportamientos aparecen en
`/metrics` y en `/api/v2/metrics` sin tocar la observabilidad.

**Mapa recomendado de magnitudes (BEH-05):**

| Evento | Campos de primer nivel | `payload` |
|---|---|---|
| `LOITERING` | `track_id`, `zone_id` (o `None`, ver Q8) | `duration_s`, `net_displacement_px` |
| `RUNNING` | `track_id` | `speed_px_s`, `duration_s` |
| `IMMOBILE` | `track_id` | `duration_s`, `net_displacement_px` |
| `CROWD_DETECTED` | — (evento de escena, `track_id=None`) | `track_count` |
| `ZONE_EXITED` | `track_id`, `zone_id` (ya) | `duration_s` **(nuevo)** |
| `ZONE_ENTERED` | `track_id`, `zone_id` (ya) | — (sin duración por definición) |

`zone_id` como campo de primer nivel (no dentro del payload) es lo correcto: así
`when.zone` de `rules.yaml` lo filtra (`rules.py:75-76`) y la columna dedicada de la
tabla lo indexa.

### Q8 — ¿LOITERING depende de que haya zonas configuradas? → **Sí, y hoy no hay ninguna zona por defecto: hay que decidir el fallback**

[VERIFIED: `backend/pipeline/detection.py:237-251`] El bucle de zonas es
`for st in self._zone_states:` → con `_zone_states` vacío **no se llama a
`process_zone` ni una vez**. Cero `ZONE_ENTERED`/`ZONE_EXITED`.

[VERIFIED: `backend/main.py:458`] Las zonas se cargan con
`pipeline.set_zones(await get_zones())`, y `get_zones()` (`database.py:295-308`) lee
la tabla `Zone`. [VERIFIED: no hay ningún seed en `database.py` ni en `scripts/`] →
**una instalación limpia tiene cero zonas**.

Consecuencia: si `LOITERING` se implementa literalmente como "tiempo *en zona*", en
la instalación por defecto **nunca se emitiría**, el criterio 1 del ROADMAP
("se emiten LOITERING, ...") no sería verificable en un sistema real sin
configuración previa, y la fase entera dependería de un paso manual no documentado.

**Recomendación: escena implícita.** Cuando el track no está en ninguna zona, tratar
"el frame entero" como zona implícita: el analizador arranca el ancla de LOITERING en
`first_seen` del track y emite el evento con `zone_id=None`.
- Ventaja: el sistema funciona out-of-the-box, el criterio 1 es verificable sin
  configurar nada, y quien sí tenga zonas obtiene el comportamiento de SPEC con
  `zone_id` poblado (y por tanto filtrable con `when.zone`).
- Semánticamente coherente: "lleva 2 minutos delante de la cámara sin moverse de
  sitio" es merodeo tanto si hay un polígono dibujado como si no.
- Riesgo: en una escena con mucho tránsito, LOITERING de escena puede ser ruidoso.
  Mitigación disponible sin código: `enabled: false` en la regla, o el `debounce_secs`
  de `rules.yaml`. Se puede añadir además un `loiter_require_zone: bool = False` en
  config si el planner quiere una salida limpia.

**Alternativa descartada:** gatear LOITERING a que haya zonas. Deja el criterio 1
sin evidencia posible en el entorno de desarrollo (no hay cámara ni zonas en esta
sesión — ver los 7 checkpoints manuales abiertos en `STATE.md`).

Esto es una decisión de producto disfrazada de decisión técnica → marcada como
`## Open Questions` #2 para confirmación del usuario.

---

## Discrepancias con SPEC (la reality-check que pidió el orquestador)

Por tercera fase consecutiva, `SPEC_v2.md` §9 se equivoca en la lista de ficheros.
**El planner debe seguir la columna "Realidad".**

### D-1 — Lista de ficheros de SPEC §9 Phase 26 (`SPEC_v2.md:899-906`)

| SPEC dice | Realidad | Evidencia |
|---|---|---|
| Crear `backend/perception/behavior.py` | ✅ Correcto | — |
| Modificar `backend/pipeline/tracking.py` | ❌ **No hace falta tocarlo** | Con agregados O(1) (Q1) el analizador no necesita historia nueva; `centroid_history` se lee tal cual. Tocarlo solo tendría sentido para *borrar* `zones`/`zone_entry_times`, que son código muerto (H-3) — cambio cosmético, no requisito |
| Modificar `config/rules.yaml` | ⚠️ **No, y CONTEXT lo difiere** | El criterio 5 pide *demostrar* usabilidad; poblar reglas de producción es decisión del usuario (`26-CONTEXT.md` §Deferred). Un test en `tests/test_rule_engine.py` lo cubre |
| — (omitido) | ✅ **`backend/pipeline/detection.py`** | Es donde corre el analizador (Q2), `detection.py:153-185` |
| — (omitido) | ✅ **`backend/events/engine.py`** | `emit_behavior()` + `duration_s` en `process_zone` (Q3, Q4) |
| — (omitido) | ✅ **`backend/config.py`** | 6-8 parámetros nuevos + validador de rango |
| — (omitido) | ✅ **`backend/pipeline/manager.py`** | Construcción FUERA de la factoría (Q2) + propagación de parámetros |
| — (omitido) | ✅ **`backend/main.py`** | Propagar `settings.*` a `CameraPipeline`, como hizo `25-05` |
| Tests: `tests/test_behavior_analyzer.py` | ⚠️ Incompleto | Faltan las ampliaciones de `test_event_engine.py`, `test_memory_bounds.py`, `test_rule_engine.py`, `test_config.py`, `test_detection_worker.py` (ver Q6) |

### D-2 — El `TrackState` de SPEC §5.7 (`SPEC_v2.md:450-458`)

Redundante (H-3, confirmado). **No crear.** Ya existe en `tracking.py:18-34` con
todos los campos y algunos más (`bbox`, `confidence`, `person_name`).

### D-3 — La firma de SPEC §5.7 `analyze(...) -> list[Event]` (`SPEC_v2.md:461`)

❌ **Contradice el patrón establecido en las Fases 24 y 25.** `perception/` es
dominio puro: no conoce `camera_id`, no conoce el reloj de pared y no importa
`backend.events`. Está escrito explícitamente en `identity.py:33-35` ("La FSM
devuelve esto, NO un Event: perception/ no conoce camera_id ni el reloj de pared")
y en `gallery.py:1-14` ("no importa `time`, no arranca hilos, no hace I/O y **no
construye eventos**").

→ La firma correcta es
`analyze(...) -> list[BehaviorFinding]`, con `BehaviorFinding` como dataclass plano
(calco de `IdentityTransition`, `identity.py:30-45`), y `EventEngine.emit_behavior()`
haciendo la traducción a `Event`.

### D-4 — El docstring de SPEC §5.7 menciona `ZONE_ENTERED/EXITED` y `DIRECTION_CHANGED`

Ambos fuera de alcance por H-2 y por el CONTEXT. `DIRECTION_CHANGED` ni siquiera
existe en `EventType` (`types.py:19-46`) y `tests/test_event_types.py:12` congela la
lista.

### D-5 — El default de `IMMOBILE` en la tabla de SPEC (`SPEC_v2.md:470`) está vacío

La celda "Default" de la fila `IMMOBILE` está en blanco en SPEC. El CONTEXT la
completa a `20 px / 60 s` a partir del texto de la regla. **Seguir el CONTEXT**
(está en Locked Decisions).

---

## Standard Stack

**Cero dependencias nuevas.** [VERIFIED: `requirements.txt` no necesita cambios]

### Core (ya en el proyecto)

| Módulo | Origen | Uso en esta fase |
|---|---|---|
| `math` (stdlib) | — | `hypot` para desplazamiento neto y velocidad |
| `dataclasses` (stdlib) | — | `BehaviorFinding`, `_TrackAgg` (patrón `identity.py`/`gallery.py`) |
| `pydantic-settings` | ya en uso | Umbrales en `backend/config.py` con `@model_validator` |
| `supervision` | ya en uso | Solo indirectamente: `sv.PolygonZone.trigger()` en `detection.py:238` da la pertenencia a zonas |

**No usar `numpy` en `behavior.py`.** Con estado O(1) por track, `math.hypot` sobre
floats de Python es más rápido que crear arrays de 2 elementos, y mantiene el módulo
sin dependencias pesadas (`gallery.py` sí usa numpy porque maneja vectores 512D; aquí
son 2 coordenadas).

### Alternatives Considered

| En vez de | Se podría usar | Por qué no |
|---|---|---|
| Agregados O(1) | Ampliar `history_len` a 1000 | +120 KB/track para todos los consumidores, ninguno lee el historial hoy, y `TrackRegistry` no tiene cota dura de tracks (Q1) |
| Agregados O(1) | Historia propia submuestreada a 1 Hz | 30x más memoria (17,7 KB vs 584 B) para un resultado idéntico; añade su propio gate temporal y pierde resolución justo en modo degradado (Q1) |
| Latch en el dominio | `debounce_secs` de `rules.yaml` | Actúa después de persistir y difundir el evento; no evita las 480 filas/min en SQLite (Q4) |
| `BehaviorFinding` | `analyze() -> list[Event]` (SPEC) | Rompe la pureza de `perception/` establecida en las Fases 24/25 (D-3) |

**Installation:** ninguna.

---

## Architecture Patterns

### System Architecture Diagram

```text
RTSP ─► CaptureWorker ─► FrameBroker (latest-frame)
                              │
                              └─► DetectionWorker._loop          [hilo, sin await]
                                     │
                                     ├─(1) detect_sv + tracker.update      (YOLO, ~60-100 ms)
                                     ├─(2) rate.observe(latencia)   ◄── mide SOLO (1)
                                     ├─(3) registry.update_from_detections(tracked, now)
                                     │        └─► TrackState.centroid_history  ((t,x,y) a FPS de detección)
                                     ├─(4) _update_zones_and_heat(...)
                                     │        ├─ sv.PolygonZone.trigger() → inside:set[int] por zona
                                     │        └─► EventEngine.process_zone()  ──┐
                                     │                 │ diff contra _zone_inside │
                                     │                 │ + _zone_entry_at (NUEVO) │
                                     │                 └─► ZONE_ENTERED           │
                                     │                     ZONE_EXITED{duration_s}│ (BEH-04)
                                     │                                            │
                                     ├─(5) BehaviorAnalyzer.analyze(...)  ◄── NUEVO, ~12 µs
                                     │        entrada: frame_ids, centroides del frame,
                                     │                 zone_membership, now (monotónico)
                                     │        estado:  dict[track_id → agregado O(1) + latches]
                                     │        salida:  list[BehaviorFinding]  (NUNCA Event)
                                     │        └─► EventEngine.emit_behavior() ───┤
                                     │                 traduce a Event tipado    │
                                     │                 LOITERING / RUNNING /     │
                                     │                 IMMOBILE / CROWD_DETECTED │
                                     ├─(6) _emit_track_lifecycle → PERSON_ENTERED/EXITED
                                     └─(7) registry.prune(now) + analyzer.prune(now, frame_ids)
                                                                                  │
                                                                                  ▼
                                                                            EventBus (thread→loop)
                                     ┌────────────────────────────────────────────┤
                                     ▼            ▼              ▼                ▼
                              _persist_event  _broadcast_v2  _apply_rules   metrics.events_total
                              (SQLite, JSON)   (WebSocket)   (RuleEngine)   (Prometheus, gratis)
                                                                  │
                                                        when.event: LOITERING
                                                        when.duration_gte → payload["duration_s"]
```

Construcción (no en el camino caliente):
```text
CameraPipeline.__init__
  ├─ self.identity_fsm  = IdentityStateMachine(...)   ← FUERA de la factoría (Fase 24)
  ├─ self.reid_gallery  = TrackGallery(...)            ← FUERA de la factoría (Fase 25)
  └─ self.behavior      = BehaviorAnalyzer(...)        ← FUERA de la factoría (Fase 26) ★
                                │
        _make_detection() ──────┘  (WorkerSupervisor la re-ejecuta en cada reinicio)
```

### Recommended Project Structure

```text
backend/
  perception/
    behavior.py            # NUEVO — BehaviorFinding + BehaviorAnalyzer (dominio puro)
    face/identity.py       # referencia de patrón: FSM, emits, on_tick, cota de _states
    reid/gallery.py        # referencia de patrón: reloj inyectado, prune, _enforce_cap
  events/
    engine.py              # + emit_behavior(), + _zone_entry_at en process_zone
  pipeline/
    detection.py           # + llamada al analizador en _loop, try/except, prune
    manager.py             # + construcción fuera de la factoría, + params
  config.py                # + bloque "Análisis de comportamiento (Fase 26)"
  main.py                  # + propagación de settings
```

### Pattern 1 — Dominio puro con reloj inyectado (Fases 24/25)

**Qué:** la clase de dominio no importa `time`, no arranca hilos, no hace I/O y no
construye eventos. Todo método que dependa del reloj recibe `now: float` monotónico.

**Cuándo:** siempre, para todo lo que vaya en `backend/perception/`.

```python
# Fuente: backend/perception/reid/gallery.py:33-43 (patrón a copiar)
class TrackGallery:
    """Reloj inyectado: ningun metodo llama a time.monotonic(). Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock — igual que IdentityStateMachine."""
    def needs_embedding(self, track_id: int, now: float) -> bool: ...
    def update(self, track_id: int, emb, identity: int | None, now: float) -> None: ...
```

Aplicado aquí: `BehaviorAnalyzer.analyze(frame_ids, centroids, zone_membership, now)`.
Un solo hilo lo llama (`DetectionWorker._loop`) → **sin lock**, igual que
`TrackGallery`. Documentarlo en el docstring, como hacen los otros dos.

### Pattern 2 — Agregado incremental con ancla (IMMOBILE / LOITERING)

**Qué:** en vez de guardar la trayectoria y escanearla, mantener el mínimo estado que
responde a la pregunta. Para "no se ha movido más de R px en los últimos T s":

```python
# Estado por track: 7 floats. Sin deque, sin lista, sin numpy.
#   anchor_t, anchor_x, anchor_y, min_x, max_x, min_y, max_y

def _update_immobile(agg, now: float, x: float, y: float, radius_px: float) -> float:
    """Devuelve los segundos que el track lleva dentro de un cuadrado de lado radius_px."""
    agg.min_x = min(agg.min_x, x); agg.max_x = max(agg.max_x, x)
    agg.min_y = min(agg.min_y, y); agg.max_y = max(agg.max_y, y)
    span = max(agg.max_x - agg.min_x, agg.max_y - agg.min_y)
    if span > radius_px:
        # Se salió del radio: el episodio de inmovilidad empieza de cero aquí.
        agg.anchor_t = now
        agg.min_x = agg.max_x = x
        agg.min_y = agg.max_y = y
    return now - agg.anchor_t
```

**Por qué la caja envolvente y no la distancia al ancla:** con la distancia al ancla
la garantía sería "todos los puntos a ≤ R del ancla", lo que permite un diámetro real
de 2R. Con la caja envolvente, `span` **es** la extensión real del recorrido, que es
lo que dice la regla ("desplazamiento < 20 px").

**Cuándo NO usarlo:** si en el futuro hiciera falta reevaluar con umbrales distintos
sobre el pasado (no es el caso hoy) o calcular estadísticas sobre la forma de la
trayectoria (Fase 27, contexto de escena) — ahí sí haría falta historia.

### Pattern 3 — Ventana corta leída del `centroid_history` existente (RUNNING)

**Qué:** para ventanas ≤ 12 s, `TrackState.centroid_history` ya sirve; se recorre
desde el final hacia atrás por tiempo, no por índice.

```python
def _window_speed(history, now: float, window_s: float) -> float | None:
    """Velocidad media (desplazamiento NETO / Δt) sobre los últimos window_s segundos.
    None si el track aún no tiene window_s de historia."""
    if not history:
        return None
    t_now, x_now, y_now = history[-1]
    old = None
    for t, x, y in reversed(history):          # 3-12 iteraciones a 3-12 FPS
        old = (t, x, y)
        if t_now - t >= window_s:
            break
    if old is None or t_now - old[0] < window_s:
        return None                            # guarda: historia insuficiente
    dt = t_now - old[0]
    return math.hypot(x_now - old[1], y_now - old[2]) / dt
```

**Invariante que respeta:** el corte es por `t`, nunca por número de muestras — es lo
que lo hace inmune a los escalones de `AdaptiveRate` (H-4, corrección 2).

### Pattern 4 — Latch de estado con re-armado (idempotencia)

**Qué:** un booleano que se pone a `True` al emitir y solo se re-arma cuando la
condición deja de cumplirse. Es el patrón literal de `camera_offline`.

```python
# Fuente: backend/events/engine.py:144-154 (patrón a copiar)
def camera_offline(self, now: datetime.datetime) -> None:
    if self._camera_offline:
        return
    self._camera_offline = True
    self._publish(EventType.CAMERA_OFFLINE, ts=now, severity=Severity.CRITICAL)

def camera_recovered(self, now: datetime.datetime) -> None:
    if not self._camera_offline:
        return
    self._camera_offline = False
    self._publish(EventType.CAMERA_RECOVERED, ts=now)
```

Aplicado aquí con **histéresis** (`camera_offline` no la necesita porque la conexión
es binaria; un umbral numérico sí):

```python
# armar
if not agg.running_latched and speed > run_speed_px_s:
    agg.running_latched = True
    findings.append(BehaviorFinding(kind=RUNNING, track_id=tid,
                                    speed_px_s=speed, duration_s=window_s))
# re-armar (silencioso: no hay evento inverso en el catálogo)
elif agg.running_latched and speed < run_speed_px_s * REARM_RATIO:   # p. ej. 0.8
    agg.running_latched = False
```

### Pattern 5 — Traducción veredicto → evento en `EventEngine`

```python
# Fuente: backend/events/engine.py:196-217 (emit_identity, patrón a calcar)
def emit_behavior(self, finding, now: datetime.datetime,
                  captured_at=None, processed_at=None) -> None:
    event_type = _BEHAVIOR_EVENT_TYPE.get(finding.kind)   # dict, como _identity_event_type
    if event_type is None:
        return
    self._publish(
        event_type, ts=now, captured_at=captured_at, processed_at=processed_at,
        track_id=finding.track_id, zone_id=finding.zone_id,
        payload={k: v for k, v in finding.magnitudes.items() if v is not None},
    )
```

**Nota:** `emit_identity` nunca pasa `severity=` explícita para que el
`@model_validator` de `Event` aplique el default del catálogo (decisión registrada de
la Fase 24, `STATE.md`). Hacer lo mismo aquí.

### Anti-Patterns to Avoid

- **Emitir por frame mientras la condición se cumple.** `engine.py:3-4` lo llama
  literalmente el fallo conceptual de v1. 480 eventos/min/track a 8 FPS.
- **Construir el analizador dentro de `_make_detection`.** Cada reinicio del
  `WorkerSupervisor` borraría anclas y latches → ráfaga de duplicados
  (`manager.py:134-160` documenta el mismo problema resuelto dos veces).
- **Escribir en `TrackState.zones` / `zone_entry_times`.** Segundo dueño del estado de
  zona (invariante 7 de CLAUDE.md); están muertos, que sigan muertos.
- **Contar frames en vez de segundos.** 150 muestras son 12,5 s o 50 s según la carga
  (H-4, corrección 2).
- **Llamar `time.monotonic()` dentro de `behavior.py`.** Rompe el patrón de reloj
  inyectado y hace los tests dependientes del reloj real.
- **Llamar `self._rate.observe()` con el tiempo del analizador.** Contaminaría el
  control adaptativo y `avg_latency` de `/api/v2/cameras/{id}/health` (mismo cuidado
  que la Fase 25 tuvo con ReID).
- **Llamar al campo de duración algo distinto de `duration_s`.** Rompe `duration_gte`
  (`rules.py:88-91`) y con él la mitad del criterio 5.
- **Añadir `DIRECTION_CHANGED` o cualquier `EventType` nuevo.** Fuera de alcance y
  rompería `tests/test_event_types.py:12`.

---

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por qué |
|---|---|---|---|
| Pertenencia de un track a un polígono | Test punto-en-polígono propio | `sv.PolygonZone.trigger()`, ya invocado en `detection.py:238` | Ya está calculado en el mismo frame; recalcularlo duplica coste y puede divergir del conteo de `get_zone_stats()` |
| Idempotencia de eventos | Set de "ya emitidos" con timestamps y limpieza propia | Latch booleano + re-armado, patrón `camera_offline` (`engine.py:144-154`) | 4 líneas, sin estructura que expirar, ya probado en producción |
| Deduplicación de alertas | Lógica de cooldown propia en el analizador | `debounce_secs` de `rules.yaml` (`rules.py:152-158`), **encima** del latch | Ya existe, es configurable por regla y su clave ya contempla `track_id` |
| Publicar el evento al frontend / BD / métricas | Cualquier cosa | `EventEngine._publish` → `EventBus` | `_persist_event`, `_broadcast_v2`, `_apply_rules` y `events_total` ya son genéricos por tipo (`main.py:276-279`, `bus.py:61`) |
| Expiración del estado por track | Barrido propio con `threading.Timer` | `prune(now, frame_ids)` + `_enforce_cap()`, calcado de `gallery.py:129-158` | La Fase 22 fijó el patrón "doble guarda: TTL + cota dura"; hay tests que lo verifican |
| Validación de umbrales | `assert` sueltos | `@model_validator(mode="after")` en `Settings`, como `validate_reid_params` (`config.py:232-249`) | Falla al arrancar con mensaje claro, no a las 3 horas |
| Historial de trayectoria | Buffer nuevo | `TrackState.centroid_history` para ventanas ≤ 12 s; agregados O(1) para el resto | Q1 |

**Key insight:** esta fase es 90 % "conectar piezas que ya existen correctamente" y
10 % lógica nueva. Todo lo que parezca requerir infraestructura nueva (buffer,
scheduler, deduplicador, tabla) es señal de que se está reimplementando algo que ya
está en el repo.

---

## Runtime State Inventory

No aplica en sentido estricto (no es rename/refactor/migración), pero conviene
declarar el estado en runtime que esta fase toca:

| Categoría | Encontrado | Acción |
|---|---|---|
| Datos almacenados | Tabla `events`, columna `payload` (`storage/models.py:102`, tipo `JSON`) | **Ninguna.** Las claves nuevas persisten solas; sin migración de esquema |
| Configuración de servicio viva | `config/rules.yaml` — editable a mano y **no regenerado** salvo que se ejecute `scripts/generate_initial_rules.py` (que sobrescribe, ver cabecera del fichero, líneas 4-5) | Ninguna. La fase **no** debe modificar `rules.yaml` (CONTEXT lo difiere) |
| Estado registrado en el SO | Ninguno | Ninguna |
| Secretos / variables de entorno | Los nuevos parámetros son umbrales numéricos, sin secretos. `Settings.model_config` tiene `extra: "ignore"` (`config.py:211`) → un `.env` viejo sin ellos arranca con los defaults | Ninguna |
| Artefactos de build | Ninguno (sin modelos, sin ONNX, sin binarios) | Ninguna |
| Estado en memoria del proceso | `EventEngine._zone_inside`, `_known_tracks`, `_minute_buckets`; `TrackRegistry._tracks` | Se añaden `EventEngine._zone_entry_at` y `BehaviorAnalyzer._aggs` — **ambos necesitan test de cota** (criterio 4, invariante Fase 22) |

---

## Common Pitfalls

### Pitfall 1 — Contar frames en vez de segundos
**Qué sale mal:** un umbral "480 muestras = 60 s a 8 FPS" pasa a ser 40 s cuando
`AdaptiveRate` sube a 12 FPS y 160 s cuando baja a 3.
**Por qué pasa:** `centroid_history` es un `deque(maxlen=150)`, invita a razonar en
índices. Y el FPS efectivo cambia solo, sin avisar (`rate.py:74-92`).
**Cómo evitarlo:** todo umbral en segundos, todo corte contra el `t` de la tupla.
**Señal temprana:** aparece `len(history)`, `history[-N]` o `int(secs * fps)` en
`behavior.py`.

### Pitfall 2 — El analizador construido dentro de la factoría del worker
**Qué sale mal:** `WorkerSupervisor` reinicia el `DetectionWorker` (por excepción o
por hilo muerto) y todo el estado del analizador se pierde: contadores a cero y
latches re-armados → una ráfaga de eventos duplicados en el frame siguiente.
**Por qué pasa:** `manager.py:96-108` construye el worker dentro de una `def` que la
supervisión re-ejecuta.
**Cómo evitarlo:** `self.behavior = BehaviorAnalyzer(...)` en `__init__`, pasado por
argumento a la factoría (patrón `identity_fsm` y `reid_gallery`).
**Señal temprana:** `BehaviorAnalyzer(` aparece dentro de un `def _make_*`.

### Pitfall 3 — Un evento por frame
**Qué sale mal:** persona parada 10 min → ~4.800 filas en `events` y 4.800 mensajes
WebSocket. El dashboard se cae y la BD engorda.
**Por qué pasa:** las cuatro reglas son condiciones continuas, no transiciones — a
diferencia de `process_tracks`/`process_zone`, que son diffs por naturaleza.
**Cómo evitarlo:** latch por episodio en el dominio (Pattern 4), no `debounce_secs`.
**Señal temprana:** un test que corre 100 frames con la condición activa y espera
1 evento; si sale más de 1, está roto.

### Pitfall 4 — Estado del analizador sin política de expiración
**Qué sale mal:** ByteTrack asigna `track_id` monótonamente crecientes y nunca los
reutiliza (`tracking.py:104-108`); sin poda, `_aggs` crece con cada persona que pasa
y no baja nunca. Rompe el criterio 4 y el invariante de la Fase 22.
**Por qué pasa:** el analizador no puede saber solo cuándo un track ha desaparecido.
**Cómo evitarlo:** `prune(now, frame_ids)` llamado desde `DetectionWorker._loop`
junto a `registry.prune(now)` (línea 185), **más** `_enforce_cap()` invocado también
desde el camino de escritura — la "doble guarda" de `gallery.py:129-158`, cuyo
razonamiento está documentado: "Actua aunque nadie llame a prune() a tiempo".
**Señal temprana:** un test tipo `TEST_behavior_state_bounded` que mete 10.000 tracks
efímeros y comprueba que el estado se queda en un puñado — el patrón exacto de
`tests/test_memory_bounds.py:47-55`.

### Pitfall 5 — `_zone_entry_at` que no se limpia
**Qué sale mal:** el mismo problema que #4, en `EventEngine`.
**Por qué pasa:** si el `pop` se hace solo en la rama de salida y algún camino de
código sale de la zona sin pasar por ahí.
**Cómo evitarlo:** el `pop` va en el mismo bucle `for track_id in exited:` que emite
`ZONE_EXITED`; como `exited = previous - inside_track_ids` (`engine.py:127`), todo
track que desaparece está garantizado ahí. Test: N zonas × 10.000 tracks efímeros,
`len(_zone_entry_at[z]) == 0` al final.

### Pitfall 6 — La velocidad medida como longitud de camino
**Qué sale mal:** el jitter del bbox de YOLO/ByteTrack se acumula frame a frame; a
más FPS, más velocidad aparente para un track quieto. `RUNNING` empezaría a saltar en
las máquinas rápidas y no en las lentas.
**Cómo evitarlo:** desplazamiento neto entre los dos extremos de la ventana / Δt.
**Señal temprana:** un test con jitter puro (±5 px aleatorio, sin desplazamiento) que
exija velocidad ≈ 0.

### Pitfall 7 — Solapamiento de comportamientos ("y ninguno más" del criterio 2)
**Qué sale mal:** una persona parada 130 s dentro de una zona cumple LOITERING **e**
IMMOBILE a la vez. El criterio 2 exige que cada trayectoria produzca *exactamente* el
evento esperado.
**Cómo evitarlo:** dos cosas distintas. (1) En los **tests**, construir las
trayectorias para que aíslen (la de IMMOBILE por debajo de `loiter_secs` o fuera de
zona). (2) En el **producto**, decidir si LOITERING e IMMOBILE son mutuamente
excluyentes o coexisten. Recomendación: **coexisten** (son hechos distintos: "lleva
mucho aquí" vs "no se mueve"), y el aislamiento se resuelve en el test. Añadir
supresión mutua metería política de producto en el dominio sin que ningún requisito
lo pida. → `## Open Questions` #3.

### Pitfall 8 — Nombres de clave del payload inventados
**Qué sale mal:** `duration_gte` de `rules.yaml` deja de funcionar en silencio
(`rules.py:88-91` devuelve `False` si la clave no está → la regla nunca dispara, sin
error ni log).
**Cómo evitarlo:** `duration_s` literal. Test explícito que lo verifique.

### Pitfall 9 — Subir la severidad por defecto sin querer
**Qué sale mal:** meter `LOITERING: Severity.WARNING` en `DEFAULT_SEVERITY` activa la
subida automática de clips a Google Drive (`upload_min_severity="warning"`,
`config.py:115` → `recording.py:309`). Consumo de red y cuota sin que nadie lo pida.
**Cómo evitarlo:** dejar los cuatro en `INFO` (el default) y escalar desde
`rules.yaml` si el usuario lo quiere. → `## Open Questions` #1.

---

## Code Examples

### Bloque de configuración (patrón `config.py`, Fases 24/25)

```python
# backend/config.py — insertar tras el bloque de ReID (config.py:150-165)

    # --- Analisis de comportamiento (Fase 26 — BEH-01..BEH-05) ---
    # Defaults locked de SPEC_v2.md §5.7. Todos los umbrales temporales estan en
    # SEGUNDOS y todos los espaciales en PIXELES del frame procesado
    # (process_width x process_height, 1280x720 por defecto): cambiar la
    # resolucion de proceso cambia el significado de los umbrales en px.
    behavior_enabled: bool = True
    loiter_secs: float = 120.0
    loiter_radius_px: float = 80.0
    run_speed_px_s: float = 350.0
    run_window_secs: float = 1.0
    immobile_secs: float = 60.0
    immobile_radius_px: float = 20.0
    crowd_threshold: int = 5

    @model_validator(mode="after")
    def validate_behavior_params(self) -> "Settings":
        for name in ("loiter_secs", "run_window_secs", "immobile_secs"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser > 0")
        for name in ("loiter_radius_px", "run_speed_px_s", "immobile_radius_px"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser > 0")
        if self.crowd_threshold < 1:
            raise ValueError("crowd_threshold debe ser >= 1")
        if self.run_window_secs > 12.0:
            # centroid_history cubre 12.5 s en el peor caso (150 muestras a 12 FPS,
            # AdaptiveRate.STEPS[0]). Una ventana mayor no se podria calcular.
            raise ValueError(
                "run_window_secs no puede superar 12.0 s: centroid_history solo "
                "garantiza 12.5 s de historial a 12 FPS (tracking.py:47, rate.py:26)"
            )
        return self
```

**Nota sobre `run_window_secs > 12.0`:** ese validador es el que convierte H-4 en algo
imposible de romper por configuración. Es la clase de guarda que las Fases 24/25
añadieron (`validate_identity_params` impide `vote_window < min_votes`, es decir "una
configuración que nunca alcanzaría el mínimo").

### Cableado en `DetectionWorker._loop`

```python
# backend/pipeline/detection.py — dentro de _loop, tras la linea 182
            self._update_zones_and_heat(tracked, frame.image.shape, frame.captured_at, now)
            self._analyze_behavior(tracked, frame.captured_at, now)      # NUEVO
            self._emit_crossings(crossings, frame.captured_at, now)
            self._emit_track_lifecycle(tracked, frame.captured_at, now)
            self._registry.prune(now)

    def _analyze_behavior(self, tracked, captured_at: float, processed_at: float) -> None:
        """Patron de aislamiento de fallos de RecognitionWorker._sync_identity
        (recognition.py:366-374): un fallo del analizador nunca mata el hilo de
        deteccion, solo incrementa el contador de excepciones."""
        if self._behavior is None or self._event_engine is None:
            return
        try:
            findings = self._behavior.analyze(
                registry=self._registry,
                frame_ids=self._registry.frame_ids(),
                zone_membership=self._zone_membership_snapshot(),
                now=processed_at,                     # monotonico, el mismo del frame
            )
            self._behavior.prune(processed_at, self._registry.frame_ids())
        except Exception:
            self._exceptions += 1
            logger.exception("DetectionWorker: analisis de comportamiento fallo")
            return
        wall_now = datetime.datetime.now()
        for f in findings:
            self._event_engine.emit_behavior(f, wall_now, captured_at, processed_at)
```

⚠️ **Orden importante:** `set_frame_ids()` se llama dentro de `_emit_track_lifecycle`
(`detection.py:199`), que va **después**. Si el analizador usa `frame_ids()` verá el
frame **anterior**. Dos salidas: (a) mover el analizador después de
`_emit_track_lifecycle`, o (b) pasarle los ids del frame directamente desde `tracked`.
**Recomendación: (b)** — el analizador recibe explícitamente los datos del frame
(`dict[int, tuple[float,float]]` de centroides) en vez de leerlos del registry. Es más
puro, más testeable y elimina la dependencia de orden. El `centroid_history` sí se lee
del registry, pero solo para RUNNING y solo hacia atrás.

### Dwell time en `process_zone`

```python
# backend/events/engine.py — modificar process_zone (117-138)
    def process_zone(self, zone_id, inside_track_ids, now, captured_at=None,
                     processed_at=None, now_monotonic: float | None = None) -> None:
        previous = self._zone_inside.get(zone_id, set())
        entered = inside_track_ids - previous
        exited = previous - inside_track_ids
        entry_at = self._zone_entry_at.setdefault(zone_id, {})
        for track_id in entered:
            if now_monotonic is not None:
                entry_at[track_id] = now_monotonic
            self._publish(EventType.ZONE_ENTERED, ts=now, captured_at=captured_at,
                          processed_at=processed_at, track_id=track_id, zone_id=zone_id)
        for track_id in exited:
            t0 = entry_at.pop(track_id, None)          # pop: la limpieza va aqui (Pitfall 5)
            payload = {}
            if t0 is not None and now_monotonic is not None:
                payload["duration_s"] = round(now_monotonic - t0, 3)   # BEH-04, clave obligatoria
            self._publish(EventType.ZONE_EXITED, ts=now, captured_at=captured_at,
                          processed_at=processed_at, track_id=track_id, zone_id=zone_id,
                          payload=payload)
        self._zone_inside[zone_id] = set(inside_track_ids)
```

**Compatibilidad:** con `now_monotonic=None` (todos los tests actuales y cualquier
llamador que no se actualice) el comportamiento es idéntico al de hoy salvo un
`payload` vacío. `TEST_zone_transitions` (`test_event_engine.py:52-65`) sigue verde.

### Regla de ejemplo para el criterio 5 (test, no `rules.yaml`)

```yaml
# Solo para el test — NO añadir a config/rules.yaml (CONTEXT lo difiere)
- name: merodeo_nocturno
  enabled: true
  when:
    event: LOITERING          # valida contra EventType sin tocar codigo (rules.py:25)
    duration_gte: 120         # lee payload["duration_s"] (rules.py:88-91)
    time_range: "23:00-06:00"
  debounce_secs: 300.0
  actions:
  - type: notify
```

---

## State of the Art

| Enfoque antiguo | Enfoque actual en este repo | Cuándo cambió | Impacto |
|---|---|---|---|
| Lógica de detección/eventos dentro de `RTSPStream._process_frame` | Workers desacoplados + `TrackRegistry` como punto de encuentro | Fases 17-18 | El analizador debe vivir en un worker, no en la capa web |
| Un evento por detección | `EventEngine` con diff de transiciones (`engine.py:3-4`) | Fase 19 | Los comportamientos continuos necesitan latch propio |
| Estado no acotado en estructuras del pipeline | Doble guarda: TTL + cota dura, con test por estructura | Fase 22 (`test_memory_bounds.py`) | El estado del analizador necesita `prune()` + `_enforce_cap()` + test |
| Lógica de dominio mezclada con el worker | `perception/` como dominio puro con reloj inyectado | Fases 24-25 (`identity.py`, `gallery.py`) | `analyze() -> list[Event]` de SPEC está obsoleto (D-3) |
| Componentes construidos dentro de la factoría del worker | Estado con memoria construido en `CameraPipeline.__init__` | Fases 24-25 (`manager.py:134-160`) | El analizador va fuera de la factoría |

**Obsoleto / muerto en el código actual:**
- `TrackState.zones` y `TrackState.zone_entry_times` (`tracking.py:28-29`) — declarados
  y nunca usados. No resucitarlos.
- `SPEC_v2.md` §5.7 `TrackState` (D-2), `analyze() -> list[Event]` (D-3),
  `DIRECTION_CHANGED` (D-4) y la lista de ficheros de §9 (D-1).

---

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|---|---|
| Framework | pytest 9.0.3 + pytest-asyncio (`asyncio_mode = auto`) |
| Fichero de config | `pytest.ini` (`python_functions = TEST_*`, `asyncio_mode = auto`) |
| Intérprete | `F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe` (Python 3.12.10) — el worktree no tiene `.venv` propio |
| Comando rápido | `.venv/Scripts/python.exe -m pytest tests/test_behavior_analyzer.py -q` |
| Suite completa | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90 s, 413 tests hoy) |
| Línea base | **413/413** tras `25-06` (`STATE.md`) |

### Phase Requirements → Test Map

| Req | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|---|---|---|---|---|
| BEH-01 | LOITERING con umbrales configurables | unit | `pytest tests/test_behavior_analyzer.py -k loiter -q` | ❌ Wave 0 |
| BEH-02 | RUNNING sobre ventana de 1 s | unit | `pytest tests/test_behavior_analyzer.py -k running -q` | ❌ Wave 0 |
| BEH-02 | IMMOBILE 20 px / 60 s | unit | `pytest tests/test_behavior_analyzer.py -k immobile -q` | ❌ Wave 0 |
| BEH-03 | CROWD_DETECTED >= 5 tracks | unit | `pytest tests/test_behavior_analyzer.py -k crowd -q` | ❌ Wave 0 |
| BEH-04 | `duration_s` en ZONE_EXITED | unit (async) | `pytest tests/test_event_engine.py -k zone_dwell -q` | ⚠️ fichero existe, test no |
| BEH-05 | Magnitudes en el payload | unit | `pytest tests/test_behavior_analyzer.py -k payload -q` | ❌ Wave 0 |

### Criterios de éxito del ROADMAP → comando

| # | Criterio | Comando | Nota |
|---|---|---|---|
| 1 | Los 6 eventos se emiten con umbrales configurables | `pytest tests/test_behavior_analyzer.py tests/test_config.py -k "behavior or loiter or crowd or immobile or run_speed" -q` | Config: defaults + rango |
| 2 | Seis trayectorias → exactamente el evento esperado y ninguno más | `pytest tests/test_behavior_analyzer.py -k trajectory -q` | Afirmar sobre el **conjunto** de tipos, no sobre la presencia (Pitfall 7) |
| 3 | Cada evento incluye las magnitudes que lo justifican | `pytest tests/test_behavior_analyzer.py -k payload -q` | Comprobar nombres exactos, `duration_s` incluido |
| 4 | Historial acotado, no crece con la sesión | `pytest tests/test_memory_bounds.py -k behavior -q` | 10.000 tracks efímeros, patrón `test_memory_bounds.py:47-55` |
| 5 | Usables como `when.event` sin tocar `RuleEngine` | `pytest tests/test_rule_engine.py -k behavior -q` | **Debe cargarse desde YAML** con `load_rules`, no solo `Rule.model_validate`, para probar el camino real |
| — | Sin regresión | `pytest tests/ -q` | 413 + nuevos |

### Sampling Rate

- **Por commit de tarea:** el fichero afectado (`pytest tests/test_behavior_analyzer.py -q`).
- **Por merge de wave:** `pytest tests/test_behavior_analyzer.py tests/test_event_engine.py tests/test_detection_worker.py tests/test_memory_bounds.py -q`.
- **Puerta de fase:** `pytest tests/ -q` en verde antes de `/gsd-verify-work`
  (obligatorio: la fase toca pipeline, eventos y configuración → CLAUDE.md §Tests
  punto 2 exige suite completa).
- **Barrera de arquitectura:** `pytest tests/test_architecture.py -q` debe seguir
  verde — `behavior.py` no debe importar `fastapi`, y el nuevo código en
  `detection.py` no debe introducir `await`.

### Wave 0 Gaps

- [ ] `tests/test_behavior_analyzer.py` — fichero nuevo. Cubre BEH-01/02/03/05 y los
      criterios 1, 2 y 3. Incluye el helper local `_walk(...)` de trayectorias.
- [ ] Helper de trayectorias sintéticas — **local al fichero de test**, no en
      `conftest.py`: `conftest.py` son 825 B y no contiene helpers de dominio; el
      repo mantiene los helpers junto a sus tests (`_tracked` en
      `test_detection_worker.py:27`, `_fake_tracked` en `test_memory_bounds.py:34`).
- [ ] Ampliar `tests/test_event_engine.py` — dwell time y `emit_behavior`.
- [ ] Ampliar `tests/test_memory_bounds.py` — `TEST_behavior_state_bounded` y
      `TEST_zone_entry_times_bounded` (criterio 4).
- [ ] Ampliar `tests/test_rule_engine.py` — criterio 5 vía `load_rules` sobre un YAML
      temporal (`tmp_path`).
- [ ] Ampliar `tests/test_config.py` — defaults y validadores de rango
      (patrón `TEST_reid_*`).
- [ ] Ampliar `tests/test_detection_worker.py` — cableado end-to-end reutilizando
      `_tracked_at` (línea 252).
- **Instalación de framework:** ninguna. pytest + pytest-asyncio ya están.

---

## Security Domain

Fase de bajo riesgo de seguridad: sin entrada de red nueva, sin endpoints nuevos, sin
deserialización, sin ficheros nuevos, sin credenciales.

### Applicable ASVS Categories

| Categoría ASVS | Aplica | Control estándar |
|---|---|---|
| V2 Authentication | no | Sin superficie nueva |
| V3 Session Management | no | Sin sesiones |
| V4 Access Control | no | Los eventos salen por el WS ya autenticado (`dashboard_user`/`dashboard_pass`, `config.py:98-99`) |
| V5 Input Validation | **sí** | Umbrales validados con `@model_validator` en `Settings`; `rules.yaml` ya validado con Pydantic sin `eval()` (`rules.py:3-4`) |
| V6 Cryptography | no | Sin criptografía |
| V7 Error Handling | **sí** | `try/except` + `logger.exception` en el worker; ningún dato sensible en el payload de los eventos de comportamiento (solo números y `track_id`) |
| V14 Configuration | **sí** | Config por `pydantic-settings`, `extra: "ignore"` → un `.env` viejo no rompe el arranque |

### Known Threat Patterns

| Patrón | STRIDE | Mitigación |
|---|---|---|
| Inundación de eventos (auto-DoS de SQLite/WebSocket) | Denial of Service | Latch por episodio (Pitfall 3) — **es el riesgo real de esta fase** |
| Crecimiento no acotado del estado por track (OOM a 24/7) | Denial of Service | `prune()` + `_enforce_cap()` con test (Pitfall 4), invariante Fase 22 / PIPE-07 |
| Umbral mal configurado que hace la detección inútil o ruidosa | Tampering (config) | `validate_behavior_params` rechaza valores <= 0 y `run_window_secs > 12.0` |
| Fuga de PII en el payload | Information Disclosure | Los eventos de comportamiento no llevan `person_name` ni recortes; solo magnitudes y `track_id` |
| `pickle` / deserialización insegura | Tampering | Ya prohibido y testeado (`test_architecture.py:117-124`, SEC-15) |

---

## Assumptions Log

| # | Afirmación asumida | Sección | Riesgo si es falsa |
|---|---|---|---|
| A1 | El desplazamiento neto es mejor métrica que la longitud de camino para RUNNING, por el jitter del bbox | Q1-bis, Pitfall 6 | Si el jitter real fuese despreciable, ambas fórmulas darían igual — cambio trivial. Sin cámara real no se puede medir en esta sesión |
| A2 | `LOITERING` con `zone_id=None` (escena implícita) es el comportamiento deseado sin zonas configuradas | Q8 | Es una decisión de producto. Si el usuario prefiere exigir zona, LOITERING no se puede verificar en el entorno actual |
| A3 | `LOITERING` e `IMMOBILE` coexisten en vez de excluirse mutuamente | Pitfall 7 | Si el usuario los quiere excluyentes, cambia la lógica de emisión y las trayectorias del criterio 2 |
| A4 | Dejar los 4 comportamientos en `Severity.INFO` es lo correcto | H-1, Pitfall 9 | Subirlos a `WARNING` activaría la subida automática de clips a Drive |
| A5 | Una latencia de YOLO de ~60-100 ms en CPU deja el presupuesto de 100 ms holgado | Q2 | Aunque fuese peor, el analizador cuesta 12,3 µs (medido) — el margen relativo no cambia la conclusión |
| A6 | El histéresis de re-armado de RUNNING/CROWD (ratio 0,8) es un valor razonable | Pattern 4, Q4 | Un valor mal elegido produce eventos duplicados en el borde del umbral; ajustable sin rediseño |

**Todo lo demás en este documento está VERIFIED contra el código del repo (fichero y
línea) o CITED contra `SPEC_v2.md` / `ROADMAP.md` / `REQUIREMENTS.md`.**

---

## Open Questions

1. **Severidad de los eventos de comportamiento.**
   - Qué sabemos: `DEFAULT_SEVERITY` (`types.py:49-57`) no los incluye → salen `INFO`.
     `upload_min_severity="warning"` (`config.py:115`) controla la subida de clips a
     Drive (`recording.py:309`).
   - Qué no está claro: si el usuario quiere que `CROWD_DETECTED` o `LOITERING`
     disparen grabación/subida automáticamente.
   - Recomendación: **dejarlos en `INFO`** (cambio cero) y escalar desde `rules.yaml`
     si hace falta. Es reversible en una línea.

2. **LOITERING sin zonas configuradas (Q8, A2).**
   - Qué sabemos: una instalación limpia tiene cero zonas → sin fallback, LOITERING
     nunca se emite y el criterio 1 no es verificable.
   - Qué no está claro: si "merodeo en la escena entera" es aceptable como semántica.
   - Recomendación: **escena implícita con `zone_id=None`**, más un
     `loiter_require_zone: bool = False` en config como escape.

3. **¿LOITERING e IMMOBILE se excluyen mutuamente? (Pitfall 7, A3).**
   - Qué sabemos: son condiciones solapables por construcción; el criterio 2 exige
     "exactamente el evento esperado y ninguno más" en las trayectorias de test.
   - Recomendación: **coexisten**; el aislamiento se hace en las trayectorias del
     test, no metiendo supresión mutua en el dominio.

4. **¿Se guarda el `zone_id` de LOITERING cuando el track está en varias zonas a la vez?**
   - Qué sabemos: `sv.PolygonZone` permite polígonos solapados; `_zone_states` es una
     lista y un track puede estar `inside` de varias.
   - Recomendación: llevar el ancla **por (track, zona)** y emitir un LOITERING por
     zona. Alternativa más simple: la primera zona por orden de `created_at`
     (`database.py:299` ordena por ahí). El planner debe elegir; afecta al tamaño del
     estado (multiplica por el nº de zonas solapadas, que en la práctica es 1-2).

---

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|---|---|---|---|---|
| Python | Todo | ✓ | 3.12.10 x64 (`F:/Documentos/IA/Proyecto_Camara/.venv`) | — |
| pytest + pytest-asyncio | Tests | ✓ | pytest 9.0.3 | — |
| `supervision` | `sv.PolygonZone` (indirecto) | ✓ | ya en uso en `detection.py` | — |
| Cámara Tapo real | Verificación en vivo de umbrales (px/s reales, tasa de falsos positivos) | ✗ | — | **Ninguno.** Los umbrales en px dependen de la perspectiva real |
| Zonas configuradas en `data/events.db` | ZONE_ENTERED/EXITED end-to-end | ✗ (tabla vacía por defecto) | — | Test con zonas sintéticas vía `set_zones()` (`manager.py:250`) |

**Dependencias que faltan sin fallback:**
- **Cámara real.** Ninguna de las cuatro reglas se puede calibrar sin ella: 350 px/s
  y 80 px son valores de SPEC, no medidos en esta escena. Esto es un **8º checkpoint
  manual** que se suma a los 7 ya abiertos en `STATE.md`, y no bloquea programar:
  los umbrales son configurables y todo el criterio 2 es determinista con
  trayectorias sintéticas.

**Dependencias que faltan con fallback:**
- **Zonas.** Los tests las inyectan con `pipeline.set_zones([...])`; el producto se
  degrada a escena implícita (Q8).

**Nota de entorno:** el worktree `event-engine-schema-v2-653038` **no tiene `.venv`
propio**. Usar el del repo principal:
`F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe`.

---

## Project Constraints (from CLAUDE.md)

| Directiva | Cómo la cumple esta fase |
|---|---|
| La captura nunca espera a la IA | El analizador vive en `DetectionWorker`, aguas abajo del broker |
| Ningún hilo hace `await` | `behavior.py` es síncrono puro; `test_architecture.py:57-74` lo verifica |
| Ninguna corrutina ejecuta inferencia | No hay inferencia nueva |
| Tracks compartidos → `TrackRegistry` | El analizador **lee** el registry, no crea un segundo estado de tracks |
| No colas ilimitadas / sin estado global oculto | Estado O(1) por track con `prune()` + `_enforce_cap()` y test |
| No añadir dependencias sin necesidad | Cero dependencias nuevas |
| Cambio mínimo | ~1 fichero nuevo + 5 modificados; no se reescribe zonas ni `EventEngine` |
| No inventar APIs ni rutas | Todo lo citado está verificado con fichero:línea |
| Tests: suite completa si toca pipeline/eventos/config | Obligatorio en la puerta de fase (toca los tres) |
| `test_architecture.py` como barrera | Debe seguir verde |
| Windows 11 + Python 3.12 | Verificado: 3.12.10 |
| Nunca exponer credenciales RTSP | Esta fase no toca RTSP ni logs de conexión |

---

## Sources

### Primary (HIGH confidence) — código del repo, leído en esta sesión
- `backend/events/types.py` — catálogo `EventType`, `DEFAULT_SEVERITY`, modelo `Event`
- `backend/events/engine.py` — `_publish`, `process_zone`, `process_tracks`, `camera_offline`, `emit_identity`
- `backend/events/rules.py` — `When`, `_matches`, `duration_gte`, `load_rules`, debounce
- `backend/events/bus.py:61` — `events_total`
- `backend/pipeline/tracking.py` — `TrackState`, `TrackRegistry`, `centroid_history`, `prune`
- `backend/pipeline/detection.py` — `_loop`, `_update_zones_and_heat`, `_emit_track_lifecycle`
- `backend/pipeline/rate.py` — `AdaptiveRate.STEPS`, `should_process`, presupuesto
- `backend/pipeline/manager.py:55-177` — construcción dentro/fuera de las factorías
- `backend/pipeline/recognition.py:355-408` — patrón de aislamiento de fallos y prune
- `backend/perception/face/identity.py` — `IdentityTransition`, `emits`, `on_tick`, cota de `_states`
- `backend/perception/reid/gallery.py` — reloj inyectado, `prune`, `_enforce_cap`
- `backend/config.py` — bloques por fase, `validate_reid_params`, `upload_min_severity`
- `backend/main.py:85-120,276-279,458` — suscriptores del bus, `set_zones`
- `backend/database.py:295-308` — `get_zones`, ausencia de seed
- `backend/storage/models.py:102`, `repositories.py:61` — columna `payload` JSON
- `tests/test_event_engine.py`, `test_detection_worker.py`, `test_memory_bounds.py`, `test_track_gallery.py`, `test_architecture.py`, `test_event_types.py`, `pytest.ini`
- `config/rules.yaml` — esquema real y advertencia de sobrescritura

### Primary (HIGH confidence) — mediciones hechas en esta sesión
- Memoria de `deque` de tuplas `(t,x,y)`: 150 → 22.216 B; 1000 → 145.208 B; 120 → 18.136 B
  (`sys.getsizeof` recursivo, Python 3.12.10 x64 del proyecto)
- Estado O(1) (dataclass de 10 `float`): 584 B
- Coste del agregado incremental: 12,3 µs/frame con 10 tracks (100.000 iteraciones)
- Colección de pytest: `test_track_registry.py` recoge 11 tests con `python_functions = TEST_*`
  incluyendo los 7 nombrados `test_*` (matching case-insensitive en Windows)

### Secondary (MEDIUM confidence) — documentos del proyecto
- `propuesta_mejora/SPEC_v2.md` §5.7 (447-473), §6.1 (479-499), §9 Phase 26 (899-906)
  — **con 5 discrepancias documentadas contra el código real (D-1..D-5)**
- `.planning/ROADMAP.md` líneas 470-481 — goal y 5 criterios de éxito
- `.planning/REQUIREMENTS.md` líneas 231-235 — BEH-01..BEH-05
- `.planning/STATE.md` — decisiones acumuladas de las Fases 24/25, 413/413, 7 checkpoints abiertos
- `.planning/phases/26-an-lisis-de-comportamiento/26-CONTEXT.md` — decisiones bloqueadas

### Tertiary (LOW confidence)
- Ninguna. No hizo falta búsqueda web ni Context7: la fase no introduce dependencias
  externas y todas las decisiones se resuelven contra el código del repo.

---

## Metadata

**Desglose de confianza:**
- Stack: **HIGH** — cero dependencias nuevas, verificado contra `requirements.txt`
- Arquitectura (dónde corre, cómo se construye, cómo emite): **HIGH** — el repo tiene
  dos precedentes idénticos documentados (Fases 24 y 25) y la evidencia es fichero:línea
- Ventana temporal / memoria (Q1): **HIGH** — las tres opciones medidas en la máquina
  del proyecto; el argumento de que no hace falta historia es derivación matemática
  de las cuatro reglas de SPEC, no opinión
- Idempotencia (Q4): **HIGH** — patrón existente en `engine.py:144-154` y motivación
  explícita en el docstring del propio `EventEngine`
- Criterio 5 / `RuleEngine` (Q5): **HIGH** — leído línea a línea; el acoplamiento
  `duration_gte` ↔ `payload["duration_s"]` es literal
- Dwell time (Q3): **HIGH** en el diagnóstico (`zone_entry_times` muerto, verificado
  por grep exhaustivo); **MEDIUM** en la elección del reloj (tres caminos válidos,
  decisión del planner)
- Umbrales y calibración: **LOW** — 350 px/s y 80 px vienen de SPEC, sin validación
  con cámara real. No bloquea: son configurables y los tests son sintéticos
- Fórmula de velocidad (A1): **MEDIUM** — razonamiento sobre el jitter, no medido

**Research date:** 2026-08-15
**Valid until:** sin caducidad externa — no depende de versiones de librerías ni de
documentación de terceros. Solo se invalida si cambia el código citado (`AdaptiveRate.STEPS`,
`history_len`, la firma de `process_zone` o el esquema de `When`).
