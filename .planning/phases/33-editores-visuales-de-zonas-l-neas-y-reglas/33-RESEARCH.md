# Fase 33: Editores visuales de zonas, líneas y reglas - Investigación

**Investigado:** 2026-08-24
**Dominio:** Editor canvas-sobre-vídeo (frontend vanilla) + CRUD backend (zonas/líneas/reglas) + motor de reglas con modo de prueba
**Confianza:** MEDIA — el patrón de canvas y el hot-reload de zonas están verificados en código; la arquitectura de líneas y reglas requiere decisiones de diseño porque hoy son de un solo elemento y basadas en YAML respectivamente

## Resumen

Esta fase tiene menos "investigar librerías" y mucho más "reconciliar tres piezas de arquitectura que ya existen a medias en el código, en estados distintos de terminación". Las zonas (`zones`) ya tienen CRUD v1 funcional (`/api/zones`), coordenadas normalizadas por diseño, y recarga en caliente verificada (`set_zones()` + flag `_zones_dirty`, recogido en el siguiente frame). Las líneas de conteo, en cambio, son hoy una única línea global configurada por `.env`/ajustes con `applies="restart_camera"` — no hay CRUD, no hay tabla `lines` en uso, y solo existe una `sv.LineZone` por pipeline aunque el modelo de datos v2 (`storage/models.py:Line`) ya prevé varias por cámara. Las reglas tienen un motor completo y probado (`RuleEngine`, `_matches()`, debounce, acciones) pero su fuente de verdad es `config/rules.yaml`, no la tabla `rules` — `RuleRepo` existe en `storage/repositories.py` pero está muerto (cero referencias fuera de su propio fichero).

El frontend ya resuelve la parte más delicada del editor visual: `frontend/js/components/videoCanvas.js` tiene el patrón exacto de canvas superpuesto a un `<img>` MJPEG con `object-fit: cover`, incluida la matemática de letterboxing (`normalizedBoxToCanvasRect`) que un editor de zonas necesita invertir (click en canvas → fracción normalizada). No existe ningún componente de diálogo/modal en `components.css`; habrá que crearlo.

**Recomendación principal:** tratar esta fase como tres entregables con acoplamiento fuerte pero secuenciables — (1) CRUD de zonas y líneas sobre la tabla `zones`/`lines` con hot-reload igual al patrón ya usado por `set_zones()`, extendiendo `PersonTracker` para soportar N líneas en vez de una; (2) editor visual canvas reutilizando `videoCanvas.js`; (3) migrar la fuente de verdad de reglas de YAML a la tabla `rules` (reutilizando `RuleRepo`, hoy muerto) y añadir `POST /api/v2/rules/{id}/test` sobre la función pura `_matches()` ya existente en `backend/events/rules.py`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dibujo/edición de polígonos y líneas (canvas, drag de vértices) | Browser / Client | — | Interacción de ratón, sin lógica de negocio; solo produce coordenadas fraccionarias |
| Conversión pixel-canvas ↔ fracción normalizada | Browser / Client | — | Ya resuelto en `videoCanvas.js` para bboxes; se reutiliza/invierte, no se recalcula en servidor |
| CRUD de zonas/líneas/reglas (persistencia, validación de esquema) | API / Backend | Database / Storage | `ZoneRepo`/`RuleRepo` ya modelan esto; falta wiring de rutas |
| Recarga en caliente del pipeline al cambiar zona/línea | API / Backend | — | `CameraPipeline.set_zones()` ya es el patrón; línea necesita el mismo tratamiento |
| Evaluación de regla contra histórico (`/rules/{id}/test`) | API / Backend | Database / Storage | Reutiliza `EventRepo.query()` + `_matches()` puro de `backend/events/rules.py` |
| Persistencia de zonas/líneas/reglas | Database / Storage | — | Tablas `zones`, `lines`, `rules` ya existen en el esquema v2 (algunas sin usar) |

## Phase Requirements

| ID | Descripción | Soporte de la investigación |
|----|-------------|------------------------------|
| OPS-21 | Zonas dibujadas/editadas/borradas sobre vídeo, coordenadas independientes de resolución | Patrón de coordenadas ya normalizado en BD y en pipeline (`p[0]*fw`); falta UI de dibujo y CRUD completo sobre `/api/zones` (o `/api/v2/zones`) |
| OPS-22 | Líneas de conteo dibujadas con indicador de dirección | Requiere refactor: hoy 1 línea global, no N líneas por cámara vía tabla `lines` |
| OPS-23 | Zonas con tipo (conteo/restringida/exclusión) y horario propio | Columnas `kind`/`schedule` ya existen en `storage/models.py:Zone`; el consumo en pipeline solo usa `kind` parcialmente (ver Pitfall 2) |
| OPS-24 | Reglas compuestas por formularios, sin YAML | Requiere migrar fuente de verdad de `config/rules.yaml` a tabla `rules` (`RuleRepo` ya existe, sin usar) |
| RULE-05 | Regla probable contra histórico reciente antes de activarse | `_matches(when, event)` en `backend/events/rules.py:72` es puro y reutilizable; `EventRepo.query(limit=500)` da los eventos |

## Standard Stack

### Core (ya en el proyecto, sin librerías nuevas)

| Librería | Versión instalada | Uso en esta fase | Por qué es la estándar |
|----------|---------|---------|---------------|
| `supervision` | 0.27.0.post2 `[VERIFIED: pip/venv]` | `sv.PolygonZone`, `sv.LineZone` ya en uso en `backend/tracker.py` y `backend/pipeline/detection.py` | Ya es el motor de zonas/líneas del proyecto; no se cambia |
| Canvas API nativo (sin librería) | — | Dibujo interactivo de polígonos/líneas | CLAUDE.md prohíbe frameworks JS nuevos; `videoCanvas.js` ya prueba que el Canvas 2D nativo basta para overlays sobre el MJPEG |
| FastAPI + Pydantic | ya en requirements.txt | Validación de esquema de regla en servidor (OPS-24 exige "valida en servidor antes de guardar") | Los modelos `Rule`/`When`/`Action` de `backend/events/rules.py` ya son Pydantic — reutilizables tal cual para el POST/PUT |
| SQLAlchemy 2 async | ya en requirements.txt | `ZoneRepo`/`RuleRepo` (existentes) + nuevo `LineRepo` | Mismo patrón que `EventRepo`/`RecordingRepo` |

### Alternativas consideradas

| En vez de | Podría usarse | Por qué no |
|------------|-----------|----------|
| Canvas 2D nativo | Fabric.js / Konva.js (librería de canvas interactivo) | CLAUDE.md: "No introducir [...] frameworks JS [...] sin decisión explícita"; el proyecto no tiene build step y estas librerías son overkill para polígonos simples con <10 vértices |
| Tabla `rules` como fuente de verdad | Seguir usando `config/rules.yaml` y que el editor lo reescriba en disco | Rompe "sin editar YAML" en espíritu (seguiría siendo YAML bajo el capó, con problemas de concurrencia de escritura de fichero) y no aprovecha `RuleRepo` ya existente en el esquema v2 |

**Instalación:** ninguna — no se añaden dependencias.

## Architecture Patterns

### Diagrama de flujo de datos

```
Usuario dibuja polígono/línea sobre <canvas> (Cámara o Ajustes > Zonas)
        │  click/drag → coords en pixeles de canvas
        ▼
JS: canvasToFrac(x, y) — inversa de normalizedBoxToCanvasRect (videoCanvas.js)
        │  {x_frac, y_frac} por vértice
        ▼
POST/PUT /api/v2/zones  o  /api/v2/lines        (nuevo router, valida con Pydantic)
        │
        ▼
ZoneRepo.upsert() / LineRepo.upsert()  ──►  tabla zones/lines (SQLite)
        │
        ▼
CameraManager.all() → pipeline.set_zones(zones) / pipeline.set_lines(lines)
        │  thread-safe, flag "dirty"
        ▼
DetectionWorker/PersonTracker: en el siguiente frame reconstruye
sv.PolygonZone / sv.LineZone a partir de fracciones × (frame_w, frame_h) actuales
        │
        ▼
Overlay opcional en /video_feed + eventos ZONE_ENTERED/LINE_CROSSED sin cambios

--- Camino del editor de reglas ---

Formulario (when/actions) → POST/PUT /api/v2/rules
        │  valida contra modelos Pydantic Rule/When/Action (backend/events/rules.py)
        ▼
RuleRepo.upsert() → tabla rules
        │
        ▼
rule_engine.reload(rules_desde_BD)   (ya existe, usado hoy solo al arrancar)

--- Camino de prueba de regla ---

POST /api/v2/rules/{id}/test
        │
        ▼
EventRepo.query(limit=500)  → últimos N eventos
        │
        ▼
for event in eventos: _matches(rule.when, event)   (función pura, sin mutar debounce)
        │
        ▼
{"would_fire": N, "total_checked": 500}
```

### Estructura de ficheros propuesta

```
backend/
  api/v2/
    zones.py      # NUEVO: GET/POST/DELETE /api/v2/zones (o extender /api/zones existente)
    lines.py      # NUEVO: GET/POST/DELETE /api/v2/lines
    rules.py      # NUEVO: GET/POST/PUT/DELETE /api/v2/rules + POST /rules/{id}/test
                   #   (sustituye al GET suelto de main.py:998)
  storage/
    repositories.py  # ZoneRepo (existe), RuleRepo (existe), LineRepo (NUEVO)
  pipeline/
    detection.py   # set_zones() ya existe; añadir set_lines() análogo
  tracker.py       # PersonTracker: refactor de _line_zone único a lista de líneas
                    # (mismo patrón que _zone_states en detection.py)
  events/
    rules.py        # RuleEngine.reload() ya existe; exponer _matches() como función
                     # pública reutilizable para /rules/{id}/test (o método de clase)

frontend/
  js/
    components/
      videoCanvas.js   # ya existe: reutilizar normalizedBoxToCanvasRect + inversa
      zoneEditor.js    # NUEVO: dibujo/edición de polígonos y líneas
    views/
      zones.js         # NUEVO orquestador, o sub-sección dentro de camera.js/settings.js
      rules-editor.js  # NUEVO: formulario when/actions + llamada a /test
  css/
    components.css     # añadir .zone-editor, .vertex-handle, .modal (no existe hoy)
```

### Patrón 1: Coordenadas normalizadas ya establecidas — no reinventar

**Qué:** El pipeline YA consume zonas como fracciones `[0,1]` y las multiplica por el tamaño de frame actual en cada rebuild (`backend/pipeline/detection.py:527`: `p[0]*fw, p[1]*fh`). Esto es exactamente lo que exige el criterio de éxito 7 (720p→1080p).
**Cuándo usar:** Todo dato de vértice/punto que el editor envíe al backend debe ser fracción `float` en `[0.0, 1.0]`, nunca píxeles absolutos.
**Ejemplo:**
```python
# Fuente: backend/pipeline/detection.py:521-538 (código real del proyecto)
pts = np.array(
    [[int(p[0] * fw), int(p[1] * fh)] for p in json.loads(z["polygon_json"])],
    dtype=np.int64,
)
states.append({..., "zone": sv.PolygonZone(polygon=pts), ...})
```

### Patrón 2: Hot-reload thread-safe con flag "dirty"

**Qué:** `CameraPipeline.set_zones()` / `DetectionWorker.set_zones()` reemplazan la lista bajo lock y marcan `_zones_dirty = True`; el siguiente frame reconstruye los `PolygonZone`. Ya cumple el criterio 6 (<1s, sin reiniciar) para zonas — a ritmo de detección (~10-15 FPS), la recarga tarda como mucho un frame.
**Cuándo usar:** Mismo patrón para líneas — hoy `tracker.py:144` (`reconfigure_line`) ya tiene la mecánica pero solo se llama una vez al construir el pipeline, nunca desde un endpoint en caliente.
**Ejemplo:**
```python
# Fuente: backend/pipeline/detection.py:135-139 (código real)
def set_zones(self, zones: list[dict]) -> None:
    """Replace the active interest zones list. Thread-safe."""
    with self._lock:
        self._zones = list(zones)
        self._zones_dirty = True
```

### Patrón 3: Canvas superpuesto al MJPEG con corrección de letterboxing

**Qué:** `videoCanvas.js` ya resuelve "el `<img>` tiene `object-fit: cover`, así que el frame visible no coincide 1:1 con el tamaño mostrado" con `normalizedBoxToCanvasRect` (usa `naturalWidth/naturalHeight`, nunca `width/height`).
**Cuándo usar:** El editor de zonas necesita la función inversa: click en canvas (px mostrados) → fracción del frame fuente. Reutilizar el mismo `scale`/`offsetX`/`offsetY`.
**Ejemplo (inversión a escribir, mismo patrón):**
```javascript
// Basado en backend real: frontend/js/components/videoCanvas.js:86-101
function canvasClickToFrac(clickX, clickY, img, canvas) {
  const iw = img.naturalWidth, ih = img.naturalHeight;
  const cw = canvas.width, ch = canvas.height;
  const scale = Math.max(cw / iw, ch / ih);
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2, offsetY = (ch - drawH) / 2;
  return {
    x_frac: (clickX - offsetX) / drawW,
    y_frac: (clickY - offsetY) / drawH,
  };
}
```

### Anti-patrones a evitar

- **Guardar coordenadas en píxeles absolutos:** rompe el criterio 7 directamente y contradice el patrón ya establecido en `zones.polygon_json`.
- **Escribir el editor de reglas contra `config/rules.yaml` en disco:** introduce condiciones de carrera de escritura concurrente y dos fuentes de verdad (BD `rules` sin usar + YAML). Migrar a BD.
- **Un único `sv.LineZone` global reconfigurado:** no soporta "líneas" en plural (OPS-22 dice "líneas de conteo", y la tabla `lines` ya prevé varias por cámara con nombre propio). Diseñar para N líneas desde el principio, como ya se hizo con zonas (`_zone_states` es una lista).
- **Reinferir zoom/pan/`object-fit` con matemáticas nuevas:** ya existe `normalizedBoxToCanvasRect`; cualquier desviación es una fuente de bugs de desalineación entre lo dibujado y lo evaluado por el pipeline.

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por qué |
|---------|-------------|-----------------|-----|
| Punto-en-polígono, cruce de línea con dirección | Matemática de intersección de segmentos a mano | `sv.PolygonZone.trigger()` / `sv.LineZone.trigger()` (ya en uso) | Ya validado en producción por Fases 4/13/27; reinventar introduce bugs de bordes (vértices duplicados, polígonos no convexos) |
| Evaluación de reglas contra eventos | Reimplementar condiciones `when` para el modo test | `_matches(when, event)` de `backend/events/rules.py:72` | Es pura (no toca `_last_fired`/debounce), ya cubre event/zone/camera/time_range/days/min_confidence/duration_gte/person/payload — exactamente lo que necesita el "qué habría disparado" |
| Paginación/filtrado de eventos para el test de regla | Query SQL ad-hoc para "últimos 500 eventos" | `EventRepo.query(limit=500)` (ya existe, cursor-paginado) | Reutiliza índices ya declarados (`idx_events_ts`) y el mismo DTO que usa `/api/v2/events` |

**Idea clave:** las tres piezas de bajo nivel (geometría, evaluación de reglas, consulta de eventos) YA existen y están probadas. El trabajo real de esta fase es CRUD + UI + wiring, no algoritmos nuevos.

## Common Pitfalls

### Pitfall 1: Dos ORMs mapeando la misma tabla `zones` con columnas distintas
**Qué falla:** `backend/database.py:Zone` (legacy: `id, name, polygon_json, enabled, kind, created_at`) y `backend/storage/models.py:Zone` (v2: `id, camera_id, name, polygon, kind, schedule, enabled`) son DOS clases SQLAlchemy distintas apuntando a la MISMA tabla física `zones`, con columnas parcialmente solapadas (`polygon_json` TEXT vs `polygon` JSON son columnas *diferentes* en la misma fila).
**Por qué pasa:** Migración incremental v1→v2 (comentario explícito en `storage/models.py:174-176`: "Nullable [...] hasta que la edición de zonas se mueva a ZoneRepo").
**Cómo evitarlo:** Decidir en el discuss-phase (o en el plan) si esta fase por fin migra `/api/zones` a `ZoneRepo`/columna `polygon` (JSON) y deja `polygon_json` solo para lectura de compatibilidad, o si se sigue escribiendo en ambas columnas a la vez. No añadir una tercera variante.
**Señales de alerta:** Un zoom/kind que se ve en `/api/zones` pero no en `/api/v2/zones` (o viceversa) porque cada uno lee una columna distinta.

### Pitfall 2: `kind` de zona ya tiene un significado en producción que no es "counting/restricted/exclusion"
**Qué falla:** `backend/database.py:48-50` documenta que `kind == "exclude_objects"` ya se usa en producción (Fase 27) para marcar zonas donde los objetos nunca disparan `OBJECT_LEFT`. El vocabulario de `kind` que pide OPS-23 (`counting`, `restricted`, `exclusion`) puede chocar con ese valor ya en uso.
**Por qué pasa:** El campo `kind` se añadió primero para un caso de uso (mobiliario fijo / objetos) antes de que existiera el requisito de tipos de zona genéricos.
**Cómo evitarlo:** Al definir el enum de `kind` para el editor, verificar contra datos reales en BD (`SELECT DISTINCT kind FROM zones`) y decidir explícitamente si `exclude_objects` es un cuarto valor a mantener o se remapea a `exclusion`.
**Señales de alerta:** Zonas creadas en Fase 27 que dejan de excluir objetos correctamente tras esta fase.

### Pitfall 3: `RuleRepo`/`ZoneRepo` "existen" pero son código muerto
**Qué falla:** Es tentador asumir que como las clases ya están escritas y con tests indirectos, "solo hay que exponerlas". Pero cero código las instancia hoy — no hay garantía de que su contrato (p. ej. `RuleRepo.upsert(rule_id, name, enabled, definition)`) encaje sin fricción con `RuleEngine.reload()`, que espera objetos `Rule` (Pydantic), no dicts crudos de BD.
**Por qué pasa:** Se escribieron con la Fase 19/v2 en mente pero el wiring se pospuso.
**Cómo evitarlo:** Al usar `RuleRepo`, escribir explícitamente la función `rule_from_db_dict() -> Rule` (validación Pydantic) — no asumir que `definition JSON` ya tiene la forma exacta de `When`/`Action`.
**Señales de alerta:** `ValidationError` silenciosa al cargar reglas desde BD que "parecían" válidas.

### Pitfall 4: Migrar la línea de conteo de "una" a "N" es un cambio de forma en `PersonTracker`, no solo de config
**Qué falla:** `PersonTracker` hoy tiene un único atributo `_line_zone`; `get_counts()` devuelve `in_count`/`out_count` globales, no por línea. Añadir CRUD de líneas sin refactorizar esta clase deja el conteo roto (¿cuál línea cuenta qué?) o limita el editor a una sola línea, incumpliendo el plural de OPS-22.
**Por qué pasa:** El diseño original (Fase 4) asumía una única línea de conteo por cámara; el modelo de datos v2 (`lines` con `id`, `name`, `camera_id`) ya anticipaba más, pero el tracker nunca se actualizó.
**Cómo evitarlo:** Decisión explícita de alcance en el plan: ¿esta fase soporta N líneas con conteo independiente (refactor de `PersonTracker` similar a `_zone_states`), o solo mejora la edición visual de la línea única existente? Esto debe quedar como decisión bloqueada antes de planificar tareas, no descubrirse a mitad de implementación.
**Señales de alerta:** El plan asume "CRUD de líneas" sin tocar `tracker.py`.

### Pitfall 5: Aplicar cambios de línea hoy exige reinicio (`applies="restart_camera"`), inconsistente con el criterio de zonas
**Qué falla:** El criterio de éxito 6 solo menciona "zona" explícitamente, pero un editor visual de líneas que exige reiniciar la cámara para ver el cambio es una UX incoherente frente al de zonas (<1s, sin reiniciar) y probablemente sorprenderá al usuario.
**Por qué pasa:** `line_start_x_frac`/etc. se metabolizan hoy como ajustes de arranque (`config_schema.py:582`, `applies="restart_camera"`), no como estado mutable del pipeline — a diferencia de zonas.
**Cómo evitarlo:** Aplicar el mismo patrón `set_zones()`/dirty-flag a líneas (`reconfigure_line()` en `tracker.py:144` ya existe y es thread-safe, solo falta invocarlo desde un endpoint en caliente en vez de solo al construir el pipeline).
**Señales de alerta:** El plan deja `applies="restart_camera"` para líneas sin discutirlo — sería una limitación de producto no declarada.

### Pitfall 6: `_matches()` en `backend/events/rules.py` es función de módulo privada (prefijo `_`)
**Qué falla:** No se puede importar limpiamente desde `backend/api/v2/rules.py` sin violar la convención de "privado" o sin duplicar lógica.
**Por qué pasa:** Se escribió como helper interno de `RuleEngine.match()`, no pensado para reutilización externa cuando se escribió (Fase 19).
**Cómo evitarlo:** Exponerla explícitamente (quitar el guion bajo, o añadir un método público `RuleEngine.would_match(when, event)` / `test_rule(rule, events)` que la envuelva) como parte del trabajo de esta fase — no importar el símbolo privado tal cual desde otro módulo.
**Señales de alerta:** `from backend.events.rules import _matches` en código nuevo — señal de que falta hacer pública la API.

## Code Examples

### Cómo el pipeline ya resuelve el rebuild de zonas (referencia para el nuevo `set_lines`)
```python
# Fuente: backend/pipeline/detection.py:483-538 (código real del proyecto)
def _update_zones_and_heat(self, tracked, shape, captured_at=0.0, processed_at=0.0):
    fh, fw = shape[:2]
    with self._lock:
        dirty = self._zones_dirty
        self._zones_dirty = False
        zones_snap = list(self._zones)
    if dirty or self._zone_frame_size != (fw, fh):
        self._zone_frame_size = (fw, fh)
        self._rebuild_zone_states(zones_snap, fw, fh)
    ...
```

### `reconfigure_line`: ya existe el hot-swap de línea, solo falta wiring
```python
# Fuente: backend/tracker.py:144-... (nombre confirmado por grep, firma real)
def reconfigure_line(self, start: sv.Point, end: sv.Point) -> None:
    """Replace the LineZone with new pixel coordinates. Thread-safe."""
    with self._lock:
        self._line_zone = sv.LineZone(...)
```

### Evaluación pura de reglas, base para `/rules/{id}/test`
```python
# Fuente: backend/events/rules.py:72-102 (código real, firma completa)
def _matches(when: When, event: Event) -> bool:
    if when.event != event.type:
        return False
    if when.zone is not None and when.zone != event.zone_id:
        return False
    # ... camera, time_range, days, min_confidence, duration_gte, person, payload
    return True
```

## State of the Art

| Antes (código actual) | Estado propuesto por la fase | Cuándo cambia | Impacto |
|--------------|------------------|---------------|--------|
| Zonas vía `/api/zones` (v1, `database.py:Zone`) | CRUD unificado `/api/v2/zones` sobre `ZoneRepo` (v2) | Esta fase (a decidir) | El grupo `zonas_definidas` de Ajustes (`external_source="/api/zones"`) debe apuntar a la ruta final elegida |
| 1 línea de conteo global, `applies=restart_camera` | N líneas por cámara, hot-reload | Esta fase | Refactor de `PersonTracker` (ver Pitfall 4) |
| Reglas en `config/rules.yaml`, solo lectura vía `/api/v2/rules` (GET) | Reglas en tabla `rules`, CRUD completo + `/test` | Esta fase | `RuleEngine.reload()` pasa a alimentarse de BD en vez de (o además de) YAML al arrancar |

**Obsoleto tras esta fase (si se toman las decisiones anteriores):**
- `config/rules.yaml` como única fuente de verdad — pasaría a ser, como mucho, semilla inicial (`scripts/generate_initial_rules.py` ya existe para eso).
- `applies="restart_camera"` en los 4 campos `line_*_frac` de `config_schema.py` — si se implementa hot-reload de líneas, ya no aplica.

## Assumptions Log

| # | Afirmación | Sección | Riesgo si es incorrecta |
|---|-------|---------|---------------|
| A1 | El editor de zonas/líneas debe montarse en la pestaña "Cámara" (sobre `#camera-feed`) y no en Ajustes ni en una pestaña nueva | Architecture Patterns / estructura de ficheros | Bajo — es una decisión de UI que el plan puede fijar explícitamente sin afectar backend; pero cambia qué ficheros JS se tocan |
| A2 | Esta fase debe soportar múltiples líneas de conteo (no solo mejorar la edición de la línea única existente) | Pitfall 4 | Alto — si la decisión real es "solo una línea, mejor editada", el refactor de `PersonTracker` es trabajo innecesario; si la decisión es "N líneas" y no se planifica el refactor, el criterio OPS-22 (plural) queda incumplido |
| A3 | La migración de reglas de YAML a tabla `rules` es aceptable (no hay compromiso operativo de mantener `rules.yaml` como fuente editable a mano en producción) | State of the Art | Medio — si el usuario edita `rules.yaml` manualmente en producción hoy, migrar a BD sin plan de sincronización rompería ese flujo |

## Open Questions (RESOLVED)

1. **¿Dónde vive el editor en la navegación de 4 pestañas?**
   - Qué sabemos: `nav.js` tiene Operaciones/Analítica/Cámara/Ajustes; Ajustes ya tiene un grupo "Zonas definidas" (solo lectura) y "Reglas cargadas" (solo lectura) apuntando a `external_source`.
   - Qué no está claro: si el editor visual (canvas) sustituye esas listas de solo lectura dentro de Ajustes, o si vive como modal lanzado desde la pestaña Cámara (donde está el feed grande `#camera-feed`), o si necesita una pestaña propia.
   - Recomendación: decidirlo en discuss-phase antes de planificar tareas de frontend — condiciona qué ficheros JS/HTML se tocan y si `#tracks-overlay` se reutiliza o se crea un canvas nuevo sobre `#camera-feed`.
   - **RESOLVED: ver 33-CONTEXT.md D-03** — el editor vive dentro de la vista Cámara (no en Ajustes ni en pestaña nueva), como panel/sub-vista que reutiliza el frame de vídeo en vivo (extensión del patrón de `videoCanvas.js`). Las subsecciones de solo lectura de Ajustes se mantienen como listado/resumen con enlace al editor real.

2. **¿La migración de `/api/zones` (v1) a `/api/v2/zones` (ZoneRepo) es parte de esta fase o se mantiene el v1 y se añade v2 en paralelo?**
   - Qué sabemos: ambas rutas escriben a la misma tabla física con columnas distintas (Pitfall 1).
   - Qué no está claro: si mantener las dos rutas coexistiendo introduce inconsistencia visible al usuario (zona creada por una no aparece en la otra).
   - Recomendación: unificar en `/api/v2/zones` sobre `ZoneRepo`/columna `polygon`, con migración de datos de `polygon_json`→`polygon` si hay filas existentes, y dejar `/api/zones` como alias de compatibilidad o eliminarlo si nada más lo consume (verificar `frontend/*.js` primero).
   - **RESOLVED: ver 33-CONTEXT.md D-02** — unificar en el modelo v2 (`storage/models.py:Zone` + `ZoneRepo`). El editor visual escribe y lee únicamente contra el esquema v2; el modelo legacy de `database.py` queda fuera de esta fase salvo verificación previa de qué código v1 sigue usándolo (documentar como riesgo conocido si algo v1 lo usa activamente, sin migrarlo a ciegas). Si `/api/zones` (v1) se unifica o coexiste con `/api/v2/zones` queda a discreción del planificador (33-CONTEXT.md "Claude's Discretion").

3. **¿Cuántos eventos históricos hay realmente disponibles para probar `/rules/{id}/test` con datos reales?**
   - Qué sabemos: el endpoint debe evaluar "los últimos 500 eventos" (RULE-05/criterio 5).
   - Qué no está claro: si el volumen de eventos en `data/events.db` en desarrollo es suficiente para verificar el comportamiento sin generar eventos sintéticos.
   - Recomendación: el plan de verificación debería incluir un fixture/seed de eventos de prueba (pytest) más que depender de datos reales de la cámara.
   - **RESOLVED: ver 33-CONTEXT.md "Claude's Discretion"** — si el volumen de eventos reales no basta para una prueba significativa, usar `scripts/seed_events.py` (ya existe, usado en la Fase 30) en vez de inventar un generador ad hoc. Los tests automatizados (33-06) mockean `EventRepo.query`; el volumen real solo importa para el checkpoint manual (33-14).

## Environment Availability

Fase de código/config sin dependencias externas nuevas (no se instala nada; `supervision` y FastAPI ya están en el entorno y verificados arriba). Sección omitida por no aplicar.

## Validation Architecture

### Test Framework

| Propiedad | Valor |
|----------|-------|
| Framework | pytest (`[VERIFIED: pytest.ini presente en raíz]`) |
| Config file | `pytest.ini` + `tests/conftest.py` |
| Comando rápido | `.venv/Scripts/python.exe -m pytest tests/test_rule_engine.py tests/test_config_api.py -q` |
| Suite completa | `.venv/Scripts/python.exe -m pytest tests/ -v` |

### Mapa Requisitos de fase → Tests

| Req ID | Comportamiento | Tipo de test | Comando automatizado | ¿Fichero existe? |
|--------|----------|-----------|-------------------|-------------|
| OPS-21 | CRUD de zona persiste polígono normalizado y recarga pipeline sin reinicio | integration | `pytest tests/test_zones_api.py -x -q` | ❌ Wave 0 |
| OPS-22 | CRUD de línea con dirección, N líneas por cámara | integration | `pytest tests/test_lines_api.py -x -q` | ❌ Wave 0 |
| OPS-23 | Zona con `kind` + `schedule`, filtrado correcto por horario | unit | `pytest tests/test_zones_api.py::test_zone_kind_and_schedule -x -q` | ❌ Wave 0 |
| OPS-24 | Regla creada por formulario valida en servidor antes de guardar | unit | `pytest tests/test_rules_api.py -x -q` | ❌ Wave 0 |
| RULE-05 | `POST /rules/{id}/test` reporta cuántos de los últimos 500 eventos habrían disparado | integration | `pytest tests/test_rules_api.py::test_rule_test_endpoint -x -q` | ❌ Wave 0 |
| Criterio 6 (hot-reload <1s) | Cambiar zona no reinicia el pipeline, se refleja en el siguiente frame | integration | `pytest tests/test_detection_config_api.py -k zones -x -q` (extender el existente) | ⚠ Fichero existe (`test_detection_config_api.py`), caso nuevo |
| Criterio 7 (720p→1080p) | Zona dibujada a 720p da el mismo punto físico a 1080p | unit | `pytest tests/test_detection.py -k zone_frac -x -q` | ❌ Wave 0 (o añadir a fichero existente si `test_detection.py` ya cubre `_rebuild_zone_states`) |

### Frecuencia de muestreo
- **Por commit de tarea:** comando rápido de arriba.
- **Por merge de wave:** suite completa.
- **Puerta de fase:** suite completa en verde antes de `/gsd-verify-work`.

### Huecos detectados para Wave 0
- [ ] `tests/test_zones_api.py` — cubre OPS-21, OPS-23
- [ ] `tests/test_lines_api.py` — cubre OPS-22
- [ ] `tests/test_rules_api.py` — cubre OPS-24, RULE-05
- [ ] Fixture de eventos sintéticos en `tests/conftest.py` (o fichero dedicado) para poblar el histórico que consume `/rules/{id}/test`
- El frontend (canvas, drag de vértices) no tiene cobertura automatizada en esta fase (Playwright llega en Fase 34) — verificación manual/checkpoint visual, como ya es costumbre en fases de frontend anteriores (32-08).

## Security Domain

### Categorías ASVS aplicables

| Categoría ASVS | Aplica | Control estándar |
|---------------|---------|-----------------|
| V2 Autenticación | Ya cubierto globalmente | `Depends(verify)` a nivel de `FastAPI(...)`, heredado automáticamente por cualquier router nuevo (confirmado en `backend/api/v2/events.py` docstring) |
| V3 Gestión de sesión | No aplica de forma distinta | Sin cambios frente al resto de `/api/v2` |
| V4 Control de acceso | Ya cubierto | Mismo modelo de auth de un solo operador que el resto del dashboard (no hay roles) |
| V5 Validación de entrada | Sí | Reutilizar modelos Pydantic `Rule`/`When`/`Action` para validar reglas en servidor (OPS-24 lo exige explícitamente); validar polígonos (mínimo 3 puntos, fracciones en `[0,1]`) igual que ya hace `api_upsert_zone` en `main.py:1108-1126` |
| V6 Criptografía | No aplica | Sin secretos nuevos en esta fase |

### Patrones de amenaza conocidos para este stack

| Patrón | STRIDE | Mitigación estándar |
|---------|--------|---------------------|
| Polígono/línea con coordenadas fuera de `[0,1]` o degenerado (<3 puntos, línea de longitud 0) | Tampering | Validación de rango server-side antes de persistir (ya existe precedente en `main.py:1119-1125` para zonas v1: `if not isinstance(pts, list) or len(pts) < 3: raise ValueError`) |
| Regla con `payload` arbitrario que intente inyectar claves no esperadas | Tampering | Los modelos Pydantic `When`/`Action` ya restringen campos (`Literal` en `Action.type`); mantener ese cierre al persistir desde formulario |
| Rate-limit en `/rules/{id}/test` (evalúa hasta 500 eventos, coste no trivial) | Denial of Service | Reutilizar `V2_RATE_LIMIT`/`limiter` de `backend/api/v2/deps.py`, mismo patrón que el resto de rutas `/api/v2/*` |

## Sources

### Primarias (confianza ALTA — código real leído en esta sesión)
- `backend/storage/repositories.py` (ZoneRepo, RuleRepo, EventRepo.query, AnalyticsRepo)
- `backend/storage/models.py` (Zone, Line, Rule — esquema v2)
- `backend/database.py` (Zone legacy, get_zones/upsert_zone/delete_zone)
- `backend/storage/migrations.py` (confirma columnas fusionadas en tabla física `zones`)
- `backend/pipeline/detection.py` (set_zones, _update_zones_and_heat, _rebuild_zone_states)
- `backend/pipeline/manager.py` (CameraPipeline.set_zones, CameraManager)
- `backend/tracker.py` (PersonTracker, LineZone único, reconfigure_line)
- `backend/events/rules.py` (When, Action, Rule, RuleEngine, _matches, load_rules)
- `backend/main.py` (rutas `/api/zones`, `/api/v2/rules` GET, wiring de rule_engine/event_pipeline)
- `backend/api/v2/config.py` y `backend/api/v2/config_schema.py` (line_*_frac con `applies="restart_camera"`, external_source de zonas/reglas)
- `frontend/js/components/videoCanvas.js` (patrón de canvas sobre MJPEG, letterboxing)
- `frontend/js/nav.js`, `frontend/js/views/camera.js` (estructura de pestañas y vista Cámara)
- `frontend/css/components.css` (ausencia confirmada de `.modal`/`.dialog`)
- `.planning/REQUIREMENTS.md` (texto exacto de OPS-21..24, RULE-05)
- `.planning/ROADMAP.md` líneas 637-650 (criterios de éxito de la fase)
- `propuesta_mejora/SPEC_v2.md` §6.4 y §7.1/§8.1 (esquema `rules.yaml`, tablas `zones`/`lines`/`rules`, endpoints `/api/v2/zones`, `/api/v2/lines`, `/api/v2/rules`, `/rules/{id}/test`)
- `supervision==0.27.0.post2` `[VERIFIED: .venv/Scripts/python.exe -c "import supervision"]`

No se usó Context7/WebSearch: todo el conocimiento necesario para planificar esta fase reside en el propio repositorio (arquitectura interna), no en documentación de librerías externas nuevas.

## Metadata

**Desglose de confianza:**
- Standard stack: ALTA — no se añade nada nuevo, todo verificado por import directo o grep del código en uso.
- Arquitectura (zonas): ALTA — patrón de hot-reload y normalización verificado línea a línea.
- Arquitectura (líneas): MEDIA — el patrón existe (`reconfigure_line`) pero requiere refactor de alcance no trivial (Pitfall 4) que debe decidirse, no solo ejecutarse.
- Arquitectura (reglas): MEDIA — el motor de evaluación es sólido, pero la migración YAML→BD es una decisión de producto, no solo técnica.
- Pitfalls: ALTA — todos derivados de código real leído en esta sesión, no de suposiciones genéricas.

**Fecha de investigación:** 2026-08-24
**Válida hasta:** el código base cambia con cada fase completada (ritmo ~1-2 semanas por fase según STATE.md); revalidar si Fase 32-08 (puerta de fase pendiente) introduce cambios en `config_schema.py` o `camera.js` antes de que arranque esta fase.
