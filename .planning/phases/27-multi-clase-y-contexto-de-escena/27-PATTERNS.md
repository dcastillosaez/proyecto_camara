# Phase 27: Multi-clase y contexto de escena - Pattern Map

**Mapped:** 2026-08-16
**Files analyzed:** 25 (4 nuevos de producción + 11 modificados + 3 tests nuevos + 7 tests ampliados)
**Analogs found:** 25 / 25 (todos con análogo real en el repo; 2 con matiz, ver `## No Analog Found`)

> El diseño ya lo cerró `27-RESEARCH.md` (partición por clase antes del tracker, `ObjectAnalyzer`
> puro, mutación en caliente de `_classes`, query de baseline, campos del endpoint). Este
> documento **solo** aporta el código real que hay que imitar, con fichero y líneas. No
> rediseña nada y no contradice al research.

---

## File Classification

| Fichero nuevo/modificado | Rol | Data flow | Análogo más cercano | Calidad |
|---|---|---|---|---|
| `backend/perception/objects.py` (CREAR) | domain model + service (dominio puro) | transform (estado por objeto → veredictos) | `backend/perception/behavior.py:1-283` **completo** | exacto |
| `backend/tracker.py` → `ObjectTracker` (MOD/CREAR) | adaptador de librería | streaming (frame → tracks) | `PersonTracker`, `tracker.py:25-54,60-93,129-142` | exacto (por sustracción) |
| `backend/api/v2/context.py` (CREAR) | router de lectura | request-response (agregación) | `backend/api/v2/metrics.py:19-42` (referencia viva) + `recordings.py:22-52` (repo) | exacto |
| `backend/api/v2/detection.py` (CREAR) | router de configuración | request-response (mutación) | `recordings.py:88-101` (POST con 400/409) + `main.py:908-931` (validación de body) | role-match |
| `backend/detector.py` (MOD) | adaptador de librería | transform | **`PersonTracker.set_frame_rate`, `tracker.py:129-142`** (mutar instancia viva en vez de recrear) | exacto |
| `backend/pipeline/detection.py` (MOD) | worker (hilo) | streaming / bucle caliente | él mismo: `_analyze_behavior` (191-227), `set_zones` (119-123), `get_zone_stats` (125-130), `_sync_tracker_frame_rate` (260-265) | exacto |
| `backend/pipeline/streaming.py` (MOD) | worker (hilo) | streaming | él mismo: `set_zone_overlay` (95-98) + bucle de zonas de `_annotate` (154-162) | role-match |
| `backend/pipeline/manager.py` (MOD) | composición / factoría | config-time wiring | él mismo: `manager.py:107-124` (behavior, Fase 26), `165-192` (fsm+reid), `282-284`/`301-308` (fachada) | exacto |
| `backend/events/engine.py` (MOD) | traductor dominio→evento | event-driven (pub) | él mismo: `_BEHAVIOR_EVENT_TYPE` (29-34) + `emit_behavior` (242-267) | exacto |
| `backend/config.py` (MOD) | config | config | él mismo: bloque comportamiento (165-188) + `validate_behavior_params` (275-295) | exacto |
| `backend/storage/repositories.py` (MOD) | repositorio | CRUD / agregación SQL | `EventRepo.hourly_counts` (153-169) + `DetectionStatRepo.recent` (244-261) | exacto |
| `backend/database.py` (MOD) | ORM legacy | CRUD | `ZoneRepo._to_dict` (`repositories.py:500-506`) — el v2 ya expone `kind` | exacto |
| `backend/main.py` (MOD) | composition root | config wiring | él mismo: `245-246` (`configure`), `258` (repo), `281-287` (detector), `413-454` (add), `557-561` (routers) | exacto |
| `backend/events/types.py` | — | — | **NO SE TOCA** (H-3: ya catalogados; `tests/test_event_types.py:12` congela la lista) | n/a |
| `backend/pipeline/tracking.py` | — | — | **NO SE TOCA** (Q4: los objetos no entran en el registry) | n/a |
| `frontend/index.html` (MOD) | UI inline | request-response | panel de zonas: markup `658-700`, JS `1672-1733`, `loadZones` `1735-1772` | exacto |
| `tests/test_object_analyzer.py` (NUEVO) | test unitario de dominio | transform | `tests/test_behavior_analyzer.py:1-75` | exacto |
| `tests/test_scene_context.py` (NUEVO) | test de endpoint + SQL | request-response | `tests/test_security_regression.py:27-28` (cliente) + `tests/test_repositories.py:20-31` (fixture db) | exacto |
| `tests/test_detection_config_api.py` (NUEVO) | test de endpoint | request-response | idem anterior | exacto |
| `tests/test_detection_worker.py` (AMPLIAR) | test de cableado | streaming | `_tracked_at` (253-260), `TEST_behavior_*` (329-438) | exacto |
| `tests/test_detector.py` (AMPLIAR) | test unitario + perf | transform | fixture `detector` (30-36), `TEST_033` (94-101); perf: `tests/test_reid_engine.py:54-70` | exacto |
| `tests/test_memory_bounds.py` (AMPLIAR) | test de cota | batch | `TEST_behavior_state_bounded` + `..._without_prune` (318-340) | exacto |
| `tests/test_event_engine.py` (AMPLIAR) | test async con bus | event-driven | `TEST_emit_behavior_*` (292-355) | exacto |
| `tests/test_config.py` (AMPLIAR) | test de config | config | `TEST_behavior_defaults_match_spec` (288-300) + `TEST_behavior_params_must_be_positive` (308-321) | exacto |
| `tests/test_repositories.py` (AMPLIAR) | test de repositorio | CRUD | `TEST_detection_stats_upsert` (92-104), `TEST_count_since_and_hourly_counts` (107-119) | exacto |
| `tests/test_streaming_worker.py` (AMPLIAR) | test de worker | streaming | `_tracker_mock` (26-29) + `test_overlay_uses_registry_not_detector` (72-76) | exacto |

**NO TOCAR** (verificado en esta sesión, coincide con RESEARCH D-1):
`backend/perception/behavior.py`, `backend/pipeline/tracking.py`, `backend/pipeline/recognition.py`,
`backend/events/types.py`, `PersonTracker.update` (`tracker.py:60-93`).

---

## Pattern Assignments

### `backend/perception/objects.py` (CREAR — dominio puro, transform)

**Análogo:** `backend/perception/behavior.py` **completo (1-283)**. No es "inspirarse": es el
mismo esqueleto, cambiando persona por objeto. Cinco piezas a copiar en orden.

#### 1. Docstring de módulo — declaración de pureza (`behavior.py:1-15`)

```python
"""BehaviorAnalyzer — LOITERING / RUNNING / IMMOBILE / CROWD (SPEC_v2.md §5.7).

Dominio puro: no importa `time`, no arranca hilos, no hace I/O y no construye
eventos. Reloj inyectado: todos los metodos que dependen del reloj lo reciben
como parametro `now: float` (monotonico). Un solo hilo lo llama
(DetectionWorker._loop), por eso no hay lock.

Fuera de alcance aqui: construir Event, conocer camera_id, conocer el reloj de
pared, decidir la severidad y emitir ZONE_ENTERED/ZONE_EXITED (los emite
EventEngine.process_zone desde la Fase 19; reimplementarlos aqui duplicaria
cada evento de zona — 26-CONTEXT.md H-2).

La firma de SPEC_v2.md §5.7 (`analyze(...) -> list[Event]`) queda corregida a
`-> list[BehaviorFinding]` por 26-RESEARCH.md D-3.
"""
```

> El de `objects.py` debe declarar como fuera de alcance: construir `Event`, conocer
> `camera_id`, conocer el reloj de pared, **decidir si un objeto entra o no en el tracker**
> (eso es `DetectionWorker`) y **calcular la pertenencia a zonas** (eso ya lo hace
> `sv.PolygonZone.trigger()` en `_update_zones_and_heat`).
> Imports permitidos: `math`, `dataclasses`, `enum`, `collections.abc` — exactamente los de
> `behavior.py:17-22`. **Nada de `numpy` ni de `time`** (RESEARCH § Standard Stack).

#### 2. `ObjectKind` + `ObjectFinding` — calco de `behavior.py:24-59`

```python
REARM_RATIO = 0.8  # histeresis de re-armado: un umbral numerico oscilaria en el borde


class BehaviorKind(str, Enum):
    LOITERING = "loitering"
    RUNNING = "running"
    IMMOBILE = "immobile"
    CROWD = "crowd"


@dataclass
class BehaviorFinding:
    """El analizador devuelve esto, NO un Event: perception/ no conoce camera_id ni el
    reloj de pared. EventEngine.emit_behavior() lo traduce a Event (26-RESEARCH.md D-3).
    """

    kind: BehaviorKind
    track_id: int | None = None            # None solo para CROWD: evento de escena
    zone_id: str | None = None             # None = escena implicita cuando el track no esta en ninguna zona, D-02
    duration_s: float | None = None        # nombre OBLIGATORIO: rules.py:88-91 lee literalmente payload['duration_s'] para resolver duration_gte
    net_displacement_px: float | None = None
    speed_px_s: float | None = None
    track_count: int | None = None

    def magnitudes(self) -> dict[str, float | int]:
        """Payload que EventEngine.emit_behavior pasara como `payload=` (BEH-05)."""
        out: dict[str, float | int] = {}
        if self.duration_s is not None:
            out["duration_s"] = self.duration_s
        ...
        return out
```

**Qué copiar literalmente:** `str, Enum` como base del kind (serializa solo al payload),
campos obligatorios primero y opcionales con default `None`, comentario inline **solo** en el
campo no obvio, y `magnitudes()` que **omite los `None`** (`test_event_engine.py:339` afirma
`all(v is not None for v in event.payload.values())`).

**Qué adaptar:** `ObjectFinding` lleva `kind`, `track_id`, `zone_id`, `duration_s`,
`class_name: str | None`, `class_id: int | None`, `net_displacement_px`,
`person_distance_px`, `person_track_id` (tabla de payload de RESEARCH § Payload recomendado).
`duration_s` es **nombre obligatorio** por `backend/events/rules.py:88-91`.

#### 3. `_ObjAgg` — molde `_TrackAgg` (`behavior.py:62-73`)

```python
@dataclass
class _TrackAgg:
    """Estado O(1) por track para IMMOBILE y RUNNING (patron `_GalleryEntry`)."""

    imm_anchor_t: float            # ancla temporal del episodio de inmovilidad
    imm_min_x: float                # caja envolvente de las posiciones desde el ancla:
    imm_max_x: float                # su span ES el desplazamiento real, mientras que
    imm_min_y: float                # la distancia al ancla permitiria un diametro de 2R
    imm_max_y: float
    last_seen: float                # base del TTL y del LRU de la cota dura
    imm_latched: bool = False       # un evento IMMOBILE por episodio
    run_latched: bool = False       # un evento RUNNING por episodio
```

> Prefijo `_`, docstring de una línea que cita el patrón del que deriva, **un comentario por
> campo explicando qué invariante sostiene**. Los 11 campos de `_ObjAgg` (tabla de RESEARCH
> Q2, "Estado total del ObjectAnalyzer") van comentados igual.

#### 4. `analyze()` — el núcleo de inmovilidad, copiar tal cual (`behavior.py:175-190`)

```python
            # ─── IMMOBILE (BEH-02) ─────────────────────────────────────────
            agg.imm_min_x = min(agg.imm_min_x, x); agg.imm_max_x = max(agg.imm_max_x, x)
            agg.imm_min_y = min(agg.imm_min_y, y); agg.imm_max_y = max(agg.imm_max_y, y)
            span = max(agg.imm_max_x - agg.imm_min_x, agg.imm_max_y - agg.imm_min_y)
            if span > self._immobile_radius_px:
                agg.imm_anchor_t = now
                agg.imm_min_x = agg.imm_max_x = x
                agg.imm_min_y = agg.imm_max_y = y
                agg.imm_latched = False              # re-armado: el episodio empieza de cero
            else:
                dur = now - agg.imm_anchor_t
                if not agg.imm_latched and dur > self._immobile_secs:
                    agg.imm_latched = True
                    findings.append(BehaviorFinding(kind=BehaviorKind.IMMOBILE, track_id=tid,
                                                    duration_s=round(dur, 3),
                                                    net_displacement_px=round(span, 3)))
```

**Qué copiar literalmente:** la caja envolvente + `span`, el reset del ancla y **el latch con
re-armado** (criterio 5 del ROADMAP: un único `OBJECT_LEFT`), y el `round(..., 3)` en las
magnitudes.
**Qué adaptar:** el bucle es `for tid in sorted(centroids)` (`behavior.py:162`) —
determinismo de orden, importante para tests. Antes del bloque de inmovilidad van las dos
guardas nuevas de Q2 (warmup y zona de exclusión), y después la marca
`last_person_near_t` del Pattern 3 del research. Sin `_window_speed` (`behavior.py:87-109`):
un objeto abandonado no necesita velocidad.

#### 5. `prune()` + `_enforce_cap()` — la doble guarda (`behavior.py:245-283`)

```python
    def prune(self, now: float, frame_ids: set[int]) -> None:
        """Doble guarda de expiracion, calcada de TrackGallery.prune.

        Guarda 1 (TTL): borra agregados mas viejos que state_ttl. Un track visible
        refresca `last_seen` en cada analyze() (<= state_ttl), asi que nunca caduca
        estando en pantalla.
        Guarda 2 (cota dura): ver _enforce_cap — "seguro de vida" de la Fase 22.
        """
        for tid in list(self._aggs):
            if tid in frame_ids:
                self._aggs[tid].last_seen = now
        for tid in list(self._aggs):
            if now - self._aggs[tid].last_seen > self._state_ttl:
                del self._aggs[tid]
        for key in list(self._loiter):
            if now - self._loiter[key].last_seen > self._state_ttl:
                del self._loiter[key]
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        """Cota dura por max_tracks, LRU por last_seen (Fase 22, "seguro de vida").

        Actua aunque nadie llame a prune() a tiempo. Se llama tanto desde
        analyze() como desde prune() para que la cota se cumpla sin depender del
        mantenimiento periodico.
        """
        if len(self._aggs) > self._max_tracks:
            overflow = len(self._aggs) - self._max_tracks
            oldest = sorted(self._aggs.items(), key=lambda kv: kv[1].last_seen)[:overflow]
            for tid, _ in oldest:
                del self._aggs[tid]
                for key in [k for k in self._loiter if k[0] == tid]:
                    del self._loiter[key]
        ...
```

Y la llamada desde el camino de escritura, `behavior.py:241-243`:

```python
        # Cota dura tambien desde este camino de escritura, no solo desde prune(): _enforce_cap()
        self._enforce_cap()
        return findings
```

**Diferencia estructural de esta fase y la única parte sin calco directo:** `prune()` de
`ObjectAnalyzer` **devuelve findings** (`OBJECT_REMOVED` se decide al expirar, RESEARCH Q2),
mientras que `BehaviorAnalyzer.prune()` devuelve `None`. Consecuencia para el llamador: en
`_analyze_objects` hay que recoger `findings += self._objects.prune(...)`, no ignorarlo.
El `set` de ids ignorados (warmup / zona de exclusión) se poda en el **mismo**
`_enforce_cap`, como `_loiter` en `behavior.py:276-277`.

---

### `backend/tracker.py` → `ObjectTracker` (CREAR clase; `PersonTracker` INTACTO)

**Análogo:** `PersonTracker`. Es un análogo **por sustracción**: se copia el constructor
quitando `DetectionsSmoother`, `LineZone` y los anotadores.

`tracker.py:25-35` — lo que se conserva (incluido el comentario del `frame_rate`, que sigue
aplicando):

```python
    def __init__(self, start: sv.Point, end: sv.Point, frame_rate: int = 15) -> None:
        # frame_rate debe ser el FPS real del pipeline (MEJORAS.md punto 14):
        # ByteTrack calcula max_time_lost = frame_rate/30 * lost_track_buffer,
        # así que con el default (30) y un stream real a ~15 FPS el buffer
        # efectivo en segundos era el doble del esperado.
        self._byte_tracker = sv.ByteTrack(
            lost_track_buffer=self.LOST_TRACK_BUFFER, frame_rate=frame_rate
        )
        # Suaviza las bboxes entre frames (MEJORAS.md Bajas): menos jitter
        # visual y menos cruces falsos — complementa minimum_crossing_threshold.
        self._smoother = sv.DetectionsSmoother(length=5)
```

**Qué copiar:** `sv.ByteTrack(lost_track_buffer=..., frame_rate=...)` y las constantes de
clase `LOST_TRACK_BUFFER` (`tracker.py:23`).
**Qué NO copiar (decisión de RESEARCH Q2, con motivo):** `self._smoother` — congela
`class_id` hasta 5 frames y retrasa la desaparición ~0,6 s; `self._line_zone` — es el conteo
de la Fase 4 y solo debe ver personas; los anotadores (`tracker.py:45-49`) — el overlay de
objetos se dibuja aparte.

`update()` se reduce a una línea del original (`tracker.py:76`):

```python
        tracked = self._byte_tracker.update_with_detections(detections)
```
(sin el `self._smoother.update_with_detections(tracked)` de la línea 78, sin `LineZone`,
sin `crossings`; devuelve solo `sv.Detections`).

**`set_frame_rate` — copiar literalmente (`tracker.py:129-142`), es obligatorio:**

```python
    def set_frame_rate(self, frame_rate: float) -> None:
        """
        Sync ByteTrack's lost-track window to a new effective frame rate
        (Fase 18: AdaptiveRate cambia el ritmo de detección en caliente).

        Muta ``max_time_lost`` directamente en vez de recrear el
        ``ByteTrack`` — recrearlo perdería todos los tracks activos y sus
        IDs. Es el mismo cálculo que hace ``ByteTrack.__init__``
        internamente (``max_time_lost = frame_rate/30 * lost_track_buffer``).
        """
        with self._lock:
            self._byte_tracker.max_time_lost = int(
                frame_rate / 30.0 * self.LOST_TRACK_BUFFER
            )
```

> **Por qué es obligatorio:** `DetectionWorker._sync_tracker_frame_rate` (`detection.py:260-265`)
> ya llama a `self._tracker.set_frame_rate(fps)` en cada cambio de escalón de `AdaptiveRate`.
> Si `ObjectTracker` no expone el mismo método y el worker no lo llama también, el tracker de
> objetos queda desincronizado del FPS real y pierde tracks antes de tiempo (o los mantiene
> el doble), justo el bug que documenta ese comentario.

---

### `backend/detector.py` — `set_classes()` (MOD)

**Análogo exacto y prescriptivo: `PersonTracker.set_frame_rate` (`tracker.py:129-142`, arriba).**
Es el precedente del repo para "cambiar un parámetro en una instancia viva en vez de
reconstruir el objeto y perder el estado", **con la justificación escrita en el docstring**.
El nuevo `set_classes` debe tener la misma forma de docstring: qué se muta, por qué no se
reconstruye, y qué se perdería si se reconstruyera.

Lo que ya existe y **no hay que tocar** — `detector.py:31-35` y `51-57`:

```python
        self._model = YOLO(model_path)
        self._confidence = confidence
        self._classes = classes if classes is not None else [0]
        ...
    def detect_sv(self, frame: np.ndarray) -> sv.Detections:
        """Run inference and return a supervision ``Detections`` object."""
        results = self._model(
            frame, classes=self._classes, conf=self._confidence,
            imgsz=self._imgsz, verbose=False,
        )
        return sv.Detections.from_ultralytics(results[0])
```

`self._classes` se lee **en cada llamada** (línea 54) → la mutación surte efecto en la
siguiente inferencia. El cuerpo del método nuevo es una línea (RESEARCH § Cambio en caliente):
`self._classes = list(classes)` — **rebind, nunca `append`/`clear`**.

**Diferencia con el análogo:** `PersonTracker.set_frame_rate` usa `self._lock`; `PersonDetector`
**no tiene lock ni lo necesita** (`STORE_ATTR` es atómico bajo el GIL, RESEARCH Q3). El
docstring debe decirlo explícitamente, siguiendo la convención de escritor único documentado
de `TrackRegistry` (`tracking.py:38-45`):

```python
    """
    Estado compartido de tracks, protegido por un unico RLock.

    Se prohibe que dos workers escriban el mismo campo: DetectionWorker es
    el unico escritor de bbox/confidence/centroid_history/_frame_ids (via
    set_frame_ids); RecognitionWorker es el unico escritor de
    person_id/person_name/identity_state via set_identity/set_identity_state.
    """
```

---

### `backend/pipeline/detection.py` (MOD — el fichero con más trabajo de la fase)

#### a) Punto de enganche de la partición, `detection.py:164-189`

```python
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
            ...
            now = time.monotonic()  # "processed_at" for OBS-03 — right after inference, before event emission
            _metrics.active_tracks.labels(camera=self._camera_id).set(len(tracked))
            self._registry.update_from_detections(tracked, now)
            self._update_zones_and_heat(tracked, frame.image.shape, frame.captured_at, now)
            self._analyze_behavior(tracked, frame.captured_at, now)      # NUEVO (Fase 26)
            self._emit_crossings(crossings, frame.captured_at, now)
            self._emit_track_lifecycle(tracked, frame.captured_at, now)
            self._registry.prune(now)
```

**Qué copiar:** la forma de "una línea por etapa, con comentario `# NUEVO (Fase N)`" que
introdujo la Fase 26 en la línea 186 — la llamada a `_analyze_objects(...)` va justo después,
con el mismo estilo.
**Qué adaptar (3 puntos exactos):**
1. La partición va **dentro del `try` de inferencia**, entre las líneas 166 y 167, para que
   un `sv_dets` malformado siga cayendo en el mismo `except` que ya existe.
2. `self._tracker.update(...)` recibe **`person_dets`**, no `sv_dets` (Pitfall 1).
3. Las líneas 183-184 (`_metrics.active_tracks`, `registry.update_from_detections`) siguen
   recibiendo `tracked` (personas). No cambian.
4. `self._rate.observe(inference_latency)` (línea 174) se calcula **antes** del tracking de
   objetos: `t0` cierra en la línea 173, así que basta con no mover nada. La vía de objetos
   nunca debe llamar a `observe()` (anti-patrón del research).

#### b) `_analyze_objects` — molde `_analyze_behavior`, `detection.py:191-227` (copiar entero)

```python
    def _analyze_behavior(self, tracked: Any, captured_at: float, processed_at: float) -> None:
        """Analisis de comportamiento del frame (Fase 26, BEH-01..BEH-05).

        Patron de aislamiento de fallos de RecognitionWorker._sync_identity
        (recognition.py:366-374): un fallo del analizador nunca mata el hilo de
        deteccion, solo incrementa el contador de excepciones que ya expone
        /api/v2/cameras/{id}/health.
        """
        if self._behavior is None or self._event_engine is None:
            return
        ids = tracked.tracker_id
        if ids is None:
            return
        try:
            centroids: dict[int, tuple[float, float]] = {}
            histories: dict[int, Any] = {}
            for i, tid in enumerate(ids):
                tid = int(tid)
                x1, y1, x2, y2 = map(int, tracked.xyxy[i])
                centroids[tid] = ((x1 + x2) / 2, (y1 + y2) / 2)   # igual que tracking.py:66
                st = self._registry.get(tid)
                if st is not None:
                    histories[tid] = st.centroid_history          # por referencia, sin copiar
            findings = self._behavior.analyze(
                centroids=centroids,
                zone_membership=self._zone_membership_snapshot(),
                histories=histories,
                now=processed_at,                                 # monotonico del frame
            )
            self._behavior.prune(processed_at, set(centroids))
        except Exception:
            self._exceptions += 1
            logger.exception("DetectionWorker: analisis de comportamiento fallo")
            return
        wall_now = datetime.datetime.now()
        for f in findings:
            self._event_engine.emit_behavior(f, wall_now, captured_at, processed_at)
```

**Qué copiar literalmente:** las dos guardas de arriba (`is None` → `return`, `ids is None` →
`return`), el `try` que envuelve **analyze + prune juntos**, el `except` con
`self._exceptions += 1` + `logger.exception` + `return`, y el bucle de emisión **fuera** del
`try` con `wall_now = datetime.datetime.now()` calculado una sola vez.
**Qué adaptar:**
- La anchura de referencia **no es el centroide**: aquí se usa
  `tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)` (RESEARCH Q1), que ya se usa
  en este mismo fichero, `detection.py:312`:
  ```python
        for xy in tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER):
  ```
- Hay **dos** entradas: los objetos (`obj_tracked`) y las personas (`tracked`, para el radio
  "persona cerca" y su altura de bbox). La firma es
  `_analyze_objects(self, obj_tracked, tracked, captured_at, processed_at)`.
- `findings = analyze(...)` **más** `findings += prune(...)` (ver nota de `objects.py`).
- La emisión llama a `self._event_engine.emit_object(f, wall_now, captured_at, processed_at)`.

#### c) `set_object_classes` — molde `set_zones`, `detection.py:119-123`

```python
    def set_zones(self, zones: list[dict]) -> None:
        """Replace the active interest zones list. Thread-safe."""
        with self._lock:
            self._zones = list(zones)
            self._zones_dirty = True
```

Copiar la forma exacta (docstring de una línea acabado en "Thread-safe.", `with self._lock`,
rebind del atributo). El lector del hilo caliente hace el snapshot igual que
`_update_zones_and_heat` (`detection.py:281-284`):

```python
        with self._lock:
            dirty = self._zones_dirty
            self._zones_dirty = False
            zones_snap = list(self._zones)
```

#### d) `get_object_stats` / `get_object_boxes` — molde `get_zone_stats`, `detection.py:125-130`

```python
    def get_zone_stats(self) -> list[dict]:
        with self._lock:
            return [
                {"id": st["id"], "name": st["name"], "current": st["current"], "entries": st["entries"]}
                for st in self._zone_states
            ]
```

Estado bajo `self._lock` declarado en `__init__` junto a los demás (`detection.py:81-86`):

```python
        self._lock = threading.Lock()
        self._zones: list[dict] = []
        self._zones_dirty = True
        self._zone_states: list[dict] = []
        self._zone_frame_size: tuple[int, int] = (0, 0)
        self._heat_mask: np.ndarray | None = None
```

> Este es exactamente el patrón que RESEARCH Q4 manda usar para el estado de objetos ("un
> dict bajo `self._lock`, no un segundo registry"). El writer es el hilo de detección; los
> readers son el event loop (endpoint de contexto) y el `StreamingWorker`.

#### e) Reutilizar la pertenencia a zonas, `detection.py:229-238` (no recalcular)

```python
    def _zone_membership_snapshot(self) -> dict[str, set[int]]:
        """Track ids por zona de ESTE frame, reutilizando `st["inside"]` (T-26-*).

        `st["inside"]` ya lo calculo `_update_zones_and_heat` con
        `sv.PolygonZone.trigger()` en este mismo frame. Recalcularlo aqui
        duplicaria la inferencia geometrica y podria divergir del conteo de
        `get_zone_stats()`.
        """
        with self._lock:
            return {st["id"]: set(st["inside"]) for st in self._zone_states}
```

**Qué adaptar:** los objetos **no** pasan por `_update_zones_and_heat` (ese bucle alimenta
zonas y heatmap de personas). Para la guarda (b) de Q2 hay que llamar
`st["zone"].trigger(obj_tracked)` sobre los mismos `_zone_states`, filtrando por
`st["kind"] == "exclude_objects"`. El bucle a imitar es `detection.py:289-300`:

```python
        ids = tracked.tracker_id
        for st in self._zone_states:
            mask = st["zone"].trigger(tracked)
            inside = (
                {int(ids[i]) for i in np.flatnonzero(mask)}
                if ids is not None and len(mask)
                else set()
            )
```

Y `kind` se propaga en `_rebuild_zone_states` (`detection.py:328-336`) añadiendo una clave más
al dict, igual que `id` y `name`:

```python
                states.append({
                    "id": z["id"],
                    "name": z["name"],
                    "polygon": pts,
                    "zone": sv.PolygonZone(polygon=pts),
                    "inside": set(),
                    "entries": 0,
                    "current": 0,
                })
```

#### f) Constructor — dependencias opcionales al final (`detection.py:49-61`)

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
        behavior: "BehaviorAnalyzer | None" = None,
    ) -> None:
```

→ `objects: "ObjectAnalyzer | None" = None` y `object_tracker: "ObjectTracker | None" = None`
al final, con default `None` (la Fase 26 añadió `behavior` así; hay decenas de tests que
construyen `DetectionWorker` con 5 posicionales y nada más — `test_detection_worker.py:245-250`).

Import bajo `TYPE_CHECKING`, nunca en runtime (`detection.py:26-32`):

```python
if TYPE_CHECKING:
    from backend.detector import PersonDetector
    from backend.events.engine import EventEngine
    from backend.observability.latency import LatencyTracker
    from backend.perception.behavior import BehaviorAnalyzer
    from backend.pipeline.broker import Subscription
    from backend.tracker import PersonTracker
```

---

### `backend/pipeline/streaming.py` (MOD — overlay de objetos)

**Análogo (push, ya existe en el fichero): `set_zone_overlay` + su consumo en `_annotate`.**

`streaming.py:55-57` y `95-98` — el estado y el setter:

```python
        # Zonas a dibujar: lista de (poligono_px, texto). La actualiza el
        # DetectionWorker via set_zone_overlay — el streaming no las calcula.
        self._zone_overlay: list[tuple[np.ndarray, str]] = []
    ...
    def set_zone_overlay(self, overlay: list[tuple[np.ndarray, str]]) -> None:
        """Zonas a dibujar, calculadas por el DetectionWorker."""
        with self._lock:
            self._zone_overlay = list(overlay)
```

y el consumo, `streaming.py:154-162` — **el molde exacto del bucle de dibujo con color propio**:

```python
        with self._lock:
            zones = list(self._zone_overlay)
        for pts, text in zones:
            pts32 = np.asarray(pts, dtype=np.int32)
            cv2.polylines(out, [pts32], isClosed=True, color=(0, 200, 255), thickness=2)
            cv2.putText(
                out, text, tuple(pts32[0]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1,
            )
        return out
```

**Qué copiar:** snapshot bajo lock → bucle → `cv2.rectangle`/`cv2.putText` con un color
distinto del de personas. El overlay de personas usa `self._tracker.annotate(...)`
(`streaming.py:150`), que dibuja en verde/azul de `sv.BoxAnnotator`; para objetos, dibujo
directo con `cv2` como el de zonas (naranja `(0, 200, 255)` ya está ocupado por zonas → elegir
otro, p.ej. magenta).

**Restricción dura que el planner DEBE respetar** — `tests/test_streaming_worker.py:72-76`:

```python
def test_overlay_uses_registry_not_detector():
    src = Path("backend/pipeline/streaming.py").read_text(encoding="utf-8")
    assert "PersonDetector" not in src
    assert "detect_sv" not in src
```

→ El fichero **no puede mencionar `PersonDetector` ni `detect_sv`**, ni siquiera en un
comentario o en un import bajo `TYPE_CHECKING`. Dos vías compatibles:
- **(push, análogo literal):** `set_object_overlay(list[dict])` calcado de `set_zone_overlay`,
  y `DetectionWorker` lo empuja. **Aviso:** `set_zone_overlay` **no tiene ni un solo llamador
  hoy** (verificado por grep en `backend/`, `frontend/`, `tests/`) — es un patrón escrito pero
  muerto, así que copiarlo significa estrenarlo.
- **(pull, análogo vivo):** inyectar en el constructor un `Callable[[], list[dict]]`, igual
  que hoy se inyecta `registry` (`streaming.py:39-47`) y se lee en `_annotate` línea 134
  (`self._registry.snapshot()`). Es el patrón que sí está en uso.

El cableado en `manager.py:142-152` (`_make_streaming`) es donde entra la referencia, y ya
tiene el precedente de rescatar estado en el reinicio:

```python
            def _make_streaming() -> StreamingWorker:
                clients = self.streaming.stats["clients"] if self.streaming else 0
                self.streaming = StreamingWorker(
                    self.broker.subscribe("streaming", replace=True), self.registry, tracker
                )
                # Un reinicio no debe dejar de servir a los clientes ya conectados
                for _ in range(clients):
                    self.streaming.client_connected()
                return self.streaming
```

---

### `backend/pipeline/manager.py` (MOD — construcción FUERA de la factoría + fachada)

**Análogo exacto y con TRES precedentes** (Fases 24, 25, 26). El más reciente y literal es el
de la Fase 26, `manager.py:105-124`:

```python
        self.behavior: "BehaviorAnalyzer | None" = None

        if behavior_enabled:
            # El analizador vive FUERA de la factoria: WorkerSupervisor la re-ejecuta en
            # cada reinicio del DetectionWorker, y construirlo dentro borraria todas las
            # anclas y latches — una persona con 100 s de inmovilidad acumulada volveria a
            # empezar el contador y los cuatro latches se re-armarian, provocando una
            # rafaga de eventos duplicados en el frame siguiente. Mismo motivo que la FSM
            # de identidad (Fase 24) y la galeria de apariencia (Fase 25).
            self.behavior = BehaviorAnalyzer(
                loiter_secs=loiter_secs,
                ...
                max_tracks=behavior_max_tracks,
            )
```

y la factoría que sí se re-ejecuta, `manager.py:126-140`:

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
                    behavior=self.behavior,
                )
                return self.detection

            self.supervisor.register("detector", _make_detection)
```

**Los tres pasos, en orden (idénticos a la Fase 26):**
1. Declarar los atributos junto a los demás (`manager.py:98-105`):
   ```python
        self.detection: DetectionWorker | None = None
        self.streaming: StreamingWorker | None = None
        self.recording: RecordingWorker | None = None
        self.recognition: RecognitionWorker | None = None
        self.identity_fsm: IdentityStateMachine | None = None
        self.reid_engine: "ReIDEngine | None" = None
        self.reid_gallery: "TrackGallery | None" = None
        self.behavior: "BehaviorAnalyzer | None" = None
   ```
   → añadir `self.objects: "ObjectAnalyzer | None" = None` y
   `self.object_tracker: "ObjectTracker | None" = None`.
2. Construir **antes** de `_make_detection`, gateado por `if objects_enabled:`, con el
   comentario que explica el porqué. **El comentario de esta fase debe añadir el agravante
   propio** (RESEARCH Pitfall 4): reconstruir reabre la ventana de warmup y reinicia los
   `track_id` de objeto ⇒ ráfaga de `OBJECT_LEFT` de todo el mobiliario ⇒ **subida de clips a
   Drive** (`OBJECT_LEFT` es `WARNING`, `types.py:55`).
3. Pasarlos como kwargs dentro de la factoría (`objects=self.objects,
   object_tracker=self.object_tracker,`).

**Fachada `set_detection_classes` — moldes `set_zones` (282-284) y `set_process_size` (301-308):**

```python
    def set_zones(self, zones: list[dict]) -> None:
        if self.detection:
            self.detection.set_zones(zones)
    ...
    def set_process_size(self, w: int, h: int) -> None:
        """Cambia la resolucion de proceso reiniciando el CaptureWorker."""
        self._process_size = (w, h) if (w > 0 and h > 0) else None
        self.capture.stop()
        ...
```

> `set_zones` es el molde de forma (guarda `if self.detection:` y delegación). `set_process_size`
> es el **contra-ejemplo** que el docstring nuevo debe citar: ahí sí se reinicia un worker,
> pero es el `CaptureWorker` y se hace fuera del supervisor. El `DetectionWorker` **nunca** se
> reinicia para aplicar configuración (RESEARCH Q3 / Pitfall 5).

**Parámetros de la firma** — bloque por fase al final de `__init__` (`manager.py:72-81`, Fase 26):

```python
        behavior_enabled: bool = True,
        loiter_secs: float = 120.0,
        loiter_radius_px: float = 80.0,
        loiter_require_zone: bool = False,
        run_speed_px_s: float = 350.0,
        run_window_secs: float = 1.0,
        immobile_secs: float = 60.0,
        immobile_radius_px: float = 20.0,
        crowd_threshold: int = 5,
        behavior_max_tracks: int = 256,
```

Convención confirmada en las Fases 24/25/26: los nombres en `manager.py` **sueltan el sufijo
`_secs`** que sí llevan en `config.py` (`reid_inherit_window_secs` → `reid_inherit_window`),
salvo cuando `config.py` tampoco lo lleva (`loiter_secs` se queda igual). `CameraManager.add`
(`manager.py:331-334`) no se toca: reenvía `**kwargs`.

---

### `backend/events/engine.py` — `emit_object()` (MOD)

**Análogo exacto: `_BEHAVIOR_EVENT_TYPE` + `emit_behavior`.**

Tabla de traducción a nivel de módulo, `engine.py:29-34` (no es un `@staticmethod` como en
identidad: la Fase 26 la sacó fuera de la clase porque el mapeo es 1:1 y sin lógica):

```python
_BEHAVIOR_EVENT_TYPE: dict[BehaviorKind, EventType] = {
    BehaviorKind.LOITERING: EventType.LOITERING,
    BehaviorKind.RUNNING: EventType.RUNNING,
    BehaviorKind.IMMOBILE: EventType.IMMOBILE,
    BehaviorKind.CROWD: EventType.CROWD_DETECTED,
}
```

Método, `engine.py:238-267` — **copiar entero, incluida la banda de comentario de sección**:

```python
    # ------------------------------------------------------------------
    # Comportamiento (Fase 26)
    # ------------------------------------------------------------------

    def emit_behavior(
        self,
        finding: BehaviorFinding,
        now: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
    ) -> None:
        """Publica el evento de comportamiento correspondiente a *finding*, si lo hay.

        La guarda de idempotencia NO esta aqui: vive en el latch por episodio de
        BehaviorAnalyzer, igual que `emits` vive en la FSM para emit_identity. Sin ese
        latch, una persona parada 10 min generaria ~4.800 IMMOBILE a 8 FPS — "the point
        where v1 failed conceptually" (docstring de esta clase).
        """
        event_type = _BEHAVIOR_EVENT_TYPE.get(finding.kind)
        if event_type is None:
            return
        self._publish(
            event_type,
            ts=now,
            captured_at=captured_at,
            processed_at=processed_at,
            track_id=finding.track_id,
            zone_id=finding.zone_id,
            payload=finding.magnitudes(),
        )
```

**Cuatro cosas a copiar exactamente:**
1. El import del tipo de dominio arriba (`engine.py:21`):
   `from backend.perception.behavior import BehaviorFinding, BehaviorKind`
   → añadir `from backend.perception.objects import ObjectFinding, ObjectKind`. Dirección de
   la dependencia: `events/ → perception/`, **nunca** al revés.
2. `event_type is None → return` tras la tabla.
3. `payload=finding.magnitudes()` — el dominio decide el payload, `EventEngine` no lo compone.
4. **No pasar `severity=`**: así se aplica el default del catálogo
   (`types.py:49-57` → `OBJECT_LEFT: Severity.WARNING`, `OBJECT_REMOVED` → `INFO`). El único
   sitio del fichero que sí la pasa es `camera_offline` (`_publish(..., severity=Severity.CRITICAL)`).

**Qué adaptar:** `emit_object` debe pasar también `bbox=finding.bbox` (los eventos de objeto
llevan caja, los de comportamiento no). `_publish` ya lo acepta por `**fields`
(`engine.py:56-63`).

---

### `backend/config.py` (MOD — D-03 + bloque de fase con validador)

**D-03**, `config.py:33-37` (cambio de una línea, el validador de las 39-51 ya lo acepta):

```python
    # YOLO model file — swap for yolo26n.pt, yolov8s.pt, an ONNX export, etc.
    # Extension and path containment enforced below (SEC-16) — resolved relative
    # to the project root, never to the process cwd, so it can't be fooled by
    # launching uvicorn from an unexpected working directory.
    yolo_model_path: str = "yolov8n.pt"
```

**Bloque nuevo — análogo literal: bloque de comportamiento (Fase 26), `config.py:165-188`:**

```python
    # --- Analisis de comportamiento (Fase 26 — BEH-01..BEH-05) ---
    # Defaults locked de SPEC_v2.md §5.7 (26-CONTEXT.md § Umbrales y reglas). Los
    # umbrales temporales estan en SEGUNDOS y los espaciales en PIXELES DEL FRAME
    # PROCESADO (process_width x process_height, 1280x720 por defecto): cambiar la
    # resolucion de proceso cambia el significado de loiter_radius_px, run_speed_px_s
    # e immobile_radius_px, que ademas no estan calibrados contra una escena real
    # (26-RESEARCH.md § Environment Availability: la calibracion con camara real es un
    # checkpoint manual abierto).
    # loiter_require_zone=False es el fallback de D-02: una instalacion limpia tiene
    # cero zonas (get_zones() lee de BD y no hay seed), asi que sin el LOITERING no se
    # emitiria nunca. A True exige zona explicita.
    # Los cuatro comportamientos salen con Severity.INFO por defecto del catalogo
    # (types.py:49-57, D-01): subirlos a WARNING activaria la subida automatica de
    # clips a Drive (upload_min_severity="warning", config.py:115 -> recording.py:309).
    behavior_enabled: bool = True
    loiter_secs: float = 120.0
    ...
    behavior_max_tracks: int = 256
```

**Forma obligatoria del comentario:** título `--- <Tema> (Fase N — IDs de requisito) ---` +
párrafo que justifica *por qué* los defaults son esos y **qué pasa si alguien los cambia**.
El bloque de la Fase 27 debe decir, como mínimo: (a) los píxeles son del frame procesado y no
están calibrados; (b) `OBJECT_LEFT` **sí** es `WARNING` y por tanto **sube clips a Drive**
(justo al revés que el bloque de la Fase 26 — el comentario existente es el sitio literal donde
copiar la frase e invertirla); (c) `yolo_classes=[]` ciega el sistema.

**Validador — molde `validate_behavior_params`, `config.py:275-295`** (bucle sobre nombres +
mensajes que explican la consecuencia, no solo el rango):

```python
    @model_validator(mode="after")
    def validate_behavior_params(self) -> "Settings":
        for name in ("loiter_secs", "run_window_secs", "immobile_secs",
                     "loiter_radius_px", "run_speed_px_s", "immobile_radius_px"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser > 0")
        if self.crowd_threshold < 1:
            raise ValueError(
                "crowd_threshold debe ser >= 1: con 0 se emitiria CROWD_DETECTED "
                "con la escena vacia"
            )
        if self.behavior_max_tracks < 1:
            raise ValueError("behavior_max_tracks debe ser >= 1")
        if self.run_window_secs > 12.0:
            raise ValueError(
                "run_window_secs no puede superar 12.0 s: centroid_history solo "
                "garantiza 12.5 s de historial a 12 FPS (tracking.py:47 history_len=150, "
                "rate.py:26 AdaptiveRate.STEPS[0]=12.0); una ventana mayor no se podria "
                "calcular y RUNNING no se emitiria nunca"
            )
        return self
```

> Ubicación: los **campos** van en su bloque temático (tras el bloque de la Fase 26, línea 188);
> los **validadores** van todos juntos al final de la clase, después de `model_config`
> (línea 236). No mezclar. `validate_object_params` va después de `validate_behavior_params`.

---

### `backend/storage/repositories.py` — `DetectionStatRepo.hourly_baseline()` (MOD)

**Ubicación:** dentro de `DetectionStatRepo`, justo después de `recent()` (`repositories.py:261`).
Es el sitio correcto: la clase ya es la dueña de todas las queries sobre `detection_stats`, y
el docstring del módulo lo fija (`repositories.py:1`):

```python
"""Repositories: every SQL query in the project lives here (verified by grep in Phase 37).
```

**Análogo del SQL — `EventRepo.hourly_counts`, `repositories.py:153-169`** (precedente literal
de `func.strftime` + `group_by(text("hour"))`, y precedente de que el repo asume SQLite):

```python
    async def hourly_counts(
        self, ts_from: datetime.datetime, type: EventType | None = None
    ) -> dict[str, int]:
        conditions = [models.Event.ts >= ts_from]
        if type is not None:
            conditions.append(models.Event.type == type.value)
        async with self._sf() as session:
            result = await session.execute(
                select(
                    func.strftime("%H", models.Event.ts).label("hour"),
                    func.count().label("count"),
                )
                .where(and_(*conditions))
                .group_by(text("hour"))
                .order_by(text("hour"))
            )
            return {row.hour: row.count for row in result.all()}
```

**Análogo de la forma del método en esta clase — `recent()`, `repositories.py:244-261`**
(`async with self._sf() as session`, sin `session.begin()` porque es lectura, y comprensión de
dict/lista sobre `result`):

```python
    async def recent(self, camera_id: str, limit: int = 60) -> list[dict[str, Any]]:
        async with self._sf() as session:
            result = await session.execute(
                select(models.DetectionStat)
                .where(models.DetectionStat.camera_id == camera_id)
                .order_by(models.DetectionStat.minute.desc())
                .limit(limit)
            )
            return [ ... for r in result.scalars().all()]
```

**Qué adaptar:** la query concreta ya la escribió el research (Q7, con su docstring de 3
párrafos justificando el doble `GROUP BY` y el uso de `unique_tracks`); `text` y `func` ya
están importados (`repositories.py:15`). No hace falta índice nuevo.

**`ConfigRepo` NO se toca** (`repositories.py:551-574`): `get`/`set`/`get_all` ya existen y son
suficientes. Lo nuevo es que esta fase es su **primer usuario en todo el repo**. El patrón de
instanciación a copiar está en `backend/api/v2/recordings.py:25-26` y en `main.py:258`:

```python
def _recording_repo() -> RecordingRepo:
    return RecordingRepo(get_session_factory())
```
```python
    event_repo = EventRepo(get_session_factory())
```

---

### `backend/database.py` (MOD — 2 líneas para `kind`)

**Análogo: el modelo v2 ya lo hace bien.** `ZoneRepo._to_dict` (`repositories.py:500-506`)
devuelve `kind`, y `models.Zone` lo declara (`models.py:168`, `kind = Column(String(30), nullable=True)`).
El ORM legacy que alimenta al pipeline se quedó atrás — `database.py:37-44`:

```python
class Zone(Base):
    __tablename__ = "zones"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    polygon_json = Column(String, nullable=False)  # JSON: [[x_frac, y_frac], ...]
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
```

y `get_zones()` — `database.py:295-309`:

```python
async def get_zones() -> list[dict[str, Any]]:
    """Return all zones ordered by creation date."""
    sf = _get_session_factory()
    async with sf() as session:
        result = await session.execute(select(Zone).order_by(Zone.created_at))
        return [
            {
                "id": z.id,
                "name": z.name,
                "polygon_json": z.polygon_json,
                "enabled": bool(z.enabled),
                "created_at": z.created_at.isoformat(),
            }
            for z in result.scalars().all()
        ]
```

**Cambio exacto:** una línea `kind = Column(String(30), nullable=True)` en la clase (copiando
la declaración de `models.py:168` **carácter a carácter**, para que ambas mapeen la misma
columna física) y una línea `"kind": z.kind,` en el dict. El consumidor
(`_rebuild_zone_states`, `detection.py:316-338`) ya recibe el dict `z` completo.

---

### `backend/api/v2/context.py` (CREAR — router de lectura)

**Análogo principal: `backend/api/v2/metrics.py:19-42`** — el patrón `configure()` con global de
módulo, que es la única forma limpia de inyectar la referencia viva sin ciclo de imports:

```python
router = APIRouter(tags=["metrics"])

_latency_tracker: Any = None


def configure(latency_tracker: Any) -> None:
    """Wire the live LatencyTracker instance. Called once from main.py's lifespan."""
    global _latency_tracker
    _latency_tracker = latency_tracker


@router.get("/metrics")
@limiter.limit(V2_RATE_LIMIT)
async def prometheus_metrics(request: Request) -> PlainTextResponse:
    return PlainTextResponse(generate_latest_text(), media_type="text/plain; version=0.0.4")
```

**Análogo secundario: `backend/api/v2/recordings.py:1-52`** — el docstring que explica auth y
rate limit, el `prefix`, la factoría privada de repo y la firma con `request: Request`:

```python
"""API v2 — recordings: listing, detail, thumbnail, retry-upload (Fase 20).

Auth and rate limiting: the app applies auth globally (FastAPI(dependencies=[Depends(verify)])),
so routers included via app.include_router() inherit it automatically — no per-route
Depends(verify) needed here, matching the v1 endpoints' convention. Rate limiting
(SEC-16, Fase 22) uses the shared limiter/rate value from backend/api/v2/deps.py.
"""
...
from backend.api.v2.deps import V2_RATE_LIMIT, limiter, pagination_limit
from backend.database import get_session_factory
from backend.storage.repositories import EventRepo, RecordingRepo, UploadState

router = APIRouter(prefix="/api/v2/recordings", tags=["recordings"])


def _recording_repo() -> RecordingRepo:
    return RecordingRepo(get_session_factory())


@router.get("")
@limiter.limit(V2_RATE_LIMIT)
async def list_recordings(
    request: Request,
    camera_id: str | None = Query(default=None),
    ...
```

**Qué copiar literalmente:**
- `router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])`.
- `@limiter.limit(V2_RATE_LIMIT)` + `request: Request` **en cada endpoint**
  (`tests/test_security_regression.py:128` recorre las rutas y falla si falta alguno).
- El bloque de docstring sobre auth heredada (copiar el párrafo de `recordings.py:3-6`).
- `Query(...)` para parámetros con rango: `days: int = Query(default=7, ge=1, le=90)`
  (`deps.py:29-31` es la factoría equivalente para `limit`).
- La factoría privada de repo, `def _stat_repo() -> DetectionStatRepo`.

**Qué adaptar:** el `configure()` recibe el `CameraManager` (o el `CameraPipeline`), no el
`LatencyTracker`. La llamada va en el `lifespan` junto a la de metrics, `main.py:245-246`:

```python
    from backend.api.v2 import metrics as metrics_v2_module
    metrics_v2_module.configure(latency_tracker)
```

**Fuentes de datos del endpoint (todas ya existen, sin lógica nueva):**

| Campo | Llamada | Evidencia |
|---|---|---|
| `persons.total` | `registry.frame_ids()` | `tracking.py:113-115`; **no** `active_ids()` (96-98, arrastra el TTL de 30 s de `prune`, línea 130) |
| `persons.known/pending` | `registry.snapshot()` + `ts.identity_state` | `tracking.py:91-94` y `TrackState.identity_state`, `tracking.py:32-34` |
| `zones[]` | `pipeline.get_zone_stats()` | `manager.py:286-287` → `detection.py:125-130` |
| `objects[]` | `detection.get_object_stats()` (nuevo) | mismo patrón que `get_zone_stats` |
| `activity.*` | `DetectionStatRepo.hourly_baseline(...)` (nuevo) | ver sección de repositorios |

---

### `backend/api/v2/detection.py` (CREAR — GET/PUT de clases activas)

**Análogo de estructura:** el mismo `recordings.py` de arriba (router con prefix + limiter).
**Análogo del método que muta y devuelve códigos de error** — `recordings.py:88-101`:

```python
@router.post("/{recording_id}/retry-upload")
@limiter.limit(V2_RATE_LIMIT)
async def retry_upload(request: Request, recording_id: int):
    """Requeue a permanently failed upload as pending for the next poll cycle."""
    repo = _recording_repo()
    rec = await repo.get(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec["upload_state"] != UploadState.FAILED.value:
        raise HTTPException(
            status_code=409, detail=f"Recording is {rec['upload_state']!r}, not failed"
        )
    await repo.mark_upload(recording_id, UploadState.PENDING, next_attempt_at=None)
    return await repo.get(recording_id)
```

**Análogo de la validación de body + propagación al pipeline** — `main.py:908-931`
(`POST /api/zones`). Es el precedente **exacto** del flujo "valida → persiste → empuja al
pipeline → devuelve el estado nuevo":

```python
@app.post("/api/zones")
async def api_upsert_zone(request: Request):
    """Create or update a zone. Body: {id, name, polygon_json, enabled?}."""
    body = await request.json()
    zone_id = str(body.get("id", "")).strip()
    ...
    if not zone_id or not name:
        raise HTTPException(status_code=400, detail="id and name are required")
    if len(zone_id) > 50 or len(name) > 100:
        raise HTTPException(status_code=400, detail="id/name too long")
    ...
    await upsert_zone(zone_id, name, _json.dumps(pts), enabled)
    zones = await get_zones()
    if rtsp_stream is not None:
        rtsp_stream.set_zones(zones)
    return {"zones": zones}
```

**Qué copiar:** el orden (validar → 400 con `detail` explicativo → persistir → propagar bajo
guarda `if <pipeline> is not None` → devolver el estado resultante) y el `detail` en lenguaje
llano.
**Qué adaptar:**
- La referencia al pipeline **no puede ser el global `rtsp_stream` de `main.py`** (ciclo de
  imports, RESEARCH Q5): se usa el `configure()` del módulo, patrón `metrics.py`.
- La validación es la de RESEARCH Q6 (enteros 0..79, no vacía, sin duplicados, `0` obligatorio).
  A diferencia de `/api/zones`, aquí conviene un modelo Pydantic de body en vez de
  `await request.json()`: el repo ya usa Pydantic para validar entrada en
  `backend/events/rules.py:24` (`class When(BaseModel)`), y `main.py:908` es código de la Fase
  13, anterior a la convención v2.
- Tras persistir + propagar, emitir `CONFIG_CHANGED` (tipo ya en el catálogo, `types.py:45`).

---

### `backend/main.py` (MOD — composition root)

Cuatro puntos, todos con precedente literal en el fichero.

**1. Lectura de `AppConfig` antes de construir el detector** — `main.py:238` (`init_db`) ya
corrió, y el detector se construye en `281-287`:

```python
    detector = PersonDetector(
        model_path=settings.yolo_model_path,
        confidence=settings.yolo_confidence,
        classes=settings.yolo_classes,
        label=settings.detection_label,
        imgsz=settings.yolo_imgsz,
    )
```

El molde para instanciar un repo en el lifespan es `main.py:258`:
`event_repo = EventRepo(get_session_factory())`.

**2. Propagación de settings** — bloque contiguo al final de `camera_manager.add(...)`,
`main.py:413-454`; las últimas 10 líneas son el bloque de la Fase 26, uno por línea, sin lógica:

```python
        reid_max_gallery_entries=settings.reid_max_gallery_entries,
        behavior_enabled=settings.behavior_enabled,
        loiter_secs=settings.loiter_secs,
        loiter_radius_px=settings.loiter_radius_px,
        loiter_require_zone=settings.loiter_require_zone,
        run_speed_px_s=settings.run_speed_px_s,
        run_window_secs=settings.run_window_secs,
        immobile_secs=settings.immobile_secs,
        immobile_radius_px=settings.immobile_radius_px,
        crowd_threshold=settings.crowd_threshold,
        behavior_max_tracks=settings.behavior_max_tracks,
    )
```

**3. `configure()` del router de contexto** — junto al de metrics, `main.py:245-246` (citado
arriba). Debe ir **después** de crear `camera_manager` (línea 412), no en la 245.

**4. `include_router`** — `main.py:557-561`, a nivel de módulo, con import local:

```python
from backend.api.v2.recordings import router as recordings_v2_router
app.include_router(recordings_v2_router)

from backend.api.v2.metrics import router as metrics_v2_router
app.include_router(metrics_v2_router)
```

Y el precedente de cargar estado persistido en el pipeline tras arrancar — `main.py:467-468`:

```python
    # Load persisted zones into the detection worker
    pipeline.set_zones(await get_zones())
```

> Si el planner prefiere leer las clases persistidas **después** de `pipeline.start()` en vez de
> antes de construir el detector, este es el patrón; pero RESEARCH Q6 recomienda antes (línea
> 281) para que el primer frame ya salga con las clases correctas.

---

### `frontend/index.html` (MOD — panel de clases + panel de contexto)

**Análogo exacto: el panel de zonas.** Tres piezas.

**Markup del card + panel oculto** — `index.html:658-700` (extracto de la cabecera y el patrón
de panel plegable):

```html
      <!-- INTEREST ZONES -->
      <div class="card bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <svg class="w-4 h-4 text-slate-500" ...></svg>
            <h2 class="text-sm font-semibold text-slate-200">Zonas de interés</h2>
          </div>
          <button id="btn-add-zone" class="text-xs text-blue-400 hover:text-blue-300 transition-colors cursor-pointer" aria-label="Añadir zona">+ Añadir</button>
        </div>
        <!-- Add zone form (hidden) -->
        <div id="add-zone-panel" class="hidden mb-3 p-3 bg-slate-800/60 border border-slate-700 rounded-xl flex flex-col gap-2">
          ...
          <p id="zone-msg" class="text-xs text-center hidden"></p>
        </div>
        <div id="zones-list" class="flex flex-col gap-1.5 overflow-y-auto" style="max-height:140px">
          <div id="zones-empty" class="flex flex-col items-center justify-center py-5 text-center">
            <p class="text-slate-600 text-xs">Sin zonas configuradas</p>
          </div>
        </div>
      </div>
```

**JS de guardado con fetch + estado del botón + mensaje de error** — `index.html:1708-1733`:

```javascript
      const btn = document.getElementById('zone-save-btn');
      btn.disabled = true; btn.style.opacity = '0.5';
      try {
        const res = await fetch('/api/zones', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: zoneId, name: zoneName, polygon_json: JSON.stringify(pts), enabled: true }),
        });
        if (res.ok) {
          addZonePanel.classList.add('hidden');
          showToast(`Zona "${zoneName}" guardada`, 'success');
          loadZones();
        } else {
          const d = await res.json().catch(() => ({}));
          zoneMsg.textContent = d.detail ?? 'Error al guardar.';
          zoneMsg.className = 'text-xs text-center text-red-400';
          zoneMsg.classList.remove('hidden');
        }
      } catch {
        zoneMsg.textContent = 'Sin respuesta del servidor.';
        zoneMsg.className = 'text-xs text-center text-red-400';
        zoneMsg.classList.remove('hidden');
      } finally {
        btn.disabled = false; btn.style.opacity = '';
      }
```

**Qué copiar literalmente:** `fetch` con `Content-Type: application/json`, `if (res.ok)` →
`showToast(...)` + recarga; `else` → leer `d.detail` del backend (por eso los `HTTPException`
del PUT deben traer `detail` legible); `catch` para "sin respuesta"; `finally` que rehabilita
el botón.

**Carga + repintado** — `index.html:1735-1744` y la llamada inicial en la 1772 (`loadZones();`):

```javascript
    async function loadZones() {
      try {
        const res = await fetch('/api/zones');
        if (!res.ok) return;
        const data = await res.json();
        const zones = data.zones ?? [];
        const list  = document.getElementById('zones-list');
        const empty = document.getElementById('zones-empty');
        list.querySelectorAll('.zone-row').forEach(el => el.remove());
        if (zones.length === 0) { empty.style.display = ''; return; }
```

**Refresco periódico del panel de contexto** — el idioma del fichero es `setInterval` al final
del bloque, con periodos por tipo de dato (`index.html:1438` `loadRecordings, 30000`;
`1893` `loadHealth, 30000`; `1939` `loadObservability, 5000`; `842`/`854` contadores cada 2000).
El contexto de escena encaja con 5000-10000 ms.

**Restricción:** todo inline en `index.html`, sin módulos ES (decisión ya tomada; el refactor es
la Fase 28). `frontend/app.js` sigue siendo un stub.

---

### Tests

#### `tests/test_object_analyzer.py` (NUEVO — dominio puro)

**Análogo: `tests/test_behavior_analyzer.py:1-46`** — docstring, helpers locales, y el estilo de
aserción sobre el conjunto:

```python
"""Tests para BehaviorAnalyzer (Fase 26, BEH-01/BEH-02/BEH-03/BEH-05).

Dominio puro: sin hilos, sin bus, sin reloj real. El reloj se inyecta como
float sintetico, igual que en test_track_gallery.py y
test_identity_state_machine.py. Las trayectorias son sinteticas y deterministas
(patron de las Fases 24/25): cada test construye la secuencia de posiciones
minima que aisla el comportamiento bajo prueba, sin supresion mutua en el
dominio (D-03).
"""
...
def _jitter_run(analyzer, track_id, cx, cy, n, dt, amp, zone_membership=None, start_t=0.0):
    """Alimenta `n` frames de jitter ciclico (±amp) alrededor de (cx, cy).

    Ciclo de 3 fases (-amp, 0, +amp): el desplazamiento neto entre fases
    consecutivas es `amp`, no `2*amp` (nunca salta directamente de -amp a
    +amp). Devuelve la lista acumulada de findings.
    """
    zone_membership = zone_membership or {}
    findings: list[BehaviorFinding] = []
    for i in range(n):
        t = start_t + i * dt
        x = cx + amp * ((i % 3) - 1)
        findings.extend(analyzer.analyze({track_id: (x, cy)}, zone_membership, {}, t))
    return findings


def TEST_immobile_after_threshold():
    analyzer = BehaviorAnalyzer()
    findings = _jitter_run(analyzer, 1, 100.0, 100.0, n=561, dt=0.125, amp=2.0)
    imm = [f for f in findings if f.kind is BehaviorKind.IMMOBILE]
    assert len(imm) == 1
    assert imm[0].duration_s > 60
    assert imm[0].net_displacement_px <= 20
```

**Qué copiar:** el helper de jitter cíclico de 3 fases (es exactamente el escenario "objeto
inmóvil con ruido de bbox"), `dt=0.125` (8 FPS), la aserción `len(...) == 1` para el latch, y
`f.kind is <Kind>` con `is`, no `==`.
**Qué adaptar:** el analizador recibe **más argumentos** (objetos, personas, zonas excluidas,
`now`), así que el helper debe aceptar la lista de personas. Y para el criterio 5 el research
exige aserción sobre el **conjunto completo** (`assert kinds == {ObjectKind.LEFT}`), no sobre
la presencia.

#### `tests/test_detection_worker.py` (AMPLIAR — cableado y regresiones)

Helper posicional a extender — `test_detection_worker.py:253-260` (RESEARCH prohíbe escribir un
cuarto helper: hay que hacer **una** variante `_tracked_cls` y reutilizarla):

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

Construcción del worker con la dependencia inyectada y llamada directa al método privado —
`test_detection_worker.py:329-346`:

```python
def TEST_behavior_analyzer_emits_crowd_from_worker():
    broker = FrameBroker()
    event_engine = MagicMock()
    worker = DetectionWorker(
        broker.subscribe("detector"), MagicMock(), MagicMock(),
        TrackRegistry(), AdaptiveRate(),
        event_engine=event_engine,
        behavior=BehaviorAnalyzer(crowd_threshold=5),
    )
    boxes = [[i * 100, 10, i * 100 + 30, 50] for i in range(5)]
    tids = [1, 2, 3, 4, 5]

    worker._analyze_behavior(_tracked_at(boxes, tids), captured_at=0.0, processed_at=0.0)

    event_engine.emit_behavior.assert_called_once()
    finding = event_engine.emit_behavior.call_args[0][0]
    assert finding.kind == BehaviorKind.CROWD
```

Aislamiento de fallos — `test_detection_worker.py:363-378`:

```python
def TEST_behavior_failure_does_not_kill_thread():
    ...
    behavior = MagicMock()
    behavior.analyze.side_effect = RuntimeError("boom")
    ...
    worker._analyze_behavior(_tracked_at([[10, 10, 50, 50]], [1]), captured_at=0.0, processed_at=0.0)

    assert worker._exceptions == 1
    event_engine.emit_behavior.assert_not_called()
```

**Y el test que protege el patrón "fuera de la factoría" — `test_detection_worker.py:400-420`,
molde literal del que exige RESEARCH Pitfall 4:**

```python
# ─── El BehaviorAnalyzer sobrevive a un reinicio del worker por el supervisor ─
def TEST_behavior_analyzer_survives_worker_restart():
    """El analizador se construye FUERA de _make_detection (manager.py): un
    reinicio del worker (el supervisor la re-ejecuta) no debe borrar las
    anclas y latches ya acumulados -- eso produciria una rafaga de eventos
    duplicados en el frame siguiente. Mismo motivo que la FSM de identidad
    (Fase 24) y la galeria de apariencia (Fase 25)."""
    from backend.pipeline.manager import CameraPipeline

    pipeline = CameraPipeline("cam1", "rtsp://fake", detector=MagicMock(), tracker=MagicMock())

    factory = pipeline.supervisor._entries["detector"].factory
    worker1 = factory()
    analyzer = pipeline.behavior
    assert analyzer is not None
    assert worker1._behavior is analyzer

    worker2 = factory()
    assert worker2 is not worker1
    assert pipeline.behavior is analyzer     # misma instancia, no una nueva
    assert worker2._behavior is analyzer
```

> Replicar **dos veces**: para `ObjectAnalyzer` y para `ObjectTracker` (si el tracker se
> reconstruyera, los `track_id` de objeto volverían a 1 y todo el mobiliario "aparecería" otra
> vez). El acceso a `pipeline.supervisor._entries["detector"].factory` es la convención aceptada
> en este fichero. Y el par lo completa `TEST_behavior_disabled_leaves_pipeline_without_analyzer`
> (424-438) para `objects_enabled=False`.

#### `tests/test_detector.py` (AMPLIAR — `set_classes` + criterio 6)

Fixture con YOLO mockeado — `test_detector.py:30-36` (para `set_classes`, sin pesos):

```python
@pytest.fixture
def detector():
    """PersonDetector with a mocked YOLO backend (no weights loaded)."""
    with patch("backend.detector.YOLO") as MockYOLO:
        d = PersonDetector(model_path="yolov8n.pt", confidence=0.45)
        d._mock_model = MockYOLO.return_value
        yield d
```

Aserción sobre los kwargs que llegan al modelo — `test_detector.py:94-101`:

```python
def TEST_033_detect_passes_confidence_and_classes_to_model(detector, blank_frame):
    """detect() forwards configured confidence and classes to the YOLO call."""
    detector._mock_model.return_value = [_make_yolo_result([])]
    detector.detect(blank_frame)
    _, kwargs = detector._mock_model.call_args
    assert kwargs["conf"] == 0.45
    assert kwargs["classes"] == [0]
    assert kwargs["verbose"] is False
```

> `TEST_set_classes` = llamar `detector.set_classes([0, 24])`, ejecutar `detect_sv`, y afirmar
> `kwargs["classes"] == [0, 24]` **y** que `detector._model` es el mismo objeto (`id()` estable).

Benchmark del criterio 6 — molde literal `tests/test_reid_engine.py:54-70`:

```python
def TEST_reid_latency_under_20ms(engine, person_crop_bgr):
    """Criterio 1 (latencia). Se mide p50, no un maximo ni una sola llamada:
    el p95 medido en el research sube a ~30 ms por jitter del planificador de
    Windows en esta maquina compartida, un assert sobre una sola llamada seria
    flaky."""
    for _ in range(5):                       # warmup: la primera inferencia paga la
        engine.embed(person_crop_bgr)        # inicializacion de los kernels de ORT
    samples = []
    for _ in range(30):                      # >= 30 iteraciones
        t0 = time.perf_counter()
        engine.embed(person_crop_bgr)
        samples.append(time.perf_counter() - t0)
    p50 = statistics.median(samples)
    assert p50 < 0.020, (
        f"criterio 1: p50 de embed() = {p50 * 1000:.2f} ms, se exige < 20 ms "
        f"(medido en el research: 5,50 ms; 84,5 ms si el eje batch sigue fijo a 16)"
    )
```

**Qué copiar:** 5 warmup + 30 muestras + `statistics.median`, assert sobre **p50**, y el mensaje
de fallo con la cifra medida en el research (aquí: 38,90 ms con 1 clase, 40,74 con 6, +4,7 %).
Este test carga pesos reales, así que va con el mismo tipo de fixture `scope="module"` que usa
`test_reid_engine.py:40-43`, no con el YOLO mockeado.

#### `tests/test_memory_bounds.py` (AMPLIAR — cota del analizador)

Par con/sin prune — `test_memory_bounds.py:318-340` (**dos tests, no uno**: es lo que demuestra
la doble guarda):

```python
# ─── BehaviorAnalyzer._aggs / _loiter no acumulan tracks efimeros ────────────
# ByteTrack asigna ids monotonamente crecientes y nunca los reutiliza (Fase 26,
# criterio 4). Sin doble guarda (TTL de state_ttl + cota dura max_tracks) un
# proceso 24/7 haria crecer _aggs y _loiter sin limite: cada track efimero deja
# una entrada por track y otra por (track, zona implicita).
# ─────────────────────────────────────────────────────────────────────────────
def TEST_behavior_state_bounded():
    analyzer = BehaviorAnalyzer(max_tracks=256, state_ttl=30.0)
    for tid in range(10_000):
        now = float(tid)
        analyzer.analyze({tid: (1.0, 1.0)}, {}, {}, now)
        analyzer.prune(now, frame_ids={tid})
    assert len(analyzer._aggs) <= 256
    assert len(analyzer._loiter) <= 256


def TEST_behavior_state_bounded_without_prune():
    """La cota dura actua aunque el mantenimiento periodico nunca se ejecute."""
    analyzer = BehaviorAnalyzer(max_tracks=256)
    for tid in range(10_000):
        analyzer.analyze({tid: (1.0, 1.0)}, {}, {}, float(tid))
    assert len(analyzer._aggs) <= 256
    assert len(analyzer._loiter) <= 256
```

**Qué copiar:** banda de comentario `─` con el motivo antes de la función, bucle de `10_000`,
acceso directo al atributo privado (convención aceptada en este fichero), y el par con/sin
prune.
**Qué adaptar:** afirmar también sobre el `set` de ids ignorados del warmup
(`len(analyzer._ignored) <= 256`), que es la estructura nueva de esta fase.

#### `tests/test_event_engine.py` (AMPLIAR — `emit_object`)

Molde — `test_event_engine.py:294-355` (los tres tests: traducción de kinds, payload, severidad):

```python
async def TEST_emit_behavior_translates_the_four_kinds():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_behavior(
        BehaviorFinding(kind=BehaviorKind.LOITERING, track_id=3, zone_id="z1",
                        duration_s=130.0, net_displacement_px=42.0), now,
    )
    ...
    await wait_until(lambda: len(received) == 4)

    assert {e.type for e in received} == {
        EventType.LOITERING, EventType.RUNNING, EventType.IMMOBILE, EventType.CROWD_DETECTED,
    }
...
async def TEST_emit_behavior_payload_carries_magnitudes():
    ...
    assert event.payload["duration_s"] == 61.0
    assert "speed_px_s" not in event.payload
    assert all(v is not None for v in event.payload.values())
...
async def TEST_emit_behavior_keeps_default_info_severity():
    ...
    assert all(e.severity is Severity.INFO for e in received)
```

**Qué adaptar:** el tercer test se invierte — `OBJECT_LEFT` debe salir con
`Severity.WARNING` y `OBJECT_REMOVED` con `Severity.INFO`, **sin pasar `severity=`**
(`types.py:49-57`). Ese test es el que documenta que la subida a Drive es intencional.

#### `tests/test_config.py` (AMPLIAR — defaults + rangos + D-03)

Molde — `test_config.py:283-321`:

```python
def TEST_behavior_defaults_match_spec():
    """Settings() expone los 10 parametros behavior_* con los defaults del SPEC."""
    s = Settings()
    assert s.behavior_enabled is True
    assert s.loiter_secs == 120.0
    ...

def TEST_behavior_params_must_be_positive():
    """loiter_secs, immobile_secs, loiter_radius_px, run_speed_px_s, crowd_threshold y behavior_max_tracks <= 0 lanzan."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(loiter_secs=0)
    ...
```

**Qué adaptar:** añadir `TEST_yolo_model_default_is_yolo26n` (D-03) y el caso
`0 in object_class_ids` → lanza (RESEARCH § Bloque de configuración).

#### `tests/test_repositories.py` (AMPLIAR — `hourly_baseline` + `ConfigRepo`)

Fixture de BD in-memory por test — `test_repositories.py:20-31`:

```python
@pytest_asyncio.fixture
async def db(tmp_path):
    db_file = tmp_path / "storage_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        async with session.begin():
            session.add(models.Camera(id="cam1", name="Cam 1", enabled=True))
    yield str(db_file), sf
    await engine.dispose()
```

Siembra + aserción sobre una agregación — `test_repositories.py:92-119`:

```python
async def TEST_detection_stats_upsert(db):
    _, sf = db
    repo = DetectionStatRepo(sf)
    minute = datetime.datetime(2026, 1, 1, 12, 5, 0)

    await repo.upsert_minute("cam1", minute, detections=10, unique_tracks=2, avg_confidence=0.8, max_concurrent=2)
    ...
async def TEST_count_since_and_hourly_counts(db):
    ...
    assert hourly == {"09": 2, "14": 1}
```

**Qué copiar:** sembrar con el propio repo (`upsert_minute`), fechas fijas y explícitas, y
afirmar sobre el dict completo (`==`, no `in`). La clave de hora es **string de dos dígitos**
(`"09"`), porque viene de `strftime("%H", ...)` — el test de `hourly_baseline` debe usar la
misma convención.

#### `tests/test_scene_context.py` y `tests/test_detection_config_api.py` (NUEVOS)

Cliente ASGI — `test_security_regression.py:27-28` (el patrón del repo para pegar a la app sin
levantar servidor):

```python
async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test")
```

y el uso con parcheo del global del pipeline — `test_security_regression.py:50-58`:

```python
async def TEST_vuln_02_enroll_face_rejects_bad_content_type():
    with patch.object(main_module, "rtsp_stream", _mock_recognizer_stream()):
        async with await _client() as client:
            resp = await client.post(
                "/api/enroll_face",
                data={"name": "Eve"},
                files={"image": ("evil.txt", b"not an image", "text/plain")},
            )
    assert resp.status_code == 415
```

**Qué adaptar:** como el router nuevo usa `configure()` con un global **de su propio módulo**
(no `main_module.rtsp_stream`), el parcheo es
`patch.object(context_module, "_camera_manager", <mock>)` — o simplemente llamar a
`context_module.configure(mock)` en el test. Es más limpio que el `patch.object` de la Fase 22 y
es la ventaja de copiar `metrics.py` en vez del global de `main.py`.

**Restricción de nombres:** `pytest.ini` fija `python_functions = TEST_*`. Todo lo nuevo va en
`TEST_*` (en Linux/CI los `test_*` dejarían de recogerse en silencio).

---

## Shared Patterns

### Construcción con estado FUERA de la factoría del supervisor

**Fuente (3 precedentes, es convención, no coincidencia):**
`manager.py:107-124` (`BehaviorAnalyzer`, Fase 26) · `manager.py:165-178` (`IdentityStateMachine`,
Fase 24) · `manager.py:180-192` (`ReIDEngine` + `TrackGallery`, Fase 25).
**Aplicar a:** `ObjectAnalyzer` **y** `ObjectTracker`.
**Señal de que está mal:** `ObjectAnalyzer(` u `ObjectTracker(` dentro de un `def _make_*`.
**Test asociado:** `tests/test_detection_worker.py:400-420` (comparación de identidad de
instancia tras invocar la factoría dos veces).
**Agravante propio de esta fase:** reconstruir reabre la ventana de warmup y reinicia los ids
de objeto → ráfaga de `OBJECT_LEFT` (`WARNING`) → subida de clips a Drive.

### Doble guarda de memoria: TTL + cota dura LRU

**Fuente:** `backend/perception/behavior.py:245-283` (excerpt completo arriba), a su vez calcada
de `backend/perception/reid/gallery.py:129-158`.
**Aplicar a:** `ObjectAnalyzer._aggs` **y** al `set` de ids ignorados del warmup.
**Clave:** `_enforce_cap()` se invoca también desde el camino de escritura (`analyze()`,
`behavior.py:241-243`), no solo desde `prune()`.
**Test asociado:** `tests/test_memory_bounds.py:318-340` (par con/sin prune).

### Reloj inyectado

**Fuente:** `behavior.py:3-6` y `112-118`. Toda función de dominio recibe `now: float`
(monotónico). **Ningún `import time` en `backend/perception/objects.py`.** El llamador pasa
`processed_at` (`detection.py:218`), que es `time.monotonic()` medido en la línea 182 —
**después** de `self._rate.observe()`, para no contaminar el control adaptativo.

### Aislamiento de fallos en el hilo del worker

**Fuente:** `backend/pipeline/detection.py:191-227` (`_analyze_behavior`, que a su vez cita
`recognition.py:366-374`).
**Forma canónica:** guardas de `None` → `try` con dominio **y** `prune` dentro →
`except Exception: self._exceptions += 1; logger.exception(...); return` → bucle de emisión
**fuera** del `try`.
El contador ya se expone en `stats` (`detection.py:112-117`) → sale gratis en
`/api/v2/cameras/{id}/health`.

### Mutar la instancia viva en vez de reconstruirla

**Fuente:** `backend/tracker.py:129-142` (`set_frame_rate`, con el "por qué" en el docstring).
**Aplicar a:** `PersonDetector.set_classes()` y `DetectionWorker.set_object_classes()`.
**Contra-ejemplo del repo (leerlo para NO imitarlo aquí):** `manager.py:301-308`
(`set_process_size` sí reinicia el `CaptureWorker`) — vale para captura, nunca para el
`DetectionWorker` (RESEARCH Pitfall 5).

### Setter thread-safe + snapshot bajo lock

**Fuente:** `detection.py:119-123` (`set_zones`) y `detection.py:281-284` (snapshot en el hilo).
**Aplicar a:** `set_object_classes`, `get_object_stats`, `get_object_boxes`.
**Regla:** el escritor es el event loop, el lector es el hilo de detección; siempre rebind del
atributo, nunca mutación in-place.

### Router v2: prefix + limiter + configure()

**Fuente:** `backend/api/v2/metrics.py:19-33` (global + `configure`) y
`backend/api/v2/recordings.py:1-31` (docstring de auth, prefix, factoría de repo,
`@limiter.limit(V2_RATE_LIMIT)` + `request: Request`).
**Aplicar a:** `context.py` y `detection.py`.
**Test que lo vigila:** `tests/test_security_regression.py:128-147`
(`TEST_all_v2_endpoints_rate_limited`, `TEST_v2_rate_limit_value_is_shared_constant`) — un
endpoint v2 sin decorador rompe la suite.

### Nombre obligatorio de clave del payload

**Fuente:** `backend/events/rules.py:88-91` — `RuleEngine` lee literalmente
`event.payload.get("duration_s")` para resolver `duration_gte`.
**Aplicar a:** `OBJECT_LEFT` (segundos inmóvil) y `OBJECT_REMOVED` (segundos estable).
Cualquier otro nombre rompe las reglas YAML en silencio.

### Severidad por defecto del catálogo

**Fuente:** `backend/events/types.py:49-57` + `emit_behavior` (`engine.py:259-267`, que **no**
pasa `severity=`).
**Consecuencia específica de esta fase:** `OBJECT_LEFT: Severity.WARNING` (`types.py:55`) cruza
`upload_min_severity="warning"` → **sube clips a Drive desde el primer evento**. Es intencional,
pero el plan debe decirlo y el checkpoint manual verificarlo.

### Dirección de las dependencias

`events/ → perception/` (`engine.py:21-22`). `perception/` **nunca** importa de `backend.events`
— es lo que hace que `ObjectFinding` no pueda ser un `Event`.
`pipeline/` **nunca** importa FastAPI (`tests/test_architecture.py:128-135`).
`streaming.py` **nunca** menciona `PersonDetector` ni `detect_sv`
(`tests/test_streaming_worker.py:72-76`).

---

## No Analog Found

Ninguno sin análogo. Dos matices que el planner debe conocer:

| Elemento | Situación | Nota |
|---|---|---|
| **Primer usuario de `app_config`** | El repo **no** tiene precedente de escritura en esa tabla | `ConfigRepo` (`repositories.py:551-574`) está completo y probado por construcción, pero sin ni un llamador (verificado por grep). El análogo de *forma* es `ZoneRepo`/`RuleRepo` (mismo fichero, 459-548): factoría de repo + `upsert` + `_to_dict`. La **convención de claves** (`key = "yolo_classes"`, una por parámetro) la establece esta fase, no la copia |
| **`prune()` que devuelve findings** | `BehaviorAnalyzer.prune` devuelve `None`; el de objetos devuelve `list[ObjectFinding]` | Sin análogo exacto. El más cercano es `IdentityStateMachine.on_tick(now)` → `list[IdentityTransition]`, consumido en `recognition.py:640` (`transitions += self._fsm.on_tick(now)`): un método de mantenimiento periódico que **sí** produce veredictos. Copiar esa forma de consumo |
| **`set_zone_overlay`** | Patrón escrito pero **sin llamadores** | Si el planner elige la vía push para el overlay de objetos, está estrenando un patrón muerto en vez de copiar uno vivo. La vía pull (inyección en el constructor, como `registry`) tiene precedente en uso |

---

## Metadata

**Ámbito de búsqueda:** `backend/perception/`, `backend/pipeline/`, `backend/api/v2/`,
`backend/events/`, `backend/storage/`, `backend/detector.py`, `backend/tracker.py`,
`backend/database.py`, `backend/config.py`, `backend/main.py`, `frontend/index.html`, `tests/`

**Ficheros leídos en esta sesión:** `behavior.py` (completo), `detector.py` (completo),
`tracker.py` (completo), `detection.py` (completo), `streaming.py` (completo),
`manager.py` (completo), `tracking.py` (completo), `api/v2/metrics.py`,
`api/v2/recordings.py`, `api/v2/deps.py` (completos), `events/engine.py:1-70,230-301`,
`events/types.py:30-58`, `config.py:30-99,145-304`, `storage/repositories.py:1-60,140-264,455-574`,
`database.py:28-57,285-324`, `main.py:230-309,400-489,540-579,890-949`,
`frontend/index.html:655-709,1665-1744`, `tests/test_behavior_analyzer.py:1-75`,
`tests/test_detection_worker.py:1-45,240-309,324-438`, `tests/test_detector.py:28-142`,
`tests/test_memory_bounds.py:316-363`, `tests/test_event_engine.py:290-359`,
`tests/test_repositories.py` (completo), `tests/test_reid_engine.py:40-74`,
`tests/test_security_regression.py:1-75`, `tests/test_streaming_worker.py:17-78`,
`tests/test_architecture.py:36-135`

**Fecha de extracción:** 2026-08-16
