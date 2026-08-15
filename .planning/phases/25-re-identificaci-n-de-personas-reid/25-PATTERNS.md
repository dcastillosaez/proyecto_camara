# Phase 25: Re-identificación de personas (ReID) — Pattern Map

**Mapped:** 2026-08-13
**Files analyzed:** 19 (5 crear + 8 modificar + 6 tests)
**Analogs found:** 18 / 19 (1 parcial: `scripts/fetch_models.py`)
**Fuente de la lista de ficheros:** `25-RESEARCH.md` § "Ficheros reales de la fase"
(sustituye a SPEC §9 — `tracking.py` y `events/engine.py` NO se tocan)

Todo lo que sigue es **código real leído del repo en esta sesión**, con fichero y
líneas. El diseño (contratos, integración, throttling) ya lo cerró el RESEARCH; aquí
solo está el código que hay que imitar.

---

## File Classification

| Fichero nuevo/modificado | Rol | Flujo de datos | Analog más cercano | Calidad |
|---|---|---|---|---|
| `backend/perception/reid/__init__.py` | package init | — | `backend/perception/face/__init__.py` | exacta |
| `backend/perception/reid/engine.py` | service (adaptador de inferencia) | transform (imagen → vector) | `backend/perception/face/engine.py` (`FaceEngine`) | exacta |
| `backend/perception/reid/gallery.py` | model (dominio puro con estado) | event-driven (reloj inyectado) | `backend/perception/face/identity.py` (`TemporalVoter` + `IdentityStateMachine`) | exacta |
| `backend/perception/face/identity.py` (MOD) | model (FSM) | event-driven | el propio `on_face_result` / `_claim_lost` del fichero | exacta (self-analog) |
| `backend/pipeline/recognition.py` (MOD) | worker (hilo) | streaming (latest-frame) | el propio `_next_candidate` / `_sync_identity` (Fase 24) | exacta (self-analog) |
| `backend/pipeline/manager.py` (MOD) | wiring / factoría | request-response (construcción) | bloque `identity_fsm` en `manager.py:122-149` | exacta |
| `backend/config.py` (MOD) | config | — | bloque "Identidad temporal (Fase 24)" + `validate_identity_params` | exacta |
| `backend/main.py` (MOD) | wiring | — | `main.py:431-436` (kwargs `identity_*`) | exacta |
| `scripts/fetch_models.py` | utility / script CLI | file-I/O + red | `scripts/migrate_embeddings.py` | **parcial** (no hay precedente de descarga + sha256) |
| `requirements.txt` (MOD) | config | — | línea `onnxruntime>=1.19` | exacta |
| `.gitignore` (MOD) | config | — | bloque `data/thumbnails/` | exacta |
| `tests/test_reid_engine.py` | test (motor ONNX real) | — | `tests/test_face_engine.py` | exacta |
| `tests/test_track_gallery.py` | test (dominio puro) | — | `tests/test_identity_state_machine.py` | exacta |
| `tests/test_identity_state_machine.py` (MOD) | test | — | el propio fichero (`TEST_track_recovery_keeps_same_identity`) | exacta |
| `tests/test_recognition_worker.py` (MOD) | test (worker + mocks) | — | el propio fichero (`TEST_inference_budget_drops_on_unconfirmed_track`) | exacta |
| `tests/test_memory_bounds.py` (MOD) | test (cota de memoria) | — | `TEST_temporal_voter_bounded` | exacta |
| `tests/test_config.py` (MOD) | test (validadores) | — | `TEST_identity_ratio_out_of_range_rejected` | exacta |

---

## Pattern Assignments

### 1. `backend/perception/reid/engine.py` — `ReIDEngine`

**Analog:** `backend/perception/face/engine.py` (fichero completo, 106 líneas)

**Docstring de módulo — el patrón "adaptador fino"** (`engine.py:1-15`):

```python
"""FaceEngine — detection + landmark alignment + ArcFace embedding (buffalo_s).

Thin adapter over insightface.app.FaceAnalysis (SPEC_v2.md §5.4): insightface
already does detection (SCRFD), landmark alignment and ArcFace embedding in a
single FaceAnalysis.get() call — this module does not reimplement any of
that, it only translates insightface's Face objects into the project's own
FaceCandidate type and isolates the rest of the codebase from the
insightface API, same role backend/detector.py plays for ultralytics.
...
"""
```

**Construcción de `available` + degradación graciosa** (`engine.py:45-77`) — el patrón
exacto que `ReIDEngine.__init__` debe copiar (flag a `False` primero, `try/except` con
`logger.exception`, `return` temprano si la dependencia falta, `available` como
`@property` de solo lectura):

```python
class FaceEngine:
    """Detects faces and produces 512-d L2-normalized ArcFace embeddings.

    Degrades gracefully if insightface/onnxruntime aren't installed or the
    model fails to load — same contract as PersonRecognizer.available today.
    """

    # buffalo_s ships 5 sub-models; this project only needs detection (bbox +
    # 5-point kps) and recognition (the 512d embedding). Loading genderage
    # and the dense 2d/3d landmark models too costs ~10-20x more per call
    # for outputs nothing here reads — measured empirically (23-01-SUMMARY.md
    # Task 4): ~300ms vs ~15-40ms per detect() on this CPU for the same image.
    _ALLOWED_MODULES = ["detection", "recognition"]

    def __init__(self, model_name: str = "buffalo_s", det_size: tuple[int, int] = (320, 320)) -> None:
        self._available = False
        self._app = None
        if FaceAnalysis is None:
            logger.warning("insightface not installed — face recognition disabled")
            return
        try:
            self._app = FaceAnalysis(
                name=model_name, providers=["CPUExecutionProvider"],
                allowed_modules=self._ALLOWED_MODULES,
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)
            self._available = True
        except Exception:
            logger.exception("FaceEngine: failed to load %s", model_name)

    @property
    def available(self) -> bool:
        return self._available
```

Nota de estilo: la constante de clase lleva **un comentario que justifica la decisión
con la medición que la respalda**. `ReIDEngine` debe hacer lo mismo con `INPUT_HW`,
`_MEAN`/`_STD` (valores de boxmot) y con `intra_op_num_threads=1` (12,2 ms vs 5,0 ms
medidos en el RESEARCH).

**Normalización L2 de la salida** (`engine.py:93-106`) — la línea 106 es la que el
RESEARCH cita; aquí va con su contexto completo, incluido el patrón de "devolver `None`
en vez de lanzar cuando el motor no está":

```python
    def embed(self, frame: np.ndarray, cand: FaceCandidate | None) -> np.ndarray | None:
        """512-d L2-normalized ArcFace embedding for *cand* on *frame*.

        Calls the recognition sub-model directly (alignment via cand.kps +
        forward pass) instead of re-running full detection — verified to
        produce bit-identical output to FaceAnalysis.get()'s own embedding
        (23-CONTEXT.md) at a fraction of the cost.
        """
        if not self._available or cand is None:
            return None
        rec = self._app.models["recognition"]
        face_like = SimpleNamespace(kps=cand.kps, embedding=None)
        raw = rec.get(frame, face_like)
        return raw / np.linalg.norm(raw)
```

Diferencia obligatoria en `ReIDEngine`: `.astype(np.float32)` sobre el resultado
(el RESEARCH §Q6 lo exige para que la galería ocupe 2 KB/entrada, no 4 KB).

**Otros detalles a copiar:**
- `engine.py:17-26` — `from __future__ import annotations`, `logger = logging.getLogger(__name__)` a nivel de módulo.
- `engine.py:31-34` — import de la dependencia pesada envuelto en `try/except ImportError` con `# noqa` explicativo. Para `ReIDEngine`, `onnxruntime` ya es dependencia dura (Fase 23), así que el import puede ir directo; lo que degrada es el **fichero del modelo**, no la librería.
- `backend/perception/face/__init__.py` es una sola línea: `"""Face detection, quality gating and identity search (ArcFace / buffalo_s)."""`. `backend/perception/reid/__init__.py` debe ser igual de escueto.

---

### 2. `backend/perception/reid/gallery.py` — `TrackGallery`

**Analog:** `backend/perception/face/identity.py` (`_TrackIdentity`, `TemporalVoter`, `IdentityStateMachine`)

**Docstring de módulo — la regla de dominio puro y reloj inyectado** (`identity.py:1-12`):

```python
"""IdentityState / IdentityTransition / TemporalVoter — identidad temporal (Fase 24).

SPEC_v2.md §5.5 fija el contrato de TemporalVoter (window/min_votes/min_ratio) y
los 4 estados de identidad. Este modulo es dominio puro: no importa `time`, no
arranca hilos, no hace I/O y no construye eventos. Todos los metodos que dependen
del reloj lo reciben como parametro `now: float` (monotonico), igual que
AdaptiveRate.should_process(now) en backend/pipeline/rate.py.

Fuera de alcance aqui: publicar eventos (lo hace EventEngine traduciendo
IdentityTransition), persistir el estado y la re-identificacion por apariencia
sin cara visible (Fase 25).
"""
```

(La última frase de ese docstring es literalmente esta fase — merece actualizarse.)

**`_TrackIdentity` — plantilla exacta de `_GalleryEntry`** (`identity.py:111-124`).
Fíjate en que **cada campo lleva su comentario en línea** cuando su semántica no es
obvia, y en que la referencia al patrón hermano va en el docstring:

```python
@dataclass
class _TrackIdentity:
    """Estado de identidad de un track (patron `TrackState` de tracking.py)."""

    state: IdentityState = IdentityState.UNKNOWN
    person_id: int | None = None
    confidence: float = 0.0
    last_face_at: float = 0.0            # ultima inferencia facial de este track
    last_revalidation_at: float = 0.0    # ultima revalidacion CON EXITO (D-06)
    lost_at: float | None = None         # instante de entrada en TEMPORARILY_LOST
    failed_revalidations: int = 0
    recognized_emitted: bool = False     # PERSON_RECOGNIZED ya emitido (una vez)
    unknown_emitted: bool = False        # UNKNOWN_PERSON ya emitido (una vez, D-02)
```

**Docstring de clase + `__init__` con parámetros de política** (`identity.py:126-148`):

```python
class IdentityStateMachine:
    """4 estados de identidad por track y sus transiciones (SPEC_v2.md §5.5, FACE-08).

    Reloj inyectado: ningun metodo llama a time.monotonic(). Un solo hilo
    (RecognitionWorker._loop), por eso no hay lock.

    No construye Event: devuelve IdentityTransition y EventEngine traduce.
    """

    MAX_FAILED_REVALIDATIONS = 3   # criterio 5: tres ciclos de revalidacion (D-04)

    def __init__(
        self,
        voter: TemporalVoter | None = None,
        lost_ttl: float = 30.0,
        revalidate_after: float = 120.0,
        low_confidence: float = 0.55,
    ) -> None:
        self._voter = voter if voter is not None else TemporalVoter()
        self._lost_ttl = lost_ttl
        self._revalidate_after = revalidate_after
        self._low_confidence = low_confidence
        self._states: dict[int, _TrackIdentity] = {}
```

**Gate por track — plantilla literal de `needs_embedding()`** (`identity.py:381-404`).
El RESEARCH dice "espejo exacto"; este es el original, con su docstring justificando
**por qué** existe el gate (el coste que evita), no solo qué hace:

```python
    def needs_recognition(self, track_id: int, now: float) -> bool:
        """A quien merece la pena hacerle inferencia facial ahora mismo (FACE-11).

        Sustituye al filtro `person_id is None` de RecognitionWorker._next_candidate,
        que reintentaba indefinidamente sobre los tracks que nunca llegan a
        identificarse (~120 inferencias/min a 2 FPS, para siempre).
        """
        st = self._states.get(track_id)
        if st is None:
            return True                                    # track nuevo
        if st.state is IdentityState.CANDIDATE:
            return True                                    # votacion en curso
        ...
        return (now - st.last_face_at) >= self._revalidate_after
```

**Prune por ids activos con la justificación de ByteTrack** (`identity.py:103-108`) —
la forma de comentario que `TrackGallery.prune(now, frame_ids)` debe reproducir:

```python
    def prune(self, active_track_ids: set[int]) -> None:
        """ByteTrack nunca reutiliza track_ids: sin prune, _votes crece sin cota en
        un proceso 24/7 (invariante de la Fase 22). Sin lock: un solo hilo."""
        for tid in list(self._votes):
            if tid not in active_track_ids:
                del self._votes[tid]
```

---

### 3. Patrón de expiración con doble guarda (TTL + cota dura)

**Source:** `backend/perception/face/identity.py:425-457` (`on_tick`)
**Apply to:** `TrackGallery.prune(now, frame_ids)` + `max_entries`

Este es el patrón que el RESEARCH §Q6 manda replicar. La primera guarda es el TTL
explícito; la segunda (líneas 450-457) es el "seguro de vida" que actúa **aunque nadie
llame al mantenimiento a tiempo** — y su comentario explica exactamente eso:

```python
    def on_tick(self, now: float) -> list[IdentityTransition]:
        stale_ttl = self._lost_ttl + self._revalidate_after * self.MAX_FAILED_REVALIDATIONS
        out: list[IdentityTransition] = []
        for tid in list(self._states):
            st = self._states.get(tid)
            if st is None:
                continue
            if (
                st.state is IdentityState.TEMPORARILY_LOST
                and st.lost_at is not None
                and now - st.lost_at > self._lost_ttl
            ):
                person_id = st.person_id
                del self._states[tid]
                self._voter.reset(tid)
                out.append(
                    IdentityTransition(
                        tid,
                        IdentityState.TEMPORARILY_LOST,
                        IdentityState.UNKNOWN,
                        person_id=person_id,
                        emits=True,
                    )
                )
                continue
            # Seguro de vida (invariante de la Fase 22): una entrada rancia
            # desaparece aunque nadie llame on_active_tracks a tiempo. Un
            # CONFIRMED que revalida cada revalidate_after refresca
            # last_face_at y sobrevive.
            if now - st.last_face_at > stale_ttl:
                del self._states[tid]
                self._voter.reset(tid)
        return out
```

Traducción a `TrackGallery` (mismo esqueleto, sin transiciones que devolver):
guarda 1 = `now - e.last_seen > self._inherit_window`; guarda 2 = si
`len(self._entries) > self._max_entries`, borrar las más antiguas por `last_seen`
(LRU) hasta la cota. Nota de estilo: itera siempre sobre `list(self._entries)`, nunca
sobre el dict vivo (mismo motivo que aquí).

---

### 4. `backend/perception/face/identity.py` (MOD) — `on_reid_result()`

**Analog:** el propio fichero — `_claim_lost` y la rama `UNKNOWN` de `on_face_result`.

**`_claim_lost` completo** (`identity.py:161-179`). Es lo que `on_reid_result` reutiliza
tal cual; **no se toca**:

```python
    def _claim_lost(self, person_id: int, now: float) -> bool:
        """Un track nuevo reclama la identidad de un track perdido hace poco.

        ByteTrack nunca reutiliza track_ids: al recuperar a una persona le asigna
        un id nuevo. Sin esta busqueda POR person_id, cada reaparicion arrancaria
        en UNKNOWN y emitiria un segundo PERSON_RECOGNIZED (rompe FACE-09 y
        FACE-10 a la vez) — Pitfall 3 del RESEARCH.
        """
        for tid, st in list(self._states.items()):
            if (
                st.state is IdentityState.TEMPORARILY_LOST
                and st.person_id == person_id
                and st.lost_at is not None
                and now - st.lost_at <= self._lost_ttl
            ):
                del self._states[tid]
                self._voter.reset(tid)
                return True
        return False
```

**El invocador de `_claim_lost` — rama `UNKNOWN` de `on_face_result`**
(`identity.py:181-220`). Este es el bloque cuyo **estilo, orden de asignaciones y
`emits=False`** debe replicar `on_reid_result`:

```python
    def on_face_result(
        self, track_id: int, person_id: int | None, score: float, now: float
    ) -> IdentityTransition | None:
        st = self._states.setdefault(track_id, _TrackIdentity())
        st.last_face_at = now
        self._voter.vote(track_id, person_id, score)
        winner, conf = self._voter.verdict(track_id)
        prev = st.state

        if prev is IdentityState.UNKNOWN:
            if person_id is None:
                return None
            # Pitfall 3: un solo match coherente basta para heredar una
            # identidad perdida hace poco, sin re-votar (FACE-09/FACE-10).
            if self._claim_lost(person_id, now):
                st.state = IdentityState.CONFIRMED
                st.person_id = person_id
                st.confidence = score
                st.failed_revalidations = 0
                st.last_revalidation_at = now
                st.recognized_emitted = True
                return IdentityTransition(
                    track_id,
                    IdentityState.UNKNOWN,
                    IdentityState.CONFIRMED,
                    person_id=person_id,
                    confidence=score,
                    votes=self._voter.votes_for(track_id),
                    window=self._voter.window,
                    emits=False,
                )
            st.state = IdentityState.CANDIDATE
            ...
```

Diferencias que `on_reid_result` introduce (ya decididas en el RESEARCH — **copiar el
método del RESEARCH §Q1 tal cual, no rediseñarlo**):
1. **NO** llama a `self._voter.vote(...)` (línea 186) — la votación es facial.
2. Sale con `None` si el track ya no está en `UNKNOWN` o si `matched_votes(track_id) > 0`.
3. Fija además `st.last_face_at = now` (Pitfall 5 del RESEARCH).
4. `confidence = similarity`, `votes=0`.

**API de solo lectura que el worker usa** (`identity.py:150-159`) — `identity_of()` es la
que construye `active_identities` para la comprobación de conflicto, y ya devuelve
identidad **solo si CONFIRMED**, que es la semántica que hace falta:

```python
    def state_of(self, track_id: int) -> IdentityState:
        st = self._states.get(track_id)
        return st.state if st is not None else IdentityState.UNKNOWN

    def identity_of(self, track_id: int) -> tuple[int | None, float]:
        """(person_id, confianza) solo si el track esta CONFIRMED."""
        st = self._states.get(track_id)
        if st is None or st.state is not IdentityState.CONFIRMED:
            return None, 0.0
        return st.person_id, st.confidence
```

---

### 5. `backend/pipeline/recognition.py` (MOD) — cableado de engine + gallery

**Analog:** el propio fichero tras la Fase 24.

**`__init__` — cómo se inyectan las colaboraciones opcionales** (`recognition.py:47-77`).
`reid_engine`, `reid_gallery` y `reid_inherit` entran igual: keyword con default `None`/
`False` al final, guardados en atributos `_`-privados, y **contadores inicializados a 0
en el mismo bloque** que `_identified` / `_face_inferences`:

```python
    def __init__(
        self,
        sub: Subscription,
        registry: TrackRegistry,
        recognizer: PersonRecognizer,
        rate: AdaptiveRate,
        min_track_age: float = 0.5,
        prune_interval: float = 10.0,
        on_identified: Callable[[np.ndarray, int], None] | None = None,
        identity_fsm: IdentityStateMachine | None = None,
        event_engine: EventEngine | None = None,
    ) -> None:
        self._sub = sub
        self._registry = registry
        self._recognizer = recognizer
        self._rate = rate
        # Evita gastar inferencia en tracks que van a desaparecer enseguida
        self._min_track_age = min_track_age
        self._prune_interval = prune_interval
        # Callback opcional para la galeria de capturas (main.py lo cablea)
        self._on_identified = on_identified
        self._fsm = identity_fsm
        self._event_engine = event_engine

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_prune = 0.0
        self._identified = 0
        self._exceptions = 0
        self._face_inferences = 0
```

**`stats` — dónde van `reid_inferences`, `reid_matches`, `reid_inherited`,
`reid_conflicts`** (`recognition.py:101-108`). Sale por `manager.py:261` →
`/api/v2/cameras/{id}/health`, que es el canal de auditoría del criterio 4:

```python
    @property
    def stats(self) -> dict:
        return {
            "identified": self._identified,
            "exceptions": self._exceptions,
            "face_inferences": self._face_inferences,
            **self._rate.stats,
        }
```

**`_next_candidate` — plantilla de `_next_reid_candidate`** (`recognition.py:184-203`).
El RESEARCH es explícito: ReID necesita su **propia** selección, porque
`needs_recognition()` dice *no* justo en los casos que ReID cubre. Lo que se copia es la
forma (`snapshot().values()` + filtro `min_track_age` + `min(..., key=first_seen)`),
no el filtro:

```python
    def _next_candidate(self, now: float):
        """Track mas antiguo que merece una inferencia facial ahora, o None.

        Con FSM (Fase 24, FACE-11) el criterio es needs_recognition(): track nuevo,
        votacion en curso, identidad temporalmente perdida, confianza de identidad
        baja o revalidacion vencida. Sin FSM se conserva el criterio de la Fase 23
        (`person_id is None`), que reintentaba indefinidamente sobre los tracks que
        nunca llegan a identificarse.
        """
        tracks = [
            ts for ts in self._registry.snapshot().values()
            if (now - ts.first_seen) >= self._min_track_age
        ]
        if self._fsm is None:
            tracks = [ts for ts in tracks if ts.person_id is None]
        else:
            tracks = [ts for ts in tracks if self._fsm.needs_recognition(ts.track_id, now)]
        if not tracks:
            return None
        return min(tracks, key=lambda ts: ts.first_seen)
```

**`_sync_identity` — punto de mantenimiento donde entra `gallery.prune(now, frame_ids)`**
(`recognition.py:220-238`). Nota: ya recibe `now`, ya envuelve todo en `try/except` que
incrementa `_exceptions` y hace `return` sin matar el hilo, y ya usa `frame_ids()` (no
`active_ids()`, bug D-05 de la Fase 24 — la gallery debe usar la misma fuente):

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
        except Exception:
            self._exceptions += 1
            logger.exception("RecognitionWorker: mantenimiento de la FSM de identidad fallo")
            return
        for t in transitions:
            self._emit_identity(t)
```

**Bloque de inferencia dentro de `_loop` — medición de latencia y actualización de la
FSM** (`recognition.py:137-183`). La vía ReID se inserta después de este bloque, en el
mismo tick, con **una diferencia obligatoria**: `self._rate.observe(...)` **NO** se llama
para ReID (Pitfall 6), solo el histograma con `stage="reid"`:

```python
            t0 = time.monotonic()
            try:
                result = self._recognizer.process_crop_scored(crop, target.track_id)
            except Exception:
                self._exceptions += 1
                logger.exception(
                    "RecognitionWorker: fallo de reconocimiento (track %d)", target.track_id
                )
                continue
            self._face_inferences += 1
            face_latency = time.monotonic() - t0
            self._rate.observe(face_latency)               # <-- ReID NO hace esto
            _metrics.inference_latency_seconds.labels(stage="face").observe(face_latency)
            ...
            now2 = time.monotonic()
            transition = self._fsm.on_face_result(
                target.track_id, result.person_id, result.score, now2
            )
            self._registry.set_identity_state(target.track_id, self._fsm.state_of(target.track_id))
            pid, _conf = self._fsm.identity_of(target.track_id)
            if pid is not None:
                # El nombre solo es fiable si corresponde al pid que la FSM ha
                # fijado: el ganador de la votacion puede no ser el match de
                # ESTE frame.
                name = result.name if result.person_id == pid else None
                self._registry.set_identity(target.track_id, pid, name)
            if transition is not None:
                self._emit_identity(
                    transition,
                    person_name=result.name if result.person_id == transition.person_id else None,
                    bbox=target.bbox,
                    captured_at=frame.captured_at,
                    processed_at=now2,
                )
```

**Métricas ya existentes, sin cambios necesarios** (`backend/observability/metrics.py:76-82`):

```python
        reid_fps=Gauge(
            "reid_fps", "FPS real de ReID", ["camera"], registry=registry
        ),
        inference_latency_seconds=Histogram(
            "inference_latency_seconds", "Latencia de inferencia por etapa",
            ["stage"], buckets=INFERENCE_BUCKETS, registry=registry,
        ),
```

**API del registry que ReID consume (read-only, `tracking.py` NO se modifica)**
(`backend/pipeline/tracking.py:113-128`):

```python
    def frame_ids(self) -> set[int]:
        with self._lock:
            return set(self._frame_ids)

    def set_identity(self, track_id: int, person_id: int, name: str | None) -> None:
        ...
    def set_identity_state(self, track_id: int, state: IdentityState) -> None:
        ...
```

---

### 6. `backend/pipeline/manager.py` (MOD) — construir engine + gallery FUERA de la factoría

**Analog:** `manager.py:122-149` — el bloque exacto de la Fase 24, con el comentario que
explica **por qué** vive fuera de `_make_recognition`:

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

            def _make_recognition() -> RecognitionWorker:
                self.recognition = RecognitionWorker(
                    self.broker.subscribe("recognition", replace=True),
                    self.registry, recognizer,
                    AdaptiveRate(target_fps=recognition_fps,
                                 min_fps=recognition_fps, max_fps=recognition_fps),
                    identity_fsm=self.identity_fsm,
                    event_engine=event_engine,
                    on_identified=on_identified,
                )
                return self.recognition

            self.supervisor.register("recognition", _make_recognition)
```

`self.reid_engine` y `self.reid_gallery` se construyen en ese mismo `if`, junto a
`self.identity_fsm`, y se pasan como kwargs dentro de la factoría — un reinicio del
worker no debe vaciar la galería (misma razón, mismo comentario).

**Declaración previa de los atributos** (`manager.py:78-82`) — hay que añadir dos líneas
aquí:

```python
        self.detection: DetectionWorker | None = None
        self.streaming: StreamingWorker | None = None
        self.recording: RecordingWorker | None = None
        self.recognition: RecognitionWorker | None = None
        self.identity_fsm: IdentityStateMachine | None = None
```

**Firma de `CameraPipeline.__init__` — dónde van los kwargs `reid_*`**
(`manager.py:40-62`), al final, después del bloque `identity_*`:

```python
        identity_vote_window: int = 8,
        identity_min_votes: int = 3,
        identity_min_ratio: float = 0.6,
        identity_lost_ttl: float = 30.0,
        identity_revalidate_after: float = 120.0,
        identity_low_confidence: float = 0.55,
    ) -> None:
```

**`stats()` ya publica lo del worker sin cambios** (`manager.py:250-262`): los contadores
`reid_*` que se añadan a `RecognitionWorker.stats` salen solos por
`out["recognition"] = self.recognition.stats`.

---

### 7. `backend/main.py` (MOD) — pasar `settings.reid_*`

**Analog:** `main.py:417-437` — el bloque de kwargs de `camera_manager.add()`. Los
`reid_*` van justo después de `identity_low_confidence`:

```python
        recognition_fps=settings.recognition_target_fps,
        identity_vote_window=settings.identity_vote_window,
        identity_min_votes=settings.identity_min_votes,
        identity_min_ratio=settings.identity_min_ratio,
        identity_lost_ttl=settings.identity_lost_ttl_secs,
        identity_revalidate_after=settings.identity_revalidate_after_secs,
        identity_low_confidence=settings.face_confirm_threshold,
    )
```

Detalle: el nombre del kwarg **no siempre coincide** con el del setting
(`identity_lost_ttl` ← `identity_lost_ttl_secs`, `identity_low_confidence` ←
`face_confirm_threshold`). El plan debe fijar el mapeo explícito para los 7 `reid_*`.

---

### 8. `backend/config.py` (MOD) — bloque de parámetros + validadores

**Analog A — bloque de parámetros con comentario de cabecera** (`config.py:128-147`).
El patrón es: separador `# --- Nombre (Fase N — IDs de requisito) ---`, seguido de un
párrafo que explica **de dónde salen los defaults** y cualquier interacción no obvia
entre parámetros:

```python
    # --- Reconocimiento facial ArcFace (Fase 23 — FACE-01..03) ---
    # Defaults de SPEC_v2.md §5.4 — no son los mismos umbrales que usaba dlib
    # (distancia euclídea vs. similitud coseno, no comparables directamente).
    face_min_size_px: int = 60
    face_max_blur: float = 100.0
    face_max_yaw_deg: float = 40.0
    face_match_threshold: float = 0.45
    face_confirm_threshold: float = 0.55

    # --- Identidad temporal (Fase 24 — FACE-07..FACE-11) ---
    # Defaults de SPEC_v2.md §5.5. `face_confirm_threshold` (arriba, Fase 23) se
    # reutiliza como umbral de "confianza de identidad baja": por debajo de el, un
    # track CONFIRMED vuelve a pasar por reconocimiento sin esperar a la
    # revalidacion periodica (FACE-11). Es la confianza agregada del
    # TemporalVoter, no la confianza de deteccion de YOLO.
    identity_vote_window: int = 8
    identity_min_votes: int = 3
    identity_min_ratio: float = 0.6
    identity_lost_ttl_secs: float = 30.0
    identity_revalidate_after_secs: float = 120.0
```

**Analog B — `@model_validator(mode="after")` con mensajes en español y explicativos**
(`config.py:183-199`). Los validadores de rango de `reid_*` van en el mismo estilo
(mensaje que dice qué pasaría si el valor se aceptara, no solo "valor inválido"):

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
        if not 0.0 < self.identity_min_ratio <= 1.0:
            raise ValueError("identity_min_ratio debe estar en (0, 1]")
        if self.identity_lost_ttl_secs <= 0:
            raise ValueError("identity_lost_ttl_secs debe ser > 0")
        if self.identity_revalidate_after_secs <= 0:
            raise ValueError("identity_revalidate_after_secs debe ser > 0")
        return self
```

**Analog C — validador de ruta de modelo, reutilizable casi literalmente para
`reid_model_path`** (`config.py:9-13` + `39-51`). `_MODEL_PATH_ALLOWED_SUFFIXES` **ya
incluye `.onnx`**; la contención en `_PROJECT_ROOT` es SEC-16:

```python
_MODEL_PATH_ALLOWED_SUFFIXES = {".pt", ".onnx"}

# Raíz del proyecto (directorio que contiene backend/). Todo lo que deba ser
# estable frente al cwd del proceso se ancla aquí, no al directorio de trabajo.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

---

### 9. `scripts/fetch_models.py` — analog **parcial**

**Analog:** `scripts/migrate_embeddings.py` (124 líneas). Cubre el patrón de script CLI
del repo, **no** la parte de descarga HTTPS + sha256 (no hay precedente: la Fase 23 usó
la autodescarga de `insightface`).

**Lo que sí se copia — docstring con `Usage:` + idempotencia declarada + `argparse` y
`sys.exit(código)`** (`migrate_embeddings.py:1-27` y `119-123`):

```python
"""One-time migration: legacy pickle embedding blobs -> raw numpy float64 bytes.

Run once before removing the pickle fallback from backend/recognizer.py.
Idempotent: a second run reports 0 converted and exits 0. Makes a timestamped
backup of the database before writing anything. Rows whose blob cannot be
converted are left untouched and reported; the script then exits non-zero.

Usage:
    .venv/Scripts/python.exe scripts/migrate_embeddings.py [data/persons.db]
"""

from __future__ import annotations

import argparse
...
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", nargs="?", default="data/persons.db")
    args = parser.parse_args()
    sys.exit(migrate(args.db_path))
```

**Función principal que devuelve el exit code, no llama a `sys.exit` por dentro**
(`migrate_embeddings.py:53-58`) — así es testeable:

```python
def migrate(db_path: str) -> int:
    """Migrate every legacy pickle blob in *db_path* to raw numpy bytes.

    Returns the process exit code: 0 on full success (including "nothing to do"),
    1 if any blob could not be converted.
    """
```

**Reporte legible al final** (`migrate_embeddings.py:104-116`): `_report()` devuelve un
string alineado con totales. `fetch_models.py` debe imprimir algo equivalente (destino,
bytes, sha256 verificado, batch reescrito sí/no).

**Lo que NO tiene analog en el repo:** descarga HTTPS, verificación sha256, espejo de
fallback, reescritura del grafo ONNX. El código de referencia para eso está en el
RESEARCH §"Code Examples" (`ModelSpec` + `_to_dynamic_batch`) — no hay que buscar más en
el repo.

**Otros ficheros de configuración:**
- `requirements.txt` — añadir `onnx>=1.16`. El fichero usa `>=` sin pins; `onnxruntime>=1.19` es la última línea del bloque de la Fase 23.
- `.gitignore` — añadir `models/`. El estilo del fichero es bloque con comentario, p. ej.:
  ```
  # Clip thumbnails (Fase 20) — generated at runtime from the trigger frame
  data/thumbnails/
  ```

---

## Patrones de Test

### 10. `tests/test_reid_engine.py`

**Analog:** `tests/test_face_engine.py` (fichero completo, 75 líneas).

**Docstring que justifica la fixture real y por qué no se guarda en el repo**
(`test_face_engine.py:1-18`):

```python
"""Tests for backend.perception.face.engine.FaceEngine — real inference on buffalo_s.

Uses skimage.data.astronaut() (Eileen Collins, NASA Great Images, public
domain, bundled with scikit-image — a transitive dependency of insightface
already installed for exactly this purpose) as the one real face fixture,
fetched at test time rather than stored as a repo asset. No synthetic/AI
-generated face is used to validate a detector trained on real faces.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from backend.perception.face.engine import FaceCandidate, FaceEngine

pytestmark = pytest.mark.filterwarnings("ignore:.*estimate.*deprecated.*:FutureWarning")
```

**Fixtures `scope="module"` — el motor se carga una sola vez** (`test_face_engine.py:21-29`):

```python
@pytest.fixture(scope="module")
def engine() -> FaceEngine:
    return FaceEngine()


@pytest.fixture(scope="module")
def real_face_bgr() -> np.ndarray:
    import skimage.data as data
    return cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
```

**Assert de 512D + norma L2** (`test_face_engine.py:55-61`) — el test del criterio 1 del
RESEARCH parte de aquí:

```python
def TEST_embed_returns_512d_l2_normalized(engine, real_face_bgr):
    """embed() on a detected face returns a 512-d vector with unit L2 norm."""
    cand = engine.detect(real_face_bgr)[0]
    emb = engine.embed(real_face_bgr, cand)
    assert emb.shape == (512,)
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-3
```

**Degradación graciosa vía `monkeypatch` del símbolo del módulo**
(`test_face_engine.py:64-75`):

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
    assert broken.embed(np.zeros((10, 10, 3), dtype=np.uint8), cand=None) is None
```

Adaptación para ReID (según RESEARCH §Q5): la variante equivalente es apuntar a una ruta
de modelo inexistente (`ReIDEngine("no/such.onnx")`), y **la fixture del motor debe hacer
`pytest.skip` si `models/reid/*.onnx` no existe** — `test_face_engine.py` no lo necesita
porque `insightface` autodescarga, ReID no.

---

### 11. `tests/test_recognition_worker.py` (MOD)

**Analog:** el propio fichero.

**Helpers compartidos que ya existen y hay que reutilizar** (`test_recognition_worker.py:24-49`):

```python
def _make_frame(seq: int) -> Frame:
    return Frame(
        camera_id="cam1", seq=seq, captured_at=time.monotonic(),
        wall_clock=datetime.now(), image=np.zeros((360, 640, 3), dtype=np.uint8),
    )


class _FakeTracked:
    def __init__(self, ids: list[int]):
        self.tracker_id = np.array(ids)
        n = len(ids)
        self.xyxy = np.array([[10, 10, 80, 200]] * n, dtype=float)
        self.confidence = np.full(n, 0.9)


def _publish_for(broker: FrameBroker, seconds: float, interval: float = 0.02) -> None:
    deadline = time.time() + seconds
    seq = 0
    while time.time() < deadline:
        broker.publish(_make_frame(seq))
        seq += 1
        time.sleep(interval)


def _face(person_id=None, name=None, is_new=False, score=0.0, ambiguous=False) -> FaceResult:
    return FaceResult(person_id, name, is_new, score, ambiguous)
```

**Mock de motor + contador de llamadas** (`test_recognition_worker.py:85-87`) — el patrón
literal para mockear `ReIDEngine`:

```python
    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop_scored.return_value = _face()  # nunca identifica
```

Para ReID: `engine = MagicMock(); engine.available = True;
engine.embed.return_value = <vector 512D sintético>`, y el conteo con
`engine.embed.call_count`.

**Presupuesto de inferencias — plantilla exacta del criterio 5**
(`test_recognition_worker.py:318-358`). La estructura clave: función interna `_run()` que
monta worker + registry, publica frames durante N segundos y **devuelve el
`call_count`**; luego se comparan dos configuraciones. El comentario de cabecera documenta
el escalado del reloj:

```python
# ─── Criterio 6: presupuesto de inferencias sobre un track no confirmado ─────
# Escenario medido (24-CONTEXT.md, decision del usuario D-01): UNA persona
# estatica cuyo reconocimiento NUNCA tiene exito ...
#
# Escalado del reloj: los 120 s reales de produccion se comprimen a
# revalidate_after=10s en el test, manteniendo la proporcion ventana/backoff.
# ───────────────────────────────────────────────────────────────────────────
def TEST_inference_budget_drops_on_unconfirmed_track(broker):
    def _run(fsm) -> int:
        registry = TrackRegistry()
        registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)
        # El track sigue "en el frame" durante todo el test: sin esto,
        # frame_ids() vacio haria que on_active_tracks() lo diera por perdido
        # y reiniciara el voter en cada ciclo, invalidando la medicion.
        registry.set_frame_ids({1})
        recognizer = MagicMock()
        recognizer.available = True
        recognizer.process_crop_scored.return_value = _face()   # nunca identifica
        sub = broker.subscribe("recognition")
        rate = AdaptiveRate(target_fps=20.0, min_fps=20.0, max_fps=20.0)
        worker = RecognitionWorker(sub, registry, recognizer, rate,
                                   min_track_age=0.0, identity_fsm=fsm)
        worker.start()
        _publish_for(broker, seconds=1.0)
        worker.stop()
        return recognizer.process_crop_scored.call_count

    baseline = _run(None)                                   # comportamiento Fase 23
    fsm = IdentityStateMachine(TemporalVoter(window=2, min_votes=2),
                               lost_ttl=30.0, revalidate_after=10.0)
    with_fsm = _run(fsm)

    assert baseline >= 8, f"baseline degenerado ({baseline}): el test no mide nada"
    assert with_fsm <= baseline * 0.30, (
        f"reduccion insuficiente: {baseline} -> {with_fsm} "
        f"({100 * (1 - with_fsm / baseline):.0f}%, se exige >= 70%)"
    )
```

Para el criterio 5 de ReID, la variante es más directa: `reid_interval_secs` pequeño y
conocido (p. ej. 0.5 s), publicar 1 s de frames a 20 FPS y assertar
`engine.embed.call_count <= ceil(duración / intervalo) + 1`.

**Test end-to-end de identidad conservada (criterio 3)** — plantilla en
`test_recognition_worker.py:230-292` (`TEST_track_recovery_via_real_path_emits_person_recognized_once`).
Elementos que hay que reutilizar tal cual:
- El mock que "solo reconoce al track activo" via `match_track = {"id": 1}` + `side_effect` (líneas 234-243) — para ReID, el equivalente es un `side_effect` que devuelve el mismo vector para la misma persona.
- La secuencia `set_frame_ids({1})` → `set_frame_ids(set())` → `registry.prune(now, ttl=0.01)` → `update_from_detections(_FakeTracked([99]))` + `set_frame_ids({99})` (líneas 254-275), que es exactamente el escenario "se gira / desaparece 10 s y vuelve con track_id nuevo".
- `make_engine()` + `wait_until()` + `await asyncio.sleep(0.1)` antes de contar eventos, con su comentario (líneas 283-292):

```python
    worker.stop()
    # wait_until puede salir sin haber cedido el control al loop ni una sola
    # vez si el predicado ya era cierto en la primera comprobacion ...
    await asyncio.sleep(0.1)
    recognized = [e for e in received if e.type is EventType.PERSON_RECOGNIZED]
    assert len(recognized) == 1, (
        f"se esperaba 1 PERSON_RECOGNIZED, hubo {len(recognized)} -- "
        "el track nuevo confirmo como visita nueva en vez de heredar la identidad"
    )
```

**Test de que engine/gallery sobreviven al reinicio del worker** — copia directa de
`TEST_fsm_survives_worker_restart` (`test_recognition_worker.py:296-316`), incluida la
técnica de sacar la factoría del supervisor:

```python
def TEST_fsm_survives_worker_restart():
    """La FSM se construye FUERA de _make_recognition (manager.py): un
    reinicio del worker (el supervisor la re-ejecuta) no debe perder la
    identidad ya confirmada, igual que _make_streaming rescata `clients`."""
    from backend.pipeline.manager import CameraPipeline

    recognizer = MagicMock()
    recognizer.available = True
    pipeline = CameraPipeline("cam1", "rtsp://fake", recognizer=recognizer)

    factory = pipeline.supervisor._entries["recognition"].factory
    worker1 = factory()
    fsm = pipeline.identity_fsm
    assert fsm is not None
    assert worker1._fsm is fsm

    worker2 = factory()
    assert worker2 is not worker1
    assert pipeline.identity_fsm is fsm   # misma instancia, no una nueva
    assert worker2._fsm is fsm
```

**Test de `_next_reid_candidate` sin arrancar el hilo** — patrón de
`TEST_low_identity_confidence_retriggers_recognition` (`test_recognition_worker.py:362-390`):
se construye el worker con `MagicMock()` como `Subscription` y se llama al método privado
directamente, sin `start()`.

---

### 12. `tests/test_track_gallery.py`

**Analog:** `tests/test_identity_state_machine.py` (dominio puro, reloj sintético).

**Docstring + helper de construcción con defaults sobreescribibles**
(`test_identity_state_machine.py:1-35`):

```python
"""Tests para IdentityStateMachine (Fase 24, FACE-08..FACE-11).

La FSM es pura: no hay hilos, no hay reloj real, no hace falta mockear nada.
El reloj se inyecta como float sintetico (mismo patron que
test_memory_bounds.py: `now = float(i)`), asi que los 200 frames de
TEST_single_recognition_over_200_frames tardan microsegundos en vez de 100
segundos reales.
"""

from __future__ import annotations

from backend.perception.face.identity import (
    IdentityState,
    IdentityStateMachine,
    TemporalVoter,
)


def _fsm(
    window: int = 8,
    min_votes: int = 3,
    min_ratio: float = 0.6,
    lost_ttl: float = 30.0,
    revalidate_after: float = 120.0,
    low_confidence: float = 0.55,
) -> IdentityStateMachine:
    return IdentityStateMachine(
        TemporalVoter(window=window, min_votes=min_votes, min_ratio=min_ratio),
        lost_ttl=lost_ttl,
        revalidate_after=revalidate_after,
        low_confidence=low_confidence,
    )
```

`test_track_gallery.py` necesita el equivalente `_gallery(inherit_window=15.0,
similarity_threshold=0.7, interval=2.0, max_entries=256)` **más** un helper de vectores
sintéticos (RESEARCH Pitfall 3: nunca `np.random` como crop, siempre vectores con coseno
controlado, p. ej. `normalize(np.eye(512)[i] + eps * ruido)`).

**Separadores de sección y `now=` explícito en cada llamada**
(`test_identity_state_machine.py:306-327`) — el estilo para los tests de herencia/ventana:

```python
def TEST_track_recovery_keeps_same_identity():
    """Criterio 4: perder y recuperar un track (con id NUEVO, como ByteTrack)
    conserva la identidad sin duplicarla."""
    fsm = _fsm()
    fsm.on_face_result(1, 7, 0.7, now=0.0)
    fsm.on_face_result(1, 7, 0.7, now=1.0)
    confirmations = []

    def _record(t):
        if t is not None and t.to_state is IdentityState.CONFIRMED and t.emits:
            confirmations.append(t)

    _record(fsm.on_face_result(1, 7, 0.7, now=2.0))
    fsm.on_track_lost(1, now=10.0)

    _record(fsm.on_face_result(2, 7, 0.7, now=15.0))

    assert fsm.identity_of(2) == (7, fsm.identity_of(2)[1])
    assert fsm.state_of(2) is IdentityState.CONFIRMED
    assert len(confirmations) == 1
```

El test "no hereda pasada la ventana" tiene su plantilla en
`TEST_recovery_after_lost_ttl_is_a_new_visit` (líneas 329-350): misma secuencia, reloj
avanzado más allá del TTL, aserción opuesta.

---

### 13. `tests/test_memory_bounds.py` (MOD)

**Analog:** `TEST_temporal_voter_bounded` (`test_memory_bounds.py:91-100`) — el RESEARCH
lo cita como plantilla exacta:

```python
# ─── TemporalVoter no acumula votos de tracks muertos ────────────────────────
# ByteTrack asigna ids monotonamente crecientes y nunca los reutiliza: sin
# prune(active_ids), _votes crece sin cota en un proceso 24/7.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_temporal_voter_bounded():
    voter = TemporalVoter(window=8)
    for tid in range(10_000):
        voter.vote(tid, 1, 0.9)
        voter.prune(set(range(max(0, tid - 5), tid + 1)))
    assert len(voter._votes) <= 6
```

Y la variante con **cota holgada y comentario que explica por qué el número exacto no
importa** — útil si la cota de la gallery depende de la interacción TTL/LRU
(`test_memory_bounds.py:103-120`):

```python
# ─── IdentityStateMachine expira sus estados por tiempo, no por active_ids ───
# ... el límite de 500 deja margen amplio (orden de magnitud, no el valor
# exacto) frente a otras combinaciones de parámetros/identidades concurrentes.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_state_machine_bounded():
    fsm = IdentityStateMachine(TemporalVoter(window=8), lost_ttl=30.0,
                                revalidate_after=120.0)
    for tid in range(10_000):
        now = float(tid)
        fsm.on_face_result(tid, 1, 0.9, now)
        fsm.on_active_tracks({tid}, now)
        fsm.on_tick(now)
    assert len(fsm._states) <= 500
```

El import nuevo va en el bloque de `test_memory_bounds.py:23-30` (imports ordenados
alfabéticamente por módulo backend).

---

### 14. `tests/test_config.py` (MOD)

**Analog:** `test_config.py:182-217`. Tres tests por bloque de parámetros: defaults,
y un test por familia de valor inválido, cada uno con comentario de cabecera que explica
la consecuencia de aceptar el valor malo:

```python
# Los 5 parámetros de la fase deben tener exactamente los defaults documentados
# en el SPEC para que TemporalVoter/IdentityStateMachine se comporten como se
# especificó sin necesidad de configuración explícita.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_defaults_match_spec():
    """Settings() expone los 5 parámetros de identidad con los defaults del SPEC."""
    s = Settings()
    assert s.identity_vote_window == 8
    ...

# ─── Ratio fuera de (0, 1] es rechazado ────────────────────────────────────────
# identity_min_ratio es una proporción sobre el total de votos: 0.0 permitiría
# que cualquier voto (incluso ninguno) ganase, y valores > 1.0 harían que
# ninguna identidad pudiera confirmarse nunca.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_identity_ratio_out_of_range_rejected():
    """identity_min_ratio fuera de (0, 1] lanza ValueError."""
    with pytest.raises((ValidationError, ValueError)):
        Settings(identity_min_ratio=0.0)
    with pytest.raises((ValidationError, ValueError)):
        Settings(identity_min_ratio=1.5)
```

---

## Shared Patterns

### Naming de tests
**Source:** `pytest.ini`
```
[pytest]
python_functions = TEST_*
asyncio_mode = auto
```
**Apply to:** todos los tests nuevos. Deben llamarse `TEST_*` o pytest no los recoge por
nombre de función (los `test_*` heredados solo se recogen por el prefijo del fichero).

### Reloj inyectado
**Source:** `backend/perception/face/identity.py:1-12` + `backend/pipeline/rate.py`
**Apply to:** `TrackGallery` (todos los métodos con `now: float`), `on_reid_result`.
Ningún módulo bajo `backend/perception/` importa `time`. El único que llama a
`time.monotonic()` es el worker (`recognition.py:123`, `:137`, `:160`).

### Comentario que explica el "por qué", con la medición o el bug detrás
**Source:** `engine.py:52-56`, `recognition.py:63`, `identity.py:104-105`,
`identity.py:450-453`, `manager.py:123-125`, `recognition.py:222-227`
**Apply to:** todo código nuevo. Es la convención más consistente del repo: cada decisión
no obvia lleva su justificación con la cifra medida o la referencia al bug/requisito
(`D-05`, `FACE-11`, `Pitfall 3`, `invariante de la Fase 22`). Para la Fase 25, las cifras
ya están en el RESEARCH (84,5 ms vs 4,97 ms; norma cruda ~52; 2 KB/entrada).

### Degradación graciosa (nunca lanzar hacia el hilo del worker)
**Source:** `engine.py:60-77` (`available` + `try/except` + `logger.exception`),
`recognition.py:138-145` (`try/except` que incrementa `_exceptions` y hace `continue`),
`recognition.py:212-218` (`_notify_identified`)
**Apply to:** `ReIDEngine.__init__`/`embed()` y la vía ReID dentro de `_loop`. Sin
`models/reid/`, el sistema debe arrancar exactamente igual que hoy.

### Estado compartido sin lock, un solo hilo
**Source:** `identity.py:129-130` ("Un solo hilo (RecognitionWorker._loop), por eso no hay
lock"), `identity.py:105`, `recognition.py:221`
**Apply to:** `TrackGallery`. El único punto con lock es `TrackRegistry`
(`tracking.py:110-128`), porque ahí sí escriben varios hilos.

---

## No Analog Found

| Fichero | Rol | Flujo | Motivo |
|---|---|---|---|
| `scripts/fetch_models.py` (parcial) | utility CLI | file-I/O + red | El repo nunca ha descargado un artefacto de un tercero ni verificado un sha256: la Fase 23 delegó en la autodescarga de `insightface`. `scripts/migrate_embeddings.py` da el esqueleto del script (docstring con `Usage:`, idempotencia, `argparse`, exit code, reporte), pero la descarga + hash + reescritura ONNX salen del RESEARCH § "Code Examples", no del repo. |

Todo lo demás tiene analog exacto dentro del propio proyecto.

---

## Metadata

**Analog search scope:** `backend/perception/`, `backend/pipeline/`, `backend/observability/`,
`backend/config.py`, `backend/main.py`, `scripts/`, `tests/`, `pytest.ini`, `.gitignore`,
`requirements.txt`
**Files scanned:** 15 leídos completos o por rangos dirigidos
**Pattern extraction date:** 2026-08-13
