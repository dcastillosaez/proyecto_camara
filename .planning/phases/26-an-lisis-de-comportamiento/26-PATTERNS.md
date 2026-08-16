# Phase 26: Análisis de comportamiento - Pattern Map

**Mapped:** 2026-08-15
**Files analyzed:** 12 (1 nuevo + 5 modificados + 6 ficheros de test)
**Analogs found:** 12 / 12 (todos con análogo exacto en el repo)

> El diseño ya lo cerró `26-RESEARCH.md` (agregados O(1), latches, `BehaviorFinding`,
> dónde corre y dónde se construye). Este documento **solo** aporta el código real
> que hay que imitar, con fichero y líneas. No rediseña nada.

---

## File Classification

| Fichero nuevo/modificado | Rol | Data flow | Análogo más cercano | Calidad |
|---|---|---|---|---|
| `backend/perception/behavior.py` (CREAR) | domain model + service (dominio puro) | transform (estado por track → veredictos) | `backend/perception/reid/gallery.py` + `backend/perception/face/identity.py` | exacto |
| `backend/events/engine.py` (MOD) | service / traductor dominio→evento | event-driven (pub) | él mismo: `emit_identity` (180-217) y `camera_offline` (144-154) | exacto |
| `backend/events/engine.py` → `process_zone` (MOD) | service | event-driven (diff de conjuntos) | él mismo: `process_zone` (117-138) + `process_tracks` (91-111) | exacto |
| `backend/pipeline/detection.py` (MOD) | worker (hilo) | streaming / bucle caliente | él mismo: `_emit_track_lifecycle` (187-205) y `_emit_crossings` (214-221); aislamiento de fallos en `recognition.py:355-375` | exacto |
| `backend/pipeline/manager.py` (MOD) | composición / factoría | config-time wiring | `manager.py:133-177` (`identity_fsm` Fase 24, `reid_engine`/`reid_gallery` Fase 25) | exacto |
| `backend/config.py` (MOD) | config | config | bloque ReID `config.py:149-177` + `validate_reid_params` (231-248) | exacto |
| `backend/main.py` (MOD) | composition root | config wiring | `main.py:413-444` (propagación `identity_*` / `reid_*`) | exacto |
| `tests/test_behavior_analyzer.py` (NUEVO) | test unitario de dominio | transform | `tests/test_track_gallery.py`, `tests/test_identity_state_machine.py` | exacto |
| `tests/test_event_engine.py` (AMPLIAR) | test async con bus | event-driven | `TEST_zone_transitions` (52-65), `TEST_identity_*` (197-287) | exacto |
| `tests/test_memory_bounds.py` (AMPLIAR) | test de cota | batch | `TEST_track_gallery_bounded` (293-312) | exacto |
| `tests/test_rule_engine.py` (AMPLIAR) | test de carga YAML | file-I/O | `TEST_loads_valid_yaml` (60-67) + `SPEC_RULES_YAML` (13-45) | exacto |
| `tests/test_config.py` (AMPLIAR) | test de config | config | `TEST_reid_defaults_match_spec` (229-238) y siguientes | exacto |
| `tests/test_detection_worker.py` (AMPLIAR) | test de cableado | streaming | `_tracked` (27-35), `_tracked_at` (252-259), `_worker_for_zones` (244-249) | exacto |

**NO TOCAR:** `backend/pipeline/tracking.py` (los agregados O(1) no necesitan historia
nueva; `zones`/`zone_entry_times` están muertos y siguen muertos) y `config/rules.yaml`
(CONTEXT lo difiere).

---

## Pattern Assignments

### `backend/perception/behavior.py` (CREAR — dominio puro, transform)

**Análogos:** `backend/perception/face/identity.py` (para `BehaviorFinding`) y
`backend/perception/reid/gallery.py` (para el módulo, el reloj inyectado y la poda).

#### 1. Docstring de módulo — la declaración de pureza a calcar

`backend/perception/reid/gallery.py:1-14`:

```python
"""TrackGallery — continuidad de identidad por apariencia (SPEC_v2.md §5.6, REID-02/03/04).

Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
eventos. Todos los metodos que dependen del reloj lo reciben como parametro
`now: float` (monotonico), igual que IdentityStateMachine y AdaptiveRate.
La firma de SPEC §5.6 omitia `now` y `active_identities`; sin el primero no se
puede aplicar la ventana de 15 s y sin el segundo no se puede detectar el
conflicto que exige REID-02 (misma correccion que la Fase 24 hizo con
on_face_result).

Fuera de alcance aqui: decidir si la herencia se aplica (esa politica de
producto vive en RecognitionWorker) y transicionar el estado de identidad
(eso es IdentityStateMachine.on_reid_result).
"""
```

`backend/perception/face/identity.py:1-13` dice lo mismo con otras palabras:

```python
"""IdentityState / IdentityTransition / TemporalVoter — identidad temporal (Fase 24).

SPEC_v2.md §5.5 fija el contrato de TemporalVoter (window/min_votes/min_ratio) y
los 4 estados de identidad. Este modulo es dominio puro: no importa `time`, no
arranca hilos, no hace I/O y no construye eventos. Todos los metodos que dependen
del reloj lo reciben como parametro `now: float` (monotonico), igual que
AdaptiveRate.should_process(now) en backend/pipeline/rate.py.

Fuera de alcance aqui: publicar eventos (lo hace EventEngine traduciendo
IdentityTransition) y persistir el estado. [...]
"""
```

> Ambos declaran explícitamente el "fuera de alcance". El de `behavior.py` debe
> declarar como fuera de alcance: construir `Event`, conocer `camera_id`, conocer el
> reloj de pared y decidir la severidad.

#### 2. `BehaviorFinding` — calco literal de `IdentityTransition`

`backend/perception/face/identity.py:29-45` (**este es el modelo a copiar**, incluido
el docstring que justifica por qué NO devuelve un `Event` — corrige la firma de
SPEC §5.7, ver RESEARCH D-3):

```python
@dataclass
class IdentityTransition:
    """Cambio de estado de identidad de un track.

    La FSM devuelve esto, NO un Event: perception/ no conoce camera_id ni el reloj
    de pared. EventEngine lo traduce a Event (o lo descarta si `emits` es False o si
    la transicion no tiene tipo de evento en el catalogo de SPEC_v2.md §6.1).
    """

    track_id: int
    from_state: IdentityState
    to_state: IdentityState
    person_id: int | None = None
    confidence: float = 0.0
    votes: int = 0
    window: int = 0
    emits: bool = True   # False = cambio de estado silencioso (misma visita)
```

Notar el patrón: campos obligatorios primero, opcionales con default después, y
comentario inline solo en el campo no obvio. `BehaviorFinding` debe seguir la misma
forma (`kind`, `track_id`, `zone_id=None`, magnitudes con default `None`).

#### 3. Dataclass de estado interno privado — `_GalleryEntry`

`backend/perception/reid/gallery.py:23-31` — el molde de `_TrackAgg`:

```python
@dataclass
class _GalleryEntry:
    """Ultimo embedding conocido de un track (patron `_TrackIdentity` de identity.py)."""

    emb: np.ndarray                # float32 512D L2-normalizado (2 KB; float64 costaria 4 KB)
    person_id: int | None          # identidad CONFIRMED del track cuando se embebio
    last_seen: float                # ultima vez que el track se refresco: base del TTL
    last_embedded_at: float         # ultima inferencia ReID de este track: base del criterio 5
```

> Prefijo `_`, docstring de una línea que cita el patrón del que deriva, y **un
> comentario por campo explicando qué invariante sostiene**. Los ~10 floats de
> `_TrackAgg` (ancla + caja envolvente + latches) deben ir comentados igual.

#### 4. `__init__` con umbrales inyectados y estado en un solo dict

`backend/perception/reid/gallery.py:33-56`:

```python
class TrackGallery:
    """Memoria de apariencia de los tracks recientes (SPEC_v2.md §5.6, REID-02/04).

    Reloj inyectado: ningun metodo llama a time.monotonic(). Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock — igual que IdentityStateMachine.

    No aplica politica de producto: resolve() calcula SIEMPRE el candidato real y
    devuelve (person_id, similitud). [...]
    """

    def __init__(
        self,
        inherit_window: float = 15.0,
        similarity_threshold: float = 0.7,
        interval: float = 2.0,
        max_entries: int = 256,
    ) -> None:
        self._inherit_window = inherit_window
        self._threshold = similarity_threshold
        self._interval = interval
        self._max_entries = max_entries
        self._entries: dict[int, _GalleryEntry] = {}
```

> `BehaviorAnalyzer.__init__` copia esto literalmente: todos los umbrales con default
> igual al de `config.py`, un único `self._aggs: dict[int, _TrackAgg]`, más `max_tracks`
> para la cota dura. El docstring debe repetir "Reloj inyectado: ningun metodo llama a
> time.monotonic(). Un solo hilo (**DetectionWorker._loop**), por eso no hay lock".

#### 5. `prune()` + `_enforce_cap()` — la doble guarda (criterio 4)

`backend/perception/reid/gallery.py:129-158` — **copiar tal cual, cambiando `_entries`
por `_aggs` y `inherit_window` por el TTL del analizador**:

```python
    def prune(self, now: float, frame_ids: set[int]) -> None:
        """Doble guarda de expiracion, calcada de IdentityStateMachine.on_tick.

        Guarda 1 (TTL): borra entradas mas viejas que la ventana de herencia. Un
        track visible refresca `last_seen` en cada update() (<= 2 s), asi que
        nunca caduca estando en pantalla.
        Guarda 2 (cota dura): ver _enforce_cap — "seguro de vida" de la Fase 22.
        """
        for tid in list(self._entries):
            if tid in frame_ids:
                self._entries[tid].last_seen = now
        for tid in list(self._entries):
            if now - self._entries[tid].last_seen > self._inherit_window:
                del self._entries[tid]
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        """Cota dura por max_entries, LRU por last_seen (Fase 22, "seguro de vida").

        Actua aunque nadie llame a prune() a tiempo — igual que la cota de
        _states en IdentityStateMachine.on_tick (identity.py:450-453). Se llama
        tanto desde update() como desde prune() para que la cota se cumpla sin
        depender del mantenimiento periodico.
        """
        if len(self._entries) <= self._max_entries:
            return
        overflow = len(self._entries) - self._max_entries
        oldest = sorted(self._entries.items(), key=lambda kv: kv[1].last_seen)[:overflow]
        for tid, _ in oldest:
            del self._entries[tid]
```

> Clave: `_enforce_cap()` se invoca **también desde el camino de escritura**
> (`analyze()`), no solo desde `prune()`. Eso es lo que hace pasar
> `TEST_..._bounded_without_prune`.

#### 6. Lectura de `centroid_history` para RUNNING (solo lectura, sin copia)

Fuente del dato — `backend/pipeline/tracking.py:84` (dentro de
`update_from_detections`, bajo `self._lock`):

```python
                ts.centroid_history.append((now, cx, cy))
```

y el acceso — `backend/pipeline/tracking.py:87-89`:

```python
    def get(self, track_id: int) -> TrackState | None:
        with self._lock:
            return self._tracks.get(track_id)
```

Contrato de escritor único que el analizador NO debe romper —
`backend/pipeline/tracking.py:38-45`:

```python
    """
    Estado compartido de tracks, protegido por un unico RLock.

    Se prohibe que dos workers escriban el mismo campo: DetectionWorker es
    el unico escritor de bbox/confidence/centroid_history/_frame_ids (via
    set_frame_ids); RecognitionWorker es el unico escritor de
    person_id/person_name/identity_state via set_identity/set_identity_state.
    """
```

Y el campo muerto que **no** hay que resucitar (`tracking.py:27-29`):

```python
    centroid_history: deque = field(default_factory=lambda: deque(maxlen=150))
    zones: set[str] = field(default_factory=set)
    zone_entry_times: dict[str, float] = field(default_factory=dict)
```

---

### `backend/events/engine.py` — `emit_behavior()` (MOD, event-driven)

**Análogo exacto:** `emit_identity` + `_identity_event_type`, `engine.py:163-217`.
Copiar la estructura completa: tabla estática de traducción → guarda de emisión →
un solo `self._publish(...)`.

```python
    # ------------------------------------------------------------------
    # Identidad (Fase 24)
    # ------------------------------------------------------------------

    @staticmethod
    def _identity_event_type(transition: IdentityTransition) -> EventType | None:
        """Traduce una transicion de la FSM al catalogo de SPEC_v2.md §6.1.

        No hay tipo de evento para CANDIDATE ni para TEMPORARILY_LOST: son estados
        intermedios que la UI leera del TrackRegistry (bloque C), no eventos.
        """
        if transition.to_state is IdentityState.CONFIRMED:
            return EventType.PERSON_RECOGNIZED
        if transition.to_state is IdentityState.UNKNOWN:
            if transition.from_state is IdentityState.CANDIDATE:
                return EventType.UNKNOWN_PERSON
            if transition.from_state in (IdentityState.CONFIRMED,
                                         IdentityState.TEMPORARILY_LOST):
                return EventType.IDENTITY_LOST
        return None

    def emit_identity(
        self,
        transition: IdentityTransition,
        now: datetime.datetime,
        person_name: str | None = None,
        bbox: tuple[int, int, int, int] | None = None,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        """Publica el evento de identidad correspondiente a *transition*, si lo hay.

        FACE-09: una visita genera un unico evento de reconocimiento. La guarda de
        idempotencia vive en la FSM, que marca `emits=False` cuando el cambio de estado
        es continuacion de la misma visita (recuperacion de un track dentro de
        lost_ttl) o cuando el evento ya se emitio para ese track.
        """
        if not transition.emits:
            return
        event_type = self._identity_event_type(transition)
        if event_type is None:
            return
        self._publish(
            event_type,
            ts=now,
            captured_at=captured_at,
            processed_at=processed_at,
            track_id=transition.track_id,
            person_id=transition.person_id,
            person_name=person_name,
            confidence=transition.confidence or None,
            bbox=bbox,
            payload={
                "state": transition.to_state.value,
                "previous_state": transition.from_state.value,
                "votes": transition.votes,
                "window": transition.window,
            },
        )
```

**Cuatro cosas que copiar exactamente:**
1. El import del tipo de dominio arriba del fichero — `engine.py:21`:
   `from backend.perception.face.identity import IdentityState, IdentityTransition`
   → añadir `from backend.perception.behavior import BehaviorFinding, BehaviorKind`.
   La dirección de la dependencia es `events/ → perception/`, **nunca** al revés.
2. La guarda `if not transition.emits: return` con su justificación de idempotencia en
   el docstring (aquí: el latch vive en `BehaviorAnalyzer`, mismo argumento).
3. `event_type is None → return` tras la tabla de traducción.
4. **No pasar `severity=`**: `emit_identity` no la pasa, y así el default del catálogo
   (`types.py:49-57`, que deja los comportamientos en `INFO`) se aplica solo (D-01).

**Firma de `_publish` que da la vía abierta** — `engine.py:46-66`:

```python
    def _publish(
        self,
        event_type: EventType,
        ts: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
        **fields: Any,
    ) -> None:
        """captured_at/processed_at are monotonic timestamps for OBS-03 latency tracking —
        stashed under private payload keys, never part of the public Event contract
        (21-CONTEXT.md). _emitted_at is set unconditionally so downstream (the WebSocket
        broadcast handler) can always measure the EVENT_TO_WS stage."""
        payload = dict(fields.pop("payload", None) or {})
        emitted_at = time.monotonic()
        payload["_emitted_at"] = emitted_at
        if captured_at is not None:
            payload["_captured_at"] = captured_at
        event = Event(type=event_type, camera_id=self._camera_id, ts=ts, payload=payload, **fields)
        self._bus.publish_threadsafe(event)
        if self._latency_tracker is not None and processed_at is not None:
            self._latency_tracker.mark_event(captured_at or 0.0, processed_at)
```

---

### `backend/events/engine.py` — patrón de idempotencia / latch (MOD)

**Análogo exacto:** `camera_offline` / `camera_recovered`, `engine.py:144-154`. Es el
código que RESEARCH manda replicar para los CUATRO comportamientos (sin latch, una
persona parada 10 min genera ~4.800 `IMMOBILE` a 8 FPS).

Estado (`engine.py:36-38`):

```python
        self._known_tracks: set[int] = set()
        self._zone_inside: dict[str, set[int]] = {}
        self._camera_offline = False
```

Latch (`engine.py:144-154`) — **el excerpt literal**:

```python
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

**Cómo se traslada:** el latch de `LOITERING`/`RUNNING`/`IMMOBILE` es un booleano por
`(track_id, comportamiento)` dentro de `_TrackAgg`; el de `CROWD_DETECTED` es un único
booleano de escena en el propio `BehaviorAnalyzer` (analogía 1:1 con
`self._camera_offline`). Diferencia respecto a `camera_offline`: **no hay evento
inverso en el catálogo** (`CROWD_CLEARED` no existe), así que el re-armado es
silencioso — pone el flag a `False` y no publica nada.

El docstring del propio `EventEngine` (`engine.py:1-11`) es la justificación que el
plan debe citar:

```python
"""EventEngine: converts raw pipeline state into typed, transition-only events.

One event per transition, never per frame — this is the point where v1 failed
conceptually. Keeps the previous state of every track (zones, presence) in
memory and only emits when that state actually changes. [...]
"""
```

El otro sabor de idempotencia, por si el planner lo necesita — diff de conjuntos,
`engine.py:91-111`:

```python
    def process_tracks(
        self,
        active_track_ids: set[int],
        now: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        """Diff against the last known set of active tracks; emit only on transitions."""
        entered = active_track_ids - self._known_tracks
        exited = self._known_tracks - active_track_ids
        for track_id in entered:
            self._publish(
                EventType.PERSON_ENTERED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id,
            )
        for track_id in exited:
            self._publish(
                EventType.PERSON_EXITED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id,
            )
        self._known_tracks = set(active_track_ids)
```

---

### `backend/events/engine.py` — `process_zone` + `duration_s` (BEH-04)

**Código actual completo, `engine.py:117-138`** — es lo que hay que modificar de forma
puramente aditiva:

```python
    def process_zone(
        self,
        zone_id: str,
        inside_track_ids: set[int],
        now: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        previous = self._zone_inside.get(zone_id, set())
        entered = inside_track_ids - previous
        exited = previous - inside_track_ids
        for track_id in entered:
            self._publish(
                EventType.ZONE_ENTERED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id, zone_id=zone_id,
            )
        for track_id in exited:
            self._publish(
                EventType.ZONE_EXITED, ts=now, captured_at=captured_at,
                processed_at=processed_at, track_id=track_id, zone_id=zone_id,
            )
        self._zone_inside[zone_id] = set(inside_track_ids)
```

**Estado que ya lleva** (`engine.py:37`): `self._zone_inside: dict[str, set[int]] = {}`
— se declara en `__init__` junto a `_known_tracks` y `_camera_offline`. El nuevo
`self._zone_entry_at: dict[str, dict[int, float]] = {}` va en la misma línea del
`__init__`, con el mismo estilo de anotación explícita.

**Llamador único** — `backend/pipeline/detection.py:248-251`, aquí es donde hay que
añadir el argumento del reloj monotónico:

```python
            if self._event_engine is not None:
                self._event_engine.process_zone(
                    st["id"], inside, datetime.datetime.now(), captured_at, processed_at
                )
```

**Test que no se puede romper** — `tests/test_event_engine.py:52-65` (no inspecciona el
payload, así que un cambio aditivo lo deja verde):

```python
async def TEST_zone_transitions():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.process_zone("z1", {1, 2}, now)  # both enter
    await wait_until(lambda: len(received) == 2)

    engine.process_zone("z1", {2}, now + datetime.timedelta(seconds=5))  # track 1 exits
    await wait_until(lambda: len(received) == 3)

    entered = [e for e in received if e.type == EventType.ZONE_ENTERED]
    exited = [e for e in received if e.type == EventType.ZONE_EXITED]
    assert {e.track_id for e in entered} == {1, 2}
    assert {e.track_id for e in exited} == {1}
```

---

### `backend/pipeline/detection.py` (MOD — worker, bucle caliente)

#### Bucle caliente completo, `detection.py:153-185` (el punto de enganche)

```python
    def _loop(self) -> None:
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            if not self._rate.should_process(time.monotonic()):
                continue

            t0 = time.monotonic()
            try:
                sv_dets = self._detector.detect_sv(frame.image)
                tracked, crossings = self._tracker.update(sv_dets)
            except Exception:
                self._exceptions += 1
                logger.exception("DetectionWorker: fallo de inferencia, se salta el frame")
                continue

            inference_latency = time.monotonic() - t0
            self._rate.observe(inference_latency)
            _metrics.inference_latency_seconds.labels(stage="yolo").observe(inference_latency)
            self._frames_processed += 1
            self._sync_tracker_frame_rate()

            if self._latency_tracker is not None:
                self._latency_tracker.mark_processed(frame)

            now = time.monotonic()  # "processed_at" for OBS-03 — right after inference, before event emission
            _metrics.active_tracks.labels(camera=self._camera_id).set(len(tracked))
            self._registry.update_from_detections(tracked, now)
            self._update_zones_and_heat(tracked, frame.image.shape, frame.captured_at, now)
            self._emit_crossings(crossings, frame.captured_at, now)
            self._emit_track_lifecycle(tracked, frame.captured_at, now)
            self._registry.prune(now)
```

**Datos disponibles en el punto de enganche:** `tracked` (`sv.Detections` con
`tracker_id`/`xyxy`), `now` (monotónico, medido **después** de `self._rate.observe()`
→ el analizador no contamina el control adaptativo), `frame.captured_at` (monotónico
de captura) y `self._event_engine`.

#### `_update_zones_and_heat`, `detection.py:223-260` — de dónde sale la pertenencia a zonas

```python
    def _update_zones_and_heat(
        self, tracked: Any, shape: tuple, captured_at: float = 0.0, processed_at: float = 0.0
    ) -> None:
        """Trigger the PolygonZones and accumulate the activity heat mask (MEJORAS.md Bajas)."""
        fh, fw = shape[:2]
        with self._lock:
            dirty = self._zones_dirty
            self._zones_dirty = False
            zones_snap = list(self._zones)
        if dirty or self._zone_frame_size != (fw, fh):
            self._zone_frame_size = (fw, fh)
            self._rebuild_zone_states(zones_snap, fw, fh)

        ids = tracked.tracker_id
        for st in self._zone_states:
            mask = st["zone"].trigger(tracked)
            inside = (
                {int(ids[i]) for i in np.flatnonzero(mask)}
                if ids is not None and len(mask)
                else set()
            )
            with self._lock:
                st["entries"] += len(inside - st["inside"])
                st["inside"] = inside
                st["current"] = len(inside)
            if self._event_engine is not None:
                self._event_engine.process_zone(
                    st["id"], inside, datetime.datetime.now(), captured_at, processed_at
                )
```

> `st["inside"]` (set de `track_id` por zona, ya bajo `self._lock`) es exactamente el
> `zone_membership` que necesita el analizador. **No recalcular con
> `sv.PolygonZone.trigger()`**: ya está hecho en este mismo frame. Ojo con
> `_zone_states` vacío → el bucle no se ejecuta → LOITERING cae al fallback de escena
> implícita (`zone_id=None`, D-02).

#### Método privado que llama al dominio y emite — molde `_emit_track_lifecycle`, `detection.py:187-205`

```python
    def _emit_track_lifecycle(self, tracked: Any, captured_at: float, processed_at: float) -> None:
        """Publica el estado de tracks del frame actual y, si hay event_engine,
        los eventos de ciclo de vida. Son dos cosas distintas (Fase 24, D-05):
        la publicacion en el registry siempre ocurre; la emision de eventos,
        solo si hay event_engine configurado (CameraPipeline lo tiene a None por
        defecto en la mayoria de tests de este fichero). [...]
        """
        ids = tracked.tracker_id
        active_ids = {int(tid) for tid in ids} if ids is not None else set()
        self._registry.set_frame_ids(active_ids)
        if self._event_engine is None:
            return
        wall_now = datetime.datetime.now()
        self._event_engine.process_tracks(active_ids, wall_now, captured_at, processed_at)
        confidences = list(tracked.confidence) if tracked.confidence is not None else []
        self._event_engine.accumulate_detections(wall_now, active_ids, confidences)
```

Y la guarda corta de `_emit_crossings`, `detection.py:214-221`:

```python
    def _emit_crossings(self, crossings: list[dict], captured_at: float, processed_at: float) -> None:
        if not crossings or self._event_engine is None:
            return
        is_intrusion = bool(self._is_intrusion()) if self._is_intrusion else False
        for c in crossings:
            self._event_engine.emit_line_crossing(
                {**c, "is_intrusion": is_intrusion}, captured_at, processed_at
            )
```

#### Aislamiento de fallos — `backend/pipeline/recognition.py:355-375`

Este es el patrón exacto que debe envolver la llamada al analizador (un fallo del
dominio nunca mata el hilo):

```python
    def _sync_identity(self, now: float) -> None:
        """Tracks caidos + expiraciones de lost_ttl. Un solo hilo, sin lock.

        frame_ids(), no active_ids(): active_ids() tarda hasta 30s (ttl de prune)
        en dejar de ver un track desaparecido, y para entonces ByteTrack ya le
        habria asignado un track_id nuevo al reaparecer -- la FSM emitiria un
        segundo PERSON_RECOGNIZED para la misma visita (D-05).
        """
        if self._fsm is None:
            return
        try:
            transitions = self._fsm.on_active_tracks(self._registry.frame_ids(), now)
            transitions += self._fsm.on_tick(now)
            if self._gallery is not None:
                self._gallery.prune(now, self._registry.frame_ids())
        except Exception:
            self._exceptions += 1
            logger.exception("RecognitionWorker: mantenimiento de la FSM de identidad fallo")
            return
        for t in transitions:
            self._emit_identity(t)
```

> Forma canónica: guarda de `None` → `try` con la llamada al dominio **y** el `prune`
> dentro → `except Exception: self._exceptions += 1; logger.exception(...); return` →
> bucle de emisión **fuera** del `try`.

#### Constructor: cómo entra la dependencia opcional

`detection.py:48-70` — el nuevo `behavior: BehaviorAnalyzer | None = None` va al final
de la firma con default `None` (igual que `event_engine`, `is_intrusion`,
`latency_tracker`), y se guarda como `self._behavior`:

```python
    def __init__(
        self,
        sub: Subscription,
        detector: PersonDetector,
        tracker: PersonTracker,
        registry: TrackRegistry,
        rate: AdaptiveRate,
        event_engine: EventEngine | None = None,
        is_intrusion: Any = None,
        camera_id: str = "cam1",
        latency_tracker: LatencyTracker | None = None,
    ) -> None:
```

El import del tipo va bajo `TYPE_CHECKING` (`detection.py:26-31`), no en tiempo de
ejecución:

```python
if TYPE_CHECKING:
    from backend.detector import PersonDetector
    from backend.events.engine import EventEngine
    from backend.observability.latency import LatencyTracker
    from backend.pipeline.broker import Subscription
    from backend.tracker import PersonTracker
```

---

### `backend/pipeline/manager.py` (MOD — construcción FUERA de la factoría)

**Análogo exacto y prescriptivo:** `manager.py:133-177`. Nótese que el comentario que
justifica el patrón está escrito dos veces, una por fase:

```python
        if recognizer is not None and getattr(recognizer, "available", False):
            # La FSM vive FUERA de la factoria: WorkerSupervisor la re-ejecuta en cada
            # reinicio del worker, y construirla dentro perderia toda la identidad ya
            # confirmada. Mismo motivo por el que _make_streaming rescata `clients`.
            self.identity_fsm = IdentityStateMachine(
                TemporalVoter(
                    window=identity_vote_window,
                    min_votes=identity_min_votes,
                    min_ratio=identity_min_ratio,
                ),
                lost_ttl=identity_lost_ttl,
                revalidate_after=identity_revalidate_after,
                low_confidence=identity_low_confidence,
            )

            if reid_enabled:
                # Motor y galeria viven FUERA de la factoria por el mismo motivo que
                # la FSM: el WorkerSupervisor re-ejecuta la factoria en cada reinicio
                # del worker, y construirlos dentro vaciaria la galeria de apariencia
                # (perdiendo la continuidad de identidad justo tras un reinicio) y
                # recargaria el ONNX cada vez.
                self.reid_engine = ReIDEngine(reid_model_path)
                self.reid_gallery = TrackGallery(
                    inherit_window=reid_inherit_window,
                    similarity_threshold=reid_similarity_threshold,
                    interval=reid_interval,
                    max_entries=reid_max_gallery_entries,
                )

            def _make_recognition() -> RecognitionWorker:
                self.recognition = RecognitionWorker(
                    self.broker.subscribe("recognition", replace=True),
                    self.registry, recognizer,
                    AdaptiveRate(target_fps=recognition_fps,
                                 min_fps=recognition_fps, max_fps=recognition_fps),
                    identity_fsm=self.identity_fsm,
                    event_engine=event_engine,
                    on_identified=on_identified,
                    reid_engine=self.reid_engine,
                    reid_gallery=self.reid_gallery,
                    reid_inherit=reid_inherit,
                )
                return self.recognition

            self.supervisor.register("recognition", _make_recognition)
```

**Los tres pasos a replicar, en orden:**

1. Declarar el atributo con tipo junto a los demás (`manager.py:87-93`):

```python
        self.detection: DetectionWorker | None = None
        self.streaming: StreamingWorker | None = None
        self.recording: RecordingWorker | None = None
        self.recognition: RecognitionWorker | None = None
        self.identity_fsm: IdentityStateMachine | None = None
        self.reid_engine: "ReIDEngine | None" = None
        self.reid_gallery: "TrackGallery | None" = None
```
   → añadir `self.behavior: "BehaviorAnalyzer | None" = None`.

2. Construirlo **antes** de la factoría, gateado por su flag de config
   (`if behavior_enabled:`), con el comentario que explica el porqué.

3. Pasarlo como argumento dentro de la factoría (`manager.py:96-108`), que es la parte
   que el supervisor re-ejecuta:

```python
        if detector is not None and tracker is not None:
            def _make_detection() -> DetectionWorker:
                self.detection = DetectionWorker(
                    self.broker.subscribe("detector", replace=True),
                    detector, tracker, self.registry,
                    AdaptiveRate(target_fps=target, min_fps=lo, max_fps=hi),
                    event_engine=event_engine,
                    is_intrusion=is_intrusion,
                    camera_id=camera_id,
                    latency_tracker=latency_tracker,
                )
                return self.detection

            self.supervisor.register("detector", _make_detection)
```
   → añadir `behavior=self.behavior,` como último kwarg.

**Parámetros de la firma de `CameraPipeline.__init__`** — bloque por fase al final,
todos con default igual al de `config.py` (`manager.py:58-70`):

```python
        identity_vote_window: int = 8,
        identity_min_votes: int = 3,
        identity_min_ratio: float = 0.6,
        identity_lost_ttl: float = 30.0,
        identity_revalidate_after: float = 120.0,
        identity_low_confidence: float = 0.55,
        reid_enabled: bool = True,
        reid_model_path: str = "models/reid/osnet_x0_25_msmt17_dyn.onnx",
        reid_inherit_window: float = 15.0,
        reid_similarity_threshold: float = 0.7,
        reid_interval: float = 2.0,
        reid_inherit: bool = False,
        reid_max_gallery_entries: int = 256,
```

> Nótese la convención: el nombre en `manager.py` **suelta el sufijo `_secs`** que sí
> lleva en `config.py` (`reid_inherit_window_secs` → `reid_inherit_window`,
> `identity_lost_ttl_secs` → `identity_lost_ttl`). Decidir si se mantiene esa
> asimetría o se usan los mismos nombres; lo consistente con las Fases 24/25 es
> soltarlo.

`CameraManager.add` no necesita tocarse (`manager.py:299-302`), reenvía `**kwargs`:

```python
    def add(self, camera_id: str, rtsp_url: str, **kwargs) -> CameraPipeline:
        pipeline = CameraPipeline(camera_id, rtsp_url, **kwargs)
        self._pipelines[camera_id] = pipeline
        return pipeline
```

---

### `backend/config.py` (MOD — bloque por fase con validadores)

**Análogo más reciente:** bloque ReID (Fase 25), `config.py:149-177`:

```python
    # --- Re-identificacion por apariencia (Fase 25 — REID-01..REID-04) ---
    # Defaults de SPEC_v2.md §5.6 / ADR-04. reid_inherit_window_secs es MAS CORTA
    # que identity_lost_ttl_secs (30 s) a proposito: la apariencia es menos fiable
    # que la votacion facial y debe caducar antes. reid_inherit_identity arranca en
    # False (modo solo-observacion): ReID calcula y registra la decision de herencia
    # sin aplicarla, para poder auditar la tasa de falsos positivos con datos reales
    # antes de activarla. El modelo lo produce scripts/fetch_models.py; si falta,
    # ReIDEngine.available queda a False y la via ReID es no-op.
    reid_enabled: bool = True
    reid_model_path: str = "models/reid/osnet_x0_25_msmt17_dyn.onnx"
    reid_inherit_window_secs: float = 15.0
    reid_similarity_threshold: float = 0.7
    reid_interval_secs: float = 2.0
    reid_inherit_identity: bool = False
    reid_max_gallery_entries: int = 256
```

**Forma del comentario de cabecera (obligatoria):** título `--- <Tema> (Fase N — IDs de
requisito) ---` + párrafo que justifica *por qué* los defaults son esos y qué pasa si
alguien los cambia. El bloque de comportamiento debe explicar que los umbrales
espaciales están en **píxeles del frame procesado** (`process_width`/`process_height`).

**Validador de rango — `validate_reid_params`, `config.py:231-248`** (el molde exacto:
`@model_validator(mode="after")`, `-> "Settings"`, un `if` por parámetro y mensajes que
explican la consecuencia, no solo el rango):

```python
    @model_validator(mode="after")
    def validate_reid_params(self) -> "Settings":
        if not 0.0 < self.reid_similarity_threshold <= 1.0:
            raise ValueError(
                "reid_similarity_threshold debe estar en (0, 1]: es un coseno entre "
                "embeddings normalizados; 0.0 heredaria identidad de cualquier "
                "apariencia y valores > 1.0 no heredarian nunca"
            )
        if self.reid_inherit_window_secs <= 0:
            raise ValueError("reid_inherit_window_secs debe ser > 0")
        if self.reid_interval_secs <= 0:
            raise ValueError(
                "reid_interval_secs debe ser > 0: es el minimo entre inferencias "
                "ReID de un mismo track (criterio 5); 0 dejaria correr ReID en cada tick"
            )
        if self.reid_max_gallery_entries < 1:
            raise ValueError("reid_max_gallery_entries debe ser >= 1")
        return self
```

Y el validador de coherencia entre dos parámetros (`validate_identity_params`,
`config.py:213-229`) — el molde para `run_window_secs > 12.0`:

```python
    @model_validator(mode="after")
    def validate_identity_params(self) -> "Settings":
        if self.identity_min_votes < 1:
            raise ValueError("identity_min_votes debe ser >= 1")
        if self.identity_vote_window < self.identity_min_votes:
            raise ValueError(
                f"identity_vote_window ({self.identity_vote_window}) no puede ser menor "
                f"que identity_min_votes ({self.identity_min_votes}): la votacion nunca "
                f"alcanzaria el minimo"
            )
        ...
        return self
```

> Ubicación: los **campos** van en su bloque temático (tras el bloque ReID,
> `config.py:163`); los **validadores** van todos juntos al final de la clase, después
> de `model_config` (`config.py:211`). No mezclar.

---

### `backend/main.py` (MOD — propagación de settings)

**Análogo exacto:** `main.py:413-444`, la llamada única a `camera_manager.add(...)`.
Los parámetros de la Fase 25 son las últimas 7 líneas antes del cierre:

```python
    camera_manager = CameraManager()
    pipeline = camera_manager.add(
        "cam1",
        build_rtsp_url(settings),
        process_size=process_size,
        detector=detector,
        tracker=tracker,
        recognizer=recognizer,
        event_engine=event_engine,
        latency_tracker=latency_tracker,
        is_intrusion=lambda: not _is_in_schedule(),
        recording_config=recording_config,
        on_identified=_save_gallery_capture,
        detection_fps=(
            settings.detection_target_fps,
            settings.detection_min_fps,
            settings.detection_max_fps,
        ),
        recognition_fps=settings.recognition_target_fps,
        identity_vote_window=settings.identity_vote_window,
        identity_min_votes=settings.identity_min_votes,
        identity_min_ratio=settings.identity_min_ratio,
        identity_lost_ttl=settings.identity_lost_ttl_secs,
        identity_revalidate_after=settings.identity_revalidate_after_secs,
        identity_low_confidence=settings.face_confirm_threshold,
        reid_enabled=settings.reid_enabled,
        reid_model_path=settings.reid_model_path,
        reid_inherit_window=settings.reid_inherit_window_secs,
        reid_similarity_threshold=settings.reid_similarity_threshold,
        reid_interval=settings.reid_interval_secs,
        reid_inherit=settings.reid_inherit_identity,
        reid_max_gallery_entries=settings.reid_max_gallery_entries,
    )
```

> Cambio de la Fase 26: **un bloque contiguo de `behavior_*` / `loiter_*` / `run_*` /
> `immobile_*` / `crowd_*` al final de la llamada**, uno por línea, sin lógica ni
> condicionales. Es el único sitio donde `main.py` toca la configuración de
> comportamiento.

---

### Tests

#### `tests/test_behavior_analyzer.py` (NUEVO — dominio puro)

Helper de trayectorias: **local al fichero**, siguiendo la costumbre del repo. Los tres
helpers existentes, para que el planner elija forma:

`tests/test_detection_worker.py:27-35` — `sv.Detections` con bbox fijo (solo ids):

```python
def _tracked(ids: list[int]) -> sv.Detections:
    n = len(ids)
    det = sv.Detections(
        xyxy=np.array([[10, 10, 50, 50]] * n, dtype=float),
        confidence=np.full(n, 0.9),
        class_id=np.zeros(n, dtype=int),
    )
    det.tracker_id = np.array(ids)
    return det
```

`tests/test_detection_worker.py:252-259` — `_tracked_at`, la variante **posicional**
(la que sirve para mover tracks; RESEARCH prohíbe escribir un tercero):

```python
def _tracked_at(boxes, tids) -> sv.Detections:
    det = sv.Detections(
        xyxy=np.array(boxes, dtype=float),
        confidence=np.ones(len(tids)),
        class_id=np.zeros(len(tids), dtype=int),
    )
    det.tracker_id = np.array(tids)
    return det
```

`tests/test_memory_bounds.py:34-39` — `_fake_tracked`, sin depender de `supervision`
(el más ligero, ideal para el test de cota):

```python
def _fake_tracked(track_id: int):
    return SimpleNamespace(
        tracker_id=np.array([track_id]),
        xyxy=np.array([[0, 0, 10, 10]], dtype=np.float32),
        confidence=np.array([0.9], dtype=np.float32),
    )
```

> **Cuál usar dónde:** el nivel 1 (dominio puro, criterios 1/2/3) no necesita ninguno
> de los tres — el analizador recibe centroides y `now`, así que basta un `_walk(...)`
> local que devuelva `[(t, x, y), ...]`. `_tracked_at` es para el nivel 2 (cableado en
> `test_detection_worker.py`); `_fake_tracked` para `test_memory_bounds.py`.

Convención de nombres: `pytest.ini` fija `python_functions = TEST_*`. Los tests nuevos
**deben** llamarse `TEST_*` (en Linux/CI los `test_*` dejarían de recogerse).

Estilo de comentario-cabecera por test (banda `─`, motivo del test antes de la
función) — `tests/test_memory_bounds.py:42-55`:

```python
# ─── TrackRegistry._tracks se acota con prune() periódico ────────────────────
# ByteTrack asigna ids monotonamente crecientes: sin poda, 10.000 tracks
# efimeros (cada uno visto una sola vez) dejarian 10.000 entradas vivas para
# siempre. Con ttl=5 y una poda cada iteracion, el registro debe quedarse
# con solo un puñado de tracks recientes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_track_registry_bounded():
```

#### `tests/test_memory_bounds.py` (AMPLIAR — criterio 4)

**Patrón de cota, `tests/test_memory_bounds.py:286-312`** — los dos tests más recientes
(Fase 25) son el molde literal de `TEST_behavior_state_bounded`:

```python
# ─── TrackGallery no acumula embeddings de tracks muertos ─────────────────────
# ByteTrack asigna ids monotonamente crecientes y nunca los reutiliza. Cada
# entrada son 512 float32 = 2 KB; sin doble guarda (TTL de inherit_window +
# cota dura max_entries) un proceso 24/7 la haria crecer sin limite. La cota
# dura es el "seguro de vida" de la Fase 22: actua aunque nadie llame a prune()
# a tiempo. Techo: 256 x 2 KB = 512 KB.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_track_gallery_bounded():
    gallery = TrackGallery(inherit_window=15.0, similarity_threshold=0.7,
                           interval=2.0, max_entries=256)
    emb = np.zeros(512, dtype=np.float32)
    emb[0] = 1.0
    for tid in range(10_000):
        now = float(tid)
        gallery.update(tid, emb, tid % 7, now)
        gallery.prune(now, frame_ids={tid})
    assert len(gallery._entries) <= 256


def TEST_track_gallery_bounded_without_prune():
    """La cota dura actua aunque el mantenimiento periodico nunca se ejecute."""
    gallery = TrackGallery(max_entries=256)
    emb = np.zeros(512, dtype=np.float32)
    emb[0] = 1.0
    for tid in range(10_000):
        gallery.update(tid, emb, 1, now=float(tid))
    assert len(gallery._entries) <= 256
```

Y el más antiguo con el bucle `10_000` + `prune` por iteración
(`test_memory_bounds.py:48-55`):

```python
def TEST_track_registry_bounded():
    registry = TrackRegistry()
    for i in range(10_000):
        now = float(i)
        registry.update_from_detections(_fake_tracked(i), now)
        registry.prune(now, ttl=5.0)

    assert len(registry.active_ids()) <= 10
```

> **Dos tests, no uno:** el par "con prune" / "sin prune" es lo que demuestra la doble
> guarda. Replicarlo para `BehaviorAnalyzer._aggs` **y** para
> `EventEngine._zone_entry_at` (Pitfall 5: N zonas × 10.000 tracks efímeros →
> `len(_zone_entry_at[z]) == 0`). Se accede al atributo privado directamente
> (`gallery._entries`); es la convención aceptada en este fichero.

#### `tests/test_rule_engine.py` (AMPLIAR — criterio 5, vía YAML real)

**Hallazgo relevante:** el fixture ya contiene una regla `LOITERING` con
`duration_gte` — `tests/test_rule_engine.py:13-45`:

```python
SPEC_RULES_YAML = textwrap.dedent("""
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
          ...

      - name: permanencia_excesiva
        when:
          event: LOITERING
          duration_gte: 120
        actions: [ {type: notify} ]
    """)
```

y el test que lo carga desde disco — `tests/test_rule_engine.py:60-67` (**este es el
camino real que exige RESEARCH: `tmp_path` + `load_rules`, no `Rule.model_validate` a
secas**):

```python
def TEST_loads_valid_yaml(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(SPEC_RULES_YAML, encoding="utf-8")

    rules, errors = load_rules(str(path))

    assert errors == []
    assert {r.name for r in rules} == {"intrusion_nocturna", "persona_desconocida", "permanencia_excesiva"}
```

El test nuevo del criterio 5 = escribir un YAML con los cuatro eventos de
comportamiento en `tmp_path`, cargarlo con `load_rules`, comprobar `errors == []` y
después `await engine.evaluate(evento_loitering)` → dispara. El molde de la parte de
evaluación, `tests/test_rule_engine.py:94-102`:

```python
async def TEST_all_when_conditions_are_and():
    rule = Rule.model_validate(make_rule(zone="jardin", time_range="10:00-11:00"))
    engine = RuleEngine([rule], registry={})

    # Cumple event + zone pero no time_range (18:30 fuera de 10:00-11:00)
    event = make_event(zone_id="jardin", ts=datetime.datetime(2026, 4, 16, 18, 30))
    fired = await engine.evaluate(event)

    assert fired == []
```

con los factories `tests/test_rule_engine.py:48-57`:

```python
def make_event(**overrides) -> Event:
    kwargs = {"type": EventType.PERSON_ENTERED, "camera_id": "cam1", "ts": "2026-04-16T18:30:00"}
    kwargs.update(overrides)
    return Event(**kwargs)


def make_rule(**when_overrides) -> dict:
    when = {"event": "PERSON_ENTERED"}
    when.update(when_overrides)
    return {"name": "r1", "when": when, "actions": [{"type": "log"}]}
```

**El acoplamiento que fija el nombre de la clave** — `backend/events/rules.py:88-91`,
dentro de `_matches`:

```python
    if when.duration_gte is not None:
        duration = event.payload.get("duration_s")
        if duration is None or duration < when.duration_gte:
            return False
```

y la validación por enum que hace que el criterio 5 sea "cero código" —
`backend/events/rules.py:24-25` y `72-76`:

```python
class When(BaseModel):
    event: EventType
    ...

def _matches(when: When, event: Event) -> bool:
    if when.event != event.type:
        return False
    if when.zone is not None and when.zone != event.zone_id:
        return False
```

#### `tests/test_event_engine.py` (AMPLIAR — `duration_s` + `emit_behavior`)

Fixture y helper de espera — `tests/test_event_engine.py:16-34` (**es lo que hay que
reutilizar; el bus es asíncrono, así que todo test aquí es `async` y espera con
`wait_until`**):

```python
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
    engine = EventEngine(bus, camera_id="cam1")
    return engine, received
```

#### `tests/test_config.py` (AMPLIAR — defaults y rangos)

Molde exacto, `tests/test_config.py:224-265` (un test para los defaults con un `assert`
por parámetro, y uno o dos para los rangos con `pytest.raises((ValidationError, ValueError))`):

```python
# ─── Defaults de SPEC_v2.md §5.6 / ADR-04 ─────────────────────────────────────
# reid_inherit_identity=False es el fail-safe de la fase: sin decision explicita
# del operador, ReID calcula y registra pero no altera identidades. No es una
# omision del plan, es la condicion de arranque exigida por T-25-17.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_reid_defaults_match_spec():
    """Settings() expone los 7 parametros reid_* con los defaults del SPEC."""
    s = Settings()
    assert s.reid_enabled is True
    assert s.reid_model_path == "models/reid/osnet_x0_25_msmt17_dyn.onnx"
    assert s.reid_inherit_window_secs == 15.0
    ...


def TEST_reid_time_params_must_be_positive():
    """reid_inherit_window_secs, reid_interval_secs y reid_max_gallery_entries fuera de rango lanzan."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_inherit_window_secs=0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_interval_secs=-1)
    with pytest.raises((ValidationError, ValueError)):
        Settings(reid_max_gallery_entries=0)
```

#### `tests/test_detection_worker.py` (AMPLIAR — cableado)

Constructor mínimo del worker sin hilos (`tests/test_detection_worker.py:244-249`) — el
molde para probar el enganche del analizador llamando al método privado directamente,
como hacen los tests de zonas:

```python
def _worker_for_zones() -> DetectionWorker:
    broker = FrameBroker()
    return DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
    )
```

y el ejemplo de invocación directa del método privado con `_tracked_at`
(`tests/test_detection_worker.py:263-287`):

```python
def test_polygon_zone_counts_presence_and_entries():
    import json

    worker = _worker_for_zones()
    worker.set_zones([{
        "id": "z1", "name": "Puerta", "enabled": True,
        "polygon_json": json.dumps([[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]),
    }])

    shape = (720, 1280, 3)
    # frame 1: track 1 dentro (pies en x=320), track 2 fuera (x=960)
    worker._update_zones_and_heat(
        _tracked_at([[300, 100, 340, 400], [940, 100, 980, 400]], [1, 2]), shape
    )
    assert worker.get_zone_stats() == [
        {"id": "z1", "name": "Puerta", "current": 1, "entries": 1}
    ]
```

---

## Shared Patterns

### Reloj inyectado (aplica a `behavior.py` y a la firma de `process_zone`)

**Fuente:** `backend/perception/reid/gallery.py:36-37` y `identity.py:4-7`

```python
    Reloj inyectado: ningun metodo llama a time.monotonic(). Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock — igual que IdentityStateMachine.
```

Toda función de dominio recibe `now: float` como **último** parámetro posicional o
keyword explícito. Ningún `import time` en `backend/perception/behavior.py`.

### Doble guarda de memoria: TTL + cota dura

**Fuente:** `backend/perception/reid/gallery.py:129-158` (excerpt completo arriba)
**Aplicar a:** `BehaviorAnalyzer._aggs` y `EventEngine._zone_entry_at`
**Test asociado:** `tests/test_memory_bounds.py:293-312` (par con/sin prune)

### Idempotencia por latch

**Fuente:** `backend/events/engine.py:144-154` (`camera_offline`/`camera_recovered`)
**Aplicar a:** los cuatro comportamientos. Flanco de subida emite; re-armado silencioso
con histéresis para los umbrales numéricos (RUNNING, CROWD).
**Variante alternativa (flag en el veredicto):** `IdentityTransition.emits`
(`identity.py:45`) + `if not transition.emits: return` (`engine.py:196-197`) — el latch
vive en el dominio, `EventEngine` solo traduce.

### Aislamiento de fallos en el hilo del worker

**Fuente:** `backend/pipeline/recognition.py:364-374` (excerpt completo arriba)
**Aplicar a:** la llamada al analizador desde `DetectionWorker._loop`
```python
        try:
            ...  # llamada al dominio + prune
        except Exception:
            self._exceptions += 1
            logger.exception("DetectionWorker: <que fallo>")
            return
```
Contador `self._exceptions` ya existe (`detection.py:76`) y se expone en
`stats` (`detection.py:109-114`) → sale gratis en `/api/v2/cameras/{id}/health`.

### Construcción con estado FUERA de la factoría del supervisor

**Fuente:** `backend/pipeline/manager.py:133-160` (excerpt completo arriba)
**Aplicar a:** `BehaviorAnalyzer` (anclas y latches se perderían en cada reinicio del
`DetectionWorker`, provocando una ráfaga de duplicados).
**Señal de que está mal:** `BehaviorAnalyzer(` dentro de un `def _make_*`.

### Bloque de config por fase + validador

**Fuente:** `backend/config.py:149-177` (campos) y `231-248` (validador)
**Aplicar a:** los 6-8 parámetros nuevos. Campos en su bloque temático; validador al
final de la clase, tras `model_config`.

### Nombre obligatorio de clave del payload

**Fuente:** `backend/events/rules.py:88-91`
**Aplicar a:** `LOITERING`, `IMMOBILE`, `RUNNING` y `ZONE_EXITED` — la clave es
`duration_s`, literal. Cualquier otro nombre rompe `duration_gte` en silencio.

### Dirección de las dependencias

`events/ → perception/` (`engine.py:21` importa de `perception.face.identity`).
`perception/` **nunca** importa de `backend.events` — es lo que hace que
`BehaviorFinding` no pueda ser un `Event` (RESEARCH D-3).

---

## No Analog Found

Ninguno. Los 12 ficheros tienen análogo directo, en la mayoría de casos del mismo
patrón repetido dos veces (Fases 24 y 25), que es lo que lo convierte en convención y
no en coincidencia.

Dos matices para el planner:

| Elemento | Situación | Nota |
|---|---|---|
| `_TrackAgg` con agregados incrementales (ancla + caja envolvente) | Sin análogo *algorítmico* en el repo | La **forma** (dataclass privado con comentario por campo, dentro del módulo de dominio) sí la tiene: `_GalleryEntry` (`gallery.py:23-31`). El algoritmo lo especifica RESEARCH § Pattern 2 |
| Latch de escena (no por track) para `CROWD_DETECTED` | Análogo exacto pero sin evento inverso | `camera_offline`/`camera_recovered` son un par; aquí `CROWD_CLEARED` no existe en `EventType` → el re-armado no publica nada |

---

## Metadata

**Ámbito de búsqueda:** `backend/perception/`, `backend/events/`, `backend/pipeline/`,
`backend/config.py`, `backend/main.py`, `tests/`
**Ficheros leídos en esta sesión:** `engine.py` (completo), `identity.py:1-80`,
`gallery.py:1-60,120-158`, `detection.py:1-270`, `manager.py:30-219,293-313`,
`config.py:120-259`, `rules.py:1-130`, `tracking.py:14-138`, `main.py` (grep dirigido),
`test_detection_worker.py:1-70,240-320`, `test_memory_bounds.py:1-80,280-312`,
`test_rule_engine.py:1-105`, `test_event_engine.py:1-70`, `test_config.py:220-270`
**Fecha de extracción:** 2026-08-15
