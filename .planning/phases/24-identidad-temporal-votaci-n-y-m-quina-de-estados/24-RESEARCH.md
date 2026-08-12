# Phase 24: Identidad temporal — votación y máquina de estados - Research

**Researched:** 2026-08-12
**Domain:** Máquina de estados de identidad + votación temporal sobre resultados ArcFace, dentro de un pipeline multihilo existente
**Confidence:** HIGH (todo verificado leyendo el código real del repo; cero dependencias externas nuevas)

## Summary

Esta fase no necesita investigación de ecosistema: no entran librerías nuevas, la
lógica es puramente algorítmica (deque de votos + FSM) y todo el contrato está
cerrado en `SPEC_v2.md` §5.5 y `24-CONTEXT.md`. El valor de esta investigación está
en lo otro: **el contrato del SPEC no encaja con el código que existe hoy en cinco
puntos concretos**, y tres de ellos son bloqueantes si el planner los da por buenos.

El más importante: **FACE-11 (disparo por evento) es imposible de implementar
tocando solo los ficheros que lista SPEC §9.** El gating del reconocimiento no vive
en `perception/face/engine.py` ni en `recognizer.py` — vive en
`RecognitionWorker._loop`, en `backend/pipeline/recognition.py:110-116`. SPEC §9 no
menciona ese fichero. Tampoco menciona `backend/pipeline/manager.py`, que hay que
tocar porque hoy `RecognitionWorker` no recibe `event_engine` y sin él la máquina de
estados no puede publicar nada.

El segundo: **`PersonRecognizer.process_crop()` no devuelve score.** La firma real es
`process_crop(crop_bgr, tracker_id) -> tuple[int | None, str | None, bool]`
(`backend/recognizer.py:152-154`). `IdentityStateMachine.on_face_result(track_id,
person_id, score)` necesita ese score y `_best_match()` lo calcula (`best_sim`,
`recognizer.py:449`) para luego tirarlo. Hay que sacarlo de ahí.

El tercero: **ya existe una capa de votación por mayoría en `recognizer.py`**
(`_votes: dict[int, deque[int]]` con `VOTE_WINDOW = 5`, líneas 74 y 204-211). Si se
añade `TemporalVoter` encima sin retirar esa, quedan dos votaciones encadenadas y
los parámetros configurados (`window=8, min_votes=3, min_ratio=0.6`) no serán los
efectivos.

**Primary recommendation:** crear `backend/perception/face/identity.py` con
`TemporalVoter` + `IdentityStateMachine` puros (sin I/O, sin threads, reloj
inyectado), retirar `_votes`/`VOTE_WINDOW` de `recognizer.py` y devolver el score
desde `process_crop`, y hacer que `RecognitionWorker` sea el único dueño del ciclo
de vida de la FSM (llama `on_face_result`, decide a quién procesar, publica los
eventos vía `event_engine` recién cableado desde `manager.py`).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Contratos (de SPEC_v2.md §5.5 — locked)**

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

**Estados y transiciones (locked)**

- `UNKNOWN` → `CANDIDATE`: hay match por encima del umbral.
- `CANDIDATE` → `UNKNOWN`: votos insuficientes / incoherentes.
- `CANDIDATE` → `CONFIRMED`: N votos coherentes en la ventana.
- `CONFIRMED` → `TEMPORARILY_LOST`: track sin cara visible.
- `TEMPORARILY_LOST` → `CONFIRMED`: reaparece con match coherente.
- `TEMPORARILY_LOST` → `UNKNOWN`: vence `lost_ttl`.

**Parámetros por defecto (locked, configurables)**

`min_votes=3`, `window=8`, `min_ratio=0.6`, `lost_ttl=30 s`, `revalidate_after=120 s`.
Van a `backend/config.py` vía pydantic-settings, como el resto de la configuración.

**Eventos**

Usa los tipos ya existentes del catálogo (§6.1), sin inventar nuevos:
`PERSON_RECOGNIZED`, `UNKNOWN_PERSON`, `IDENTITY_LOST`.

- `PERSON_RECOGNIZED` se emite **al confirmar**, una sola vez por visita.
- `IDENTITY_LOST` se emite tras 3 revalidaciones fallidas consecutivas.

**Disparo por evento (FACE-11)**

El reconocimiento deja de ejecutarse cada N frames. Se dispara solo cuando:
- aparece un track nuevo,
- la confianza del track es baja,
- vence `revalidate_after` (120 s) en un track `CONFIRMED`.

Objetivo medible: con 1 persona estática en escena, las inferencias faciales por
minuto bajan **al menos un 70%** respecto a la Fase 23.

**Restricciones de arquitectura (de CLAUDE.md — no negociables)**

- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- El estado compartido de tracks vive en `TrackRegistry` (`pipeline/tracking.py`).
- Toda estructura con crecimiento potencial necesita política de expiración con test
  que la verifique (invariante de la Fase 22 — aplica a `TemporalVoter` y a
  `IdentityStateMachine`, ambas citadas explícitamente en su criterio 5).
- Cambio mínimo: no reescribir `recognizer.py`, que la Fase 23 ya dejó reducido a
  orquestación.

### Claude's Discretion

- Estructura interna del voto (deque, contadores) y cómo se agrega la confianza.
- Si `IdentityState` es `Enum` o `StrEnum`, y dónde vive exactamente.
- Reparto entre `identity.py` y los módulos que lo invocan.
- Nombres de los tests, más allá de los ficheros indicados en SPEC §9.

### Deferred Ideas (OUT OF SCOPE)

- **Estado "verificando…" en la interfaz** — el riesgo de SPEC §9 (latencia de
  confirmación percibida) se mitiga mostrando el candidato en la UI desde el primer
  voto. La emisión del estado entra aquí; pintarlo es del bloque C (fases 29-30).
- **ReID por apariencia** para mantener identidad sin cara visible → Fase 25. Esta fase
  cubre la pérdida temporal por `lost_ttl`, no la re-identificación por ropa/silueta.
- **Checkpoint 23-02** (tasa de aciertos ArcFace vs dlib con datos reales) sigue
  pendiente de cámara real. No bloquea esta fase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Descripción (verbatim de REQUIREMENTS.md:216-220) | Soporte en la investigación |
|----|--------------|------------------|
| FACE-07 | Una identidad solo se confirma tras N votos coherentes en una ventana deslizante | `TemporalVoter` nuevo en `identity.py`. **Conflicto:** hay que retirar la votación existente de `recognizer.py:74,204-211` (`_votes`, `VOTE_WINDOW=5`) o quedan dos capas encadenadas → ver Pitfall 1 |
| FACE-08 | Cada track tiene un estado de identidad explícito: UNKNOWN, CANDIDATE, CONFIRMED o TEMPORARILY_LOST | `IdentityStateMachine` + campo `identity_state` en `TrackState` (`pipeline/tracking.py:17-29`). La columna DB `tracks.identity_state` YA existe (`storage/models.py:78`) y nunca se escribe |
| FACE-09 | Una visita de una persona conocida genera un único evento de reconocimiento, no uno por frame | Hoy NO se emite ningún evento de identidad: `EventEngine` no tiene método para ello → ver Mismatch 3. Emisión solo en la transición `→ CONFIRMED` |
| FACE-10 | La pérdida y recuperación de un track no crea identidades duplicadas | El anti-duplicado real ya vive en `_best_match` + `_pending`/`NEW_PERSON_CONSENSUS` (`recognizer.py:229-252`). Lo que aporta la fase 24 es el estado `TEMPORARILY_LOST` indexado por identidad, no por `track_id` → ver Pitfall 3 |
| FACE-11 | El reconocimiento se dispara por evento (track nuevo, confianza baja, revalidación vencida), no ciegamente cada N frames | El gating actual está en `RecognitionWorker._loop` (`pipeline/recognition.py:110-116`) + `_next_candidate` (144-152). **Fichero no listado en SPEC §9** → ver Mismatch 1 |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Acumular votos por track (`TemporalVoter`) | Lógica pura (`perception/face/identity.py`) | — | Sin I/O, sin threads, sin reloj propio → testeable en microsegundos |
| Transiciones de estado (`IdentityStateMachine`) | Lógica pura (`perception/face/identity.py`) | — | Igual: recibe `now` como parámetro, nunca llama `time.monotonic()` internamente |
| Decidir a qué track hacer inferencia (FACE-11) | Worker (`pipeline/recognition.py`) | — | Es donde vive hoy el bucle y el `AdaptiveRate`; único punto con acceso al frame y al registry |
| Ejecutar detección+embedding+matching | `recognizer.py` → `perception/face/{engine,quality,index}.py` | — | Sin cambios salvo devolver el score |
| Publicar `PERSON_RECOGNIZED`/`UNKNOWN_PERSON`/`IDENTITY_LOST` | `events/engine.py` (`EventEngine`) | `pipeline/recognition.py` lo invoca | El EventEngine es el único que conoce `camera_id`, construye el `Event` y llama `bus.publish_threadsafe` |
| Exponer el estado a la UI / métricas | `pipeline/tracking.py` (`TrackState.identity_state`) | `observability/sampler.py` | Ya es el punto de lectura del frontend y del sampler de métricas |
| Persistir `identity_state` | `storage/` (columna ya existe) | — | **Fuera de alcance de esta fase** — nadie escribe `tracks` todavía |

## Standard Stack

### Core

**No entran librerías nuevas.** Todo lo que hace falta está en la stdlib de Python 3.12
y en lo ya instalado.

| Módulo | Origen | Uso |
|--------|--------|-----|
| `collections.deque(maxlen=N)` | stdlib | Ventana deslizante de votos — patrón ya usado en el repo: `TrackState.centroid_history` (`tracking.py:25`), `PersonRecognizer._votes` (`recognizer.py:75`), `LatencyTracker._samples` |
| `collections.Counter` | stdlib | Recuento del ganador — ya usado en `recognizer.py:210` |
| `enum.StrEnum` | stdlib 3.11+ | `IdentityState`. El repo usa `class Severity(str, Enum)` (`events/types.py:13`) y `class EventType(str, Enum)` (línea 19) — coherente con cualquiera de las dos formas |
| `dataclasses.dataclass` | stdlib | Estado por track. Patrón de `TrackState` (`tracking.py:16`) y `FaceQuality` (`quality.py:27`) |
| `threading.RLock` | stdlib | Solo si la FSM se comparte entre hilos. **Recomendación: no compartirla** — que viva dentro de `RecognitionWorker` y sea de un solo hilo |

**Instalación:** ninguna. `requirements.txt` no cambia.

### Alternatives Considered

| En lugar de | Se podría usar | Trade-off |
|-------------|---------------|-----------|
| FSM escrita a mano (dict de transiciones) | `transitions`, `python-statemachine` | Dependencia nueva para 4 estados y 6 transiciones. Contradice CLAUDE.md ("no añadir dependencias por funciones pequeñas"). **Rechazado.** |
| `deque(maxlen=window)` de `(person_id, score)` | Contadores incrementales por persona | El deque es O(window) por consulta con window=8 — irrelevante. El contador incremental es más rápido pero mucho más difícil de razonar con expiración. **Deque gana.** |
| `time.monotonic()` dentro de la FSM | `now: float` inyectado por parámetro | El SPEC ya inyecta `now` en `on_tick(now)`. Hacerlo en TODOS los métodos hace los tests deterministas sin `freezegun` ni `sleep`. **Inyectar siempre.** |

## Architecture Patterns

### Flujo actual (Fase 23) — verificado en código

```
CaptureWorker ──► FrameBroker ──► Subscription("recognition")
                                        │
                                        ▼
                          RecognitionWorker._loop()          recognition.py:99-142
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  │                     │                     │
         _maybe_prune(now)     _rate.should_process(now)   _next_candidate(now)
         recognition.py:161    AdaptiveRate 2 FPS fijo     recognition.py:144-152
         cada 10 s                                        filtra person_id is None
                                        │
                                        ▼
                            _crop_for(frame.image, bbox)   recognition.py:154
                                        │
                                        ▼
                  recognizer.process_crop(crop, track_id)  recognizer.py:152
                    ├─ FaceEngine.detect()                 face/engine.py:79
                    ├─ _select_face()                      recognizer.py:398
                    ├─ FaceQualityAssessor.assess()        face/quality.py:50
                    ├─ FaceEngine.embed()                  face/engine.py:93
                    ├─ _best_match() → (pid, name, ambiguous)   recognizer.py:424
                    │    └── best_sim SE CALCULA Y SE DESCARTA  recognizer.py:449
                    ├─ _votes[tid] deque(maxlen=5) + Counter     recognizer.py:204-211
                    └─ _pending[tid] consenso ≥3 → _register()   recognizer.py:229-252
                                        │
                     returns (person_id, name, is_new)  ← SIN SCORE
                                        │
                                        ▼
                  registry.set_identity(tid, pid, name)   recognition.py:136
                                        │
                                        └──► on_identified(crop, pid) ──► galería
                                             (main.py:389 _save_gallery_capture)

  ❌ NINGÚN EVENTO DE IDENTIDAD SE EMITE EN NINGÚN PUNTO DE ESTE FLUJO
```

Cableado (`pipeline/manager.py:114-125`):

```python
self.recognition = RecognitionWorker(
    self.broker.subscribe("recognition", replace=True),
    self.registry, recognizer,
    AdaptiveRate(target_fps=recognition_fps,
                 min_fps=recognition_fps, max_fps=recognition_fps),
    on_identified=on_identified,
)
```

`event_engine` sí se pasa a `DetectionWorker` (`manager.py:82`) pero **no** a
`RecognitionWorker`.

### Flujo objetivo (Fase 24) — propuesto

```
RecognitionWorker._loop()
        │
        ├─► fsm.on_tick(now) ──► [Event, ...]        # lost_ttl vencidos
        │        └──► event_engine.emit_identity(ev) para cada uno
        │
        ├─► _next_candidate(now)   ← REESCRITO: pregunta a la FSM, no a person_id
        │       ├─ track nuevo (state == UNKNOWN)                       → sí
        │       ├─ state == CANDIDATE (aún votando)                     → sí
        │       ├─ state == TEMPORARILY_LOST                            → sí
        │       ├─ state == CONFIRMED y now-last_check > revalidate_after → sí
        │       └─ state == CONFIRMED y dentro de ventana               → NO   ← el 70%
        │
        ├─► crop + recognizer.process_crop(...) → (pid, name, is_new, score)  ← +score
        │
        ├─► ev = fsm.on_face_result(track_id, pid, score, now)
        │       └── internamente: voter.vote(...) + voter.verdict(...) → transición
        │
        ├─► si ev is not None: event_engine.emit_identity(ev)
        │
        └─► registry.set_identity_state(tid, fsm.state_of(tid))
            registry.set_identity(tid, pid, name)   solo al CONFIRMAR

  + diff de active_ids entre iteraciones → fsm.on_track_lost(tid) para los que caen
```

### Pattern 1: Lógica pura + reloj inyectado

**Qué:** `identity.py` no importa `time`, no arranca hilos, no hace I/O. Todos los
métodos que dependan del tiempo reciben `now: float` (monotónico).

**Por qué:** es lo que permite que el criterio de éxito 5 ("revalidación tras 120 s
y tres fallos consecutivos") se teste en microsegundos en vez de esperar 120 segundos
reales. El SPEC ya inyecta `now` en `on_tick(now)`; extenderlo a `on_face_result` y
`on_track_lost` es discrecional y muy recomendable.

**Precedente en el repo:** `AdaptiveRate.should_process(now)` (`pipeline/rate.py:55`)
está diseñado exactamente así, y su docstring lo dice: *"determinista y facil de
testear con reloj simulado"*.

### Pattern 2: Prune por TTL propio, NO por `active_ids`

**Qué:** el resto del proyecto poda estado por track con `prune(active_tracker_ids)`
(`recognizer.py:340-351`, invocado desde `recognition.py:175` y `main.py:194`).
`IdentityStateMachine` **no puede** usar ese patrón sin más.

**Por qué:** `TEMPORARILY_LOST` existe precisamente para sobrevivir a que el track
desaparezca. Si se poda por `active_ids`, el estado se borra en el mismo instante en
que empieza a ser útil y la transición `TEMPORARILY_LOST → CONFIRMED` nunca ocurre.

**Cómo:** dos niveles.
- `TemporalVoter._votes[track_id]` → sí se puede podar por `active_ids` (es un deque
  por track vivo).
- `IdentityStateMachine._states[track_id]` → se poda por `lost_ttl` en `on_tick(now)`.
  Un track en `TEMPORARILY_LOST` se elimina cuando `now - lost_at > lost_ttl`; uno en
  `UNKNOWN`/`CANDIDATE` cuyo track ya no está activo se elimina inmediatamente.

**Dato relevante:** `TrackRegistry.prune(now, ttl=30.0)` (`tracking.py:98`) usa 30 s
por defecto y `DetectionWorker` lo llama con el default (`detection.py:185`). Es el
mismo valor que `lost_ttl=30 s`. Coincidencia, no causalidad — el planner debería
mantenerlos como parámetros independientes.

### Pattern 3: El worker es el único con estado mutable compartido

`TrackRegistry` documenta explícitamente (`tracking.py:32-39`):

> Se prohibe que dos workers escriban el mismo campo: DetectionWorker es el unico
> escritor de bbox/confidence/centroid_history; RecognitionWorker es el unico
> escritor de person_id/person_name via set_identity.

Añadir `identity_state` a `TrackState` respeta ese invariante mientras el único
escritor sea `RecognitionWorker`. Añadir `set_identity_state(track_id, state)` a
`TrackRegistry` (con el mismo `_lock`) es el camino consistente.

### Anti-Patterns to Avoid

- **Meter la FSM en `TrackRegistry`.** El registry es un contenedor de estado con
  lock, sin lógica de dominio. Poner transiciones ahí lo convierte en otra cosa y
  rompe la separación que la Fase 18 estableció.
- **Que `identity.py` publique en el `EventBus` directamente.** Rompe la
  responsabilidad de `EventEngine` (que es quien conoce `camera_id`, aplica severidad
  por defecto y añade `_emitted_at`) y mete `asyncio` en `perception/`.
- **Hacer `on_tick` desde una corrutina de `main.py`.** Tentador (ya hay
  `_housekeeping_loop`), pero mete una segunda fuente de mutación concurrente sobre
  la FSM. Llamarlo desde el propio `_loop` del `RecognitionWorker` la deja de un solo
  hilo y sin lock.
- **Guardar `IdentityState` como string suelto en el registry.** Usar el enum;
  `TrackState.identity_state: IdentityState` con default `UNKNOWN`.

## Don't Hand-Roll

| Problema | No construyas | Usa lo que ya hay | Por qué |
|----------|---------------|-------------------|---------|
| Ventana deslizante acotada | Lista + `pop(0)` manual | `deque(maxlen=window)` | El maxlen ES la política de expiración; test de cota trivial |
| Recuento de mayoría | Bucle contando a mano | `Counter(votes).most_common(1)` | Ya se usa en `recognizer.py:210` |
| Construcción del `Event` | `Event(...)` a mano en `identity.py` | `EventEngine._publish()` (`events/engine.py:45-65`) | Aplica severidad por defecto, `_emitted_at`, `camera_id` y el bridge `publish_threadsafe` |
| Bridge hilo → event loop | `asyncio.run_coroutine_threadsafe` nuevo | `EventBus.publish_threadsafe()` (`bus.py:83`) | Ya resuelto y probado desde la Fase 19 |
| Similitud coseno | `np.dot` a mano en `identity.py` | `IdentityIndex.search()` (`face/index.py:25`) | La FSM recibe scores, no embeddings — no debe tocar numpy |
| Contador de inferencias faciales | Contador nuevo en el worker | `inference_latency_seconds{stage="face"}` `_count` (`recognition.py:132`) | Ya cuenta exactamente una observación por llamada a `process_crop` — es la métrica del criterio 6 |
| Purga periódica | Hilo nuevo | `RecognitionWorker._maybe_prune` (`recognition.py:161`) + `_housekeeping_loop` (`main.py:186-196`) | Dos niveles ya cableados |

**Key insight:** casi todo lo que la fase 24 necesita "de infraestructura" ya existe.
Lo único genuinamente nuevo es la lógica de estados. Si el plan crece más allá de un
fichero nuevo + tres ficheros tocados, algo se está reimplementando.

## Mismatches SPEC ↔ código actual

> Esta es la sección más importante del documento. Cada punto es una discrepancia
> **verificada** entre lo que dice el contrato y lo que hay en el repo hoy.

### Mismatch 1 — SPEC §9 lista los ficheros equivocados (BLOQUEANTE)

SPEC_v2.md:879-882 dice:

> - Crear: `backend/perception/face/identity.py`
> - Modificar: `backend/perception/face/engine.py`, `backend/events/engine.py`

`backend/perception/face/engine.py` tiene 106 líneas y es un adaptador *thin* de
insightface: `FaceCandidate` (dataclass), `FaceEngine.__init__`, `.available`,
`.detect(frame)`, `.embed(frame, cand)`. **No conoce tracks, no conoce identidades,
no conoce tiempo.** Su propio docstring lo declara: *"this module does not
reimplement any of that, it only translates insightface's Face objects into the
project's own FaceCandidate type"*. No hay nada natural que cambiar ahí para esta
fase.

Los ficheros que realmente hay que tocar:

| Fichero | Por qué | ¿En SPEC §9? |
|---------|---------|--------------|
| `backend/perception/face/identity.py` | `TemporalVoter`, `IdentityStateMachine`, `IdentityState` | ✅ sí (crear) |
| `backend/events/engine.py` | Método(s) para emitir los 3 eventos de identidad | ✅ sí |
| **`backend/pipeline/recognition.py`** | **FACE-11 vive aquí (`_loop` líneas 99-142, `_next_candidate` 144-152)** | ❌ **no** |
| **`backend/pipeline/manager.py`** | Pasar `event_engine` al `RecognitionWorker` (hoy no lo recibe, líneas 114-125) | ❌ **no** |
| `backend/recognizer.py` | Devolver el score; retirar `_votes` duplicado | ❌ no (y CONTEXT dice "no reescribir") |
| `backend/config.py` | 5 parámetros nuevos | ❌ no (pero CONTEXT sí lo exige) |
| `backend/pipeline/tracking.py` | `identity_state` en `TrackState` (FACE-08) | ❌ no |

**Recomendación:** el planner debe usar esta tabla, no SPEC §9. Tocar
`recognition.py` NO viola "cambio mínimo" — es el único sitio donde el requisito
puede cumplirse.

### Mismatch 2 — `process_crop` no devuelve el score (BLOQUEANTE)

Firma real (`backend/recognizer.py:152-154`):

```python
def process_crop(
    self, crop_bgr: np.ndarray, tracker_id: int
) -> tuple[int | None, str | None, bool]:   # (person_id, name, is_new)
```

`on_face_result(track_id, person_id, score)` necesita el score. `_best_match`
(`recognizer.py:424-454`) lo tiene:

```python
best_pid, best_sim = ranked[0]
if best_sim < self._match_threshold:
    return None, None, False        # ← best_sim descartado
if len(ranked) > 1 and (best_sim - ranked[1][1]) < self.MATCH_MARGIN:
    return None, None, True         # ← best_sim descartado
return best_pid, self._name_of(best_pid), False   # ← best_sim descartado
```

Opciones para el planner (discrecional, pero **hay que elegir una explícitamente**):

1. **Añadir un 4º elemento a la tupla** — rompe `recognition.py:123` y los tests
   `test_recognizer_orchestration.py` (que hacen unpacking de 3). Barrido amplio.
2. **Método nuevo `process_crop_scored()`** que devuelva un dataclass y dejar
   `process_crop` como wrapper compatible. Cero roturas. **Recomendado.**
3. **Devolver un dataclass `FaceResult(person_id, name, is_new, score, ambiguous)`**
   y migrar los 2 callers + los tests. Más limpio a largo plazo, más trabajo ahora.

Ojo con `test_architecture.py:15-17`: `INFERENCE_CALLS = {"detect_sv", "detect",
"embed", "process_crop", "identify_or_register"}`. Si se crea un método nuevo que
ejecuta inferencia, **hay que añadirlo a ese set** o el test de arquitectura deja de
proteger esa ruta.

### Mismatch 3 — `EventEngine` no sabe emitir eventos de identidad (BLOQUEANTE)

`EventType.PERSON_RECOGNIZED`, `UNKNOWN_PERSON` e `IDENTITY_LOST` existen en
`events/types.py:27-29` desde la Fase 19, pero **ningún código los emite**. Grep sobre
todo el repo: solo aparecen en `types.py` (declaración), `test_event_types.py:14`
(test de existencia del catálogo) y `test_rule_engine.py:35` (regla de fixture).

`EventEngine` (`events/engine.py`) tiene exactamente estos métodos públicos:
`emit_line_crossing`, `process_tracks`, `process_zone`, `camera_offline`,
`camera_recovered`, `degraded_mode`, `accumulate_detections`, `flush_stats`.
Ninguno de identidad.

Corolario: **no hay payload previo que respetar.** El planner es libre de definirlo.
Campos del `Event` (`types.py:60-74`) relevantes y ya disponibles: `track_id`,
`person_id`, `person_name`, `confidence`, `bbox`. Severidad por defecto ya asignada:
`UNKNOWN_PERSON → WARNING`, el resto `INFO` (`types.py:49-57`).

Nota lateral: `config/rules.yaml` (regla `persona_desconocida`) usa hoy
`event: LINE_CROSSED` + `person: unknown`, **no** `UNKNOWN_PERSON`. Emitir
`UNKNOWN_PERSON` de verdad puede duplicar notificaciones si alguien añade una regla
para él sin retirar la otra. Fuera de alcance, pero conviene anotarlo.

### Mismatch 4 — La métrica `identities_created_total` no existe

`24-CONTEXT.md:159` cita: *"Métrica citada en el criterio 4: `identities_created_total`
= 0 en ese test."*

El catálogo real (`observability/metrics.py:23-46`) tiene:
- `identities_confirmed` — **Gauge**, labels `["camera"]` (línea 89)
- `identities_unknown` — **Gauge**, labels `["camera"]` (línea 92)

Ambas las alimenta `MetricsSampler` (`sampler.py:111-119`) contando tracks del
registry con `person_id is not None`. **No hay ningún counter de identidades
creadas.**

Opciones:
1. Añadir `identities_created_total = Counter("identities_created_total", ...,
   ["camera"])` al catálogo e incrementarlo donde `recognizer._register()` crea una
   persona (`recognizer.py:522-534`). Nota: `_register` está *dentro* de
   `PersonRecognizer`, que no conoce `camera_id` — habría que pasar el incremento
   desde el worker.
2. **Reformular el criterio 4 sin métrica**: contar filas en `persons.db` antes y
   después de la secuencia de test, o afirmar que `registry.get(new_tid).person_id ==
   pid_original`. Más directo, sin tocar el catálogo de métricas. **Recomendado** —
   la métrica es un medio, no el requisito.

Si se añade la métrica, cuidado: `metrics.py:117-123` documenta que añadir algo fuera
del catálogo de SPEC §8.4 requiere justificación explícita.

### Mismatch 5 — `face_fps` no mide inferencias reales (afecta al criterio 6)

`sampler.py:107-109`:

```python
if pipeline.recognition is not None:
    rec_stats = pipeline.recognition.stats
    m.face_fps.labels(camera=camera_id).set(rec_stats.get("effective_fps", 0.0))
```

`effective_fps` viene de `AdaptiveRate.stats` (`rate.py:98-104`) y es el FPS
**objetivo** configurado, no el número de inferencias ejecutadas. Con
`recognition_fps=2.0` fijo (`manager.py:119-120`: `min_fps == max_fps == target`),
`face_fps` marca 2.0 constante aunque `process_crop` no se llame ni una vez.

**Para medir el 70% de FACE-11 hay que usar
`inference_latency_seconds{stage="face"}` y su `_count`** — se observa exactamente
una vez por llamada real a `process_crop` (`recognition.py:132`). `snapshot()`
(`metrics.py:163-176`) ya expone `count` por etiqueta.

Alternativa más simple y auto-contenida: añadir `face_inferences` a
`RecognitionWorker.stats` (hoy devuelve `{"identified", "exceptions", **rate.stats}`,
líneas 87-93) y comparar antes/después en el test.

## Runtime State Inventory

> Fase de código nuevo, no de rename/refactor. Se incluye por el invariante de la
> Fase 22: toda estructura acumulativa nueva necesita política de expiración.

| Categoría | Encontrado | Acción |
|-----------|------------|--------|
| Estructuras nuevas por `track_id` | `TemporalVoter._votes: dict[int, deque]`, `IdentityStateMachine._states: dict[int, ...]` | **Ambas necesitan expiración + test en `tests/test_memory_bounds.py`.** ByteTrack asigna ids monótonamente crecientes y nunca los reutiliza (documentado en `test_memory_bounds.py:41-44`) |
| Estructuras existentes que quedan obsoletas | `PersonRecognizer._votes` (`recognizer.py:75`) si se retira `VOTE_WINDOW` | Si se elimina, hay que actualizar `prune()` (`recognizer.py:348`) y `TEST_recognizer_cache_bounded` (`test_memory_bounds.py:76-89`), que afirma `len(r._votes) == 10` |
| Datos almacenados | `data/persons.db` (tablas `persons`, `face_encodings`, `recognizer.py:456-474`) | Sin migración. La fase no cambia el esquema |
| Columna DB sin usar | `tracks.identity_state VARCHAR(30) NULL` (`storage/models.py:78`) | Existe desde la Fase 19 y **nunca se escribe**. Esta fase produce el valor pero persistirlo está fuera de alcance |
| Código muerto que puede confundir | `should_attempt()`, `identify_or_register()`, `REVERIFY_INTERVAL=300`, `get_cached()` (`recognizer.py:110-150`) | **Verificado por grep: ningún código de producción los llama.** Solo los usan `test_phase9.py:304-314` y `test_recognizer_orchestration.py`. El pipeline vivo usa `_next_candidate` + `process_crop` directamente. No reimplementar FACE-11 sobre `should_attempt` creyendo que es el gate activo |
| Configuración / secretos | Ninguno. Los 5 parámetros nuevos son numéricos sin sensibilidad | Añadir a `config.py` con defaults; `.env` opcional |
| Artefactos de build | Ninguno | — |

## Common Pitfalls

### Pitfall 1: Doble votación encadenada

**Qué falla:** `PersonRecognizer` ya vota por mayoría — `_votes: dict[int, deque[int]]`
con `VOTE_WINDOW = 5` (`recognizer.py:74`), aplicado en las líneas 204-211:

```python
votes = self._votes.setdefault(tracker_id, deque(maxlen=self.VOTE_WINDOW))
votes.append(pid)
winner = Counter(votes).most_common(1)[0][0]
```

Si `TemporalVoter` (window=8, min_votes=3, min_ratio=0.6) recibe el `winner` de esa
mayoría en vez del match crudo del frame, los votos que entran ya están suavizados y
**el criterio 3 falla**: con embeddings ruidosos alternando dos identidades, la capa
interna ya elige un ganador estable, así que la externa confirmará en vez de quedarse
en CANDIDATE.

**Por qué pasa:** la Fase 23 conservó la lógica de negocio de la era dlib intacta
("The business logic below (consensus buffering, majority-vote re-verification,
ratio-test ambiguity handling) is unchanged from the dlib era", docstring de
`recognizer.py:4-7`). Nadie la retiró porque la Fase 24 aún no existía. De hecho
`recognizer.py:78` lo anticipa: `self._confirm_threshold = confirm_threshold  #
reserved for Fase 24's TemporalVoter`.

**Cómo evitarlo:** retirar `_votes`, `VOTE_WINDOW` y el bloque `Counter` de
`process_crop`, dejando que devuelva el match crudo del frame + score. Es una
**eliminación**, no una reescritura — compatible con "no reescribir recognizer.py".

**Señales de alarma:** el test del criterio 3 pasa "demasiado fácil"; el track
confirma en menos votos de los configurados.

### Pitfall 2: `TEMPORARILY_LOST` podado por `active_ids`

**Qué falla:** se sigue el patrón del repo (`prune(active_tracker_ids)`) y el estado
del track se borra en cuanto ByteTrack lo pierde — que es exactamente cuando entra en
`TEMPORARILY_LOST`. La transición `TEMPORARILY_LOST → CONFIRMED` nunca se ejecuta y
el criterio 4 falla.

**Por qué pasa:** `RecognitionWorker._maybe_prune` (`recognition.py:161-177`) llama
`recognizer.prune(registry.active_ids())` cada 10 s, y `_housekeeping_loop`
(`main.py:186-196`) lo repite cada 60 s. Enganchar la FSM ahí "porque es el sitio
donde se poda" es el error natural.

**Cómo evitarlo:** dos políticas distintas — `TemporalVoter` sí por `active_ids`,
`IdentityStateMachine` por `lost_ttl` dentro de `on_tick(now)`.

**Señales de alarma:** el test de pérdida/recuperación de track pasa solo si la
recuperación ocurre en el mismo ciclo del worker.

### Pitfall 3: Indexar el estado "perdido" por `track_id`

**Qué falla:** cuando ByteTrack pierde y recupera a una persona, le asigna un
`track_id` **nuevo** — nunca reutiliza ids (`test_memory_bounds.py:41-42`: *"ByteTrack
asigna ids monotonamente crecientes"*). Si `TEMPORARILY_LOST` se guarda solo bajo el
`track_id` viejo, el track nuevo arranca en `UNKNOWN` y no hay forma de reconectarlo.

**Cómo evitarlo:** el estado `TEMPORARILY_LOST` debe ser consultable **por
`person_id`**, no solo por `track_id`. Cuando llega el primer `on_face_result` de un
track nuevo con `person_id=X` y existe un `TEMPORARILY_LOST` con ese `person_id`
dentro de `lost_ttl`, el track nuevo hereda `CONFIRMED` directamente sin re-votar (y
**sin emitir un segundo `PERSON_RECOGNIZED`** — eso es lo que cierra FACE-09 + FACE-10
a la vez).

**Nota de alcance:** esto es herencia de identidad *por cara*, no por apariencia. La
herencia sin cara visible es la Fase 25 (ReID) y está explícitamente diferida.

**Contexto:** el anti-duplicado a nivel de base de datos ya existe y funciona —
`_best_match` reconoce a la persona ya registrada, y `_pending` +
`NEW_PERSON_CONSENSUS=3` + `CONSENSUS_TOLERANCE=0.30` (`recognizer.py:229-252`)
impiden registrar duplicados. Lo que hoy NO existe es evitar el **segundo evento** y
el hueco de "desconocido" durante la reconexión.

### Pitfall 4: Medir el 70% sobre el baseline equivocado

**Qué falla:** el criterio 6 dice "inferencias faciales por minuto con una persona
estática bajan al menos un 70% respecto a la Phase 23". Pero el baseline de la Fase 23
**depende de si la persona llega a identificarse**:

- **Persona estática que SÍ se identifica:** en cuanto `set_identity` escribe el
  `person_id` (`recognition.py:136`), `_next_candidate` la filtra
  (`recognition.py:147`: `if ts.person_id is None`) y las inferencias caen a **0/min**
  indefinidamente. Baseline = 0. Bajar un 70% de 0 es imposible — y la Fase 24 en
  realidad **añade** carga aquí (revalidación cada 120 s = 0,5 inferencias/min donde
  antes había 0).
- **Persona estática que NO se identifica** (cara no detectable, calidad insuficiente,
  match ambiguo): `_next_candidate` la devuelve siempre, `AdaptiveRate` a 2 FPS fijos
  → **~120 inferencias/min, para siempre**. Este es el caso patológico que FACE-11
  arregla.

**Cómo evitarlo:** definir el escenario del test explícitamente. El único donde el 70%
es medible y significativo es el segundo. Documentar en el plan que la revalidación
periódica es un **coste nuevo aceptado** y que el ahorro neto está en los tracks no
confirmados.

**Señal de alarma:** el test del criterio 6 mide un baseline de 0 y divide por cero.

### Pitfall 5: Nombres de test en minúscula → no se ejecutan en CI

**Qué falla:** `pytest.ini` contiene:

```ini
[pytest]
python_functions = TEST_*
asyncio_mode = auto
```

En Windows `fnmatch` normaliza mayúsculas (usa `os.path.normcase`), así que `TEST_*`
también empareja `test_algo` y todo se recoge localmente — **verificado**: colectar
`test_recognition_worker.py` + `test_memory_bounds.py` da 17 tests aunque el primero
usa `def test_...` en minúscula. En Linux (`.github/workflows/tests.yml:14`,
`runs-on: ubuntu-latest`) el emparejamiento es sensible a mayúsculas y esos tests
**no se recogen**. El workflow tiene `continue-on-error: true` (línea 36), así que
nadie se entera.

**Cómo evitarlo:** nombrar los tests nuevos `TEST_*`, como hacen
`test_memory_bounds.py`, `test_event_engine.py` y `test_phase9.py`.

**Bonus:** `asyncio_mode = auto` significa que un test `async def` no necesita
`@pytest.mark.asyncio`.

### Pitfall 6: Emitir el `Event` desde `perception/`

**Qué falla:** el SPEC firma `on_face_result(...) -> Event | None`, donde `Event` es
el modelo pydantic de `events/types.py:60`, que exige `camera_id: str` y `ts:
datetime` obligatorios. `identity.py` (en `perception/face/`) no conoce ninguno de los
dos, y construirlos ahí acopla `perception/` a `events/` y le mete un `datetime.now()`
que rompe el determinismo de los tests.

**Cómo evitarlo (discrecional, elegir una):**
1. La FSM devuelve un dataclass ligero de transición (`IdentityTransition(track_id,
   from_state, to_state, person_id, confidence)`) y `EventEngine` lo traduce a
   `Event`. Desacopla y mantiene los tests puros. **Recomendado.**
2. La FSM devuelve `EventType | None` + los datos, y el worker llama al método de
   `EventEngine` correspondiente.
3. Se sigue el SPEC literal y la FSM recibe `camera_id` en el constructor.

Nota: `test_architecture.py:127-141` prohíbe que `backend/pipeline/` importe FastAPI,
pero **no** hay ningún test que prohíba `perception/ → events/`. La opción 3 no rompe
nada automáticamente; es una decisión de diseño, no una violación.

## Code Examples

### Patrón de deque acotado con Counter (ya en el repo)

```python
# Source: backend/recognizer.py:204-211 (código real, a retirar en esta fase)
votes = self._votes.setdefault(tracker_id, deque(maxlen=self.VOTE_WINDOW))
votes.append(pid)
winner = Counter(votes).most_common(1)[0][0]
```

### Publicación de eventos desde un hilo (patrón a seguir)

```python
# Source: backend/events/engine.py:45-65
def _publish(self, event_type, ts, captured_at=None, processed_at=None, **fields):
    payload = dict(fields.pop("payload", None) or {})
    payload["_emitted_at"] = time.monotonic()
    if captured_at is not None:
        payload["_captured_at"] = captured_at
    event = Event(type=event_type, camera_id=self._camera_id, ts=ts,
                  payload=payload, **fields)
    self._bus.publish_threadsafe(event)
```

### Emisión solo en transición (patrón exacto que necesita FACE-09)

```python
# Source: backend/events/engine.py:143-153
def camera_offline(self, now: datetime.datetime) -> None:
    if self._camera_offline:
        return                       # ← guarda de idempotencia
    self._camera_offline = True
    self._publish(EventType.CAMERA_OFFLINE, ts=now, severity=Severity.CRITICAL)
```

### Test de eventos con bus real (patrón de `test_event_engine.py`)

```python
# Source: tests/test_event_engine.py:15-48
async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed >= timeout:
            raise AssertionError(f"condition not met within {timeout}s")

def make_engine():
    bus = EventBus(loop=asyncio.get_event_loop())
    received: list = []
    async def capture(event):
        received.append(event)
    bus.subscribe("capture", capture)
    return EventEngine(bus, camera_id="cam1"), received

async def TEST_line_crossing_emits_event():
    engine, received = make_engine()
    engine.emit_line_crossing({...})
    await wait_until(lambda: len(received) == 1)
    assert received[0].type == EventType.LINE_CROSSED
```

### Simular tracks sin cámara (patrón del repo)

```python
# Source: tests/test_memory_bounds.py:32-37 y tests/test_recognition_worker.py:25-31
def _fake_tracked(track_id: int):
    return SimpleNamespace(
        tracker_id=np.array([track_id]),
        xyxy=np.array([[0, 0, 10, 10]], dtype=np.float32),
        confidence=np.array([0.9], dtype=np.float32),
    )

registry = TrackRegistry()
registry.update_from_detections(_fake_tracked(1), now=time.monotonic())
```

### Embeddings sintéticos con similitud controlada (para el criterio 3)

```python
# Source: tests/test_recognizer_orchestration.py:37-44
def _at_similarity(base: np.ndarray, similarity: float, seed: int) -> np.ndarray:
    """A unit vector with cosine similarity ~*similarity* to *base*."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(_DIM).astype(np.float32)
    noise -= np.dot(noise, base) * base
    noise /= np.linalg.norm(noise)
    result = similarity * base + np.sqrt(max(0.0, 1 - similarity**2)) * noise
    return (result / np.linalg.norm(result)).astype(np.float32)
```

Para los tests de la FSM esto probablemente ni haga falta: `on_face_result` recibe
`(person_id, score)` ya resuelto, así que basta con pasar tuplas. Los embeddings
sintéticos son útiles solo si el test cubre el camino completo desde `process_crop`.

### Mocking de `FaceEngine` para no cargar ONNX

```python
# Source: tests/test_recognizer_orchestration.py:5-14 (docstring)
# "These tests mock FaceEngine/FaceQualityAssessor (patched at construction time,
#  so PersonRecognizer never loads a real ONNX model)... IdentityIndex is NOT mocked."
```

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|-----------|-------|
| Framework | pytest ≥7.0 + pytest-asyncio ≥0.24 (`requirements.txt`) |
| Config | `pytest.ini` — `python_functions = TEST_*`, `asyncio_mode = auto` |
| Intérprete | `.venv/Scripts/python.exe` (Windows, Python 3.12) |
| Comando rápido | `.venv/Scripts/python.exe -m pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py -q` |
| Suite completa | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90 s, 326 tests base) |
| Convención | Funciones `TEST_*`; async sin decorador; comentarios de bloque con `─── título ───` explicando el *porqué* del test |

### Phase Requirements → Test Map

| Req | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|-----|---------------|------|----------------------|----------|
| FACE-07 | `TemporalVoter` confirma solo con `min_votes` coherentes en `window` y `ratio ≥ min_ratio` | unit | `pytest tests/test_temporal_voting.py -q` | ❌ Wave 0 |
| FACE-07 | Votos alternando 2 identidades → `verdict()` devuelve `(None, 0.0)` | unit | `pytest tests/test_temporal_voting.py -k ratio -q` | ❌ Wave 0 |
| FACE-08 | Las 6 transiciones, una por test (criterio 1) | unit | `pytest tests/test_identity_state_machine.py -q` | ❌ Wave 0 |
| FACE-08 | `TrackState.identity_state` legible desde el registry | unit | `pytest tests/test_track_registry.py -k identity_state -q` | ❌ Wave 0 (fichero existe) |
| FACE-09 | 200 frames de persona conocida → exactamente 1 `PERSON_RECOGNIZED` (criterio 2) | unit | `pytest tests/test_identity_state_machine.py -k single_recognition -q` | ❌ Wave 0 |
| FACE-09 | `EventEngine` publica los 3 tipos con el payload esperado | integración | `pytest tests/test_event_engine.py -k identity -q` | ❌ Wave 0 (fichero existe) |
| FACE-10 | Pérdida + recuperación de track → mismo `person_id`, 0 personas nuevas en `persons.db` (criterio 4) | integración | `pytest tests/test_identity_state_machine.py -k track_recovery -q` | ❌ Wave 0 |
| FACE-11 | `revalidate_after` a 120 s dispara re-check; 3 fallos → `IDENTITY_LOST` (criterio 5) | unit, reloj simulado | `pytest tests/test_identity_state_machine.py -k revalidate -q` | ❌ Wave 0 |
| FACE-11 | Reducción ≥70% de llamadas a `process_crop` con track no confirmado estático (criterio 6) | integración | `pytest tests/test_recognition_worker.py -k inference_budget -q` | ❌ Wave 0 (fichero existe) |
| Fase 22 | `TemporalVoter._votes` acotado tras 10.000 tracks | unit | `pytest tests/test_memory_bounds.py -k voter -q` | ❌ Wave 0 (fichero existe) |
| Fase 22 | `IdentityStateMachine._states` acotado por `lost_ttl` | unit | `pytest tests/test_memory_bounds.py -k state_machine -q` | ❌ Wave 0 (fichero existe) |
| Regresión | Ningún hilo hace `await`; inferencia fuera de corrutinas | arquitectura | `pytest tests/test_architecture.py -q` | ✅ existe |
| Regresión | La orquestación de `recognizer.py` sigue funcionando tras retirar `_votes` | unit | `pytest tests/test_recognizer_orchestration.py -q` | ✅ existe (**requiere actualización**) |
| Regresión | `TEST_recognizer_cache_bounded` afirma `len(r._votes) == 10` | unit | `pytest tests/test_memory_bounds.py -k recognizer_cache -q` | ✅ existe (**requiere actualización si se retira `_votes`**) |

### Sampling Rate

- **Por commit de tarea:** `pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py -q`
- **Por merge de wave:** `pytest tests/test_temporal_voting.py tests/test_identity_state_machine.py tests/test_recognition_worker.py tests/test_recognizer_orchestration.py tests/test_memory_bounds.py tests/test_event_engine.py tests/test_architecture.py -q`
- **Puerta de fase:** suite completa verde (`pytest tests/ -q`) antes de `/gsd:verify-work`. Toca pipeline, eventos y configuración → CLAUDE.md § Tests exige la suite entera.

### Wave 0 Gaps

- [ ] `tests/test_temporal_voting.py` — nuevo, cubre FACE-07
- [ ] `tests/test_identity_state_machine.py` — nuevo, cubre FACE-08..FACE-11 y criterios 1-5
- [ ] Extender `tests/test_memory_bounds.py` — 2 tests nuevos (invariante Fase 22, criterio 5 de la Fase 22)
- [ ] Extender `tests/test_event_engine.py` — emisión de los 3 eventos de identidad
- [ ] Extender `tests/test_recognition_worker.py` — presupuesto de inferencias (criterio 6) + tests existentes actualizados si cambia la firma de `process_crop`
- [ ] Actualizar `tests/test_recognizer_orchestration.py` y `tests/test_memory_bounds.py::TEST_recognizer_cache_bounded` si se retira `_votes`
- [ ] Añadir el método nuevo de inferencia al set `INFERENCE_CALLS` de `tests/test_architecture.py:15-17` si se crea `process_crop_scored`
- [ ] Instalación de framework: ninguna, ya está todo

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|-------------|---------------|------------|---------|----------|
| Python 3.12 + `.venv` | Todo | ✓ | `.venv/Scripts/python.exe` (raíz del proyecto, no del worktree) | — |
| pytest + pytest-asyncio | Tests | ✓ | ≥7.0 / ≥0.24 | — |
| numpy | Embeddings sintéticos | ✓ | vía opencv/ultralytics | — |
| insightface + onnxruntime | Solo si un test ejecuta ArcFace real | ✓ (instalado, Fase 23) | ≥0.7.3 / ≥1.19 | Mockear `FaceEngine` como hace `test_recognizer_orchestration.py` — **preferible**, evita cargar ONNX |
| Cámara real | Nada de esta fase | ✗ | — | Todos los criterios son verificables con tests sintéticos |
| prometheus-client | Métricas | ✓ | ≥0.21 | — |

**Bloqueantes sin fallback:** ninguno.

**Nota operativa:** el worktree
`.claude/worktrees/event-engine-schema-v2-653038/` **no tiene `.venv` propio**. Usar
`F:/Documentos/IA/Proyecto_Camara/.venv/Scripts/python.exe` desde el worktree, o crear
uno. Verificado ejecutando `pytest --collect-only` con esa ruta.

## Project Constraints (from CLAUDE.md)

| Directiva | Impacto en esta fase |
|-----------|----------------------|
| Ningún hilo hace `await` | La FSM se invoca desde `RecognitionWorker._loop` (hilo). Nada de `async def` en `identity.py`. Protegido por `test_architecture.py:56` |
| Ninguna corrutina ejecuta inferencia | Si se crea un método nuevo que llama a `FaceEngine`, añadirlo a `INFERENCE_CALLS` (`test_architecture.py:15-17`) |
| Tracks compartidos → `TrackRegistry` | `identity_state` va en `TrackState`; único escritor `RecognitionWorker` |
| No dependencias nuevas sin necesidad | Cero. `requirements.txt` sin tocar |
| No colas ilimitadas / estructuras sin cota | `TemporalVoter` y `IdentityStateMachine` necesitan expiración + test |
| Cambio mínimo | Tocar `recognition.py` y `manager.py` es imprescindible para FACE-11; retirar `_votes` de `recognizer.py` es una eliminación, no una reescritura |
| Preferir cambios pequeños y verificables | La FSM pura y sus tests van primero; el cableado al pipeline después |
| No hardcodear config | Los 5 parámetros a `backend/config.py` (`Settings`, sin `python-dotenv`) |
| Tests: solo el fichero afectado durante la iteración; suite completa al final | Reflejado en Sampling Rate |
| Módulos placeholder: docstring de una línea e importables | Aplica si `identity.py` se crea antes de rellenarlo |
| El pipeline no conoce la capa web | `identity.py` no importa FastAPI ni `main` |

## Security Domain

`security_enforcement` no está en `.planning/config.json` (ausente = habilitado).

### Categorías ASVS aplicables

| Categoría ASVS | Aplica | Control estándar |
|----------------|--------|------------------|
| V2 Autenticación | no | La fase no toca auth. `dashboard_user`/`dashboard_pass` sin cambios |
| V3 Gestión de sesión | no | — |
| V4 Control de acceso | no | Sin endpoints nuevos |
| V5 Validación de entrada | parcial | Los parámetros nuevos entran por `pydantic-settings`, que ya valida tipos. Añadir rangos sensatos (`window ≥ min_votes ≥ 1`, `0 < min_ratio ≤ 1`, `lost_ttl > 0`) evita configuraciones que rompan la FSM en silencio |
| V6 Criptografía | no | Sin secretos nuevos |
| V8 Protección de datos | **sí** | Los eventos de identidad llevan `person_id`/`person_name` — dato biométricamente derivado. No debe aparecer en logs con nivel INFO ni en mensajes de excepción |

### Patrones de amenaza para este stack

| Patrón | STRIDE | Mitigación |
|--------|--------|------------|
| Fuga de identidad en logs | Information Disclosure | El repo ya loguea `person %d → %d` con ids, no nombres (`recognizer.py:213-216`). Mantener ese criterio: ids en log, nombres solo en el evento |
| Crecimiento no acotado de estado por track (DoS por agotamiento de memoria) | Denial of Service | Política de expiración + test (invariante Fase 22) |
| Deserialización insegura | Tampering | `test_architecture.py:116` prohíbe `pickle` en `backend/`. La fase no serializa nada |
| Confirmación de identidad con evidencia insuficiente (falso positivo de identidad) | Spoofing | Es literalmente el problema que esta fase resuelve: `min_votes` + `min_ratio` + `MATCH_MARGIN` del ratio test ya existente |

## State of the Art

| Enfoque anterior | Enfoque actual | Cuándo cambió | Impacto |
|------------------|----------------|---------------|---------|
| Reconocimiento en el hilo de captura, gate por frames (`should_attempt`, `RECOG_INTERVAL=30`) | `RecognitionWorker` dedicado con `AdaptiveRate` por latencia | Fase 18 | `should_attempt`/`identify_or_register`/`REVERIFY_INTERVAL` quedaron sin llamadas en producción (verificado por grep) |
| dlib/face_recognition 128D, distancia euclídea | ArcFace 512D L2-normalizado, similitud coseno | Fase 23 | Los umbrales de `config.py:131-135` son coseno; no comparables con los antiguos |
| `FaceAnalysis` con 5 submodelos | `allowed_modules=["detection","recognition"]` | Fase 23 | ~15-40 ms por `detect()` en vez de ~250-370 ms (`STATE.md:64`). Esto hace que 2 FPS de reconocimiento sean baratos — el ahorro de FACE-11 es de CPU marginal, no de un cuello de botella |
| Identidad decidida por frame con voto interno de 5 | Ventana deslizante externa + FSM de 4 estados | **Esta fase** | Retirar el voto interno (Pitfall 1) |

**Obsoleto / a retirar:**
- `PersonRecognizer._votes` + `VOTE_WINDOW` — sustituido por `TemporalVoter`
- `should_attempt`, `identify_or_register`, `REVERIFY_INTERVAL`, `get_cached` — ya
  muertos en producción; su retirada está **fuera del alcance** de esta fase salvo que
  el plan decida limpiarlos (implicaría tocar `test_phase9.py`)

## Assumptions Log

| # | Afirmación | Sección | Riesgo si es falsa |
|---|-----------|---------|--------------------|
| A1 | El baseline del criterio 6 se mide sobre un track NO confirmado (persona estática sin identificar), no sobre uno confirmado | Pitfall 4 | El test del criterio 6 divide por cero o mide un 70% imposible. **Confirmar con el usuario antes de escribir ese test.** |
| A2 | Retirar `_votes`/`VOTE_WINDOW` de `recognizer.py` es compatible con "no reescribir recognizer.py" (es una eliminación) | Pitfall 1 | Si el usuario lo considera reescritura, hay que convivir con doble votación y el criterio 3 no se puede cumplir con los parámetros configurados |
| A3 | Persistir `identity_state` en `tracks` (columna ya existente, `models.py:78`) queda fuera de alcance | Runtime State Inventory | Si entra, hay que escribir filas de `tracks` — hoy nadie lo hace y sería trabajo no previsto |
| A4 | Sustituir `identities_created_total` por una aserción directa sobre `persons.db` es aceptable | Mismatch 4 | Si se exige la métrica literal, hay que ampliar el catálogo de `metrics.py` y justificar la salida de SPEC §8.4 |
| A5 | La transición `CONFIRMED → TEMPORARILY_LOST` se dispara por "resultado facial sin cara utilizable", no por desaparición del track del registry | Flujo objetivo | La desaparición del registry tarda `ttl=30 s` (`tracking.py:98`, llamado con default desde `detection.py:185`) — demasiado tarde. Si se implementa así, `TEMPORARILY_LOST` casi nunca se observa |
| A6 | `on_track_lost` se detecta por diff de `active_ids()` entre iteraciones del worker | Flujo objetivo | `TrackRegistry.prune()` sí devuelve los expirados (`tracking.py:98-106`) pero `DetectionWorker` ignora el retorno (`detection.py:185`), y `recognition.py:161-170` documenta que depender de quién poda primero sería una carrera |
| A7 | El estado `TEMPORARILY_LOST` se indexa también por `person_id` para permitir herencia entre `track_id`s | Pitfall 3 | Sin esto, FACE-10 no se cumple: ByteTrack nunca reutiliza ids |

## Open Questions

1. **¿Qué payload llevan los tres eventos de identidad?**
   - Lo que sabemos: no hay precedente — ninguno se emite hoy. El `Event` ya tiene
     `track_id`, `person_id`, `person_name`, `confidence`, `bbox`.
   - Lo que falta: si `PERSON_RECOGNIZED` debe llevar el estado y el número de votos
     en `payload` (útil para el "verificando…" de la fase 29-30).
   - Recomendación: campos de primer nivel para `track_id`/`person_id`/`person_name`/
     `confidence`; `payload` con `{"state": ..., "votes": ..., "window": ...}`. Es
     aditivo y no rompe nada.

2. **¿`UNKNOWN_PERSON` se emite, y cuándo?**
   - Lo que sabemos: CONTEXT lo lista entre los tipos a usar, pero las transiciones
     locked no dicen en cuál se emite. Los criterios de éxito 1-6 no lo mencionan.
   - Lo que falta: ¿en `CANDIDATE → UNKNOWN`? ¿al primer resultado sin match de un
     track nuevo? ¿tras N intentos fallidos?
   - Recomendación: emitirlo una sola vez por track cuando la FSM concluye que no hay
     identidad (votos agotados sin ganador), con la misma guarda de idempotencia de
     `camera_offline` (`events/engine.py:144-146`). Ojo con la duplicación de alertas
     frente a la regla `persona_desconocida` de `config/rules.yaml`.

3. **¿Qué significa "confianza del track es baja" como disparador de FACE-11?**
   - Lo que sabemos: `TrackState.confidence` (`tracking.py:24`) es la confianza de
     **detección de YOLO**, no de identidad.
   - Lo que falta: si el disparador mira la confianza de detección o la agregada del
     `TemporalVoter`.
   - Recomendación: la del voter (`verdict()[1]`). La de YOLO mide "hay una persona
     ahí", que no dice nada sobre si merece re-reconocerse.

4. **¿`revalidate_after=120 s` se mide desde la confirmación o desde el último
   `process_crop`?**
   - Recomendación: desde la última inferencia facial de ese track. Es lo que hace
     medible el criterio 6 y evita ráfagas tras una revalidación fallida.

5. **¿Los 3 fallos de revalidación que emiten `IDENTITY_LOST` son consecutivos en
   inferencias o en ciclos de revalidación?**
   - Lo que sabemos: CONTEXT dice "tras 3 revalidaciones fallidas consecutivas".
   - Recomendación: 3 revalidaciones (≈360 s de reloj), no 3 inferencias. Consistente
     con la literalidad y testeable con reloj simulado.

## Sources

### Primarias (HIGH confidence — código leído en esta sesión)

- `backend/perception/face/engine.py` (106 líneas) — `FaceEngine.detect/embed`, `FaceCandidate`
- `backend/perception/face/quality.py` (94) — `FaceQuality`, `FaceQualityAssessor.assess`
- `backend/perception/face/index.py` (46) — `IdentityIndex.add/search/rebuild`
- `backend/recognizer.py` (547) — `PersonRecognizer`: `process_crop`, `_best_match`, `_votes`, `prune`, constantes
- `backend/pipeline/recognition.py` (177) — `RecognitionWorker._loop`, `_next_candidate`, `_maybe_prune`
- `backend/pipeline/tracking.py` (106) — `TrackState`, `TrackRegistry`, invariante de escritores
- `backend/pipeline/manager.py` (265) — cableado de workers; `event_engine` NO llega a recognition
- `backend/pipeline/rate.py` (105) — `AdaptiveRate`
- `backend/events/engine.py` (190) — `EventEngine`, `_publish`, métodos existentes
- `backend/events/types.py` (80) — `EventType`, `Event`, `DEFAULT_SEVERITY`
- `backend/events/bus.py` (94) — `EventBus.publish_threadsafe`
- `backend/config.py` (200) — `Settings`, parámetros de la Fase 23
- `backend/observability/metrics.py` (183) — catálogo real de métricas
- `backend/observability/sampler.py` — `identities_confirmed`/`unknown`, `face_fps`
- `backend/storage/models.py` — columna `tracks.identity_state`
- `backend/main.py` — `_housekeeping_loop`, cableado de `EventEngine`, broadcast WS
- `backend/pipeline/detection.py` — llamadas a `event_engine` y `registry.prune`
- `tests/test_memory_bounds.py` (251), `tests/test_architecture.py` (142), `tests/test_recognition_worker.py` (189), `tests/test_recognizer_orchestration.py`, `tests/test_event_engine.py`, `tests/conftest.py`
- `pytest.ini`, `requirements.txt`, `.github/workflows/tests.yml`, `config/rules.yaml`

### Primarias — documentos de planificación

- `propuesta_mejora/SPEC_v2.md` §5.4 (líneas 383-391), §5.5 (393-430), §5.7 (447-473), §6.1 (479-510), §9 Phase 24 (877-884)
- `.planning/ROADMAP.md` § Phase 24 (426-437)
- `.planning/REQUIREMENTS.md` § FACE (208-220)
- `.planning/STATE.md` — estado, mediciones acumuladas
- `.planning/phases/24-.../24-CONTEXT.md`
- `CLAUDE.md`

### Verificaciones ejecutadas en esta sesión

- `grep -rn "PERSON_RECOGNIZED\|UNKNOWN_PERSON\|IDENTITY_LOST"` → 0 emisiones en producción
- `grep -rn "should_attempt\|identify_or_register\|REVERIFY_INTERVAL\|get_cached"` → solo tests
- `grep -rn "identities_created"` → 0 resultados
- `pytest --collect-only -q tests/test_recognition_worker.py tests/test_memory_bounds.py` → 17 tests (confirma que `TEST_*` empareja minúsculas en Windows)

### Secundarias / terciarias

Ninguna. No se consultó documentación externa ni búsquedas web: la fase no introduce
dependencias y todo el contrato es interno al proyecto.

## Metadata

**Desglose de confianza:**
- Stack: HIGH — cero dependencias nuevas, verificado contra `requirements.txt`
- Arquitectura y flujo actual: HIGH — leído línea a línea, con referencias exactas
- Mismatches 1-5: HIGH — cada uno verificado por lectura + grep
- Pitfalls 1-3, 5-6: HIGH — derivados de código y configuración reales
- Pitfall 4 (baseline del 70%): MEDIUM — el razonamiento es sólido pero el escenario
  exacto del criterio 6 no está escrito en ningún sitio (ver A1)
- Open Questions 1-5: MEDIUM/LOW — decisiones de diseño abiertas, sin precedente en
  el repo

**Research date:** 2026-08-12
**Valid until:** indefinido mientras el código no cambie — este documento referencia
números de línea concretos de `backend/` en el commit `7262644`. Si `recognizer.py`,
`recognition.py` o `events/engine.py` se modifican antes de planificar, reverificar
las referencias.
