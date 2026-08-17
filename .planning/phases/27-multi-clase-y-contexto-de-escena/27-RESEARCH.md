# Phase 27: Multi-clase y contexto de escena - Research

**Researched:** 2026-08-16
**Domain:** Detección multi-clase sobre un tracker class-agnostic (supervision/ByteTrack), analítica de objetos abandonados/retirados y agregación histórica en SQLite
**Confidence:** HIGH — las cuatro preguntas abiertas del CONTEXT se resuelven con medición directa sobre el código y las librerías instaladas en esta máquina. Las únicas piezas MEDIUM/LOW son las que dependen de una escena real (calibración de la distancia "persona cerca" y los umbrales de nivel de actividad).

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (BEH-06, alcance de configurabilidad)**: endpoint + control UI en vivo.
  Nuevo endpoint (GET/PUT) para leer y cambiar las clases activas en caliente,
  con persistencia en `AppConfig` y un control simple en el dashboard
  (checkboxes). El `DetectionWorker` debe recoger el cambio sin caída del
  pipeline.
- **D-02 (BEH-08/09, cálculo de media móvil)**: query sobre datos existentes,
  sin tabla nueva. La media de la franja horaria se calcula sobre los últimos 7
  días de `DetectionStat`/`Event` ya persistidos. Sin migración.
- **D-03 (modelo default)**: corregir `backend/config.py:37` a
  `yolo_model_path: str = "yolo26n.pt"`, alineado con `CLAUDE.md`. El criterio 6
  se mide contra `yolo26n.pt`.

**Hallazgos H-1..H-8 del CONTEXT** — verificados uno a uno en este research (ver
`## Verificación de H-1..H-8`). Siete confirmados, uno con corrección material.

**Restricciones de arquitectura (CLAUDE.md — no negociables):**
- Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia.
- `TrackRegistry` es la fuente de verdad del estado de tracks; escritor único por campo.
- Toda estructura con crecimiento potencial necesita política de expiración con test.
- Reloj inyectado: nada de `time.monotonic()` dentro de `perception/`.
- Cambio mínimo: no reescribir el pipeline de zonas, `PersonTracker` ni el `EventEngine`.
- Sin dependencias nuevas.

### Claude's Discretion

Los 4 puntos abiertos que CONTEXT dejó para este research (distancia "persona
cerca", exclusión de mobiliario fijo, actualización en caliente de `classes=`,
multi-clase en ByteTrack) más los 4 del orquestador (campos exactos del endpoint
de contexto, persistencia en `AppConfig`, query SQL concreta de D-02, metodología
de benchmark del criterio 6). Resueltos en `## Respuestas a las preguntas abiertas`.

### Deferred Ideas (OUT OF SCOPE)

- **Detección de caídas** — requiere pose → backlog v2.1 (SPEC_v2.md:905).
- **Refactor del frontend a módulos ES** → Fase 28. El control de clases de esta
  fase se añade inline en `index.html`, como todo lo demás hoy.
- **Retención de `detection_stats`** — hoy no existe purga para esa tabla
  (verificado). Crece 80 MB/año medidos. Fuera de alcance aquí.
- **Migrar el CRUD de zonas del ORM legacy (`backend/database.py`) al `ZoneRepo`
  v2** — esta fase solo necesita exponer una columna que ya existe físicamente.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Descripción | Soporte de este research |
|----|-------------|--------------------------|
| BEH-06 | Clases detectadas configurables más allá de "persona" | Q3 (mutación en caliente de `_classes`, medida) + Q4 (separación por clase ANTES del tracker) + Q6 (`AppConfig`) + Pitfall 1/2/3 |
| BEH-07 | Objetos abandonados (`OBJECT_LEFT`) y retirados (`OBJECT_REMOVED`) | Q1 (radio "persona cerca") + Q2 (aparición + exclusión por zona, sin estado persistente) + Patrón 2/3 |
| BEH-08 | Endpoint de contexto de escena agregado | Q5 (campos exactos y de dónde sale cada uno) + Patrón 5 |
| BEH-09 | Nivel de actividad contra la media móvil de esa franja horaria | Q7 (query SQLAlchemy real, medida: 11,2 ms a 525.600 filas, sin índice nuevo) + Pitfall 7 (sesgo de hora parcial) |
</phase_requirements>

---

## Summary

El CONTEXT dejó cuatro preguntas abiertas y las cuatro tienen respuesta
medible en esta máquina, sin depender de conocimiento de entrenamiento. Dos de
ellas cambian el plan de forma material.

**El hallazgo que domina la fase: `sv.ByteTrack` es class-agnostic, y lo he
reproducido.** `update_with_detections` construye el tensor de entrada solo con
`xyxy` y `confidence` — `class_id` nunca llega al matcher
(`supervision/tracker/byte_tracker/core.py:104-110`). El reensamblado posterior
del `tracker_id` vuelve a ser IoU puro con umbral 0,5 (`core.py:116-125`). En un
script sintético, un track de mochila con `track_id=1` **hereda su id a una
detección de persona** colocada casi en la misma caja: el id no se rompe, se
transfiere. A eso se suma que `sv.DetectionsSmoother.get_track` hace
`deepcopy(track[0])` — el elemento **más viejo** del deque — y solo promedia
`xyxy` y `confidence`, así que el `class_id` que sale del smoother es el de hace
hasta 5 frames (0,6 s a 8 FPS) y es pegajoso ante un cambio de clase (medido:
3 frames consecutivos reportando `class_id=24` con el detector diciendo `0`).
Consecuencia directa: **activar más clases sobre el pipeline actual sería una
regresión de la Fase 4**, que ya está en producción — `LineZone.trigger(tracked)`
(`tracker.py:79`) cuenta cruces de *cualquier* track, así que un coche cruzando
la línea sumaría al conteo de personas, y `RecognitionWorker` (que itera
`registry.snapshot()` y `registry.frame_ids()` sin filtrar) buscaría caras en
mochilas. La recomendación es prescriptiva: **separar las detecciones por clase
ANTES de tocar el tracker**, con un `sv.ByteTrack` propio para objetos, y **no
meter los objetos en `TrackRegistry`**.

**El segundo hallazgo relevante es que el criterio 6 ya está cumplido y sobra
margen.** `classes=` en Ultralytics es un filtro de post-proceso
(`ultralytics/models/yolo/detect/predict.py:54-58`), no cambia el forward pass, y
`yolo26n.pt` es end2end (NMS-free), así que el coste marginal es prácticamente
cero. Medido en esta máquina sobre `bus.jpg` a 1280×720, 30 muestras con 5 de
warmup: **38,90 ms con 1 clase, 40,74 ms con 6 (+4,7 %), 39,98 ms con las 80
(+2,8 %)** — todo dentro del ruido de medición y muy por debajo del 15 % del
criterio. El coste real de multi-clase no está en YOLO sino aguas abajo (más
tracks, más entradas de smoother, más estado); ahí es donde el plan debe poner
las cotas.

Lo demás encaja sin fricción: mutar `self._classes` en una instancia viva de
`PersonDetector` funciona sin recargar el modelo (verificado: `id(self._model)`
no cambia y la siguiente inferencia ya usa las clases nuevas), lo cual es
**imprescindible** porque forzar un reinicio del `DetectionWorker` vía el
supervisor lo contaría como caída y tres cambios de configuración en 60 s
dejarían el worker en `FAILED` y el pipeline en modo degradado permanente
(`supervisor.py:160-173`). La media móvil de D-02 sale de una sola query sobre
`DetectionStat`, medida en **11,2 ms sobre una tabla de 525.600 filas (un año)**
usando los índices que ya existen — no hace falta índice nuevo. Y la exclusión de
mobiliario fijo se resuelve con dos guardas en memoria (ventana de warmup +
zonas de exclusión reutilizando la columna `zones.kind`, que ya existe
físicamente en el esquema) sin ningún estado persistente nuevo.

**Primary recommendation:** dividir `sv_dets` por `class_id` en
`DetectionWorker._loop` antes de `tracker.update()`; personas siguen exactamente
el camino de hoy (`PersonTracker` → `LineZone` → `TrackRegistry` → identidad →
`BehaviorAnalyzer`), objetos van a un segundo `sv.ByteTrack` dedicado y viven
solo dentro del nuevo `ObjectAnalyzer` (dominio puro en
`backend/perception/objects.py`, calcado de `behavior.py`); `classes=` se cambia
en caliente mutando `PersonDetector._classes` (nunca reiniciando el worker), con
persistencia en `AppConfig` leída antes de construir el detector; y
`/api/v2/analytics/context` es un módulo nuevo `backend/api/v2/context.py` que
combina el estado vivo del `TrackRegistry` con una única query de baseline sobre
`DetectionStat`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Filtrado de clases en inferencia | `PersonDetector` (`backend/detector.py`) | — | Ya acepta `classes=` y lo pasa por llamada; Ultralytics lo aplica en post-proceso (verificado) |
| Separación personas / objetos | Hilo de detección (`DetectionWorker._loop`) | — | Único punto que ve `sv_dets` crudo antes de que ByteTrack borre la información de clase |
| Tracking de personas | `PersonTracker` (`backend/tracker.py`) | — | **No se toca.** Es el dueño del `LineZone` de la Fase 4, en producción |
| Tracking de objetos | `ObjectTracker` (nuevo, `sv.ByteTrack` propio) | — | ByteTrack es class-agnostic (verificado): un tracker por grupo de clases es la única forma de que la clase no migre |
| Reglas de objeto abandonado/retirado | Dominio puro (`backend/perception/objects.py`) | — | Sin reloj real, sin I/O, sin `Event`: patrón `behavior.py` (Fase 26) |
| Estado de posición de objetos para lectura externa | `DetectionWorker` (dict bajo `self._lock`) | — | Mismo patrón que `_zone_states`/`get_zone_stats()`; evita crear un segundo registry |
| Traducción veredicto → `Event` tipado | `backend/events/engine.py` (`emit_object`) | — | Calco 1:1 de `emit_behavior` (Fase 26) |
| Cambio en caliente de clases activas | `PersonDetector.set_classes()` | `CameraPipeline` (fachada) → API | Atributo leído por llamada; el supervisor NO debe intervenir (ver Q3) |
| Persistencia de la config de clases | `ConfigRepo` / tabla `app_config` | `backend/config.py` (default) | La tabla y el repo ya existen y no tienen ni un solo usuario hoy |
| Estado agregado de escena (vivo) | `backend/api/v2/context.py` | `TrackRegistry` + `CameraPipeline` | El registry ya tiene `identity_state` y `person_id` por track (Fase 24) |
| Baseline histórico por franja horaria | `DetectionStatRepo` (método nuevo) | SQLite | Una query, índice existente, 11,2 ms medidos |
| Nivel de actividad (clasificación) | `backend/api/v2/context.py` | — | Es política de producto, no dominio de percepción |
| UI de clases activas | `frontend/index.html` (inline) | — | `app.js` es un stub vacío hasta la Fase 28 |

---

## Verificación de H-1..H-8

Los ocho hallazgos del CONTEXT son correctos. Tres necesitan matiz y **uno
necesita una corrección que cambia el plan**.

### H-1 — CONFIRMADO, y con dos comportamientos medidos que el plan necesita

[VERIFIED: `backend/detector.py:23-35,51-57`] `PersonDetector.__init__` acepta
`classes: list[int] | None = None` y guarda `self._classes = classes if classes
is not None else [0]`. `detect_sv` pasa `classes=self._classes` **en cada
llamada** a `self._model(...)` (línea 54). `backend/config.py:54` tiene
`yolo_classes: list[int] = [0]`.

[VERIFIED: `backend/main.py:281-287`] El detector se construye con
`classes=settings.yolo_classes` dentro del `lifespan`, en la línea 281 —
**después** de `await init_db()` (línea 238). Es decir, la BD ya está migrada y
disponible cuando se construye el detector: leer las clases persistidas de
`AppConfig` antes de instanciarlo no requiere reordenar nada.

**Medición 1 — `sv.Detections` ya trae el nombre de clase, no solo el id.**
[VERIFIED: ejecución en esta sesión, supervision 0.27.0.post2]
`sv.Detections.from_ultralytics(...)` devuelve `class_id` (numpy int) **y**
`data["class_name"]` (numpy de strings: `['person' 'person' ...]`). No hace falta
mantener a mano un mapa COCO id→nombre en el repo: sale del modelo. Ver
`## Don't Hand-Roll`.

**Medición 2 — el slicing por clase preserva `data`.**
[VERIFIED] `det[np.isin(det.class_id, [0])]` sobre 5 detecciones devuelve 4 con
`data["class_name"]` intacto. La separación por clase es una línea.

**Medición 3 — `classes=[]` NO significa "todas".**
[VERIFIED] Con `_classes = []`, `detect_sv` devuelve 0 detecciones (no lanza).
Con `_classes = None`, devuelve las 80 clases. Es decir, una lista vacía **ciega
el sistema en silencio**, incluido el conteo de personas de la Fase 4. El
endpoint de D-01 debe rechazar la lista vacía con 400. Ver Pitfall 3.

### H-2 — CONFIRMADO, y **la corrección material de este research**

CONTEXT dice que el tracking es mono-clase hoy y que la pregunta abierta es si
`class_id` basta como metadato. La respuesta medida es que **no basta, y además
el problema es peor de lo planteado**.

[VERIFIED: `backend/pipeline/tracking.py:18-34`] `TrackState` no tiene
`class_id`/`class_name`. [VERIFIED: `tracking.py:55-85`]
`update_from_detections` solo lee `xyxy`/`confidence`. [VERIFIED:
`backend/tracker.py:30-32`] `sv.ByteTrack(lost_track_buffer=60,
frame_rate=frame_rate)` — ningún parámetro de clase (no existe ninguno).

**Evidencia nueva, en el código de la librería instalada**
[VERIFIED: `.venv/Lib/site-packages/supervision/tracker/byte_tracker/core.py`,
supervision 0.27.0.post2]:

```python
# core.py:104-110  — el tensor que entra al matcher
tensors = np.hstack((detections.xyxy, detections.confidence[:, np.newaxis]))
tracks = self.update_with_tensors(tensors=tensors)
```

`class_id` **no viaja**. La asociación interna (`core.py:210-215`) es
`matching.iou_distance` + `fuse_score` + Kalman, sin ninguna noción de clase. Y
el reensamblado del `tracker_id` sobre las detecciones originales
(`core.py:116-125`) es otra asignación húngara por IoU con umbral fijo 0,5, otra
vez sin mirar la clase.

**Reproducción sintética [VERIFIED: script ejecutado en esta sesión]:**

| Escenario | Resultado |
|---|---|
| Persona estable 7 frames, luego aparece una mochila **solapada dentro** de su caja | Ids separados y estables: persona `1`, mochila `2`. La IoU basta cuando las cajas difieren |
| Mochila estable 5 frames en `[300,300,400,500]`, luego el detector la reporta como **persona** en `[300,305,405,505]` | **`track_id=1` se mantiene**: el id de la mochila pasa a la persona. La identidad de tracking no se rompe, se transfiere entre clases |

**Y el smoother agrava el problema** [VERIFIED:
`supervision/detection/tools/smoother.py:97-110`]: `get_track` hace
`ret = deepcopy(track[0])` — el elemento **más viejo** del deque de `length=5` —
y solo recalcula `xyxy` y `confidence` con `np.mean`. `class_id` y
`data["class_name"]` salen del frame más viejo de la ventana. Medido: tras 4
frames como `class_id=24`, con el detector reportando `class_id=0` durante 3
frames seguidos, el smoother sigue devolviendo `24`. A 8 FPS son 0,6 s de clase
equivocada, y en el peor caso se queda pegada.

**Consecuencias que el plan DEBE cubrir** (ninguna es hipotética; las tres son
código en producción):

1. `LineZone.trigger(tracked)` (`tracker.py:79`) cuenta cruces de todos los
   tracks. Habilitar `car`/`bicycle` haría que los vehículos sumaran al conteo
   de personas de la Fase 4.
2. `RecognitionWorker` itera `registry.snapshot().values()`
   (`recognition.py:297,330`) y `registry.frame_ids()` (`recognition.py:314,367`)
   sin filtro: correría detección facial y ReID sobre mochilas y coches,
   quemando el presupuesto de los 2 FPS de reconocimiento.
3. `EventEngine.process_tracks` emitiría `PERSON_ENTERED`/`PERSON_EXITED` por
   cada coche, y `accumulate_detections` contaminaría `detection_stats` — que es
   justo la fuente del baseline de BEH-09.

→ Ver Q4 para la solución recomendada.

### H-3 — CONFIRMADO, sin matices

[VERIFIED: `backend/events/types.py:36-38`] `OBJECT_LEFT` y `OBJECT_REMOVED`
existen con el comentario literal "emitidos a partir de la Fase 27; catalogados
ya para estabilidad del contrato". [VERIFIED: `types.py:55`]
`OBJECT_LEFT: Severity.WARNING` en `DEFAULT_SEVERITY`; `OBJECT_REMOVED` no
aparece → cae en `Severity.INFO`.

**Consecuencia no obvia, igual que la que la Fase 26 documentó para los
comportamientos** [VERIFIED: `config.py:115` + `recording.py:309`]:
`upload_min_severity = "warning"`, así que **`OBJECT_LEFT` disparará la subida
automática de clips a Google Drive desde el primer evento**. No es un accidente
(un objeto abandonado es exactamente lo que quieres tener grabado), pero el plan
debe decirlo explícitamente y el checkpoint manual debe verificar que no se
convierte en una fuente de subidas espurias si el ajuste de la distancia
"persona cerca" no está calibrado. `OBJECT_REMOVED` en `INFO` no sube nada.

[VERIFIED: `tests/test_event_types.py:12`] congela la lista de nombres del
catálogo → no hay que añadir tipos nuevos, y no se puede sin romper ese test.

[VERIFIED: `grep emit_object backend/`] Sin resultados: no existe `emit_object*`
en `EventEngine`. La traducción `ObjectFinding → Event` es trabajo nuevo, calcado
de `emit_behavior` (`engine.py:242-267`).

### H-4 — CONFIRMADO

[VERIFIED: `backend/api/v2/recordings.py:1-24`, `backend/api/v2/metrics.py:1-19`,
`backend/api/v2/deps.py`] Dos routers reales con `APIRouter(prefix=..., tags=...)`,
registrados en `main.py:558,561`. `deps.py` aporta `limiter`, `V2_RATE_LIMIT =
"60/minute"` y `pagination_limit()`. Auth es global vía
`FastAPI(dependencies=[Depends(verify)])`, así que un router incluido la hereda
sin `Depends` por ruta.

`recordings.py` es el ejemplo a copiar: `router = APIRouter(prefix="/api/v2/...",
tags=[...])`, una factoría privada de repo (`def _recording_repo()`), y
`@limiter.limit(V2_RATE_LIMIT)` + `request: Request` en cada endpoint.
`metrics.py` aporta el otro patrón necesario: `def configure(...)` con un global
de módulo, llamado una vez desde el `lifespan` de `main.py`, para inyectar la
referencia viva (ahí es el `LatencyTracker`; aquí sería el `CameraManager`/
`CameraPipeline`).

### H-5 — CONFIRMADO, con dos datos nuevos

[VERIFIED: `backend/storage/repositories.py:153-169`] `EventRepo.hourly_counts`
agrupa con `func.strftime("%H", models.Event.ts)` y `.group_by(text("hour"))`.
Precedente directo del patrón SQL que necesita BEH-09 — y precedente de que el
repo asume SQLite (`strftime` no es portable).

[VERIFIED: `backend/storage/models.py:112-128`] `DetectionStat` tiene
`detections`, `unique_tracks`, `avg_confidence`, `max_concurrent`, con
`Index("idx_detstats_minute", "camera_id", minute.desc())` y
`UniqueConstraint("camera_id","minute")`.

**Dato nuevo 1 — qué significa realmente cada columna**
[VERIFIED: `backend/events/engine.py:273-286`]:
`bucket["detections"] += len(active_track_ids)` se ejecuta **una vez por frame
procesado**, así que `detections` es *frames × tracks*: un proxy de actividad que
depende del FPS efectivo de detección (que `AdaptiveRate` varía entre 3 y 12).
`unique_tracks` es el número de track_ids distintos del minuto — **esa es la
columna correcta para el baseline de BEH-09**, porque no depende del FPS.

**Dato nuevo 2 — `detection_stats` no tiene retención.**
[VERIFIED: no hay ninguna purga de `detection_stats` en `main.py` ni en
`repositories.py`, a diferencia de `events`/`recordings`/`persons`]. Crece a
1 fila/minuto/cámara = 525.600 filas/año, **80 MB medidos**. Irrelevante para el
rendimiento de la query de BEH-09 (ver Q7: el índice la hace O(ventana), no
O(tabla) — medido igual a 43.200 y a 525.600 filas), pero conviene que el
planner lo sepa.

**Dato nuevo 3 — el minuto en curso nunca está en la BD.**
[VERIFIED: `main.py:143-153` + `engine.py:288-301`] `_detection_stats_flush_loop`
corre cada 30 s y `flush_stats` solo persiste minutos **estrictamente anteriores**
al actual. El retardo máximo entre "ocurrió" y "está en `detection_stats`" es
~90 s. El endpoint de contexto no puede usar `DetectionStat` para el "ahora": el
"ahora" sale del `TrackRegistry`. Ver Q5 y Pitfall 7.

### H-6 — CONFIRMADO

[VERIFIED: `backend/perception/behavior.py:1-284`] El módulo es exactamente el
patrón descrito: docstring que declara la pureza, `REARM_RATIO` como constante de
histéresis, `BehaviorKind`/`BehaviorFinding` (dataclass con `magnitudes()`),
`_TrackAgg`/`_ZoneAgg` privados, reloj inyectado (`now: float` en `analyze` y
`prune`), doble guarda de expiración (`prune` por TTL + `_enforce_cap` LRU),
`_enforce_cap()` llamado también desde `analyze()`.

[VERIFIED: `backend/pipeline/detection.py:191-227`] `_analyze_behavior` con
`try/except Exception` → `self._exceptions += 1` + `logger.exception` y `return`,
antes de traducir a eventos.

[VERIFIED: `backend/pipeline/manager.py:107-124,126-140`] `BehaviorAnalyzer` se
construye en `CameraPipeline.__init__` **fuera** de `_make_detection` y se pasa
como argumento. El comentario explica el porqué. `ObjectAnalyzer` debe ir en el
mismo sitio y por el mismo motivo, con un agravante: su estado incluye la marca
de "arranque del pipeline" que hace de guarda contra el mobiliario fijo (Q2). Si
se construyera dentro de la factoría, **cada reinicio del DetectionWorker
reactivaría la ventana de warmup y podría emitir `OBJECT_LEFT` de todo el
mobiliario visible**.

[VERIFIED] `backend/perception/face/identity.py` y
`backend/perception/reid/gallery.py` son subpaquetes, tal como decía el CONTEXT.
`objects.py` va top-level junto a `behavior.py`.

### H-7 — CONFIRMADO

[VERIFIED] `frontend/app.js` es un stub; `frontend/index.html` tiene 1.954 líneas
con toda la lógica inline. [VERIFIED: `index.html:670` (`add-zone-panel`) y
`index.html:1672` (`// ── Zones panel ──`)] El panel de zonas es el análogo más
cercano a lo que necesita BEH-06: un `<div>` oculto con controles, más un bloque
JS que hace `fetch` y repinta. Copiar esa estructura.

### H-8 — CONFIRMADO

[VERIFIED: `backend/config.py:37`] `yolo_model_path: str = "yolov8n.pt"`.
[VERIFIED] Ambos ficheros existen en la raíz: `yolo26n.pt` (5,3 MB) y
`yolov8n.pt` (6,2 MB). El validador `validate_yolo_model_path`
(`config.py:39-51`) acepta `.pt` y exige contención dentro del proyecto → cambiar
el default a `"yolo26n.pt"` pasa la validación sin tocarla.

**Dato nuevo relevante para el criterio 6** [VERIFIED: medición en esta sesión]:
`yolo26n.pt` reporta `model.end2end = True` (NMS-free) y `yolov8n.pt`
`end2end = False`. Es decir, D-03 no es solo higiene: cambia la ruta de
post-proceso sobre la que se mide el criterio 6, así que **la medición debe
hacerse después de aplicar D-03**, no antes.

---

## Respuestas a las preguntas abiertas

### Q1 — Distancia "persona cerca" para BEH-07 → **150 px de suelo a 1280×720, derivado de `loiter_radius_px`, y con corrección de escala**

No hay valor en SPEC ni en ROADMAP, así que hay que derivarlo. Tres decisiones
encadenadas.

**Decisión 1 — qué se mide: anclas `BOTTOM_CENTER`, no centroides.**
Medir centroide-a-centroide es incorrecto aquí: una mochila en el suelo junto a
una persona de pie tiene el centroide desplazado verticalmente **media altura de
persona** respecto al de la persona, aunque estén tocándose. Con un umbral basado
en centroides habría que subirlo tanto (>200 px) que dejaría de discriminar.

El repo ya tiene la convención correcta y la usa dos veces:
[VERIFIED: `backend/tracker.py:41`] `LineZone(triggering_anchors=[sv.Position.BOTTOM_CENTER])`
con el comentario "los pies cruzan la línea de forma más fiable que el centro de
la caja"; y [VERIFIED: `backend/pipeline/detection.py:312`]
`tracked.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)` para el heatmap.
`BOTTOM_CENTER` es un proxy del punto de apoyo en el plano del suelo, que es
justo lo que "está cerca del objeto" significa.

→ **La distancia se mide entre los `BOTTOM_CENTER` de la persona y del objeto.**

**Decisión 2 — la magnitud base: 150 px, ≈ 1,9 × `loiter_radius_px`.**
La escala espacial que el repo ya usa a 1280×720 es
`immobile_radius_px = 20` ("no se ha movido", ruido de bbox) y
`loiter_radius_px = 80` ("sigue en el mismo sitio"). El nuevo umbral debe
significar "a un paso del objeto", que es estrictamente mayor que "en el mismo
sitio".

Referencia de tamaño medida [VERIFIED: `yolo26n.pt` sobre `bus.jpg` reescalado a
1280×720, las 4 personas detectadas]:

| bbox | ancho px | alto px | alto/ancho | alto / alto_frame |
|---|---|---|---|---|
| 1 | 271 | 358 | 1,32 | 0,50 |
| 2 | 220 | 327 | 1,48 | 0,45 |
| 3 | 187 | 309 | 1,65 | 0,43 |
| 4 | 124 | 208 | 1,69 | 0,29 |

Es una foto de gran angular a corta distancia, no una escena de vigilancia, así
que sirve para la **proporción** (ancho ≈ alto/1,5) y no para la magnitud
absoluta. En una escena típica de la C212 a media distancia una persona ocupa
25–40 % del alto del frame → alto 180–290 px, ancho 60–120 px.

`150 px` es entonces:
- **1,9 × `loiter_radius_px`** (magnitud derivada del repo, no inventada);
- **≈ media altura de persona** a media distancia → "a un paso";
- **1,25–2,5 anchos de persona** según la distancia.

**Decisión 3 — corregir por escala, porque un píxel no significa lo mismo cerca
que lejos.** `config.py:167-172` ya documenta esta debilidad para los umbrales de
la Fase 26 ("cambiar la resolución de proceso cambia el significado de
`loiter_radius_px`"). Aquí se puede arreglar con un `max()` y sin coste:

```python
radius = max(object_person_radius_px, object_person_radius_ratio * person_bbox_height)
```

con `object_person_radius_px = 150.0` (suelo) y `object_person_radius_ratio = 0.5`.
Una persona de 300 px de alto → 150 px. Una de 500 px (muy cerca) → 250 px. Una
de 100 px (lejos) → el suelo, 150 px. Es O(1) por par persona-objeto y elimina el
problema de "número mágico calibrado a una sola distancia".

**Asimetría de riesgo que el planner debe conocer.** El mismo radio se usa en dos
sentidos opuestos:

| Evento | Uso del radio | Efecto de pasarse de grande |
|---|---|---|
| `OBJECT_LEFT` | condición **negativa** (60 s sin ninguna persona dentro del radio) | **Seguro**: suprime eventos, menos falsos positivos |
| `OBJECT_REMOVED` | condición **positiva** (había una persona dentro del radio al desaparecer) | **Peligroso**: cualquiera que pase por la escena "explica" la desaparición |

Recomendación: **un solo parámetro compartido por defecto** (simplicidad, criterio
de diseño de CLAUDE.md), documentando en el docstring de config que si la
calibración con cámara real obliga a separarlos, hay que **subir** el de
`OBJECT_LEFT` y **bajar** el de `OBJECT_REMOVED`, nunca al revés.

**Confianza: MEDIUM.** La derivación (anclas, proporción, ratio de corrección) es
HIGH y está medida. El valor absoluto 150 px es una propuesta razonada, no una
calibración: no hay cámara en esta sesión (mismo estado que los checkpoints
manuales abiertos de las Fases 21/26 en `STATE.md`). El plan debe incluir un
checkpoint de calibración con escena real, igual que hizo `26-05`.

### Q2 — "Objeto que ha aparecido" y exclusión de mobiliario fijo → **se resuelve sin estado persistente nuevo, con dos guardas en memoria; el reinicio de proceso está cubierto por la primera**

SPEC exige dos condiciones (`SPEC_v2.md:917`): (a) transición ausente→presente
después del arranque, y (b) lista de exclusión por zona.

**Guarda (a) — ventana de warmup + set de ignorados. Cero persistencia.**

[VERIFIED: `backend/pipeline/tracking.py:104-108`] El repo documenta que
"ByteTrack nunca reutiliza ids". Confirmado en el código de la librería
(`core.py:62-63`, `external_id_counter = IdCounter(start_id=1)` monótono). Por
tanto "el objeto ha aparecido" ≡ "nació un `track_id` de clase-objeto".

El problema real, que el CONTEXT plantea correctamente, es el **arranque**: en el
primer frame todo lo que está en escena nace como track nuevo, indistinguible de
algo que acaba de aparecer. La solución es una ventana de gracia:

```
si (t_nacimiento_del_track - t_arranque_del_analizador) < object_warmup_secs:
    marcar el track como IGNORADO para siempre (mientras viva)
```

Un `float` (`self._started_at`) y un `set[int]` acotado por la misma cota dura y
el mismo TTL que el resto del estado. `object_warmup_secs = 10.0` es suficiente:
ByteTrack necesita ≥2 frames para activar un track (verificado empíricamente:
la primera detección de un objeto nuevo sale sin `tracker_id`), y 10 s a 3 FPS
(peor caso de `AdaptiveRate`) son 30 frames.

**¿Y un reinicio del proceso completo (no del worker)?** Es la pregunta del
orquestador y la respuesta es que **la guarda (a) lo cubre por construcción, y
el comportamiento resultante es el correcto**:

| Situación tras reiniciar el proceso | Qué pasa | ¿Aceptable? |
|---|---|---|
| Mobiliario fijo visible al arrancar (un banco, una maleta que vive ahí) | Nace dentro del warmup → ignorado permanentemente | **Sí. Es exactamente lo que SPEC pide** |
| Objeto genuinamente abandonado antes del reinicio, del que ya se emitió `OBJECT_LEFT` | Nace dentro del warmup → ignorado → **no se re-emite** | **Sí.** Evita el duplicado por reinicio, que sería el fallo peor |
| Objeto abandonado justo durante los 10 s de warmup | Se pierde ese `OBJECT_LEFT` | Aceptable: ventana de 10 s tras un reinicio manual |
| Mobiliario fijo **oculto** al arrancar y revelado después (una persona se aparta, cambia la luz, se mueve la PTZ) | Nace fuera del warmup → candidato → falso `OBJECT_LEFT` a los 60 s | **No.** Para esto está la guarda (b) |

→ **No hace falta ningún estado persistente.** Un almacén persistente de
"mobiliario conocido" tendría que resolver identidad de objeto entre sesiones
(los `track_id` no sobreviven al reinicio), lo que exigiría ReID de objetos o
matching geométrico con posiciones guardadas: una fase entera de trabajo para
cubrir un caso que la guarda (b) ya cubre con una zona dibujada. **Explícitamente
descartado.**

**Guarda (b) — exclusión por zona, reutilizando una columna que ya existe.**

[VERIFIED: `backend/storage/models.py:168`] El modelo v2 `Zone` ya tiene
`kind = Column(String(30), nullable=True)`. [VERIFIED:
`backend/storage/repositories.py:471-489,502-506`] `ZoneRepo.upsert` acepta
`kind` y `_to_dict` lo devuelve. [VERIFIED: `backend/storage/migrations.py:103-108`]
`_add_missing_columns(conn, "zones", models.Zone)` garantiza que la columna
**existe físicamente** en la tabla `zones` de cualquier instalación, nueva o
migrada.

**Pero hay un cabo suelto que el planner debe atar** [VERIFIED:
`backend/database.py:37-44` y `backend/database.py:294-308`]: el CRUD de zonas que
realmente alimenta al pipeline es el **ORM legacy** de `backend/database.py`, cuyo
modelo `Zone` solo declara `id`, `name`, `polygon_json`, `enabled`, `created_at`
— **no declara `kind`**, aunque la columna esté en la tabla. `main.py:468` hace
`pipeline.set_zones(await get_zones())` con esa función legacy, y
`get_zones()` no devuelve `kind`.

→ El trabajo es de dos líneas, no una migración: añadir `kind = Column(String(30),
nullable=True)` al `Zone` legacy de `database.py` y `"kind": z.kind` al dict de
`get_zones()`. Después, `DetectionWorker._rebuild_zone_states`
(`detection.py:316-340`) ya recibe el `kind` en el dict `z` y solo tiene que
propagarlo al `_zone_states`, exactamente como ya propaga `id` y `name`. La
pertenencia se calcula gratis: `_zone_membership_snapshot()`
(`detection.py:229-238`) ya devuelve los ids por zona del frame, calculados con
`sv.PolygonZone.trigger()` — solo hay que hacer la misma foto para los tracks de
objeto.

**Convención recomendada:** `kind == "exclude_objects"`. Un objeto cuyo
`BOTTOM_CENTER` cae dentro de una zona con ese `kind` nunca es candidato a
`OBJECT_LEFT`. La zona es visible y editable con el panel de zonas que ya existe
(`index.html:670`), así que el operador puede marcar "la esquina del sofá" sin
tocar configuración.

**Estado total del `ObjectAnalyzer` (O(1) por track, patrón `_TrackAgg`):**

| Campo | Tipo | Para qué |
|---|---|---|
| `first_seen` | float | Guarda (a) contra el warmup |
| `ignored` | bool | Mobiliario fijo o dentro de zona de exclusión |
| `anchor_t`, `min_x/max_x/min_y/max_y` | 5 float | Inmovilidad (calco exacto de `_TrackAgg` de `behavior.py:62-73`) |
| `last_seen` | float | TTL + LRU de la cota dura |
| `last_x`, `last_y` | 2 float | Última posición conocida — la necesita `OBJECT_REMOVED` cuando el track ya no está |
| `last_person_near_t` | float \| None | Instante en que hubo una persona dentro del radio. **Es la clave de `OBJECT_REMOVED`** |
| `left_latched` | bool | Un `OBJECT_LEFT` por episodio |
| `stable` | bool | El objeto llegó a considerarse establecido (ya se puede "retirar") |

`OBJECT_REMOVED` se decide **en el `prune`**, no en el `analyze`: cuando un track
de objeto marcado `stable` lleva más de `object_gone_secs` sin verse, se emite si
`now - last_person_near_t <= object_person_window_secs`, y se descarta en silencio
si no (el objeto simplemente salió de escena o el detector lo perdió). El grace
period es obligatorio: sin él, una oclusión de un frame emitiría el evento.

Y hay un retardo estructural que el plan debe contabilizar
[VERIFIED: `smoother.py:112-121`]: `DetectionsSmoother.get_smoothed_detections`
sigue emitiendo un track hasta `length` frames después de que desaparezca de las
detecciones (mientras quede una entrada no-`None` en el deque). Si el tracker de
objetos usa smoother, la desaparición ya llega con ~0,6 s de retraso a 8 FPS.
**Recomendación: el `ObjectTracker` NO usa `DetectionsSmoother`** — el smoothing
existe para reducir jitter en el cruce de línea (`tracker.py:33-35`), un objeto
inmóvil no lo necesita, y quitarlo elimina de golpe el retardo de desaparición y
el problema de `class_id` pegajoso de H-2.

**Confianza: HIGH** para el mecanismo (todo verificado en código), **MEDIUM**
para `object_warmup_secs = 10.0` y `object_gone_secs` (magnitudes razonadas, sin
escena real).

### Q3 — Actualización en caliente de `classes=` → **mutar el atributo; NUNCA reiniciar el `DetectionWorker`**

**Lo primero: Ultralytics no necesita ningún truco.**
[VERIFIED: `.venv/Lib/site-packages/ultralytics/models/yolo/detect/predict.py:54-58`]
`classes` se pasa a `nms.non_max_suppression(preds, conf, iou, self.args.classes, ...)`
— es un filtro de **post-proceso por llamada**, no un parámetro de construcción
del modelo. Y `backend/detector.py:54` ya lee `self._classes` en cada inferencia.

[VERIFIED: ejecución en esta sesión]
```
classes=[0]          -> class_ids detectados: [0]
_classes = [0,5,24,28] (mutación en caliente)
classes=[0,5,24,28]  -> class_ids detectados: [0, 5]   modelo recargado? False
```
`id(detector._model)` no cambia. **Una asignación de atributo y la siguiente
inferencia ya usa las clases nuevas.** Sin recarga, sin coste, sin pérdida de
estado de tracking.

**Lo segundo, y más importante: reiniciar el worker vía el supervisor sería
activamente dañino.** El orquestador plantea esa opción; la evidencia la descarta.

[VERIFIED: `backend/pipeline/supervisor.py:75-79,124-132,144-181`]
`WorkerSupervisor` **no tiene ninguna API de reinicio bajo demanda**:
- `register()` lanza `ValueError` si el nombre ya existe;
- `_spawn()` es privado;
- `_check()` es el único camino de reinicio y **solo actúa sobre workers muertos**.

Es decir, la única forma de forzar un reinicio sería llamar a
`worker.stop()` y esperar a que `_check()` lo detecte. Pero `_check()` lo trata
como una **caída**: `entry.crashes.append(now)` (línea 164) y, con
`max_restarts=3` en una ventana de 60 s (líneas 166-173), **el tercer cambio de
clases en un minuto dejaría el `DetectionWorker` en `WorkerStatus.FAILED`
definitivamente**, con `pipeline.degraded == True` reportado por
`/api/v2/cameras/{id}/health` y sin más reintentos. Un usuario marcando y
desmarcando checkboxes en el dashboard mataría el pipeline.

Y aunque no lo marcara FAILED, un reinicio del `DetectionWorker` cuesta:
[VERIFIED: `manager.py:127-138`] `self.broker.subscribe("detector", replace=True)`
(se pierden frames), `AdaptiveRate` nuevo (se pierde la adaptación de ritmo), y
[VERIFIED: `detection.py:82-86`] `_zone_states`, `_heat_mask`, `_frames_processed`
y `_exceptions` se pierden — las zonas habría que volver a inyectarlas con
`set_zones()` desde `main.py`, cosa que hoy solo pasa en el arranque
(`main.py:468`).

→ **Recomendación prescriptiva: `PersonDetector.set_classes(list[int])`.**

```python
def set_classes(self, classes: list[int]) -> None:
    """Cambia las clases activas en caliente. Lo lee detect_sv en la siguiente
    inferencia (detector.py:54): Ultralytics aplica `classes` en el post-proceso
    de cada llamada, no en la construccion del modelo. Sin recarga de modelo, sin
    reiniciar el worker, sin perder el estado de ByteTrack."""
    self._classes = list(classes)          # rebind atomico: nunca mutar la lista in-place
```

**Seguridad entre hilos.** El escritor es el event loop (el endpoint PUT), el
lector es el hilo de detección. Un `STORE_ATTR` sobre `self.__dict__` es un
único bytecode y por tanto atómico bajo el GIL de CPython: el hilo lector ve la
lista vieja o la nueva, nunca una a medias. **La regla dura es no hacer
`self._classes.append(...)` ni `.clear()`** — eso sí sería una mutación
observable a medias. En el peor caso el detector usa las clases viejas durante un
frame (≤ 333 ms a 3 FPS). No hace falta lock; sí hace falta que el docstring lo
diga, siguiendo la convención de escritor único documentada de
`TrackRegistry` (`tracking.py:41-44`).

**Propagación completa del cambio (los cuatro sitios):**

1. `PersonDetector.set_classes()` — la inferencia.
2. **El reparto persona/objeto del `DetectionWorker`** — hay que decirle qué ids
   son "objeto" ahora, si no seguirá mandando las clases nuevas al tracker de
   personas. Un `DetectionWorker.set_object_classes(set[int])` bajo el
   `self._lock` que ya existe (mismo patrón que `set_zones`, `detection.py:119-123`).
3. **`ConfigRepo.set("yolo_classes", [...])`** — persistencia.
4. **Un `CONFIG_CHANGED`** — [VERIFIED: `types.py:45`] el tipo ya existe en el
   catálogo y nadie lo emite. Emitirlo aquí sale gratis (persistencia, WebSocket
   y métricas son genéricos por tipo) y da trazabilidad en el histórico de
   eventos de cuándo cambió la configuración de detección. Recomendado.

La fachada `CameraPipeline` es el sitio natural para orquestar (1) y (2) en un
solo método, igual que ya hace `set_zones` (`manager.py:282-284`) y
`set_process_size` (`manager.py:301-308`).

**Confianza: HIGH.** Todo verificado: el código de Ultralytics, el código del
supervisor y la mutación en caliente ejecutada.

### Q4 — Multi-clase en `TrackRegistry`/ByteTrack → **ByteTrack NO es class-aware: hay que separar por clase ANTES del tracker, y los objetos no entran en `TrackRegistry`**

La respuesta corta a la pregunta del CONTEXT ("¿basta `class_id` como metadato?")
es **no**, y la evidencia está en H-2: los ids migran entre clases cuando las
cajas se solapan (reproducido), y el smoother congela la clase hasta 5 frames
(reproducido).

**Recomendación: partición por clase antes del tracking (Opción A).**

```
sv_dets = detector.detect_sv(frame)                    # todas las clases activas
person_dets = sv_dets[np.isin(sv_dets.class_id, PERSON_IDS)]   # [0]
object_dets = sv_dets[np.isin(sv_dets.class_id, object_ids)]   # [1,2,3,24,28,...]

tracked, crossings = person_tracker.update(person_dets)   # ← IDENTICO A HOY
obj_tracked        = object_tracker.update(object_dets)   # ← sv.ByteTrack propio, sin smoother
```

Por qué esta y no la alternativa:

| Criterio | A: partición + 2 trackers | B: 1 tracker + `class_id` en `TrackState` |
|---|---|---|
| Confusión de identidad entre clases | Imposible por construcción | Real y reproducida (H-2) |
| Conteo de línea Fase 4 (producción) | Intacto: `LineZone` solo ve personas | Hay que filtrar dentro de `PersonTracker.update` |
| `RecognitionWorker` (cara + ReID) | Intacto: el registry sigue siendo de personas | Hay que gatear 4 puntos (`recognition.py:297,314,330,367`) |
| `EventEngine.process_tracks` / `accumulate_detections` | Intacto | Hay que gatear ambos, o `PERSON_ENTERED` por cada coche y `detection_stats` contaminado (= baseline de BEH-09 corrupto) |
| `BehaviorAnalyzer` (Fase 26) | Intacto: recibe solo personas | Hay que filtrar la entrada, o `CROWD_DETECTED` con 5 coches |
| `_metrics.active_tracks` | Intacto | Contaría objetos |
| Ficheros tocados en código de producción | `detection.py`, + 1 clase nueva | `tracking.py`, `tracker.py`, `recognition.py`, `engine.py`, `detection.py`, `manager.py` |
| Colisión de espacios de id | Sí (ambos empiezan en 1) — se resuelve manteniendo los objetos fuera del registry | No |

Opción A es además la **norma del ecosistema** para trackers de tipo SORT/ByteTrack:
la implementación de referencia asocia por IoU sin clase, y el patrón habitual es
"un tracker por grupo de clases". [ASSUMED — conocimiento general del ecosistema;
lo verificado aquí es el comportamiento concreto de supervision 0.27.0.post2]

**Corolario duro: los tracks de objeto NO entran en `TrackRegistry`.**
`TrackRegistry` está documentado como estado de personas
(`tracking.py:37-45`: `person_id`, `person_name`, `identity_state`, escritor único
por campo) y sus tres lectores (`StreamingWorker`, `RecognitionWorker`,
`RecordingWorker`) asumen personas. Meter objetos ahí obligaría a auditar los tres
y resolver la colisión de `track_id`. El estado de objeto vive en el
`ObjectAnalyzer`, y la posición legible desde fuera vive en un dict del
`DetectionWorker` bajo `self._lock`, exactamente igual que `_zone_states`
(`detection.py:84`) con su `get_zone_stats()` (`detection.py:125-130`).

**Consecuencia de UX que el planner debe decidir explícitamente**
[VERIFIED: `backend/pipeline/streaming.py:132-150`]: `StreamingWorker._annotate`
dibuja desde `self._registry.snapshot()`. Si los objetos no están en el registry,
**no se dibujan en el MJPEG**. Un usuario que active "coche" y no vea ninguna caja
pensará que no funciona. Dos salidas:
- (i) pasar al `StreamingWorker` una referencia de solo-lectura a
  `DetectionWorker.get_object_boxes()` y dibujarlos con un color distinto (~15
  líneas, y da evidencia visual directa del criterio 1);
- (ii) diferir el overlay a la Fase 28 y demostrar el criterio 1 con el endpoint
  y los eventos.
Recomiendo (i) — el criterio 1 dice "configurables desde la UI" y una UI que no
muestra el efecto de la configuración es difícil de verificar en el checkpoint
manual. Marcado como `## Open Questions` #1.

**Confianza: HIGH.** El comportamiento de ByteTrack y del smoother está medido, no
supuesto.

### Q5 — Campos exactos de `/api/v2/analytics/context` (BEH-08) → **6 bloques, todos derivables de estado ya existente**

Criterio 4 del ROADMAP: "hora, zona, personas totales, conocidas, desconocidas y
nivel de actividad". Traducción a un contrato concreto, con la fuente verificada
de cada campo:

| Campo | Fuente verificada | Nota |
|---|---|---|
| `timestamp` | `datetime.datetime.now().isoformat()` | Igual que el resto de la API |
| `hour` | `now.hour` (0-23) | La franja horaria contra la que se compara el baseline |
| `camera_id` | parámetro/`"cam1"` | — |
| `persons.total` | `len(registry.frame_ids())` | **`frame_ids()`, no `active_ids()`**: `active_ids()` arrastra hasta 30 s de TTL (`tracking.py:130`) y `frame_ids()` es exacto e inmediato — el propio repo lo documenta (`tracking.py:100-108`, `recognition.py:309`) |
| `persons.known` | tracks visibles con `identity_state is IdentityState.CONFIRMED` | Ver abajo |
| `persons.unknown` | `total - known` | — |
| `persons.pending` | tracks en `CANDIDATE`/`TEMPORARILY_LOST` | Opcional pero honesto: sin él, un track en votación se cuenta como "desconocido" cuando en realidad todavía no se sabe |
| `zones[]` | `pipeline.get_zone_stats()` | Ya devuelve `[{id, name, current, entries}]` (`detection.py:125-130`, `manager.py:286-287`) |
| `objects[]` | `DetectionWorker.get_object_stats()` (nuevo) | Recuento por `class_name` de los tracks de objeto del frame |
| `activity.level` | clasificación (ver Q7) | `"low" \| "normal" \| "high" \| "unknown"` |
| `activity.current` / `activity.baseline` / `activity.ratio` | Q7 | Magnitudes que justifican el nivel — mismo principio que BEH-05 |
| `activity.sample_days` | Q7 | Cuántos días hay realmente en la ventana; `< 3` ⇒ `level = "unknown"` |

**Cómo salen "conocidas/desconocidas" sin duplicar lógica de la Fase 24.**
[VERIFIED: `backend/pipeline/tracking.py:34`] `TrackState.identity_state:
IdentityState = IdentityState.UNKNOWN` ya es un campo del registry.
[VERIFIED: `backend/perception/face/identity.py:22-26`] los cuatro valores son
`UNKNOWN`, `CANDIDATE`, `CONFIRMED`, `TEMPORARILY_LOST`.
[VERIFIED: `tracking.py:117-128`] `set_identity` y `set_identity_state` los
escribe `RecognitionWorker`, escritor único.

→ El endpoint **no toca la `IdentityStateMachine`**. Hace un
`registry.snapshot()`, se queda con los `track_id` que están en `frame_ids()`, y
cuenta por `identity_state`. Cero lógica duplicada, cero acoplamiento con la FSM.
Es una función de ~10 líneas:

```python
visible = registry.frame_ids()
states = [ts for ts in registry.snapshot().values() if ts.track_id in visible]
known   = sum(1 for ts in states if ts.identity_state is IdentityState.CONFIRMED)
pending = sum(1 for ts in states if ts.identity_state in
              (IdentityState.CANDIDATE, IdentityState.TEMPORARILY_LOST))
```

Este es exactamente el filtro que `RecognitionWorker._sync_identity`
(`recognition.py:295-297`) ya usa, así que es el idioma del repo.

**Definición de "conocida": `identity_state is CONFIRMED`, no `person_id is not
None`.** [VERIFIED: `tracking.py:117-122`] `set_identity` escribe `person_id`
en cuanto hay un match, incluso antes de que la votación temporal confirme. Usar
`person_id` contaría como "conocida" a alguien todavía en `CANDIDATE`,
contradiciendo la semántica de FACE-08. `CONFIRMED` es el criterio correcto.

**Cómo se inyecta la referencia viva al pipeline.** Copiar `metrics.py`: un
`def configure(camera_manager)` en `backend/api/v2/context.py` con un global de
módulo, llamado una vez desde el `lifespan` (`main.py`, junto a
`metrics_v2.configure(...)`). No usar un import del global `rtsp_stream` de
`main.py` — crearía un ciclo de imports.

**Confianza: HIGH.**

### Q6 — Persistencia de la config de clases en `AppConfig` → **la tabla y el repo existen, y no tienen ni un solo usuario hoy**

[VERIFIED: `backend/storage/models.py:196-201`]
```python
class AppConfig(Base):
    __tablename__ = "app_config"
    key        = Column(String(100), primary_key=True)
    value      = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.now)
```
Clave-valor con `value` de tipo `JSON` → una `list[int]` cabe directamente, sin
serializar a mano.

[VERIFIED: `backend/storage/repositories.py:551-574`] `ConfigRepo` ya tiene
`get(key, default)`, `set(key, value)` (upsert con `updated_at`) y `get_all()`.

[VERIFIED: `grep -rn "AppConfig" --include=*.py`] Las **únicas** referencias en
todo el repo son la definición del modelo y los cuatro usos dentro del propio
`ConfigRepo`. **Ninguna fase ha guardado nada en `app_config` todavía.** Esta es
la primera. No hay convención previa que seguir, así que el plan la establece.

**Convención recomendada:** una clave por parámetro, con el **mismo nombre que el
campo de `Settings`** → `key = "yolo_classes"`, `value = [0, 24, 28]`. Un solo
JSON gordo (`key="detection"`) sería más difícil de migrar y obligaría a
merges parciales.

**Orden de precedencia en el arranque, y por qué importa.** Hoy
`main.py:281-287` construye el detector con `settings.yolo_classes` y punto. Con
persistencia hay tres fuentes: default de `config.py` → env var `YOLO_CLASSES` →
fila de `app_config`. La regla que recomiendo, y que hay que documentar en el
docstring del endpoint:

> **La BD gana**, porque es lo último que el operador tocó desde la UI. La env
> var sigue siendo el valor inicial de una instalación limpia (no hay fila).

El riesgo de la regla contraria es concreto: un operador cambia las clases desde
el dashboard, reinicia el servicio, y el sistema vuelve silenciosamente a
`YOLO_CLASSES` del `.env` — el clásico "he configurado algo y no se ha guardado".

Como `init_db()` (línea 238) ya corrió antes de la línea 281, basta:
```python
persisted = await ConfigRepo(get_session_factory()).get("yolo_classes")
active_classes = persisted if persisted else settings.yolo_classes   # `or` cubre None y []
```
`if persisted` (no `is not None`) es deliberado: una fila con `[]` guardada por
error dejaría el sistema ciego (Medición 3 de H-1); tratarla como ausente es más
seguro que obedecerla.

**Validación obligatoria en el PUT:** ids enteros, `0 <= id <= 79`, lista no
vacía, sin duplicados, y — recomendado — exigir que `0` (persona) esté siempre
presente. Quitar la clase persona rompería el conteo de la Fase 4, el
reconocimiento facial, el ReID y los cuatro eventos de comportamiento de la Fase
26 de golpe. Es una decisión de producto: marcada como `## Open Questions` #2.

**Confianza: HIGH.**

### Q7 — Query concreta de D-02 (media móvil de 7 días) → **una query, índice existente, 11,2 ms medidos a 525.600 filas; sin índice nuevo**

**La query (SQLAlchemy 2, en `DetectionStatRepo`):**

```python
async def hourly_baseline(
    self, camera_id: str, since: datetime.datetime
) -> dict[str, dict[str, float]]:
    """Media movil por franja horaria sobre los ultimos N dias (BEH-09, D-02).

    Dos niveles de agregacion, y el orden importa: primero se SUMA por (dia, hora)
    y solo despues se PROMEDIA entre dias. Promediar directamente sobre las filas
    de minuto daria "media por minuto", no "media por hora", y ademas ponderaria
    mas los dias con mas minutos registrados.

    Se agrupa sobre `unique_tracks`, no sobre `detections`: `detections` acumula
    len(active_track_ids) UNA VEZ POR FRAME PROCESADO (engine.py:281), asi que
    depende del FPS efectivo que AdaptiveRate haya elegido y no es comparable
    entre dias con distinta carga de CPU.

    strftime() es especifico de SQLite; ya hay precedente en
    EventRepo.hourly_counts (repositories.py:162). El proyecto es SQLite-only.
    """
    per_day = (
        select(
            func.strftime("%Y-%m-%d", models.DetectionStat.minute).label("day"),
            func.strftime("%H", models.DetectionStat.minute).label("hour"),
            func.sum(models.DetectionStat.unique_tracks).label("total"),
            func.count().label("mins"),
        )
        .where(
            models.DetectionStat.camera_id == camera_id,
            models.DetectionStat.minute >= since,
        )
        .group_by(text("day"), text("hour"))
        .subquery()
    )
    stmt = (
        select(
            per_day.c.hour,
            func.avg(per_day.c.total).label("avg_total"),
            func.count().label("sample_days"),
            func.sum(per_day.c.mins).label("mins"),
        )
        .group_by(per_day.c.hour)
        .order_by(per_day.c.hour)
    )
    async with self._sf() as session:
        result = await session.execute(stmt)
        return {
            row.hour: {
                "avg_total": float(row.avg_total),
                "sample_days": int(row.sample_days),
                "avg_per_minute": float(row.avg_total) / max(1, row.mins / row.sample_days),
            }
            for row in result.all()
        }
```

**¿Hace falta un índice nuevo? No.** [VERIFIED: `EXPLAIN QUERY PLAN` sobre el
esquema real reproducido en SQLite]:
```
CO-ROUTINE (subquery-1)
SEARCH detection_stats USING INDEX uq_detection_stats_camera_minute (camera_id=? AND minute>?)
USE TEMP B-TREE FOR GROUP BY
SCAN (subquery-1)
USE TEMP B-TREE FOR GROUP BY
```
El `WHERE camera_id = ? AND minute >= ?` se resuelve con un **range scan** sobre
el índice único `(camera_id, minute)` que `models.py:127` ya declara (el
`idx_detstats_minute` de la línea 126 serviría igual). El coste es proporcional a
la **ventana**, no a la tabla. Los `strftime` se evalúan solo sobre las filas ya
filtradas, así que un índice funcional no aportaría nada.

**Medición [VERIFIED: esta sesión, SQLite 3 de Python 3.12.10, 30 muestras con 3
de warmup, esquema e índices copiados literalmente de `models.py`]:**

| Filas en `detection_stats` | Equivalente | p50 | max |
|---|---|---|---|
| 43.200 | 30 días | 11,39 ms | 12,08 ms |
| 525.600 | 1 año (80 MB) | **11,22 ms** | 11,70 ms |

El tiempo **no crece con la tabla**: el índice hace su trabajo. 11 ms para un
endpoint bajo demanda, en un sistema de una cámara, es coste despreciable — y
`aiosqlite` lo ejecuta en su thread pool, así que no bloquea el event loop
(invariante de CLAUDE.md "no ejecutar CPU pesado en el event loop").

**Optimización disponible si alguna vez hace falta:** filtrar también por la hora
concreta (`AND strftime('%H', minute) = :hour`) reduce el trabajo del GROUP BY,
pero devolver las 24 franjas de una vez permite que el frontend pinte la curva
del día completo con la misma llamada. **Recomiendo devolver las 24** — es más
útil y cuesta lo mismo.

**Cálculo del nivel de actividad, y el sesgo que hay que evitar.**
El "ahora" y el "baseline" deben ser la **misma magnitud**. El baseline es
"personas distintas en toda la hora H"; a las 10:05 solo han pasado 5 minutos de
la hora en curso, así que comparar directamente daría siempre "actividad baja" al
principio de cada hora. Hay que **normalizar a tasa por minuto**:

```
baseline_rate = avg_total / minutos_medios_por_dia_en_esa_hora     # ≈ avg_total / 60
current_rate  = personas_distintas_en_la_hora_en_curso / minutos_transcurridos
ratio         = current_rate / baseline_rate
```

Umbrales propuestos (política de producto, no dominio): `ratio < 0.5` → `"low"`;
`0.5 ≤ ratio ≤ 1.5` → `"normal"`; `> 1.5` → `"high"`. Y `"unknown"` cuando
`sample_days < 3`, `baseline_rate == 0` o `minutos_transcurridos < 5` (los
primeros minutos de una hora son ruido puro). Devolver siempre `ratio`,
`current`, `baseline` y `sample_days` para que el nivel sea auditable — mismo
principio que BEH-05 ("cada evento incluye las magnitudes que lo justifican").

**Fuente del "ahora":** el minuto en curso nunca está en `detection_stats`
(retardo de hasta ~90 s, H-5 dato 3). Recomendado: leer de la BD los minutos ya
volcados de la hora en curso y sumar el estado vivo del registry para el minuto
actual, **o** — más simple y honesto — usar solo la BD y documentar el retardo.
Recomiendo lo segundo: mezclar dos fuentes con semánticas distintas
(`unique_tracks` acumulado vs `frame_ids` instantáneo) es una fuente de bugs
sutiles, y 90 s de retardo en un indicador de "nivel de actividad de la franja
horaria" es irrelevante. El "ahora" instantáneo ya lo da `persons.total`.

**Confianza: HIGH** para la query y su coste (medidos). **LOW** para los umbrales
0,5/1,5 — son una propuesta sin datos históricos reales que la respalden.
Marcado en `## Assumptions Log`.

### Q8 — Metodología del benchmark del criterio 6 → **ya existe en el repo, y la fase ya está cumplida con margen**

**El precedente a reutilizar** [VERIFIED: `tests/test_reid_engine.py:54-70`,
`TEST_reid_latency_under_20ms`]: 5 iteraciones de warmup + 30 muestras +
`statistics.median` sobre `time.perf_counter()`, con un `assert` sobre el **p50**
y no sobre el máximo, y el motivo escrito en el docstring ("el p95 sube a ~30 ms
por jitter del planificador de Windows en esta máquina compartida, un assert
sobre una sola llamada sería flaky"). `25-06-SUMMARY.md:85-89` registra la cifra
exacta además del veredicto. **Ese es el molde exacto para el criterio 6.**

No hay ningún script de benchmark en `scripts/` (solo `soak_test.py`, que
muestrea `/api/v2/metrics` de un sistema en marcha). El repo también tiene la vía
de producción: [VERIFIED: `detection.py:175`]
`_metrics.inference_latency_seconds.labels(stage="yolo").observe(inference_latency)`
alimenta el histograma de Prometheus, así que el checkpoint manual con cámara real
puede leer el p50 de `stage="yolo"` antes y después de activar las 6 clases sin
instrumentar nada.

**Medición ya hecha en esta sesión** [VERIFIED: `yolo26n.pt` (`end2end=True`),
`bus.jpg` reescalado a 1280×720 = `process_width` × `process_height` reales,
`imgsz=640`, `conf=0.45`, vía `PersonDetector.detect_sv`, 5 warmup + 30 muestras,
mediana; Python 3.12.10, ultralytics 8.4.38]:

| Clases activas | p50 | Δ vs 1 clase | Criterio 6 (< +15 %) |
|---|---|---|---|
| `[0]` (persona) | 38,90 ms | — | — |
| `[0,1,2,3,24,28]` (las 6 del ROADMAP) | 40,74 ms | **+4,7 %** | ✅ con margen 3x |
| `None` (las 80 de COCO) | 39,98 ms | +2,8 % | ✅ |

Control sobre frame de ruido aleatorio (0 detecciones, aísla el forward pass):
39,54 ms vs 39,49 ms → **−0,1 %**. Y sobre `yolov8n.pt` (`end2end=False`, con
NMS clásica): 33,61 vs 32,53 ms → −3,2 %.

**Interpretación:** el +4,7 % es ruido de medición, no señal — el signo se invierte
según el frame y el modelo. Es coherente con la evidencia estructural: `classes=`
se aplica en `non_max_suppression` (`predict.py:54-58`), después del forward pass,
que es el 95 % del coste; y `yolo26n` es NMS-free, así que ni siquiera hay NMS que
escalar. **El criterio 6 se cumple por construcción.**

**Advertencia importante para el planner: el criterio 6 mide lo que no duele.**
El coste real de multi-clase no está en la inferencia sino aguas abajo: más
detecciones → más trabajo de ByteTrack (asignación húngara, O(n·m)), más entradas
en el smoother, más `TrackState`, más filas de evento. Con 6 clases en una calle
puede haber 20 detecciones por frame donde había 2. **El test automatizable del
criterio 6 debe medir `detect_sv`** (es lo que dice el criterio), pero el
checkpoint manual con cámara real debe mirar `detection_fps` y `dropped` en
`/api/v2/cameras/{id}/health`, no solo la latencia de YOLO. Ver Pitfall 6.

**Confianza: HIGH** (medido tres veces con tres frames distintos y dos modelos).

---

## Discrepancias con SPEC (reality-check)

Por cuarta fase consecutiva, `SPEC_v2.md` §9 se queda corto en la lista de
ficheros. **El planner debe seguir la columna "Realidad".**

### D-1 — Lista de ficheros de SPEC §9 Phase 27 (`SPEC_v2.md:910-915`)

| SPEC dice | Realidad | Evidencia |
|---|---|---|
| Crear `backend/perception/objects.py` | ✅ Correcto | Patrón `behavior.py` (H-6) |
| Crear `backend/api/v2/context.py` | ✅ Correcto | Patrón `recordings.py`/`metrics.py` (H-4) |
| Modificar `backend/detector.py` | ✅ Correcto — pero solo para `set_classes()` | El filtrado ya funciona (H-1); no hay que tocar `detect_sv` |
| Modificar `backend/perception/behavior.py` | ❌ **No hace falta tocarlo** | Con la partición por clase (Q4), `BehaviorAnalyzer` sigue recibiendo solo personas. Tocarlo solo introduciría riesgo en código de la fase anterior recién cerrada |
| — (omitido) | ✅ **`backend/pipeline/detection.py`** | Partición por clase, tracker de objetos, `_analyze_objects`, `get_object_stats`, `set_object_classes` — el fichero con más trabajo de la fase |
| — (omitido) | ✅ **`backend/tracker.py` o clase nueva** | `ObjectTracker` con su propio `sv.ByteTrack`, sin `LineZone` y **sin `DetectionsSmoother`** (Q2) |
| — (omitido) | ✅ **`backend/events/engine.py`** | `emit_object()`, calco de `emit_behavior` |
| — (omitido) | ✅ **`backend/config.py`** | D-03 + bloque de parámetros de objeto + validador de rango |
| — (omitido) | ✅ **`backend/pipeline/manager.py`** | `ObjectAnalyzer` FUERA de la factoría + propagación + fachada `set_classes` |
| — (omitido) | ✅ **`backend/main.py`** | Lectura de `AppConfig`, propagación, `include_router`, `context.configure(...)` |
| — (omitido) | ✅ **`backend/database.py`** | 2 líneas: `kind` en el `Zone` legacy y en `get_zones()` (Q2) |
| — (omitido) | ✅ **`backend/storage/repositories.py`** | `DetectionStatRepo.hourly_baseline()` (Q7) |
| — (omitido) | ✅ **`frontend/index.html`** | Panel de clases + panel de contexto (criterio 1) |
| Tests: `tests/test_object_events.py`, `tests/test_scene_context.py` | ⚠️ Nombre e inventario incompletos | Ver `## Validation Architecture` |

### D-2 — Nombre del fichero de test de dominio

SPEC dice `tests/test_object_events.py`. La convención establecida en las Fases
24/25/26 es que el test del dominio puro se llama como la clase que prueba:
`test_identity_state_machine.py`, `test_track_gallery.py`,
`test_behavior_analyzer.py`. → **`tests/test_object_analyzer.py`**. Cosmético,
pero el planner debe elegir a conciencia y no arrastrar el nombre de SPEC por
inercia.

### D-3 — SPEC no menciona el problema de ByteTrack

`SPEC_v2.md:917` solo identifica un riesgo para esta fase ("falsos `OBJECT_LEFT`
con mobiliario fijo"). **El riesgo mayor no está en SPEC**: activar clases nuevas
sobre el tracker actual rompe el conteo de línea de la Fase 4 y mete objetos en el
pipeline de reconocimiento facial (Q4/H-2). El plan debe tratarlo como riesgo de
primer orden y protegerlo con un test de regresión.

### D-4 — SPEC no fija ninguna distancia ni la lista de clases

Las 6 clases del criterio 1 del ROADMAP mapeadas a ids COCO
[VERIFIED: `YOLO('yolo26n.pt').names`]:

| Clase | id COCO |
|---|---|
| person | 0 |
| bicycle | 1 |
| car | 2 |
| motorcycle | 3 |
| backpack | 24 |
| suitcase | 28 |

(`handbag` es 26, por si el planner quiere una séptima; el ROADMAP dice "maleta"
→ 28.) El modelo expone 80 clases, así que la UI puede ofrecer las 80 o solo estas
6 — recomiendo **una lista blanca de las 6 en el frontend** y validación de rango
`0..79` en el backend: ofrecer las 80 invita a activar "tostadora" y degradar el
pipeline sin ganancia.

---

## Standard Stack

**Cero dependencias nuevas.** [VERIFIED: `requirements.txt` no necesita cambios]

### Core (ya en el proyecto)

| Módulo | Versión verificada | Uso en esta fase |
|---|---|---|
| `supervision` | 0.27.0.post2 | `sv.ByteTrack` (segunda instancia para objetos), slicing de `Detections` por `class_id`, `sv.Position.BOTTOM_CENTER`, `sv.PolygonZone` |
| `ultralytics` | 8.4.38 | `classes=` por llamada (post-proceso); `model.names` como fuente de nombres de clase |
| `numpy` | ya en uso | `np.isin(class_id, ids)` para la partición — una línea, vectorizado |
| `math` (stdlib) | — | `hypot` para la distancia persona↔objeto |
| `dataclasses` (stdlib) | — | `ObjectFinding`, `_ObjAgg` (patrón `behavior.py`) |
| SQLAlchemy 2 + aiosqlite | ya en uso | `hourly_baseline()`; `func.strftime`, `.subquery()` |
| `pydantic-settings` | ya en uso | Parámetros nuevos + `@model_validator` de rango |
| FastAPI + slowapi | ya en uso | `APIRouter` + `limiter` de `api/v2/deps.py` |

**No usar `numpy` dentro de `perception/objects.py`.** Igual que en
`behavior.py`: con estado O(1) por track, `math.hypot` sobre floats de Python es
más rápido que crear arrays de 2 elementos, y mantiene el dominio puro sin
dependencias pesadas.

### Alternatives Considered

| En vez de | Se podría usar | Por qué no |
|---|---|---|
| Partición por clase + 2 trackers | 1 tracker con `class_id` en `TrackState` | Ids que migran entre clases (reproducido), regresión del `LineZone` de la Fase 4, reconocimiento facial sobre mochilas, 6 ficheros de producción tocados en vez de 1 (Q4) |
| Mutar `_classes` en caliente | Reinicio del `DetectionWorker` vía supervisor | `_check()` lo cuenta como caída; 3 cambios en 60 s ⇒ `FAILED` + modo degradado permanente (`supervisor.py:166-173`) (Q3) |
| Mutar `_classes` en caliente | Reconstruir `YOLO(model_path)` | Innecesario: `classes` es post-proceso por llamada (verificado). Recargar cuesta segundos y tira el estado |
| Warmup + zona de exclusión | Tabla persistente de "mobiliario conocido" | Los `track_id` no sobreviven al reinicio ⇒ haría falta ReID de objetos o matching geométrico. Una fase entera para un caso que una zona dibujada ya cubre (Q2) |
| `unique_tracks` como baseline | `detections` | `detections` es *frames × tracks* y depende del FPS que `AdaptiveRate` elija ⇒ no comparable entre días (H-5) |
| Query sobre `DetectionStat` | Tabla nueva de agregados horarios | D-02 lo prohíbe, y la medición lo hace innecesario: 11,2 ms a 525.600 filas con los índices actuales (Q7) |
| `frame_ids()` para "personas ahora" | `active_ids()` / `get_live_count()` | `active_ids()` arrastra el TTL de 30 s de `prune()` (`tracking.py:130`); el repo ya documenta la diferencia (Q5) |
| `identity_state is CONFIRMED` | `person_id is not None` | `set_identity` escribe `person_id` antes de que la votación confirme ⇒ contaría CANDIDATE como conocida (Q5) |
| `ObjectTracker` sin smoother | Reutilizar `DetectionsSmoother` | El smoother congela `class_id` hasta 5 frames y retrasa la desaparición ~0,6 s (medido) — justo las dos cosas que BEH-07 necesita frescas (Q2) |

**Installation:** ninguna.

---

## Architecture Patterns

### System Architecture Diagram

```text
RTSP ─► CaptureWorker ─► FrameBroker (latest-frame)
                              │
                              └─► DetectionWorker._loop            [hilo, sin await]
                                     │
                                     ├─(1) detector.detect_sv(frame)
                                     │        classes=self._classes  ◄── MUTABLE EN CALIENTE
                                     │        └─► sv.Detections{xyxy, conf, class_id, data.class_name}
                                     │
                                     ├─(2) PARTICION POR CLASE            ★ NUEVO, y el punto clave
                                     │        person_dets = dets[class_id ∈ {0}]
                                     │        object_dets = dets[class_id ∈ object_ids]
                                     │        (ByteTrack DESCARTA class_id: core.py:104-110)
                                     │
                    ┌────────────────┴────────────────────────┐
                    ▼ PERSONAS (sin cambios)                  ▼ OBJETOS (nuevo)
        PersonTracker.update(person_dets)          ObjectTracker.update(object_dets)
          ├─ sv.ByteTrack                            └─ sv.ByteTrack propio
          ├─ DetectionsSmoother                         (SIN smoother: class_id fresco,
          └─ LineZone ─► crossings (Fase 4)              desaparicion sin retardo)
                    │                                            │
                    ├─(3) rate.observe(latencia)  ◄── mide SOLO (1)+(tracking de personas)
                    ├─(4) registry.update_from_detections   [SOLO personas]
                    ├─(5) _update_zones_and_heat ─► EventEngine.process_zone
                    │        └─ st["inside"] por zona  ─────────┐
                    ├─(6) BehaviorAnalyzer.analyze  [SOLO personas, Fase 26, intacto]
                    │                                            │
                    ├─(7) ObjectAnalyzer.analyze(...)   ★ NUEVO  │
                    │        entrada: obj_centroids(BOTTOM_CENTER), obj_classes,
                    │                 person_anchors(BOTTOM_CENTER), person_heights,
                    │                 excluded_zone_members ◄────┘ (zones.kind=="exclude_objects")
                    │                 now (monotonico)
                    │        estado:  dict[obj_track_id → _ObjAgg O(1)] + warmup + latch
                    │        salida:  list[ObjectFinding]   (NUNCA Event)
                    │        └─► EventEngine.emit_object()  ─► OBJECT_LEFT (WARNING)
                    │                                          OBJECT_REMOVED (INFO)
                    ├─(8) _emit_crossings / _emit_track_lifecycle  [sin cambios]
                    └─(9) registry.prune + behavior.prune + objects.prune
                                                                  │
                                                                  ▼
                                                            EventBus (thread→loop)
                    ┌─────────────────────────────────────────────┤
                    ▼            ▼              ▼                 ▼
             _persist_event  _broadcast_v2  _apply_rules   metrics.events_total
             (SQLite, JSON)   (WebSocket)   (RuleEngine)   (Prometheus, gratis)
                    │
                    └─► OBJECT_LEFT es WARNING ⇒ cruza upload_min_severity ⇒ SUBE CLIP A DRIVE

Camino de configuracion (event loop, nunca el hilo de deteccion):
  PUT /api/v2/detection/classes
       ├─► validar (0..79, no vacia, incluye 0)
       ├─► ConfigRepo.set("yolo_classes", [...])        [app_config, tabla existente]
       ├─► pipeline.set_detection_classes([...])
       │        ├─► detector.set_classes([...])         [rebind atomico de atributo]
       │        └─► detection.set_object_classes({...}) [bajo self._lock, patron set_zones]
       └─► EventEngine ─► CONFIG_CHANGED                [tipo ya en el catalogo]

Camino de lectura (event loop):
  GET /api/v2/analytics/context
       ├─► registry.frame_ids() + snapshot()  ─► total / known / unknown / pending
       ├─► pipeline.get_zone_stats()          ─► zonas
       ├─► detection.get_object_stats()       ─► objetos por clase
       └─► DetectionStatRepo.hourly_baseline(cam, now-7d)   [11,2 ms medidos, aiosqlite→thread pool]
                └─► ratio = current_rate / baseline_rate ─► level

Construccion (no en el camino caliente):
  CameraPipeline.__init__
    ├─ self.identity_fsm  = IdentityStateMachine(...)   ← FUERA de la factoria (Fase 24)
    ├─ self.reid_gallery  = TrackGallery(...)           ← FUERA de la factoria (Fase 25)
    ├─ self.behavior      = BehaviorAnalyzer(...)       ← FUERA de la factoria (Fase 26)
    ├─ self.objects       = ObjectAnalyzer(...)         ← FUERA de la factoria (Fase 27) ★
    └─ self.object_tracker= ObjectTracker(...)          ← FUERA de la factoria (Fase 27) ★
                              │                            (si se reconstruyera, los ids de
        _make_detection() ────┘                             objeto se reiniciarian y todo el
                                                            mobiliario volveria a "aparecer")
```

### Recommended Project Structure

```text
backend/
  perception/
    objects.py             # NUEVO — ObjectFinding + ObjectAnalyzer (dominio puro)
    behavior.py            # referencia de patrón — NO SE TOCA
  api/v2/
    context.py             # NUEVO — /api/v2/analytics/context + configure(camera_manager)
    detection.py           # NUEVO (o dentro de context.py) — GET/PUT clases activas
    recordings.py          # referencia de patrón de router
    deps.py                # limiter, V2_RATE_LIMIT
  detector.py              # + set_classes()
  tracker.py               # + ObjectTracker (o fichero propio); PersonTracker INTACTO
  events/engine.py         # + emit_object()
  pipeline/
    detection.py           # + partición por clase, _analyze_objects, get_object_stats, set_object_classes
    manager.py             # + construcción fuera de la factoría, + fachada set_detection_classes
  storage/repositories.py  # + DetectionStatRepo.hourly_baseline()
  database.py              # + `kind` en el Zone legacy y en get_zones()
  config.py                # D-03 + bloque "Objetos y contexto (Fase 27)"
  main.py                  # + lectura de AppConfig, propagación, include_router, configure()
frontend/
  index.html               # + panel de clases (checkboxes) + panel de contexto
```

### Pattern 1 — Partición por clase antes del tracker (el patrón central de la fase)

**Qué:** separar `sv.Detections` por `class_id` en cuanto sale del detector, y no
volver a mezclarlas. Cada grupo tiene su propio tracker.

**Cuándo:** siempre que un tracker class-agnostic tenga que manejar más de una
clase semántica.

```python
# Fuente: verificado en esta sesion contra supervision 0.27.0.post2
import numpy as np

PERSON_CLASS_IDS = (0,)

sv_dets = self._detector.detect_sv(frame.image)
cls = sv_dets.class_id
if cls is None:                                  # Detections.empty() lo deja a [] o None
    person_dets, object_dets = sv_dets, sv_dets[:0]
else:
    person_dets = sv_dets[np.isin(cls, PERSON_CLASS_IDS)]
    object_dets = sv_dets[np.isin(cls, self._object_class_ids)]   # snapshot bajo lock

tracked, crossings = self._tracker.update(person_dets)     # exactamente el camino de hoy
obj_tracked        = self._object_tracker.update(object_dets)
```

El slicing preserva `data["class_name"]` (verificado), así que
`obj_tracked.data["class_name"][i]` da el nombre para el payload del evento sin
ningún mapa COCO a mano.

### Pattern 2 — Ancla de inmovilidad reutilizada tal cual (BEH-07)

**Qué:** el mismo agregado O(1) con caja envolvente que `behavior.py` usa para
`IMMOBILE`, aplicado a un objeto en vez de a una persona.

```python
# Fuente: backend/perception/behavior.py:175-190 (patron a copiar literalmente)
agg.min_x = min(agg.min_x, x); agg.max_x = max(agg.max_x, x)
agg.min_y = min(agg.min_y, y); agg.max_y = max(agg.max_y, y)
span = max(agg.max_x - agg.min_x, agg.max_y - agg.min_y)
if span > self._object_still_radius_px:
    agg.anchor_t = now                       # se movio: episodio nuevo
    agg.min_x = agg.max_x = x
    agg.min_y = agg.max_y = y
    agg.left_latched = False
```

`object_still_radius_px` debe ser el mismo `immobile_radius_px = 20` o algo
cercano: es la misma magnitud física (ruido de bbox de un objeto que no se mueve).
Recomiendo **reutilizar el valor 20 px** en vez de introducir un parámetro nuevo,
documentándolo.

### Pattern 3 — Marca de "última persona cerca" (el truco de `OBJECT_REMOVED`)

**Qué:** en vez de intentar mirar hacia atrás cuando el objeto desaparece
(imposible sin historia), se escribe hacia delante un solo float por objeto.

```python
# En cada frame, por objeto:
r = max(self._person_radius_px, self._person_radius_ratio * person_height)
if any(math.hypot(ox - px, oy - py) <= r for (px, py, person_height) in persons):
    agg.last_person_near_t = now

# En prune(), cuando el objeto lleva object_gone_secs sin verse:
if agg.stable and (agg.last_person_near_t is not None) and \
   (now - agg.last_person_near_t) <= self._person_window_secs:
    findings.append(ObjectFinding(kind=OBJECT_REMOVED, ...))
# si no: desaparicion silenciosa (salio de escena, oclusion, fin del turno)
```

Un `float | None` por objeto. O(1). Sin historia, sin deque, sin ventana móvil.

### Pattern 4 — Latch por episodio (idempotencia, criterio 5)

Criterio 5 del ROADMAP: "una mochila abandonada emite **un único** `OBJECT_LEFT`".
Es el mismo problema que la Fase 26 resolvió: sin latch, un objeto inmóvil 10
minutos emitiría ~4.800 eventos a 8 FPS. El patrón ya está escrito
(`behavior.py:186-190`): `if not agg.left_latched and dur > secs: agg.left_latched
= True; findings.append(...)`, con re-armado cuando el ancla se resetea.

`OBJECT_REMOVED` no necesita latch: se emite una sola vez, en el `prune`, justo
antes de borrar la entrada.

### Pattern 5 — Router v2 con referencia viva inyectada

```python
# Fuente: backend/api/v2/metrics.py:21-27 (patron a copiar)
router = APIRouter(prefix="/api/v2/analytics", tags=["analytics"])

_camera_manager: Any = None

def configure(camera_manager: Any) -> None:
    """Wire the live CameraManager. Called once from main.py's lifespan."""
    global _camera_manager
    _camera_manager = camera_manager

@router.get("/context")
@limiter.limit(V2_RATE_LIMIT)
async def scene_context(request: Request, camera_id: str = "cam1") -> dict:
    ...
```

Nunca importar el global `rtsp_stream` de `main.py` — `main.py` importa el router,
sería un ciclo.

### Anti-Patterns to Avoid

- **Meter objetos en `TrackRegistry`:** el registry es estado de personas y sus
  tres lectores lo asumen (Q4). Además los espacios de `track_id` de los dos
  ByteTrack colisionan.
- **Pasar el `sv.Detections` completo a `PersonTracker.update()`:** rompe el
  conteo de línea de la Fase 4, en producción.
- **Reiniciar el `DetectionWorker` para aplicar la nueva configuración:** el
  supervisor lo cuenta como caída (Q3).
- **`self._classes.clear()` / `.append()`:** mutación observable a medias por el
  hilo lector. Siempre rebind: `self._classes = list(nuevas)`.
- **Usar `DetectionsSmoother` en el tracker de objetos:** congela `class_id` y
  retrasa la desaparición (Q2).
- **Llamar a `self._rate.observe()` desde la vía de objetos:** contaminaría el
  control adaptativo. El repo ya tomó esta decisión dos veces (Fase 25 con ReID,
  Fase 26 con el analizador de comportamiento); `detection.py:174` mide solo la
  inferencia + el tracking de personas.
- **Contar `active_ids()` como "personas ahora":** arrastra 30 s de TTL (Q5).
- **Promediar directamente las filas de minuto para el baseline:** da media por
  minuto y pondera mal los días incompletos (Q7).
- **Comparar la hora en curso (parcial) contra un baseline de hora completa:**
  siempre daría "actividad baja" al principio de cada hora (Q7, Pitfall 7).

---

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por qué |
|---|---|---|---|
| Mapa id COCO → nombre de clase | Un `dict` de 80 entradas en el repo | `sv.Detections.data["class_name"]`, que ya viene de `from_ultralytics` (verificado) | Cambiar de modelo (yolo26n → un modelo custom) invalidaría el dict a mano y nadie lo notaría hasta ver etiquetas equivocadas |
| Tracking de objetos | Un matcher IoU propio | Una segunda instancia de `sv.ByteTrack` | Kalman + asociación en dos pasos + gestión de tracks perdidos ya resueltos y probados |
| Filtrado de clases en inferencia | Filtrar `sv.Detections` después de YOLO | `classes=` de Ultralytics (ya cableado) | Es post-proceso pero dentro de la NMS: filtrar después haría el mismo trabajo dos veces |
| Media móvil histórica | Una tabla de agregados + su job de mantenimiento | Una query con subconsulta sobre `DetectionStat` | 11,2 ms medidos a 525.600 filas; una tabla nueva añade migración, consistencia y purga por 0 ganancia (D-02) |
| Detección de "objeto que no se mueve" | Historial de posiciones del objeto | El ancla + caja envolvente de `behavior.py` (Patrón 2) | Ya escrito, ya testeado, O(1), inmune a los saltos de `AdaptiveRate` |
| Persistencia clave-valor de configuración | Un fichero JSON en `data/` | La tabla `app_config` + `ConfigRepo` (ambos existen y están sin usar) | Transaccional, respaldado por el backup de migraciones (`migrations.py:61-67`), sin gestión de concurrencia a mano |
| Pertenencia a zona de exclusión | Un test punto-en-polígono propio | `sv.PolygonZone.trigger()`, que `_update_zones_and_heat` ya ejecuta por frame | Recalcularlo duplicaría la inferencia geométrica y podría divergir del conteo de `get_zone_stats()` — el propio repo lo documenta (`detection.py:229-238`) |
| Rate limiting del endpoint nuevo | — | `limiter` + `V2_RATE_LIMIT` de `api/v2/deps.py` | Política única para toda la superficie v2 (SEC-16) |

**Key insight:** las cinco piezas que parecen "trabajo nuevo" de esta fase
(nombres de clase, tracking, inmovilidad, config persistente, zonas) ya existen en
el repo o en las librerías. El trabajo real es **de cableado y de decidir dónde
corta la partición por clase**, no de algoritmos.

---

## Runtime State Inventory

No aplica: esta fase no es un rename, refactor ni migración. No hay estado en
ejecución con el nombre viejo que reconciliar.

Sí hay dos elementos de estado que el plan debe tener en cuenta, y ambos son
**aditivos, no migratorios**:

| Categoría | Encontrado | Acción |
|---|---|---|
| Datos almacenados | Tabla `app_config`: **vacía, sin un solo usuario en todo el repo** (verificado) | Solo escritura nueva. Sin migración |
| Esquema | `zones.kind` existe físicamente (garantizado por `migrations.py:103-108`) pero el ORM legacy no lo declara | Cambio de código (2 líneas), no migración de datos |
| Config de servicio | `YOLO_CLASSES` en `.env` (no versionado) | Sigue siendo el valor inicial; la BD pasa a tener precedencia (Q6). Documentar el cambio de semántica |
| Artefactos | `yolov8n.pt` deja de ser el default (D-03) pero se queda en el repo | Ninguna. `yolo26n.pt` ya está descargado |

---

## Common Pitfalls

### Pitfall 1 — Mandar detecciones no-persona a `PersonTracker`
**Qué falla:** `LineZone.trigger` cuenta cruces de coches y bicicletas como
personas; el conteo de la Fase 4, que lleva meses en producción, empieza a mentir.
**Por qué pasa:** el cambio "activar clases" parece de una línea en `config.py`.
**Cómo evitarlo:** partir por clase antes de `tracker.update()` (Pattern 1).
**Señal temprana:** un test de regresión que meta un `sv.Detections` mixto en
`DetectionWorker` y afirme que `get_counts()["in"]` no cambia con el coche.

### Pitfall 2 — Confiar en el `class_id` que sale del tracker
**Qué falla:** un objeto se etiqueta como persona (o al revés) durante hasta 5
frames, y con un solapamiento fuerte el `track_id` se transfiere entre clases.
**Por qué pasa:** ByteTrack no ve la clase (`core.py:104-110`) y
`DetectionsSmoother.get_track` copia `class_id` del elemento **más viejo** del
deque (`smoother.py:104`). Ambos reproducidos en esta sesión.
**Cómo evitarlo:** la clase la decide el detector, en el frame, antes de tracking.
Después del tracker, `class_id` es solo decorativo.
**Señal temprana:** eventos `OBJECT_LEFT` con `track_id` que también aparece en un
`PERSON_ENTERED` reciente.

### Pitfall 3 — `classes=[]` ciega el sistema en silencio
**Qué falla:** el operador desmarca todas las casillas y el pipeline deja de
detectar absolutamente nada: sin excepciones, sin logs, `detection_fps` normal.
**Por qué pasa:** verificado — `_classes = []` devuelve 0 detecciones (no es
equivalente a `None`, que devuelve las 80).
**Cómo evitarlo:** 400 en el PUT si la lista está vacía; y `if persisted` (no
`is not None`) al leer de `AppConfig`, para que una fila `[]` guardada por un bug
no sobreviva al reinicio.
**Señal temprana:** `active_tracks` a 0 con la cámara sana.

### Pitfall 4 — Construir `ObjectAnalyzer` u `ObjectTracker` dentro de la factoría
**Qué falla:** en cada reinicio del `DetectionWorker`, los `track_id` de objeto se
reinician y la ventana de warmup vuelve a abrirse. Todo el mobiliario fijo
"aparece" de nuevo y a los 60 s se emite una ráfaga de `OBJECT_LEFT` — que además
son `WARNING`, así que **suben clips a Google Drive**.
**Por qué pasa:** `WorkerSupervisor` re-ejecuta la factoría en cada reinicio
(`manager.py:127-140`, `supervisor.py:124-132`).
**Cómo evitarlo:** construir en `CameraPipeline.__init__`, como ya se hace con la
FSM (Fase 24), la galería ReID (Fase 25) y el `BehaviorAnalyzer` (Fase 26).
**Señal temprana:** un test que reinicie el worker vía la factoría y afirme que
el `id()` del analizador y el contador de ids del tracker no cambian.

### Pitfall 5 — Forzar un reinicio del worker para aplicar la configuración
**Qué falla:** tres cambios de clases en 60 s dejan el `DetectionWorker` en
`FAILED` para siempre y el pipeline en modo degradado.
**Por qué pasa:** `_check()` no distingue "murió solo" de "lo paramos nosotros"
(`supervisor.py:153-181`).
**Cómo evitarlo:** `set_classes()` sobre la instancia viva (Q3).
**Señal temprana:** `worker_status()["detector"] == "failed"` tras trastear con la
UI.

### Pitfall 6 — Medir el criterio 6 solo en `detect_sv` y dar la fase por buena
**Qué falla:** la latencia de YOLO no se mueve (+4,7 % medido) pero el FPS
efectivo cae, porque el coste está aguas abajo: asignación húngara de ByteTrack
sobre 10x más cajas, más entradas de smoother, más `TrackState`, más eventos.
**Por qué pasa:** el criterio está redactado sobre "la latencia de inferencia".
**Cómo evitarlo:** cumplir el criterio con el test de `detect_sv` (es lo que pide)
**y** añadir al checkpoint manual la lectura de `detection_fps` y `dropped` en
`/api/v2/cameras/{id}/health` con las 6 clases activas y escena real.
**Señal temprana:** `AdaptiveRate` bajando escalones (12→8→5) al activar clases.

### Pitfall 7 — Comparar la hora en curso (parcial) contra un baseline de hora completa
**Qué falla:** el nivel de actividad sale "low" cada hora en punto y va subiendo
hasta el minuto 59. Un indicador que depende del reloj y no de la escena.
**Por qué pasa:** el baseline es "personas de toda la hora H"; a las 10:05 solo
hay 5 minutos de datos.
**Cómo evitarlo:** normalizar ambos lados a tasa por minuto y devolver `"unknown"`
cuando hayan pasado menos de 5 minutos de la hora (Q7).
**Señal temprana:** un test que fije el reloj al minuto 3 de la hora y afirme
`level == "unknown"`.

### Pitfall 8 — Baseline con pocos días de historia
**Qué falla:** un sistema recién instalado tiene 1 día de datos y clasifica
"actividad alta" a cualquier cosa.
**Por qué pasa:** `AVG` sobre 1 muestra es esa muestra.
**Cómo evitarlo:** devolver `sample_days` y forzar `level = "unknown"` con
`sample_days < 3`. Igual que la Fase 25 arrancó ReID en modo solo-observación
(`reid_inherit_identity = False`), aquí el sistema debe decir "no sé todavía" en
vez de inventarse un veredicto.

### Pitfall 9 — Estado del `ObjectAnalyzer` sin política de expiración
**Qué falla:** el dict por objeto crece sin límite con una escena concurrida.
**Por qué pasa:** los `track_id` de ByteTrack son monótonos y nunca se reutilizan.
**Cómo evitarlo:** copiar la doble guarda de `behavior.py:245-283`: `prune()` por
TTL **más** `_enforce_cap()` LRU llamado también desde `analyze()`, para que la
cota se cumpla aunque nadie llame a `prune()` a tiempo. El `set` de ids ignorados
(warmup) va bajo la misma política.
**Señal temprana:** el test de `tests/test_memory_bounds.py` con el patrón
`TEST_*_bounded` ya establecido.

### Pitfall 10 — Emitir `OBJECT_REMOVED` en cuanto el objeto falta un frame
**Qué falla:** una oclusión de 125 ms (alguien pasa por delante) genera un evento.
**Por qué pasa:** la desaparición es la señal más ruidosa de todas.
**Cómo evitarlo:** `object_gone_secs` de gracia antes de decidir, y decidir en el
`prune`, no en el `analyze`.
**Señal temprana:** ráfagas de `OBJECT_REMOVED`/`OBJECT_LEFT` alternos sobre la
misma zona de la imagen.

### Pitfall 11 — Nombres de clave del payload inventados
**Qué falla:** las reglas de `config/rules.yaml` no pueden filtrar por duración.
**Por qué pasa:** [VERIFIED: `backend/events/rules.py:88-91`] `RuleEngine` lee
literalmente `event.payload.get("duration_s")` para resolver `duration_gte`.
**Cómo evitarlo:** `duration_s` es el nombre obligatorio también para
`OBJECT_LEFT` (segundos inmóvil). La Fase 26 ya estableció esta regla.

### Pitfall 12 — Olvidar que `OBJECT_LEFT` sube clips a Drive
**Qué falla:** con la distancia "persona cerca" mal calibrada, cada falso positivo
sube un clip a Google Drive y consume cuota.
**Por qué pasa:** `OBJECT_LEFT: Severity.WARNING` (`types.py:55`) cruza
`upload_min_severity = "warning"` (`config.py:115` → `recording.py:309`).
**Cómo evitarlo:** el checkpoint manual debe verificar la tasa de falsos positivos
con escena real **antes** de dejar el sistema desatendido. Alternativa de
emergencia sin código: subir `upload_min_severity` a `"critical"`.

---

## Code Examples

### Bloque de configuración (patrón `config.py`, Fases 24/25/26)

```python
    # --- Multi-clase y objetos (Fase 27 — BEH-06..BEH-09) ---
    # yolo_classes (arriba, linea 54) pasa a poder sobrescribirse desde la tabla
    # app_config: la BD gana sobre la env var porque es lo ultimo que el operador
    # toco desde la UI (27-RESEARCH.md Q6). Una lista vacia CIEGA el sistema
    # (verificado: classes=[] devuelve 0 detecciones, no las 80), por eso el
    # endpoint la rechaza y el arranque la trata como ausente.
    object_class_ids: list[int] = [1, 2, 3, 24, 28]   # bicycle, car, motorcycle, backpack, suitcase
    object_left_secs: float = 60.0                    # criterio 2 del ROADMAP
    object_still_radius_px: float = 20.0              # = immobile_radius_px: misma magnitud fisica
    # Distancia persona<->objeto medida entre anclas BOTTOM_CENTER (los pies), no
    # entre centroides: una mochila en el suelo junto a una persona de pie tiene el
    # centroide desplazado media altura de persona. 150 px = 1,9 x loiter_radius_px
    # y ~media altura de persona a media distancia en un frame de 1280x720
    # (27-RESEARCH.md Q1). El ratio corrige la escala: cerca de la camara una
    # persona ocupa mas pixeles y su "cerca" tambien es mas grande.
    object_person_radius_px: float = 150.0
    object_person_radius_ratio: float = 0.5           # radio = max(px, ratio * alto_bbox_persona)
    object_warmup_secs: float = 10.0                  # todo objeto nacido antes = mobiliario fijo
    object_gone_secs: float = 3.0                     # gracia antes de declarar desaparicion
    object_person_window_secs: float = 10.0           # "habia una persona cerca" al desaparecer
    object_max_tracks: int = 256
    objects_enabled: bool = True

    # --- Contexto de escena (Fase 27 — BEH-08/09) ---
    context_baseline_days: int = 7                    # criterio 4 del ROADMAP
    context_min_sample_days: int = 3                  # por debajo -> level = "unknown"
    context_low_ratio: float = 0.5
    context_high_ratio: float = 1.5

    @model_validator(mode="after")
    def validate_object_params(self) -> "Settings":
        for name in ("object_left_secs", "object_still_radius_px",
                     "object_person_radius_px", "object_warmup_secs",
                     "object_gone_secs", "object_person_window_secs"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser > 0")
        if not 0 <= self.object_person_radius_ratio <= 2.0:
            raise ValueError("object_person_radius_ratio debe estar en [0, 2]")
        if any(not 0 <= c <= 79 for c in self.object_class_ids):
            raise ValueError("object_class_ids deben ser ids COCO validos (0-79)")
        if 0 in self.object_class_ids:
            raise ValueError(
                "la clase 0 (person) no puede estar en object_class_ids: las personas "
                "van al PersonTracker (LineZone + identidad + comportamiento), no al "
                "tracker de objetos"
            )
        if self.object_max_tracks < 1:
            raise ValueError("object_max_tracks debe ser >= 1")
        if not self.context_low_ratio < self.context_high_ratio:
            raise ValueError("context_low_ratio debe ser menor que context_high_ratio")
        return self
```

### Cambio en caliente, extremo a extremo

```python
# backend/detector.py
def set_classes(self, classes: list[int]) -> None:
    """Cambia las clases activas sin recargar el modelo (27-RESEARCH.md Q3).

    detect_sv() lee self._classes en CADA inferencia (linea 54) y Ultralytics lo
    aplica en el post-proceso de la llamada (models/yolo/detect/predict.py:54-58),
    asi que la siguiente inferencia ya usa el valor nuevo. Verificado: id(self._model)
    no cambia.

    Escritor: el event loop (endpoint PUT). Lector: el hilo de deteccion. El rebind
    del atributo es un unico STORE_ATTR, atomico bajo el GIL: el lector ve la lista
    vieja o la nueva, nunca una a medias. NUNCA mutar la lista in-place
    (append/clear) — eso si seria observable a medias.
    """
    self._classes = list(classes)

# backend/pipeline/detection.py  (patron de set_zones, linea 119)
def set_object_classes(self, class_ids: set[int]) -> None:
    """Ids que van al tracker de OBJETOS. Thread-safe."""
    with self._lock:
        self._object_class_ids = frozenset(class_ids)

# backend/pipeline/manager.py  (fachada, patron de set_zones linea 282)
def set_detection_classes(self, classes: list[int]) -> None:
    """Aplica las clases activas al detector y al reparto persona/objeto.

    NO reinicia el DetectionWorker: WorkerSupervisor._check() cuenta cualquier
    parada como caida y tres en 60 s lo marcan FAILED de forma permanente
    (supervisor.py:166-173).
    """
    if self.detector is not None:
        self.detector.set_classes(classes)
    if self.detection is not None:
        self.detection.set_object_classes({c for c in classes if c != 0})
```

### Arranque con la config persistida (`main.py`, antes de la línea 281)

```python
    # app_config gana sobre la env var: es lo ultimo que el operador toco desde la
    # UI (27-RESEARCH.md Q6). init_db() ya corrio en la linea 238, asi que la tabla
    # esta disponible. `or` (no `is not None`) para que una fila [] guardada por un
    # bug no deje el sistema ciego.
    persisted_classes = await ConfigRepo(get_session_factory()).get("yolo_classes")
    active_classes = list(persisted_classes) if persisted_classes else list(settings.yolo_classes)

    detector = PersonDetector(
        model_path=settings.yolo_model_path,     # "yolo26n.pt" tras D-03
        confidence=settings.yolo_confidence,
        classes=active_classes,
        label=settings.detection_label,
        imgsz=settings.yolo_imgsz,
    )
```

### `emit_object` (calco de `emit_behavior`, `engine.py:242-267`)

```python
_OBJECT_EVENT_TYPE: dict[ObjectKind, EventType] = {
    ObjectKind.LEFT:    EventType.OBJECT_LEFT,
    ObjectKind.REMOVED: EventType.OBJECT_REMOVED,
}

def emit_object(self, finding, now, captured_at=None, processed_at=None) -> None:
    """Traduce ObjectFinding -> Event. La idempotencia NO esta aqui: vive en el
    latch por episodio de ObjectAnalyzer, igual que para emit_behavior."""
    event_type = _OBJECT_EVENT_TYPE.get(finding.kind)
    if event_type is None:
        return
    self._publish(
        event_type, ts=now, captured_at=captured_at, processed_at=processed_at,
        track_id=finding.track_id, zone_id=finding.zone_id, bbox=finding.bbox,
        payload=finding.magnitudes(),   # duration_s, class_name, person_distance_px...
    )
```

**Nunca pasar `severity=` explícita**: el `@model_validator` de `Event`
(`types.py:76-80`) aplica el default del catálogo solo si `severity` no está en
`model_fields_set`. Es la decisión que la Fase 26 ya registró en `STATE.md:342`.

### Payload recomendado (BEH-05 aplicado a objetos)

| Evento | Campos de primer nivel | `payload` |
|---|---|---|
| `OBJECT_LEFT` | `track_id`, `zone_id` (o `None`), `bbox` | `duration_s`, `class_name`, `class_id`, `net_displacement_px` |
| `OBJECT_REMOVED` | `track_id`, `zone_id`, `bbox` (última conocida) | `duration_s` (cuánto llevaba estable), `class_name`, `class_id`, `person_distance_px`, `person_track_id` |

`class_name` sale de `obj_tracked.data["class_name"][i]` (verificado), no de un
mapa a mano.

---

## State of the Art

| Enfoque antiguo | Enfoque actual | Cuándo cambió | Impacto aquí |
|---|---|---|---|
| YOLOv8 con NMS clásica | YOLO26 end2end (NMS-free) | Ultralytics 8.4.x | El coste de `classes=` es aún menor: no hay NMS que escalar con el número de clases (medido: `end2end=True` en `yolo26n.pt`) |
| Sustracción de fondo para objetos abandonados (OpenCV MOG2 + análisis de blobs) | Detección por clase + tracking + reglas temporales | Desde que los detectores de objetos son baratos en CPU | El repo ya tiene detector y tracker: la sustracción de fondo sería una segunda tubería completa, sensible a luz y sombras. **No la introduzcas** |
| Trackers class-aware (DeepSORT con feature por clase) | ByteTrack + partición por clase aguas arriba | ByteTrack (2021) y su adopción en supervision | ByteTrack es rápido y class-agnostic por diseño; la partición es la forma canónica de darle semántica de clase |

**Deprecado / desactualizado en el repo:**
- `yolov8n.pt` como default (`config.py:37`) → `yolo26n.pt` (D-03).
- `TrackState.zones` y `TrackState.zone_entry_times` (`tracking.py:28-29`) siguen
  siendo código muerto tras la Fase 26 (la Fase 26 lo verificó y decidió no
  cablearlos). Esta fase tampoco los necesita: **no cablearlos**.

---

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|---|---|
| Framework | pytest + pytest-asyncio (`asyncio_mode = auto`) |
| Config file | `pytest.ini` — `python_functions = TEST_*` |
| Intérprete | `F:\Documentos\IA\Proyecto_Camara\.venv\Scripts\python.exe` (**el worktree no tiene `.venv` propio**) |
| Quick run | `.venv/Scripts/python.exe -m pytest tests/test_object_analyzer.py -q` |
| Full suite | `.venv/Scripts/python.exe -m pytest tests/ -q` (~90 s) |

**Convención de nombres obligatoria: `TEST_*`.** `pytest.ini` fija
`python_functions = TEST_*`. En Windows el matching es case-insensitive y por eso
conviven `test_*` (v1.2) y `TEST_*` (Fases 22-26), pero en Linux/CI los `test_*`
dejarían de recogerse en silencio. Todo lo nuevo va en `TEST_*`.

### Phase Requirements → Test Map

| Req | Comportamiento | Tipo | Comando automatizado | ¿Existe? |
|---|---|---|---|---|
| BEH-06 | `set_classes()` cambia las clases sin recargar el modelo | unit | `pytest tests/test_detector.py -k TEST_set_classes -q` | ❌ Wave 0 |
| BEH-06 | `classes=[]` se rechaza con 400 | unit | `pytest tests/test_detection_config_api.py -k TEST_rejects_empty -q` | ❌ Wave 0 |
| BEH-06 | La config persiste en `app_config` y gana sobre la env var al arrancar | unit | `pytest tests/test_repositories.py -k TEST_config_repo -q` | ❌ Wave 0 |
| BEH-06 | **Regresión Fase 4**: un `sv.Detections` mixto no altera `get_counts()` | unit | `pytest tests/test_detection_worker.py -k TEST_object_class_does_not_reach_line_zone -q` | ❌ Wave 0 |
| BEH-06 | **Regresión**: los tracks de objeto no entran en `TrackRegistry` | unit | `pytest tests/test_detection_worker.py -k TEST_objects_not_in_registry -q` | ❌ Wave 0 |
| BEH-06 | Criterio 6: p50 de `detect_sv` con 6 clases < 1,15 × p50 con 1 | perf | `pytest tests/test_detector.py -k TEST_multiclass_latency -q` | ❌ Wave 0 |
| BEH-07 | `OBJECT_LEFT` tras 60 s inmóvil sin persona cerca | unit | `pytest tests/test_object_analyzer.py -k TEST_object_left -q` | ❌ Wave 0 |
| BEH-07 | Criterio 5: **un único** `OBJECT_LEFT` por episodio | unit | `pytest tests/test_object_analyzer.py -k TEST_object_left_latched -q` | ❌ Wave 0 |
| BEH-07 | Criterio 5: con la persona presente **no** se emite | unit | `pytest tests/test_object_analyzer.py -k TEST_no_left_with_person -q` | ❌ Wave 0 |
| BEH-07 | Objeto presente en el arranque (warmup) nunca emite | unit | `pytest tests/test_object_analyzer.py -k TEST_warmup_furniture -q` | ❌ Wave 0 |
| BEH-07 | Objeto dentro de zona `exclude_objects` nunca emite | unit | `pytest tests/test_object_analyzer.py -k TEST_excluded_zone -q` | ❌ Wave 0 |
| BEH-07 | `OBJECT_REMOVED` al desaparecer con persona cerca | unit | `pytest tests/test_object_analyzer.py -k TEST_object_removed -q` | ❌ Wave 0 |
| BEH-07 | Desaparición **sin** persona cerca → silencio | unit | `pytest tests/test_object_analyzer.py -k TEST_removed_needs_person -q` | ❌ Wave 0 |
| BEH-07 | Oclusión de 1 frame no dispara `OBJECT_REMOVED` | unit | `pytest tests/test_object_analyzer.py -k TEST_occlusion_grace -q` | ❌ Wave 0 |
| BEH-07 | Estado acotado: TTL + cota dura | unit | `pytest tests/test_memory_bounds.py -k TEST_object_analyzer_bounded -q` | ❌ Wave 0 |
| BEH-07 | `emit_object` traduce a `Event` con el payload correcto | unit | `pytest tests/test_event_engine.py -k TEST_emit_object -q` | ❌ Wave 0 |
| BEH-08 | El endpoint devuelve los 6 bloques del criterio 4 | integration | `pytest tests/test_scene_context.py -k TEST_context_shape -q` | ❌ Wave 0 |
| BEH-08 | `known` cuenta solo `CONFIRMED`, no `CANDIDATE` | unit | `pytest tests/test_scene_context.py -k TEST_known_requires_confirmed -q` | ❌ Wave 0 |
| BEH-09 | `hourly_baseline()` promedia por (día, hora), no por minuto | unit | `pytest tests/test_repositories.py -k TEST_hourly_baseline -q` | ❌ Wave 0 |
| BEH-09 | `sample_days < 3` ⇒ `level == "unknown"` | unit | `pytest tests/test_scene_context.py -k TEST_insufficient_history -q` | ❌ Wave 0 |
| BEH-09 | Hora parcial normalizada a tasa/minuto (Pitfall 7) | unit | `pytest tests/test_scene_context.py -k TEST_partial_hour_normalised -q` | ❌ Wave 0 |
| — | Invariantes de arquitectura siguen verdes | arch | `pytest tests/test_architecture.py -q` | ✅ existe |

### Criterios de éxito del ROADMAP → comando

| # | Criterio | Comando / evidencia |
|---|---|---|
| 1 | Clases configurables desde la UI | `pytest tests/test_detection_config_api.py -q` + **checkpoint manual** (marcar "mochila" en el dashboard y ver la caja en el MJPEG — depende de Open Question #1) |
| 2 | `OBJECT_LEFT` tras 60 s sin persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_left -q` |
| 3 | `OBJECT_REMOVED` al desaparecer con persona cerca | `pytest tests/test_object_analyzer.py -k TEST_object_removed -q` |
| 4 | `/api/v2/analytics/context` con media móvil de 7 días | `pytest tests/test_scene_context.py -q` |
| 5 | Un único `OBJECT_LEFT`; con persona presente, ninguno | `pytest tests/test_object_analyzer.py -k "TEST_object_left_latched or TEST_no_left_with_person" -q` |
| 6 | 6 clases no suben la latencia > 15 % | `pytest tests/test_detector.py -k TEST_multiclass_latency -q` — **ya medido: +4,7 %** |

### Cómo se testea el dominio puro (nivel 1, sin `sv.Detections`)

Igual que la Fase 26: se instancia `ObjectAnalyzer`, se le pasan diccionarios y un
`now` inventado, y se comprueba el veredicto. Sin hilos, sin broker, sin asyncio,
sin reloj real. `tests/test_behavior_analyzer.py` es el molde literal.

Un helper local basta para las trayectorias:
```python
def _still(x, y, secs, fps=8.0, jitter=0.0):
    """Objeto quieto en (x,y) durante `secs` segundos a `fps`."""
    n = int(secs * fps)
    return [(i / fps, x + (i % 2) * jitter, y) for i in range(n)]
```

**La mitad difícil del criterio 5 es "y ninguno más".** El test debe afirmar sobre
el **conjunto completo** de findings (`assert kinds == {ObjectKind.LEFT}`), no
sobre la presencia del esperado. Y debe cubrir explícitamente el caso "objeto
inmóvil 70 s **con** persona a 100 px" → `assert findings == []`.

### Cableado (nivel 2)

`tests/test_detection_worker.py:27-35` tiene `_tracked(ids)` y la línea 252
`_tracked_at(boxes, tids)`. **Ninguno de los dos pone `class_id`** — hace falta una
variante `_tracked_cls(boxes, tids, class_ids)`. Escribir **una sola** y
reutilizarla; no un cuarto helper.
`tests/test_memory_bounds.py:34-40` tiene `_fake_tracked(track_id)` con
`SimpleNamespace`, más ligero y sin depender de `supervision` — útil para los
tests de cota.

### Sampling Rate

- **Por commit de tarea:** el fichero de test afectado, `-q`.
- **Por merge de wave:** `pytest tests/ -q` si la wave tocó pipeline, arquitectura,
  API o configuración (regla de `CLAUDE.md`).
- **Puerta de fase:** suite completa verde antes de `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `tests/test_object_analyzer.py` — dominio puro (BEH-07, criterios 2/3/5)
- [ ] `tests/test_scene_context.py` — endpoint + baseline (BEH-08/09, criterio 4)
- [ ] `tests/test_detection_config_api.py` — GET/PUT de clases (BEH-06, criterio 1)
- [ ] Helper `_tracked_cls(boxes, tids, class_ids)` en `tests/test_detection_worker.py`
- [ ] Ampliaciones: `test_detector.py` (set_classes, latencia), `test_config.py`
      (defaults + validadores + D-03), `test_event_engine.py` (`emit_object`),
      `test_memory_bounds.py` (cota del analizador), `test_repositories.py`
      (`hourly_baseline`, `ConfigRepo`), `test_detection_worker.py` (partición,
      regresión de `LineZone`, objetos fuera del registry)
- [ ] Framework: **ninguno** — pytest ya está instalado y configurado

---

## Security Domain

### Applicable ASVS Categories

| Categoría ASVS | Aplica | Control estándar |
|---|---|---|
| V2 Authentication | sí (heredado) | HTTP Basic global vía `FastAPI(dependencies=[Depends(verify)])`; los routers v2 lo heredan sin `Depends` por ruta (`api/v2/deps.py:3-4`) |
| V3 Session Management | no | La API v2 es stateless |
| V4 Access Control | parcial | **El PUT de clases es el primer endpoint de esta fase que MUTA la configuración del pipeline.** No hay roles en el sistema (auth es todo-o-nada) → cualquiera con la Basic Auth puede cegar la detección. Mitigación disponible: rate limit + validación estricta + `CONFIG_CHANGED` para trazabilidad |
| V5 Input Validation | sí | Pydantic en el body del PUT + validación de rango `0..79` + lista no vacía + sin duplicados. `ids` es una lista de enteros, nunca un string interpolado en SQL |
| V6 Cryptography | no | No hay secretos nuevos |
| V7 Error Handling & Logging | sí | `logger.exception` + `self._exceptions += 1` en la vía de objetos (patrón `detection.py:221-224`). Nunca loguear la URL RTSP |
| V13 API | sí | `@limiter.limit(V2_RATE_LIMIT)` (60/min) en los tres endpoints nuevos, como toda la superficie v2 (SEC-16) |

### Known Threat Patterns

| Patrón | STRIDE | Mitigación |
|---|---|---|
| DoS por lista de clases enorme (las 80 activas en una escena concurrida) | Denial of Service | Lista blanca en el frontend + validación de longitud máxima en el backend; `AdaptiveRate` degrada solo pero avisa por `/health` |
| Cegado silencioso del sistema con `classes=[]` | Tampering | 400 en el PUT; `if persisted` al arrancar (Pitfall 3) |
| Inyección SQL vía `camera_id`/`days` del endpoint de contexto | Tampering | SQLAlchemy con parámetros ligados; `days` tipado como `int` con `Query(ge=1, le=90)`. **Nunca** interpolar en el `text()` del `group_by` |
| Fuga de información en el endpoint de contexto | Information Disclosure | El contexto devuelve **recuentos**, nunca nombres de persona ni `person_id`. Devolver nombres convertiría un endpoint de analítica en uno de identidad |
| Agotamiento de cuota de Google Drive por falsos `OBJECT_LEFT` | Denial of Service | `OBJECT_LEFT` es `WARNING` y cruza `upload_min_severity`; calibración obligatoria en el checkpoint manual (Pitfall 12) |
| Path traversal | — | No aplica: esta fase no toca rutas de fichero. `validate_yolo_model_path` (`config.py:39-51`) ya cubre D-03 |

---

## Assumptions Log

| # | Afirmación | Sección | Riesgo si es falsa |
|---|---|---|---|
| A1 | `object_person_radius_px = 150.0` es una distancia razonable para "persona cerca" a 1280×720 | Q1 | Demasiado grande ⇒ `OBJECT_REMOVED` falsos con cualquiera que pase. Demasiado pequeño ⇒ `OBJECT_LEFT` falsos con el dueño al lado. **Requiere calibración con escena real** |
| A2 | `object_warmup_secs = 10.0` basta para capturar todo el mobiliario visible al arranque | Q2 | Si el pipeline tarda más en estabilizarse, algo de mobiliario se cuela como candidato |
| A3 | `object_gone_secs = 3.0` filtra oclusiones sin perder retiradas reales | Q2 | Muy corto ⇒ `OBJECT_REMOVED` por oclusión. Muy largo ⇒ el evento llega tarde |
| A4 | Umbrales de nivel de actividad 0,5 / 1,5 | Q7 | Sin datos históricos reales que los respalden. Muy fácil de ajustar después: son solo dos floats de config |
| A5 | "Un tracker por grupo de clases" es el patrón estándar del ecosistema para trackers class-agnostic | Q4 | Es conocimiento general, no verificado en esta sesión. **Lo verificado y suficiente es el comportamiento concreto de supervision 0.27.0.post2** |
| A6 | La BD debe ganar sobre la env var para las clases activas | Q6 | Decisión de producto disfrazada de técnica. La contraria (env var gana) sorprendería al operador tras un reinicio → Open Question #3 |
| A7 | Una persona a media distancia ocupa 25-40 % del alto del frame en una C212 | Q1 | Razonado; la medición disponible (`bus.jpg`) es de gran angular a corta distancia, no representativa |

---

## Open Questions — RESUELTAS con el usuario (`AskUserQuestion`, opción recomendada aceptada en las 5)

1. **Overlay MJPEG**: SÍ dibujar los objetos, color distinto a las personas, vía referencia de solo lectura del `StreamingWorker` a `DetectionWorker.get_object_boxes()`.
2. **Desactivar clase "persona"**: NO permitido. Checkbox de "persona" siempre marcado y deshabilitado en la UI; el backend rechaza con 400 cualquier PUT que no la incluya.
3. **Precedencia `app_config` vs `YOLO_CLASSES`**: gana la base de datos. La env var solo es el valor inicial de una instalación limpia.
4. **Severidad `OBJECT_LEFT`**: se mantiene `WARNING` (ya publicada en el catálogo desde la Fase 26). El checkpoint manual de esta fase debe verificar la tasa de falsos positivos antes de operar desatendido.
5. **Métrica del baseline BEH-09**: `unique_tracks` por hora (flujo de personas distintas), no `max_concurrent`.

Detalle original de cada pregunta (contexto para el planner):

1. **¿Se dibujan los objetos en el overlay MJPEG?**
   - Lo que sabemos: `StreamingWorker._annotate` dibuja desde
     `registry.snapshot()` (`streaming.py:132-150`), y los objetos no van al
     registry (Q4).
   - Lo que no está claro: si el criterio 1 ("configurables desde la UI") exige
     evidencia visual o basta con el endpoint y los eventos.
   - Recomendación: **sí dibujarlos**, pasando al `StreamingWorker` una referencia
     de solo lectura a `DetectionWorker.get_object_boxes()`, con color distinto.
     ~15 líneas y hace el checkpoint manual del criterio 1 trivial. La alternativa
     (diferir a la Fase 28) es aceptable si el planner prefiere el alcance mínimo.

2. **¿Se puede desactivar la clase `person` (id 0) desde la UI?**
   - Lo que sabemos: quitarla rompe de golpe el conteo de línea (Fase 4), el
     reconocimiento facial (Fases 23/24), el ReID (Fase 25) y los cuatro eventos
     de comportamiento (Fase 26).
   - Recomendación: **forzarla siempre activa** — checkbox marcado y deshabilitado
     en el frontend, y 400 en el backend si el body no la incluye. Es una decisión
     de producto: confirmar con el usuario.

3. **Precedencia entre `app_config` y la env var `YOLO_CLASSES`.**
   - Recomendación: **la BD gana** (es lo último que el operador tocó desde la
     UI); la env var queda como valor inicial de una instalación limpia.
   - Riesgo de la contraria: cambias las clases desde el dashboard, reinicias, y
     vuelven silenciosamente al `.env`. Confirmar con el usuario y documentarlo en
     el docstring del endpoint.

4. **¿`OBJECT_LEFT` debe seguir siendo `WARNING`?**
   - Lo que sabemos: `types.py:55` ya lo fija a `WARNING`, y eso cruza
     `upload_min_severity = "warning"` ⇒ sube clips a Drive automáticamente.
   - Recomendación: **dejarlo en `WARNING`** (un objeto abandonado es exactamente
     lo que quieres grabado), pero que el checkpoint manual verifique la tasa de
     falsos positivos antes de dejar el sistema desatendido. Bajarlo a `INFO`
     rompería el contrato ya publicado del catálogo.

5. **Métrica del baseline: `unique_tracks` sumado por hora.**
   - Lo que sabemos: `detections` depende del FPS efectivo (H-5), `unique_tracks`
     no. `max_concurrent` sería otra opción (mide aglomeración, no flujo).
   - Recomendación: `unique_tracks` (flujo de personas distintas). Si el usuario
     entiende "nivel de actividad" como "cuánta gente hay a la vez",
     `max_concurrent` sería lo correcto. Confirmar la semántica.

---

## Environment Availability

| Dependencia | Requerida por | Disponible | Versión | Fallback |
|---|---|---|---|---|
| Python | todo | ✓ | 3.12.10 x64 | — |
| `ultralytics` | BEH-06, criterio 6 | ✓ | 8.4.38 | — |
| `supervision` | BEH-06/07 | ✓ | 0.27.0.post2 | — |
| `yolo26n.pt` | D-03, criterio 6 | ✓ | 5,3 MB en la raíz | `yolov8n.pt` sigue presente |
| `yolov8n.pt` | comparativa | ✓ | 6,2 MB | — |
| SQLite + aiosqlite | BEH-09 | ✓ | vía SQLAlchemy 2 | — |
| pytest | validación | ✓ | `pytest.ini` configurado | — |
| Imagen de prueba con personas | benchmark del criterio 6 | ✓ | `.venv/Lib/site-packages/ultralytics/assets/bus.jpg` (4 personas + 1 bus detectados) | frame sintético |
| **Cámara real / escena de prueba** | calibración de A1-A3, criterios 2/3/5 en producción | ✗ | — | Tests de dominio puro con trayectorias sintéticas + **checkpoint manual diferido**, igual que hicieron las Fases 21, 25 y 26 |
| **`.venv` dentro del worktree** | ejecutar tests desde el worktree | ✗ | — | Usar `F:\Documentos\IA\Proyecto_Camara\.venv\Scripts\python.exe`. **El planner debe escribir los comandos con esa ruta** |
| BD con 7 días de historia real | verificar BEH-09 con datos de verdad | ✗ | `data/events.db` está vacía (0 tablas) | `scripts/seed_events.py` existe; el test del baseline debe sembrar sus propias filas de `DetectionStat` |

**Dependencias que faltan sin fallback:** ninguna bloquea la implementación.

**Dependencias que faltan con fallback:** la cámara real y la historia de 7 días.
Ambas se cubren con tests sintéticos deterministas más un checkpoint manual
diferido — el mismo camino que la Fase 26 documentó en `26-05-SUMMARY.md`.

---

## Project Constraints (from CLAUDE.md)

| Directiva | Cómo la respeta este research |
|---|---|
| Baja latencia, estabilidad, CPU moderada, simplicidad | El coste de multi-clase está medido (+4,7 %, ruido). El analizador es O(1) por objeto. Cero dependencias nuevas |
| No añadir dependencias, frameworks ni infraestructura sin necesidad | Ninguna dependencia nueva. `app_config` y `zones.kind` ya existen |
| Verificar código/tests antes de modificar arquitectura | Los 8 hallazgos del CONTEXT verificados; el comportamiento de ByteTrack, el smoother, Ultralytics y SQLite **medidos**, no supuestos |
| No inventar APIs, rutas, variables, archivos o comportamiento | Cada afirmación lleva `fichero:línea` o una medición reproducible |
| Ningún hilo hace `await`; ninguna corrutina ejecuta inferencia | `ObjectAnalyzer` corre en el hilo de detección y es puro; los endpoints solo leen estado y lanzan una query que `aiosqlite` ejecuta en su thread pool |
| Se descartan frames antes que acumular latencia | Sin cambios en el broker ni en `AdaptiveRate`. `rate.observe()` sigue midiendo solo la vía de personas |
| Tracks compartidos → `TrackRegistry` | Se refuerza: los objetos **no** entran, para que el registry siga siendo el estado de personas con escritor único |
| Conteo = tracking/cruce, no suma de detecciones por frame | Protegido explícitamente: la partición por clase impide que los vehículos lleguen al `LineZone` |
| Los tests de arquitectura deben proteger estas reglas | `tests/test_architecture.py` (5 tests) debe seguir verde; se añade un test de regresión para el `LineZone` |
| No colas ilimitadas ni estado global oculto | Doble guarda (TTL + cota dura LRU) en el analizador, con test de `test_memory_bounds.py` |
| Nunca exponer credenciales RTSP | Ninguna ruta nueva toca la URL RTSP |
| Cambio mínimo que resuelva el problema | `PersonTracker`, `BehaviorAnalyzer` y `TrackRegistry` no se tocan. `behavior.py` **no se modifica** pese a lo que dice SPEC (D-1) |
| Frontend HTML + JS vanilla, sin build step | El panel de clases va inline en `index.html`, como el panel de zonas |

---

## Sources

### Primary (HIGH confidence) — código del repo, leído en esta sesión

- `backend/detector.py:20-57` — `classes=` por llamada, `detect_sv`
- `backend/tracker.py:11-153` — `PersonTracker`, `LineZone`, `DetectionsSmoother`, `set_frame_rate`
- `backend/pipeline/detection.py:37-341` — `_loop`, `_analyze_behavior`, `_zone_membership_snapshot`, `_update_zones_and_heat`, `_rebuild_zone_states`, `set_zones`
- `backend/pipeline/tracking.py:18-138` — `TrackState`, `TrackRegistry`, `frame_ids` vs `active_ids`, `prune`
- `backend/pipeline/manager.py:40-323` — construcción fuera de la factoría, fachada
- `backend/pipeline/supervisor.py:46-181` — `register`, `_spawn`, `_check`, ventana de caídas
- `backend/pipeline/streaming.py:132-150` — origen del overlay
- `backend/pipeline/recognition.py:286-405` — iteración sobre el registry sin filtro de clase
- `backend/perception/behavior.py:1-284` — patrón de dominio puro a replicar
- `backend/perception/face/identity.py:22-45,127-136` — `IdentityState`, `IdentityTransition`
- `backend/events/types.py:19-80` — catálogo, `DEFAULT_SEVERITY`, `Event`, validador de severidad
- `backend/events/engine.py:37-302` — `_publish`, `process_zone`, `emit_behavior`, `accumulate_detections`, `flush_stats`
- `backend/events/rules.py:88-91` — `duration_gte` lee `payload["duration_s"]`
- `backend/storage/models.py:112-128,159-171,196-201` — `DetectionStat`, `Zone`, `AppConfig` e índices
- `backend/storage/repositories.py:153-169,198-261,460-506,551-574` — `hourly_counts`, `DetectionStatRepo`, `ZoneRepo`, `ConfigRepo`
- `backend/storage/migrations.py:70-131` — `_add_missing_columns`, `_ensure_columns`
- `backend/database.py:37-44,294-308` — `Zone` legacy y `get_zones()` (sin `kind`)
- `backend/api/v2/recordings.py:1-60`, `backend/api/v2/metrics.py:1-43`, `backend/api/v2/deps.py` — patrón de router y de `configure()`
- `backend/config.py:33-58,115,165-296` — validadores, bloque de la Fase 26, `upload_min_severity`
- `backend/main.py:143-153,234-298,405-470,554-561` — lifespan, orden `init_db` → detector, flush de stats, routers
- `tests/test_reid_engine.py:54-70` — metodología de benchmark de latencia
- `tests/test_architecture.py` — los 5 invariantes protegidos
- `pytest.ini` — `python_functions = TEST_*`

### Primary (HIGH confidence) — código de librerías instaladas

- `.venv/Lib/site-packages/supervision/tracker/byte_tracker/core.py:38-63,104-133,151-215` — ByteTrack sin `class_id` (supervision 0.27.0.post2)
- `.venv/Lib/site-packages/supervision/detection/tools/smoother.py:59-121` — `deepcopy(track[0])`, ghosts hasta `length` frames
- `.venv/Lib/site-packages/ultralytics/models/yolo/detect/predict.py:53-66` — `classes` en `non_max_suppression`, `end2end` (ultralytics 8.4.38)

### Primary (HIGH confidence) — mediciones hechas en esta sesión

- **Latencia por número de clases** (`yolo26n.pt` end2end, `bus.jpg` a 1280×720, `imgsz=640`, 5 warmup + 30 muestras, mediana): 38,90 / 40,74 / 39,98 ms para 1 / 6 / 80 clases. Control con ruido aleatorio: 39,54 vs 39,49 ms. `yolov8n.pt`: 33,61 vs 32,53 ms
- **Mutación en caliente de `_classes`**: cambia el resultado sin recargar el modelo (`id(self._model)` constante)
- **`classes=[]` ⇒ 0 detecciones**; `classes=None` ⇒ las 80
- **`sv.Detections.data["class_name"]`** presente y preservado tras slicing por clase
- **Migración de `track_id` entre clases** en ByteTrack (mochila → persona en la misma caja), reproducida
- **`class_id` congelado 3+ frames** por `DetectionsSmoother`, reproducido
- **Query de baseline**: p50 11,39 ms a 43.200 filas y 11,22 ms a 525.600, con `EXPLAIN QUERY PLAN` mostrando el range scan sobre el índice existente; 80 MB de tabla al año
- **Tamaños de bbox de persona** a 1280×720: ancho 124-271 px, alto 208-358 px, alto/ancho 1,32-1,69
- **Ids COCO** de las 6 clases del ROADMAP, leídos de `YOLO('yolo26n.pt').names`

### Secondary (MEDIUM confidence) — documentos del proyecto

- `.planning/phases/27-multi-clase-y-contexto-de-escena/27-CONTEXT.md` — H-1..H-8, D-01..D-03
- `.planning/ROADMAP.md:489-500` — los 6 criterios de éxito
- `.planning/REQUIREMENTS.md:236-239` — BEH-06..BEH-09
- `propuesta_mejora/SPEC_v2.md:500-501,910-917` — catálogo y Phase 27 (lista de ficheros incompleta, ver `## Discrepancias`)
- `.planning/phases/26-an-lisis-de-comportamiento/26-RESEARCH.md` — patrones y convenciones establecidos
- `.planning/STATE.md:342` — decisiones registradas de la Fase 26 (severidad, `now_monotonic`, `duration_s`)
- `CLAUDE.md` — invariantes y restricciones de stack

### Tertiary (LOW confidence)

- A5 (patrón "un tracker por grupo de clases" como norma del ecosistema) — conocimiento general no verificado en esta sesión; lo que sí está verificado y es suficiente para decidir es el comportamiento concreto de supervision 0.27.0.post2
- Estimación de tamaño de persona en una escena de vigilancia típica (25-40 % del alto del frame) — razonada, no medida con la C212

---

## Metadata

**Desglose de confianza:**

| Área | Nivel | Motivo |
|---|---|---|
| ByteTrack class-agnostic y sus consecuencias (Q4) | **HIGH** | Código de la librería leído + comportamiento reproducido con script |
| Cambio en caliente de `classes=` (Q3) | **HIGH** | Código de Ultralytics + del supervisor + mutación ejecutada |
| Criterio 6 / benchmark (Q8) | **HIGH** | Medido tres veces, dos modelos, tres frames distintos |
| Query de media móvil y coste (Q7) | **HIGH** | `EXPLAIN QUERY PLAN` + medición a dos escalas de tabla |
| Campos y fuentes del endpoint de contexto (Q5) | **HIGH** | Cada campo trazado a `fichero:línea` |
| Persistencia en `AppConfig` (Q6) | **HIGH** | Tabla, repo y orden del lifespan verificados |
| Mecanismo de exclusión de mobiliario (Q2) | **HIGH** | Warmup, monotonía de ids y existencia física de `zones.kind` verificados |
| Magnitudes de objeto: warmup, gone, ventana (Q2) | **MEDIUM** | Razonadas contra el FPS real del pipeline; sin escena de prueba |
| Distancia "persona cerca" (Q1) | **MEDIUM** | Método (anclas `BOTTOM_CENTER`, ratio de escala) HIGH y medido; el valor 150 px es propuesta razonada, no calibración |
| Umbrales de nivel de actividad (Q7) | **LOW** | Sin datos históricos reales. Dos floats de config, triviales de ajustar |

**Research date:** 2026-08-16
**Valid until:** 2026-09-15 (30 días). Las mediciones dependen de las versiones
instaladas: `supervision 0.27.0.post2` y `ultralytics 8.4.38`. Si alguna sube de
versión menor, **re-verificar `core.py:104-110`** (que ByteTrack sigue sin recibir
`class_id`) y `smoother.py:104` (`deepcopy(track[0])`) antes de fiarse de Q2/Q4.
