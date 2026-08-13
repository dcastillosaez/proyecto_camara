# Phase 24: Identidad temporal — votación y máquina de estados - Pattern Map

**Mapped:** 2026-08-12
**Files analyzed:** 12 (1 nuevo + 6 modificados + 5 de test)
**Analogs found:** 12 / 12
**Commit de referencia:** `7262644` (las líneas citadas son de ese árbol)

> El RESEARCH ya identificó los ficheros reales y las 5 discrepancias SPEC↔código.
> Este documento no las repite: da el **código concreto que hay que copiar** para
> cada uno de esos ficheros.

## File Classification

| Fichero nuevo/modificado | Rol | Flujo de datos | Analog más cercano | Calidad |
|---|---|---|---|---|
| `backend/perception/face/identity.py` (CREAR) | dominio puro (lógica sin I/O) | transform + event-driven | `backend/pipeline/rate.py` (`AdaptiveRate`, reloj inyectado) + `backend/pipeline/tracking.py` (estado por track + expiración) + `backend/perception/face/quality.py` (dataclass + clase parametrizada) | exact (compuesto: 3 analogs, uno por eje) |
| `backend/pipeline/recognition.py` | worker (hilo) | event-driven / pull del broker | `backend/pipeline/detection.py` (`DetectionWorker`: mismo esqueleto, ya emite eventos) | exact |
| `backend/pipeline/manager.py` | wiring / factory | config | `manager.py:77-89` (`_make_detection`, ya recibe `event_engine`) | exact (mismo fichero) |
| `backend/events/engine.py` | service (traductor a `Event`) | pub-sub thread→async | `events/engine.py:143-153` (`camera_offline`: emisión solo en transición) | exact (mismo fichero) |
| `backend/pipeline/tracking.py` | model (estado compartido) | shared-state | `tracking.py:91-96` (`set_identity`) | exact (mismo fichero) |
| `backend/recognizer.py` | service (orquestación) | request-response | `recognizer.py:200-252` (bloque de votación a retirar) | exact (mismo fichero) |
| `backend/config.py` | config | — | `config.py:128-135` (bloque Fase 23) | exact |
| `backend/observability/metrics.py` (opcional) | config/catálogo | métricas | `metrics.py:95-97` + `recognition.py:132` | exact |
| `tests/test_temporal_voting.py` (NUEVO) | test unitario puro | — | `tests/test_recognizer_orchestration.py` (estilo, `TEST_*`, comentarios `─── ───`) | role-match |
| `tests/test_identity_state_machine.py` (NUEVO) | test unitario, reloj simulado | — | `tests/test_memory_bounds.py:46-53` (bucle con `now` sintético) | role-match |
| `tests/test_memory_bounds.py` (extender) | test de cota | — | `test_memory_bounds.py:76-89` (`TEST_recognizer_cache_bounded`) | exact |
| `tests/test_event_engine.py` (extender) | test de integración async | — | `test_event_engine.py:15-48` (`wait_until` + `make_engine`) | exact |
| `tests/test_recognition_worker.py` (extender) | test de worker con hilo real | — | `test_recognition_worker.py:18-65` (fixture `broker`, `MagicMock` recognizer) | exact |

---

## Pattern Assignments

### `backend/perception/face/identity.py` (CREAR — dominio puro, transform + event-driven)

Tres analogs, uno por cada eje del fichero.

#### Eje 1 — Estado por track + política de expiración

**Analog:** `backend/pipeline/tracking.py` (`TrackState` + `TrackRegistry`).

Dataclass de estado con estructura acotada por `maxlen` **declarada en el propio campo**
(`tracking.py:16-29`) — es el patrón exacto para el estado de `TemporalVoter`:

```python
@dataclass
class TrackState:
    """Estado de un track. Los lectores no deben mutarlo (snapshot es copia superficial)."""

    track_id: int
    first_seen: float
    last_seen: float
    bbox: tuple[int, int, int, int]
    confidence: float
    centroid_history: deque = field(default_factory=lambda: deque(maxlen=150))
    zones: set[str] = field(default_factory=set)
    zone_entry_times: dict[str, float] = field(default_factory=dict)
    person_id: int | None = None
    person_name: str | None = None
```

Expiración por TTL con `now` **como parámetro** y devolución de los ids expirados
(`tracking.py:98-106`) — es la firma que debe tener el prune de `IdentityStateMachine`
(que expira por `lost_ttl`, no por `active_ids` — ver Pitfall 2 del RESEARCH):

```python
    def prune(self, now: float, ttl: float = 30.0) -> list[int]:
        """Elimina tracks sin actualizar desde hace mas de ttl. Devuelve los ids expirados."""
        with self._lock:
            expired = [
                tid for tid, ts in self._tracks.items() if now - ts.last_seen > ttl
            ]
            for tid in expired:
                del self._tracks[tid]
            return expired
```

Expiración por conjunto de activos (`recognizer.py:340-351`) — es el patrón para
`TemporalVoter.prune(active_ids)`, incluyendo el docstring que justifica **por qué**
existe (ByteTrack no reutiliza ids):

```python
    def prune(self, active_tracker_ids: set[int]) -> None:
        """
        Drop per-track state for tracker_ids no longer active (MEJORAS.md
        punto 12). ByteTrack ids grow monotonically, so without pruning
        ``_cache``, ``_last_attempt``, ``_pending`` and ``_votes`` leak
        slowly on a 24/7 process.
        """
        with self._lock:
            for d in (self._cache, self._last_attempt, self._pending, self._votes):
                for tid in list(d):
                    if tid not in active_tracker_ids:
                        del d[tid]
```

> Nota para el planner: `identity.py` vive en un solo hilo (`RecognitionWorker`), así que
> **no** debe copiar el `with self._lock:`. Copia la forma del bucle, no el lock.

#### Eje 2 — Deque acotado + Counter para el voto

**Analog:** `backend/recognizer.py:200-220` (código real, que esta fase **retira**).

```python
        with self._lock:
            cached = self._cache.get(tracker_id)
            pid, name, ambiguous = self._best_match(enc)
            if pid is not None:
                # Majority vote over the last VOTE_WINDOW decisive matches:
                # the winner — not necessarily this sample — is the identity.
                votes = self._votes.setdefault(
                    tracker_id, deque(maxlen=self.VOTE_WINDOW)
                )
                votes.append(pid)
                winner = Counter(votes).most_common(1)[0][0]
```

`TemporalVoter.vote()` copia `setdefault(track_id, deque(maxlen=window))` + `append`;
`verdict()` copia `Counter(...).most_common(1)`, pero añade el filtro que el original no
tiene: `min_votes` y `min_ratio` (`ganador / len(votos) >= min_ratio`), devolviendo
`(None, 0.0)` si no se cumplen.

#### Eje 3 — Reloj inyectado (determinismo en tests)

**Analog:** `backend/pipeline/rate.py:10-24, 55-62` (`AdaptiveRate`). El docstring dice
literalmente por qué:

```python
class AdaptiveRate:
    """
    ...
    should_process(now) decide por tiempo transcurrido desde el ultimo
    procesado — determinista y facil de testear con reloj simulado.
    ...
    """

    def should_process(self, now: float) -> bool:
        if self._last_ts is None:
            self._last_ts = now
            return True
        if now - self._last_ts >= 1.0 / self.effective_fps:
            self._last_ts = now
            return True
        return False
```

`rate.py` **no importa `time`**. `identity.py` tampoco debe hacerlo: `on_face_result`,
`on_track_lost` y `on_tick` reciben `now: float` monotónico.

#### Eje 4 — Cabecera de módulo y dataclass del resultado

**Analog:** `backend/perception/face/quality.py:1-48`. Docstring que declara el contrato y
qué queda fuera, dataclass plano con comentario del dominio de valores, clase con umbrales
por constructor (nunca leídos de `config` dentro del módulo):

```python
"""FaceQualityAssessor — size/blur/pose gating with an explicit rejection reason.

SPEC_v2.md §5.4 fixes the contract (FaceQuality fields, default thresholds)
but not the pose-estimation method. ...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FaceQuality:
    size_px: int
    blur: float
    ...
    passed: bool
    reason: str | None  # "too_small" | "blurry" | "extreme_pose" | None


class FaceQualityAssessor:
    def __init__(
        self,
        min_size_px: int = 60,
        max_blur: float = 100.0,
        max_yaw_deg: float = 40.0,
    ) -> None:
        self._min_size_px = min_size_px
        self._max_blur = max_blur
        self._max_yaw_deg = max_yaw_deg
```

Para `IdentityState`, el enum del repo (`events/types.py:13-17`) usa `str, Enum`:

```python
class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
```

---

### `backend/pipeline/recognition.py` (worker, event-driven)

**Analog:** `backend/pipeline/detection.py` (`DetectionWorker`) — mismo esqueleto de worker,
y es el **único** que hoy emite eventos desde un hilo.

**Camino real hilo → EventBus** (`detection.py:187-195`). Este es el patrón completo que
`RecognitionWorker` debe replicar: guarda de `None`, `datetime.datetime.now()` para el `ts`
de pared, y llamada síncrona al `EventEngine` (nunca al bus):

```python
    def _emit_track_lifecycle(self, tracked: Any, captured_at: float, processed_at: float) -> None:
        if self._event_engine is None:
            return
        wall_now = datetime.datetime.now()
        ids = tracked.tracker_id
        active_ids = {int(tid) for tid in ids} if ids is not None else set()
        self._event_engine.process_tracks(active_ids, wall_now, captured_at, processed_at)
        confidences = list(tracked.confidence) if tracked.confidence is not None else []
        self._event_engine.accumulate_detections(wall_now, active_ids, confidences)
```

**Constructor con `event_engine` opcional** (`detection.py:48-70`) — copiar los tres
elementos: parámetro con default `None`, import bajo `TYPE_CHECKING`, atributo privado:

```python
if TYPE_CHECKING:
    from backend.events.engine import EventEngine

class DetectionWorker:
    def __init__(
        self,
        sub: Subscription,
        ...
        event_engine: EventEngine | None = None,
        ...
    ) -> None:
        ...
        self._event_engine = event_engine
```

**Bucle actual a modificar** (`recognition.py:99-142`) — el gate de FACE-11 se inserta
entre `_maybe_prune` y `_next_candidate`; el `on_tick` de la FSM va junto a `_maybe_prune`:

```python
    def _loop(self) -> None:
        available = getattr(self._recognizer, "available", False)
        while self._running:
            frame = self._sub.get(timeout=1.0)
            if frame is None:
                continue
            if not available:
                continue

            now = time.monotonic()
            self._maybe_prune(now)
            if not self._rate.should_process(now):
                continue

            target = self._next_candidate(now)
            if target is None:
                continue

            crop = self._crop_for(frame.image, target.bbox)
            if crop is None:
                continue

            t0 = time.monotonic()
            try:
                pid, name, _ = self._recognizer.process_crop(crop, target.track_id)
            except Exception:
                self._exceptions += 1
                logger.exception(
                    "RecognitionWorker: fallo de reconocimiento (track %d)", target.track_id
                )
                continue
            face_latency = time.monotonic() - t0
            self._rate.observe(face_latency)
            _metrics.inference_latency_seconds.labels(stage="face").observe(face_latency)

            if pid is None:
                continue
            self._registry.set_identity(target.track_id, pid, name)
            self._identified += 1
```

**Gate a sustituir** (`recognition.py:144-152`) — hoy filtra por `person_id is None`; pasa a
preguntar a la FSM (`state_of` + `revalidate_after`):

```python
    def _next_candidate(self, now: float):
        """Track mas antiguo sin identidad y con edad suficiente, o None."""
        candidates = [
            ts for ts in self._registry.snapshot().values()
            if ts.person_id is None and (now - ts.first_seen) >= self._min_track_age
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda ts: ts.first_seen)
```

**Contador de inferencias para el criterio 6** — ampliar `stats` (`recognition.py:87-93`),
que ya es el punto que lee `MetricsSampler`:

```python
    @property
    def stats(self) -> dict:
        return {
            "identified": self._identified,
            "exceptions": self._exceptions,
            **self._rate.stats,
        }
```

**Prune de dos niveles y su razón** (`recognition.py:161-177`) — el docstring explica por qué
se poda contra `active_ids()` y no contra el retorno de `registry.prune()`; el nuevo prune del
`TemporalVoter` va exactamente aquí, el de la FSM **no** (expira por `lost_ttl` en `on_tick`):

```python
    def _maybe_prune(self, now: float) -> None:
        """
        Limpia las caches por track del recognizer.

        Se hace contra ``registry.active_ids()`` en vez de contra los ids
        que devuelve ``registry.prune()``: el DetectionWorker tambien poda
        el registry, asi que depender de quien llama primero a prune()
        seria una carrera. Con el set de activos, el resultado es el mismo
        sin importar el orden.
        """
        if now - self._last_prune < self._prune_interval:
            return
        self._last_prune = now
        try:
            self._recognizer.prune(self._registry.active_ids())
        except Exception:
            logger.exception("RecognitionWorker: prune de caches fallo")
```

---

### `backend/events/engine.py` (service, pub-sub thread→async)

**Analog:** el propio fichero.

**Constructor del `_publish`** (`engine.py:45-65`) — los métodos nuevos de identidad NO
construyen `Event` a mano; delegan aquí:

```python
    def _publish(
        self,
        event_type: EventType,
        ts: datetime.datetime,
        captured_at: float | None = None,
        processed_at: float | None = None,
        **fields: Any,
    ) -> None:
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

**Emisión solo en transición, con guarda de idempotencia** (`engine.py:143-153`) — patrón
exacto para "un `PERSON_RECOGNIZED` por visita" (FACE-09) y para el `UNKNOWN_PERSON` único
por track:

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

**Método público con campos de primer nivel + payload** (`engine.py:71-84`) — plantilla para
`emit_identity(...)`:

```python
    def emit_line_crossing(
        self, crossing: dict[str, Any], captured_at: float | None = None, processed_at: float | None = None
    ) -> None:
        self._publish(
            EventType.LINE_CROSSED,
            ts=crossing["timestamp"],
            captured_at=captured_at,
            processed_at=processed_at,
            track_id=crossing.get("tracker_id"),
            payload={
                "direction": crossing["direction"],
                "is_intrusion": bool(crossing.get("is_intrusion", False)),
            },
        )
```

Campos del `Event` disponibles sin inventar nada (`events/types.py:60-74`): `track_id`,
`person_id`, `person_name`, `confidence`, `bbox`. La severidad por defecto de
`UNKNOWN_PERSON` ya es `WARNING` (`types.py:49-57`) — **no** pasar `severity=` explícito o
se pierde el default (`model_fields_set` deja de aplicar el validador `types.py:76-80`).

**Bridge hilo → loop** (`events/bus.py:83-86`) — no reimplementarlo, solo saber que existe:

```python
    def publish_threadsafe(self, event: Event) -> None:
        """Bridge for worker threads (Phase 18 pipeline workers). Uses call_soon_threadsafe."""
        loop = self._loop or asyncio.get_event_loop()
        loop.call_soon_threadsafe(self._enqueue, event)
```

---

### `backend/pipeline/manager.py` (wiring)

**Analog:** `manager.py:77-89` (`_make_detection`, el único worker que ya recibe `event_engine`).

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

**Bloque a modificar** (`manager.py:114-125`) — la factoría se re-ejecuta en cada reinicio del
supervisor, así que si la FSM vive dentro del worker **su estado se pierde al reiniciar**;
si eso importa, hay que construirla fuera de `_make_recognition` (como se hace con `clients`
en `_make_streaming`, `manager.py:91-99`) y pasarla por parámetro:

```python
        if recognizer is not None and getattr(recognizer, "available", False):
            def _make_recognition() -> RecognitionWorker:
                self.recognition = RecognitionWorker(
                    self.broker.subscribe("recognition", replace=True),
                    self.registry, recognizer,
                    AdaptiveRate(target_fps=recognition_fps,
                                 min_fps=recognition_fps, max_fps=recognition_fps),
                    on_identified=on_identified,
                )
                return self.recognition

            self.supervisor.register("recognition", _make_recognition)
```

Firma de `CameraPipeline.__init__` donde entran los parámetros nuevos (`manager.py:39-54`):
`event_engine` ya está en la línea 47; `recognition_fps: float = 2.0` (línea 53) es el
precedente exacto para `identity_*` como parámetros escalares con default.

---

### `backend/config.py` (config, pydantic-settings)

**Analog:** `config.py:119-135`. Bloque comentado con la fase que lo introduce, tipos
explícitos y default igual al del SPEC:

```python
    # --- Observabilidad (Fase 21) ---
    metrics_enabled: bool = True
    metrics_sample_secs: float = 5.0

    # --- Reconocimiento facial ArcFace (Fase 23 — FACE-01..03) ---
    # Defaults de SPEC_v2.md §5.4 — no son los mismos umbrales que usaba dlib
    # (distancia euclídea vs. similitud coseno, no comparables directamente).
    face_min_size_px: int = 60
    face_max_blur: float = 100.0
    face_max_yaw_deg: float = 40.0
    face_match_threshold: float = 0.45
    face_confirm_threshold: float = 0.55
```

**Validador con rango** cuando el valor puede romper el sistema en silencio
(`config.py:39-51`) — el RESEARCH pide rangos para `window ≥ min_votes ≥ 1` y
`0 < min_ratio ≤ 1`:

```python
    @field_validator("yolo_model_path")
    @classmethod
    def validate_yolo_model_path(cls, v: str) -> str:
        p = Path(v)
        if p.suffix.lower() not in _MODEL_PATH_ALLOWED_SUFFIXES:
            raise ValueError(
                f"yolo_model_path extension {p.suffix!r} not allowed. "
                f"Allowed: {sorted(_MODEL_PATH_ALLOWED_SUFFIXES)}"
            )
        ...
        return v
```

**Cómo llega la config al worker** — nunca se importa `get_settings()` dentro de
`backend/pipeline/`; se inyecta desde `main.py` (`main.py:299-305` y `main.py:417-431`):

```python
    recognizer = PersonRecognizer(
        db_path=settings.db_path.replace("events.db", "persons.db"),
        match_threshold=settings.face_match_threshold,
        confirm_threshold=settings.face_confirm_threshold,
        min_face_size_px=settings.face_min_size_px,
        ...
    )
    ...
        event_engine=event_engine,
        latency_tracker=latency_tracker,
        ...
        recognition_fps=settings.recognition_target_fps,
    )
```

Los 5 parámetros nuevos siguen ese mismo camino: `config.py` → `main.py` →
`CameraPipeline(...)` → `RecognitionWorker(...)` → constructor de `TemporalVoter` /
`IdentityStateMachine`.

---

### `backend/pipeline/tracking.py` (model, shared-state)

**Analog:** el propio fichero. Campo nuevo `identity_state: IdentityState = IdentityState.UNKNOWN`
al final de `TrackState` (`tracking.py:28-29`, junto a `person_id`/`person_name`), y setter con
el mismo lock, copiando `set_identity` (`tracking.py:91-96`):

```python
    def set_identity(self, track_id: int, person_id: int, name: str | None) -> None:
        with self._lock:
            ts = self._tracks.get(track_id)
            if ts is not None:
                ts.person_id = person_id
                ts.person_name = name
```

El invariante que hay que respetar está escrito en el docstring de la clase
(`tracking.py:33-39`) y `identity_state` cae del lado correcto (único escritor:
`RecognitionWorker`):

```python
class TrackRegistry:
    """
    Estado compartido de tracks, protegido por un unico RLock.

    Se prohibe que dos workers escriban el mismo campo: DetectionWorker es
    el unico escritor de bbox/confidence/centroid_history; RecognitionWorker
    es el unico escritor de person_id/person_name via set_identity.
    """
```

**Cuidado con la dirección del import:** `tracking.py` no importa nada de `backend/` hoy
(`tracking.py:8-13`). Importar `IdentityState` desde `backend.perception.face.identity` crea
`pipeline → perception`, dirección que ya existe (`recognition.py` usa `recognizer.py`, que
usa `perception/face/*`) y que ningún test de arquitectura prohíbe.

---

### `backend/recognizer.py` (service — retirar `_votes`, exponer score)

**Analog:** el propio fichero. Lo que se elimina (`recognizer.py:74-75, 200-220`) ya está citado
arriba en el eje 2 de `identity.py`. Lo que hay que tocar además:

- `recognizer.py:78` — el comentario que anticipa esta fase:
  ```python
        self._confirm_threshold = confirm_threshold  # reserved for Fase 24's TemporalVoter
  ```
- `recognizer.py:340-351` (`prune`) — quitar `self._votes` de la tupla si se elimina el campo.
- `recognizer.py:173-177` — el docstring de `process_crop` describe la votación por mayoría;
  hay que reescribirlo, no dejarlo mintiendo.

**Firma actual** (`recognizer.py:152-154`), a la que hay que añadir el score:

```python
    def process_crop(
        self, crop_bgr: np.ndarray, tracker_id: int
    ) -> tuple[int | None, str | None, bool]:
```

Si se crea un método nuevo que ejecuta inferencia, hay que añadirlo al set de
`tests/test_architecture.py:15-17` o el invariante deja de proteger esa ruta:

```python
INFERENCE_CALLS = {
    "detect_sv", "detect", "embed", "process_crop", "identify_or_register",
}
```

Y el test que congela la firma pública (`test_recognizer_orchestration.py:90-95`) hay que
actualizarlo en el mismo commit:

```python
def TEST_public_contract_unchanged(tmp_path):
    r, _, _ = _make_recognizer(tmp_path)
    assert list(inspect.signature(r.process_crop).parameters) == ["crop_bgr", "tracker_id"]
    assert list(inspect.signature(r.prune).parameters) == ["active_tracker_ids"]
```

---

### `backend/observability/metrics.py` (solo si el plan añade una métrica)

**Declaración en el catálogo** (`metrics.py:23-46` para el campo del dataclass, `metrics.py:95-97`
para el constructor). Un `Counter` con labels se declara así:

```python
        events_total=Counter(
            "events_total", "Eventos tipados emitidos", ["type", "severity", "camera"], registry=registry
        ),
```

**Incremento desde un worker** — import del singleton con alias `_metrics` y una sola línea en el
bucle. `recognition.py:22` y `recognition.py:132`:

```python
from backend.observability.metrics import metrics as _metrics
...
            _metrics.inference_latency_seconds.labels(stage="face").observe(face_latency)
```

`detection.py:180` para un `Gauge`:

```python
            _metrics.active_tracks.labels(camera=self._camera_id).set(len(tracked))
```

**Gauge derivado del registry, calculado en el sampler** (`sampler.py:111-119`) — es donde
encajaría un gauge de tracks por `identity_state`, no en el worker:

```python
        identities_confirmed = 0
        identities_unknown = 0
        for track in pipeline.registry.snapshot().values():
            if track.person_id is not None:
                identities_confirmed += 1
            else:
                identities_unknown += 1
        m.identities_confirmed.labels(camera=camera_id).set(identities_confirmed)
        m.identities_unknown.labels(camera=camera_id).set(identities_unknown)
```

**Aviso** (`metrics.py:117-123`): añadir algo fuera del catálogo de SPEC §8.4 exige comentario
justificativo en el propio sitio, con el patrón de `prebuffer_bytes`.

---

### `tests/test_temporal_voting.py` y `tests/test_identity_state_machine.py` (NUEVOS)

**Analog de estilo:** `tests/test_recognizer_orchestration.py` — cabecera que explica qué se
mockea y qué no, `TEST_*`, separadores de bloque con el *porqué*:

```python
"""Tests for backend.recognizer.PersonRecognizer orchestration (Fase 23).
...
backend.perception.face.index.IdentityIndex is NOT mocked: it's simple,
deterministic, and exercising the real cosine-similarity math end-to-end
is more meaningful than mocking it too.
"""

# ─── available refleja FaceEngine.available ──────────────────────────────────
def TEST_available_reflects_engine_availability(tmp_path):
    r, _, _ = _make_recognizer(tmp_path, available=False)
    assert r.available is False
```

**Analog de reloj simulado:** `tests/test_memory_bounds.py:46-53` — `now` es un `float`
sintético del bucle, cero `sleep`, cero `freezegun`:

```python
def TEST_track_registry_bounded():
    registry = TrackRegistry()
    for i in range(10_000):
        now = float(i)
        registry.update_from_detections(_fake_tracked(i), now)
        registry.prune(now, ttl=5.0)

    assert len(registry.active_ids()) <= 10
```

Los tests de la FSM son puros: `on_face_result(track_id, pid, score, now=t)` con `t` avanzando
a mano. Para el criterio 5 (`revalidate_after=120 s`, 3 ciclos) basta con `t += 121.0` tres veces.

**Analog de embeddings sintéticos** (solo si algún test recorre el camino completo desde
`process_crop`) — `test_recognizer_orchestration.py:37-44`:

```python
def _at_similarity(base: np.ndarray, similarity: float, seed: int) -> np.ndarray:
    """A unit vector with cosine similarity ~*similarity* to *base*."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(_DIM).astype(np.float32)
    noise -= np.dot(noise, base) * base
    noise /= np.linalg.norm(noise)
    result = similarity * base + np.sqrt(max(0.0, 1 - similarity**2)) * noise
    return (result / np.linalg.norm(result)).astype(np.float32)
```

**Mocking de `FaceEngine` sin cargar ONNX** — `test_recognizer_orchestration.py:66-77`:

```python
def _make_recognizer(tmp_path, available: bool = True) -> tuple[PersonRecognizer, MagicMock, MagicMock]:
    """A PersonRecognizer wired to mock FaceEngine/FaceQualityAssessor, with a real IdentityIndex."""
    engine = MagicMock()
    engine.available = available
    quality = MagicMock()
    quality.assess.return_value = _passing_quality()
    with (
        patch("backend.recognizer.FaceEngine", return_value=engine),
        patch("backend.recognizer.FaceQualityAssessor", return_value=quality),
    ):
        r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    return r, engine, quality
```

---

### `tests/test_memory_bounds.py` (extender — 2 tests de cota)

**Analog:** `test_memory_bounds.py:71-89`. Copiar el comentario-cabecera que explica el riesgo
real, no solo la aserción:

```python
# ─── Las caches de PersonRecognizer indexadas por tracker_id se podan ────────
# _cache, _last_attempt, _pending y _votes crecerian indefinidamente si no se
# purgan los tracker_ids que ya no estan activos — ByteTrack nunca reutiliza
# ids. prune(active_tracker_ids) debe dejar solo las entradas activas.
# ─────────────────────────────────────────────────────────────────────────────
def TEST_recognizer_cache_bounded(tmp_path):
    r = PersonRecognizer(db_path=str(tmp_path / "p.db"))
    for tid in range(10_000):
        r._cache[tid] = (tid, "Someone")
        r._last_attempt[tid] = 0
        r._pending[tid] = []
        r._votes[tid] = None

    r.prune(active_tracker_ids=set(range(9_990, 10_000)))

    assert len(r._cache) == 10
    assert len(r._last_attempt) == 10
    assert len(r._pending) == 10
    assert len(r._votes) == 10
```

Este test **rompe** si se elimina `_votes` (líneas 82 y 89). Actualizarlo en el mismo commit
que la retirada, no después.

---

### `tests/test_event_engine.py` (extender — los 3 eventos de identidad)

**Analog:** `test_event_engine.py:15-48`. Bus real, `asyncio_mode = auto` (sin decorador),
`wait_until` en vez de `sleep` fijo:

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


async def TEST_line_crossing_emits_event():
    engine, received = make_engine()
    now = datetime.datetime(2026, 4, 16, 18, 30)

    engine.emit_line_crossing({"direction": "in", "timestamp": now, "tracker_id": 7, "is_intrusion": False})
    await wait_until(lambda: len(received) == 1)

    event = received[0]
    assert event.type == EventType.LINE_CROSSED
    assert event.camera_id == "cam1"
    assert event.track_id == 7
    assert event.payload["direction"] == "in"
```

Para "exactamente un `PERSON_RECOGNIZED` en 200 frames" (criterio 2), la forma es el patrón de
`TEST_zone_transitions` (`test_event_engine.py:51-64`): filtrar `received` por tipo y afirmar
sobre el conteo.

---

### `tests/test_recognition_worker.py` (extender — presupuesto de inferencias, criterio 6)

**Analog:** el propio fichero, `test_recognition_worker.py:18-65`. Worker con hilo real,
`MagicMock` como recognizer, publicación de frames a ritmo alto y aserción sobre
`process_crop.call_count`. Es literalmente el test del criterio 6 con otros números:

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


@pytest.fixture
def broker():
    return FrameBroker()


# ─── Respeta el FPS objetivo de reconocimiento ──────────────────────────────
def test_recognition_respects_target_fps(broker):
    registry = TrackRegistry()
    registry.update_from_detections(_FakeTracked([1]), now=time.monotonic() - 10)

    recognizer = MagicMock()
    recognizer.available = True
    recognizer.process_crop.return_value = (None, None, False)  # nunca identifica

    sub = broker.subscribe("recognition")
    rate = AdaptiveRate(target_fps=3.0, min_fps=3.0, max_fps=3.0)
    worker = RecognitionWorker(sub, registry, recognizer, rate, min_track_age=0.0)
    worker.start()

    _publish_for(broker, seconds=1.0)   # ~50 FPS de publicacion
    worker.stop()

    # a 3 FPS objetivo durante ~1 s: ni 1 ni 50
    assert 1 <= recognizer.process_crop.call_count <= 8
```

Dos avisos concretos sobre este fichero:

1. Sus funciones son `def test_*` **en minúscula** — no se recogen en CI Linux
   (`pytest.ini`: `python_functions = TEST_*`). Los tests **nuevos** que se añadan aquí deben
   ir en `TEST_*`. No es necesario renombrar los existentes en esta fase, pero conviene saberlo.
2. `recognizer.process_crop.return_value = (None, None, False)` aparece 4 veces
   (líneas 54, 77, 128, 152). Si cambia la aridad de la tupla, **todas** hay que tocarlas.

---

## Shared Patterns

### 1. Worker de pipeline — esqueleto de hilo

**Fuente:** `backend/pipeline/recognition.py:58-93` (idéntico en `detection.py:72-114`).
**Aplica a:** cualquier cambio en `recognition.py`.

```python
        self._running = False
        self._thread: threading.Thread | None = None
        ...
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="recognition-worker"
        )
        self._thread.start()

    def is_alive(self) -> bool:
        """True si el hilo del worker sigue vivo (lo consulta WorkerSupervisor)."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("RecognitionWorker: thread did not stop within %.1fs", timeout)
        self._sub.close()
```

### 2. Manejo de errores en el bucle caliente

**Fuente:** `backend/pipeline/recognition.py:121-129`.
**Aplica a:** toda llamada nueva dentro de `_loop` (FSM, `event_engine`, `set_identity_state`).
El bucle **nunca** muere: se cuenta la excepción, se loguea con `logger.exception` y se
`continue`.

```python
            try:
                pid, name, _ = self._recognizer.process_crop(crop, target.track_id)
            except Exception:
                self._exceptions += 1
                logger.exception(
                    "RecognitionWorker: fallo de reconocimiento (track %d)", target.track_id
                )
                continue
```

Variante para un callback no crítico (`recognition.py:138-142`) — no incrementa el contador:

```python
            if self._on_identified is not None:
                try:
                    self._on_identified(crop, pid)
                except Exception:
                    logger.exception("RecognitionWorker: on_identified fallo")
```

### 3. Privacidad de identidad en logs (V8 del RESEARCH)

**Fuente:** `backend/recognizer.py:212-216`. Ids en el log, nombres solo en el `Event`.

```python
                if cached is not None and cached[0] != winner:
                    logger.info(
                        "PersonRecognizer: re-verify corrected tracker %d: "
                        "person %d → %d", tracker_id, cached[0], winner,
                    )
```

### 4. Cabecera de módulo / clase que declara el contrato

**Fuente:** `pipeline/recognition.py:1-11`, `pipeline/tracking.py:1-6`, `perception/face/quality.py:1-14`.
**Aplica a:** `identity.py` y a los docstrings que esta fase invalida.
Todo módulo del repo abre con: qué hace, de qué fase viene, qué queda explícitamente fuera.
Ojo: `recognition.py:9-10` dice hoy *"Los tracks ya identificados se saltan — la revalidacion
temporal llega en la Fase 24"*. Es esta fase: hay que reescribirlo.

### 5. Import de tipos solo para anotaciones

**Fuente:** `pipeline/recognition.py:26-28`, `pipeline/detection.py:26-31`, `events/engine.py:23-24`.
**Aplica a:** el import de `EventEngine` en `recognition.py` (evita el ciclo
`pipeline → events → storage`).

```python
if TYPE_CHECKING:
    from backend.pipeline.broker import Subscription
    from backend.recognizer import PersonRecognizer
```

---

## No Analog Found

Ninguno. Los 12 ficheros tienen analog en el repo.

Dos matices donde el analog existe pero **no debe copiarse tal cual**:

| Fichero | Analog | Qué NO copiar |
|---|---|---|
| `backend/perception/face/identity.py` | `pipeline/tracking.py` | El `threading.RLock`. La FSM vive en un solo hilo (`RecognitionWorker._loop`); un lock ahí es ruido y sugiere un uso compartido que el diseño prohíbe |
| `backend/perception/face/identity.py` | `recognizer.py::prune(active_ids)` | La política de expiración por `active_ids` para `IdentityStateMachine`. `TEMPORARILY_LOST` existe para sobrevivir a la desaparición del track (Pitfall 2 del RESEARCH). Solo `TemporalVoter` usa `active_ids` |

---

## Metadata

**Alcance de la búsqueda:** `backend/pipeline/`, `backend/events/`, `backend/perception/face/`,
`backend/observability/`, `backend/recognizer.py`, `backend/config.py`, `backend/main.py`, `tests/`
**Ficheros leídos íntegros:** 8 (`tracking.py`, `recognition.py`, `detection.py`, `events/engine.py`,
`events/bus.py`, `events/types.py`, `config.py`, `metrics.py`, `rate.py`, `test_recognition_worker.py`)
**Ficheros leídos por rangos dirigidos:** 6 (`recognizer.py`, `manager.py`, `quality.py`, `sampler.py`,
`test_memory_bounds.py`, `test_recognizer_orchestration.py`, `test_event_engine.py`, `test_architecture.py`)
**Fecha de extracción:** 2026-08-12
**Validez:** las líneas citadas corresponden al commit `7262644`. Si `recognizer.py`,
`recognition.py` o `events/engine.py` cambian antes de ejecutar el plan, reverificar.
