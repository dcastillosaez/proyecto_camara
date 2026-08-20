# Phase 29: Vista de operaciones - Research

**Researched:** 2026-08-20
**Domain:** WebSocket push a 2Hz sobre pipeline existente (FastAPI + asyncio) + overlay `<canvas>` sobre `<img>` MJPEG en frontend vanilla JS, sin frameworks
**Confidence:** HIGH (todo lo determinante está verificado leyendo el código real del repo, no hay dependencias externas nuevas ni librerías que investigar en Context7)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Diseño visual (ya fijado por 29-UI-SPEC.md — aprobado, no volver a preguntar)**
- **D-01:** Sin frameworks/dependencias nuevas. Reutilizar Tailwind CDN, `components.css`, Chart.js CDN ya existentes (Fase 28). Ver `29-UI-SPEC.md` para tokens de spacing/tipografía/color completos.
- **D-02:** Anchor visual primario = panel de vídeo en directo (3/5 del grid), donde se dibuja el overlay de canvas. Los demás paneles son lectura secundaria, nunca compiten en atención.
- **D-03:** Barra de estado del pipeline extiende el triplete existente `#cam-status`/`#status-dot`/`#status-text` de binario (online/offline) a 3 estados (online/degradado/offline), usando la tabla semáforo de `29-UI-SPEC.md` (verde/ámbar/rojo). No añadir un cuarto estado.
- **D-04:** Panel "Alertas activas" muestra como máximo el top-3 por severidad — la línea temporal completa es Fase 30 (OPS-07/08/09), no construir aquí un centro de alertas completo.
- **D-05:** Panel "Personas ahora" lista identidades activas desde `TrackRegistry` (no desde histórico de eventos), cada fila con punto de estado semáforo + nombre o "Desconocido" + etiqueta de confirmación ("confirmado"/"verificando"/"desconocido").

**Overlay de tracks vía WebSocket (OPS-05, criterio de éxito 4)**
- **D-06:** Nuevo `<canvas>` posicionado absolutamente sobre `#video-feed`, `width`/`height` sincronizados con `clientWidth`/`clientHeight` del `<img>` renderizado (NO con la resolución fuente del MJPEG) — escalar coordenadas de bbox en consecuencia.
- **D-07:** Redibujado dirigido por un **nuevo tipo de mensaje WebSocket** (`type: "tracks"`) a **2 Hz exactos** — no más rápido, es un cap deliberado independiente del FPS del MJPEG, coherente con el invariante de desacoplo latest-frame del proyecto (ver CLAUDE.md invariantes 1-4).
- **D-08:** El canvas NUNCA debe re-renderizar ni recargar `#video-feed` — `img.src` solo lo tocan los caminos existentes de cambio de resolución / reintento de conexión, nunca el código del overlay.
- **D-09:** Color de trazo de cada bbox sigue la tabla semáforo de identidad (verde=CONFIRMED, ámbar=CANDIDATE, rojo=UNKNOWN/intrusión), 2px, rectángulo sin esquinas redondeadas. Etiqueta `.mono` 11px sobre fondo `rgba(0,0,0,0.6)` (copiar patrón exacto del badge de detección existente).

**WebSocket y reconexión (OPS-06, criterio de éxito 5)**
- **D-10:** El backoff exponencial (`_wsRetry` 1s→30s) YA existe en `frontend/js/websocket.js` (canal legacy `/ws`) — no reimplementar el algoritmo, solo reutilizarlo/extenderlo.
- **D-11:** El badge de estado del header (no solo la card de WS) debe reflejar también una desconexión WS prolongada (>1 ciclo de reconexión) como parte del cómputo de degradado/offline — visible arriba, donde mira primero el operador (criterio 6, reconocer en <3s).

### Claude's Discretion
- Qué canal WebSocket usar para el nuevo mensaje `tracks`: el legacy `/ws` (ya usado por `websocket.js` para eventos/init) o el `/api/v2/ws` (canal unificado v2, actualmente documentado en `backend/main.py:859` como "currently emits {"kind": "event", ...}; metrics/tracks/system follow later phases" — este comentario sugiere que `/api/v2/ws` es el canal pensado para `tracks`, pero verificar coste de mantener 2 conexiones WS simultáneas vs añadir el nuevo tipo de mensaje al canal legacy). → **Resuelto en este research: usar `/ws` legacy** (ver Summary y Open Questions #1).
- Qué worker del backend empuja el mensaje `tracks` a 2Hz: candidatos son un nuevo loop periódico en `CameraPipeline`/`manager.py` que lea `TrackRegistry.active_ids()`/`frame_ids()` (mismo patrón que `get_object_boxes()` en `manager.py:346`, que ya existe para objetos pero no hay equivalente `get_person_boxes()` para personas) y publique al set de clientes WS suscritos, con throttle a 500ms independiente del ritmo del `DetectionWorker`. → **Resuelto: bucle asyncio en `main.py` (no worker de pipeline), ver Pattern 1/2.**
- Formato exacto del payload `type: "tracks"` (lista de bboxes normalizados vs. píxeles absolutos, inclusión de `identity_state`/`person_name`/`track_id`) — el researcher debe proponerlo basándose en lo que `TrackRegistry`/`get_object_boxes()` ya exponen, para minimizar transformación adicional en el backend. → **Resuelto: bbox normalizado 0-1, ver Pattern 2/Code Examples.**
- Detalles exactos de cómo el header computa "degradado" (qué combinación de: WS caído, `capture_fps` bajo, `dropped` creciente, etc. — ver `/api/v2/cameras/{id}/health` ya existente) — no hay una fórmula fijada, es decisión técnica de la fase. → **Resuelto: `pipeline.degraded` + `health.connected` + estado WS, explícitamente sin `dropped`, ver Pitfall 3 y Open Questions #2.**

### Deferred Ideas (OUT OF SCOPE)
- Línea temporal de eventos completa, filtros combinables en servidor, paginación por cursor, agrupación/silenciado de alertas por regla — Fase 30 (OPS-07..OPS-11), explícitamente fuera de alcance del wireframe SPEC_v2 §8.3 en esta fase.
- Vista de analítica (heatmap, ranking, tendencias) — Fase 31.
- Vista de cámara y árbol de configuración visual — Fase 32.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| OPS-04 | La pantalla principal responde sin scroll a: si el sistema está bien, qué ocurre ahora y si ha pasado algo importante | Architectural Responsibility Map (fila "Estado degradado del header"), Pattern 1/2 (fórmula de degradado), Pitfall 3 |
| OPS-05 | El overlay de detecciones se dibuja sobre canvas alimentado por WebSocket, sin re-renderizar el stream MJPEG | Pattern 1 (publicador 2Hz), Pattern 2 (`get_person_boxes()`), Pattern 3 (mapeo `object-fit:cover`), Pitfall 1/2/5 |
| OPS-06 | La reconexión del WebSocket es automática y visible sin recargar la página | Don't Hand-Roll (backoff ya existe), Architectural Responsibility Map (fila "Reconexión WS visible"), Open Question #1 |
</phase_requirements>

## Summary

Fase 29 no introduce ninguna tecnología nueva: es composición de patrones que ya existen en el repo. El pipeline ya tiene un precedente pull-based idéntico al que necesita esta fase (`get_object_boxes()`, Fase 27) para exponer bboxes sin que ningún worker haga `await` ni ejecute inferencia fuera de su hilo. El backend ya tiene dos canales WebSocket (`/ws` legacy y `/api/v2/ws`, éste último sin ningún cliente todavía) y un bucle asyncio periódico ya registrado en `lifespan()` (`_housekeeping_loop`) que es el molde exacto para el nuevo publicador de tracks a 2 Hz. El frontend no tiene ningún precedente de overlay `<canvas>` sincronizado con un `<img>` — es territorio nuevo, pero es una técnica web estándar (no requiere librería) y el `object-fit:cover` ya presente en `#video-feed` obliga a resolver el mapeo de coordenadas correctamente o los bboxes quedarán desalineados.

Las cuatro preguntas delegadas a esta investigación por 29-CONTEXT.md (`## Claude's Discretion`) tienen respuesta clara a partir del código existente:

1. **Canal WS:** reutilizar `/ws` (legacy), no abrir `/api/v2/ws`. Ahora mismo `/api/v2/ws` tiene 0 clientes frontend (`grep` confirma que ningún fichero JS lo referencia); abrirlo añadiría una segunda conexión, un segundo timer de reconexión y un segundo estado "conectado/desconectado" que habría que reconciliar con el badge único del header (D-11) — coste sin beneficio medible en un dashboard LAN de una sola cámara.
2. **Worker/mecanismo:** un bucle `asyncio.create_task(...)` nuevo en `backend/main.py`, registrado en `lifespan()` junto a `_housekeeping_loop`/`_camera_watchdog`, que llama cada 500 ms a un nuevo método `CameraPipeline.get_person_boxes()` (mismo patrón exacto que `get_object_boxes()`, Fase 27) y hace `_broadcast(...)`. Ningún hilo del pipeline se toca; es 100% lectura bajo el `RLock` que `TrackRegistry` ya expone vía `snapshot()`/`frame_ids()`.
3. **Payload:** bbox normalizado 0–1 (no píxeles absolutos) relativo al frame de proceso (`process_size`), más `track_id`, `identity_state`, `person_name`. Normalizar en el backend evita que el frontend necesite conocer la resolución de proceso además de la resolución mostrada.
4. **Fórmula degradado:** combinar `pipeline.degraded` (ya existe, boolean, "algún worker FAILED") + `health.connected` (RTSP caído) + estado de reconexión WS ya trackeado en `websocket.js` — explícitamente **sin** usar `dropped` creciente como señal (CLAUDE.md invariante #4 dice literalmente que puede ser normal).

**Primary recommendation:** extender `/ws` con `type: "tracks"`, publicado por un bucle asyncio nuevo en `main.py` (no un worker de pipeline nuevo), con bbox normalizado 0–1, y resolver el overlay en frontend con `img.naturalWidth/naturalHeight` + `getBoundingClientRect()` para deshacer el crop de `object-fit:cover` — no hay atajo que lo evite dado que el CSS ya fuerza `aspect-ratio:16/9` + `object-fit:cover` en `#video-feed`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Publicación de tracks a 2Hz | API/Backend (asyncio loop en `main.py`) | Database/Storage (`TrackRegistry`, lectura) | Es un pull periódico sobre estado ya calculado por `DetectionWorker`; no pertenece a un worker de pipeline (esos son hilos, no corrutinas) ni al frontend (no puede calcular bboxes) |
| Cálculo de bbox por track | Database/Storage (`TrackRegistry` vía `DetectionWorker`) | — | Ya escrito por el pipeline existente (Fase 18/24/27); esta fase solo lee |
| Normalización de coordenadas (px→0-1) | API/Backend | — | El backend conoce `process_size` (vía `CameraPipeline.get_process_size()`); exponerlo evita acoplar el frontend a la resolución de proceso |
| Mapeo bbox normalizado → canvas píxeles mostrados | Browser/Client | — | Solo el navegador conoce `clientWidth/clientHeight` reales y el efecto de `object-fit:cover`; no se puede resolver en backend |
| Estado "degradado" del header | Browser/Client (agregación) | API/Backend (`/api/v2/cameras/{id}/health`, fuente de verdad de `degraded`/`connected`) | El backend calcula degradado de pipeline; el frontend combina eso con su propio estado de conexión WS (que el backend no puede observar) |
| Reconexión WS visible | Browser/Client | — | Ya implementado (`websocket.js`); esta fase solo lo conecta al header, no lo reimplementa |
| Panel "Personas ahora" (lista) | Browser/Client (render) | API/Backend (fuente: mismo mensaje `tracks` o `TrackRegistry` vía endpoint) | Puede alimentarse del mismo mensaje `tracks` — evita una segunda vía de datos para lo mismo |

## Standard Stack

Esta fase **no añade ninguna dependencia**. Todo el trabajo usa librerías ya presentes en `requirements.txt` y APIs nativas del navegador.

### Core (ya presentes, verificado en `requirements.txt`)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.115 | Endpoint WS existente (`/ws`), reutilizado sin cambios de firma | Ya es el framework del proyecto (CLAUDE.md) |
| websockets | >=12.0 | Transporte WS subyacente de Starlette/FastAPI | Ya en uso por `/ws` y `/api/v2/ws` |
| starlette (vía fastapi) | — | `WebSocket`, `WebSocketDisconnect` ya importados en `backend/main.py:15` | Sin cambios |

### Frontend (0 dependencias nuevas, HTML5 nativo)
| API | Purpose | Why Standard |
|-----|---------|--------------|
| `<canvas>` + `CanvasRenderingContext2D` | Dibujo de bboxes | Nativo, sin librería — coherente con "sin build step" |
| `ResizeObserver` | Detectar cambios de `clientWidth/clientHeight` del `<img>` (resize de ventana) | Nativo, soportado en todos los navegadores modernos (Chrome/Edge/Firefox 2020+); alternativa a `window.onresize` que también captura cambios de layout sin resize de ventana (p.ej. si el grid cambia de `grid-cols-1` a `grid-cols-5` en el breakpoint `lg`) |
| `img.naturalWidth` / `img.naturalHeight` | Resolución intrínseca del frame MJPEG actual, se actualiza sola cuando `img.src` cambia (cambio de resolución) | Nativo — evita que el backend tenga que empujar la resolución en cada mensaje `tracks` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `/ws` legacy para `tracks` | `/api/v2/ws` (ya existe, 0 clientes) | v2 es semánticamente "más limpio" y el comentario del código (`main.py:859`) lo sugiere, pero implica gestionar 2 conexiones WS + 2 timers de reconexión en el frontend para una ganancia arquitectónica que no se materializa hasta que haya multi-cámara real (Fase 35+). Descartado para esta fase por simplicidad (CLAUDE.md). |
| bbox normalizado 0-1 | bbox en píxeles absolutos de `process_size` | Píxeles absolutos obligarían al frontend a conocer también `process_size` (vía un fetch adicional a `/camera/resolutions` o duplicando el dato en cada mensaje `tracks`) para poder escalar — normalizado es autosuficiente |
| Bucle asyncio en `main.py` | Nuevo `TracksWorker` en `backend/pipeline/` (hilo) | Un hilo nuevo violaría el principio de "no worker nuevo para una operación que ya es pull, no productora" — `get_object_boxes()` (Fase 27) fue deliberadamente expuesto como método de `CameraPipeline`, no como worker, precisamente para este caso de uso |
| `ResizeObserver` | `window.addEventListener('resize', ...)` | `resize` de window no dispara si el layout cambia sin resize de ventana (p.ej. el grid pasa de 1 a 5 columnas en breakpoint `lg` al cargar en distintos anchos, o si DevTools se abre) — `ResizeObserver` sobre el propio `<img>` es más robusto y es la técnica recomendada actual para "seguir el tamaño de un elemento" |

**Installation:** ninguna — no hay `npm install` en este proyecto (frontend sin build step, backend usa `requirements.txt` ya congelado).

## Architecture Patterns

### System Architecture Diagram

```
DetectionWorker (hilo, ya existe)
  │  update_from_detections() escribe bbox/confidence
  ▼
TrackRegistry (RLock, ya existe)
  │  snapshot() / frame_ids() — SOLO LECTURA desde aquí en adelante
  ▼
CameraPipeline.get_person_boxes()  ← NUEVO, mismo patrón que get_object_boxes() (Fase 27)
  │  normaliza bbox a 0-1 usando get_process_size()
  ▼
_tracks_broadcast_loop()  ← NUEVA corrutina asyncio, registrada en lifespan()
  │  cada 500ms: pull → build payload → _broadcast(payload)
  ▼
_ws_clients (set[WebSocket], YA EXISTE — el mismo set que /ws usa hoy)
  │  ws.send_text(json) a cada cliente conectado
  ▼
frontend/js/websocket.js  onmessage → case 'tracks'  ← NUEVO case, conexión ya existente
  │
  ▼
frontend/js/components/videoCanvas.js  drawTracks(tracks)  ← NUEVO
  │  para cada track: bbox normalizado → coords canvas (deshaciendo object-fit:cover)
  ▼
<canvas> superpuesto a #video-feed (NUNCA toca img.src)
```

Camino paralelo, independiente, para el header:

```
websocket.js (onopen/onclose)          /api/v2/cameras/cam1/health (fetch periódico NUEVO)
  │  estado conexión WS                  │  { connected, degraded, capture_fps }
  └───────────────┬───────────────────────┘
                   ▼
        computeHeaderState() → 'online' | 'degraded' | 'offline'
                   ▼
        setCamStatus(state)  ← EXTENDER de binario a 3 estados (D-03)
```

### Recommended Project Structure

No se crean ficheros nuevos fuera de los ya locked por 28-CONTEXT.md (`tests/test_frontend_modules.py` fija la lista `LOCKED_JS`). Todo el trabajo de frontend es edición de módulos existentes:

```
backend/
├── pipeline/
│   └── manager.py          # + get_person_boxes() (mismo patrón que get_object_boxes())
└── main.py                 # + _tracks_broadcast_loop(), + case en lifespan(), sin endpoint nuevo

frontend/
├── index.html              # + <canvas id="tracks-overlay"> sobre #video-feed, + 3er estado en cam-status ya existente
└── js/
    ├── websocket.js         # + case 'tracks' en onmessage (case 'system'/health si se decide push-based)
    ├── views/
    │   └── dashboard.js      # setCamStatus() extendido a 3 estados
    └── components/
        └── videoCanvas.js    # + drawTracks(), + sync canvas↔img (ResizeObserver)
```

**Nota:** si el plan decide crear un nuevo fichero (p.ej. `frontend/js/components/tracksOverlay.js`), debe actualizar `LOCKED_JS` en `tests/test_frontend_modules.py` — ese test falla si aparece un módulo `.js` no listado ahí (verificar exactamente qué comprueba antes de asumir; ver `## Common Pitfalls`).

### Pattern 1: Publicador pull-only a ritmo fijo (backend)

**What:** Corrutina asyncio que NO produce datos, solo lee estado ya calculado por un hilo, a un ritmo propio desacoplado del productor.
**When to use:** Cuando se necesita empujar un snapshot periódico de estado compartido sin que el consumidor (WS) tenga que sondear y sin que el productor (DetectionWorker) sepa que existe un consumidor WS.
**Example — molde ya existente a copiar literalmente:**
```python
# Source: backend/main.py:176-189 (_housekeeping_loop, patrón idéntico a replicar)
async def _housekeeping_loop(interval: float = 60.0) -> None:
    while True:
        await asyncio.sleep(interval)
        if camera_manager is None:
            continue
        now = time.monotonic()
        # ... solo lectura + limpieza, nunca await sobre el pipeline

# Registro en lifespan() — backend/main.py:540
housekeeping_task = asyncio.create_task(_housekeeping_loop(settings.housekeeping_secs))
# ...
yield
housekeeping_task.cancel()   # cancelación explícita en el shutdown — replicar para tracks
```
Nuevo bucle propuesto (mismo fichero, mismo patrón):
```python
async def _tracks_broadcast_loop(interval: float = 0.5) -> None:
    while True:
        await asyncio.sleep(interval)
        if camera_manager is None:
            continue
        for pipeline in camera_manager.all():
            boxes = pipeline.get_person_boxes()  # NUEVO método, solo lectura
            await _broadcast({
                "type": "tracks",
                "camera_id": pipeline.camera_id,
                "tracks": boxes,
            })
```

### Pattern 2: Método pull en `CameraPipeline`, no worker nuevo

**What:** Exponer estado ya calculado como método síncrono de solo lectura en `CameraPipeline`, en vez de crear un worker/hilo nuevo.
**When to use:** Cuando el dato ya existe en una estructura compartida con lock (`TrackRegistry`) y solo hace falta formatearlo.
**Example — precedente exacto (Fase 27):**
```python
# Source: backend/pipeline/manager.py:346-347
def get_object_boxes(self) -> list[dict]:
    return self.detection.get_object_boxes() if self.detection else []
```
```python
# Source: backend/pipeline/detection.py:162-165 (formato dict devuelto)
def get_object_boxes(self) -> list[dict]:
    with self._lock:
        return [dict(b) for b in self._object_boxes]
```
Nuevo método propuesto en `manager.py`, usando `TrackRegistry` directamente (no hace falta pasar por `DetectionWorker` porque `self.registry` ya es accesible desde `CameraPipeline`):
```python
def get_person_boxes(self) -> list[dict]:
    """Solo lectura. Usa frame_ids(), no snapshot() completo, para no arrastrar
    tracks que llevan hasta 30s sin verse (TrackRegistry.prune ttl) — el overlay
    debe reflejar SOLO lo visible en el frame actual (D-07/D-08)."""
    w, h = self.get_process_size()
    if w <= 0 or h <= 0:
        w, h = self.get_native_resolution()
    if w <= 0 or h <= 0:
        return []
    visible = self.registry.frame_ids()
    out = []
    for tid, ts in self.registry.snapshot().items():
        if tid not in visible:
            continue
        x1, y1, x2, y2 = ts.bbox
        out.append({
            "track_id": tid,
            "bbox": [x1 / w, y1 / h, x2 / w, y2 / h],
            "identity_state": ts.identity_state.value,
            "person_name": ts.person_name,
        })
    return out
```

### Pattern 3: Sincronizar `<canvas>` con `<img>` bajo `object-fit:cover`

**What:** El canvas debe tener el mismo tamaño en píxeles CSS que el `<img>` (`clientWidth`/`clientHeight`, per D-06), pero los bboxes normalizados están en el espacio del frame fuente (`process_size`), y `object-fit:cover` recorta ese frame para llenar la caja — sin corregir el recorte, los bboxes quedan desplazados.
**When to use:** Siempre que se dibuje sobre un `<img>`/`<video>` con `object-fit:cover`.
**Example (técnica estándar, sin librería — no hay precedente en el repo, ver Pitfall 1):**
```javascript
// Source: patrón estándar (MDN object-fit + canvas overlay), no hay precedente en el repo
function syncCanvasToImage(canvas, img) {
  const rect = img.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;
}

function normalizedBoxToCanvasRect(box, img, canvas) {
  const iw = img.naturalWidth, ih = img.naturalHeight;   // resolución del frame fuente
  const cw = canvas.width, ch = canvas.height;             // caja mostrada (object-fit:cover)
  const scale = Math.max(cw / iw, ch / ih);                // "cover" = max, no min
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2;                          // recorte centrado (comportamiento default de object-fit)
  const offsetY = (ch - drawH) / 2;

  const [x1, y1, x2, y2] = box;                              // ya normalizado 0-1
  return {
    x: offsetX + x1 * iw * scale,
    y: offsetY + y1 * ih * scale,
    w: (x2 - x1) * iw * scale,
    h: (y2 - y1) * ih * scale,
  };
}
```
Reaccionar a resize sin librería:
```javascript
const ro = new ResizeObserver(() => syncCanvasToImage(canvas, img));
ro.observe(img);
```

### Anti-Patterns to Avoid

- **Escalar por `img.width`/`img.height` (atributos HTML) en vez de `naturalWidth`/`naturalHeight`:** esos atributos reflejan el tamaño *mostrado*, no el intrínseco — usarlos para el cálculo de `scale` produce un resultado circular sin sentido.
- **Recalcular `process_size` en cada mensaje `tracks`:** el backend ya lo conoce vía `get_process_size()`; no hace falta que el frontend lo pida por separado si el bbox va normalizado (ver Pattern 3 — solo hace falta `naturalWidth/naturalHeight`, que el propio `<img>` ya expone).
- **Tratar `dropped` creciente como señal de degradado:** CLAUDE.md invariante #4 dice explícitamente que puede ser normal (el broker descarta frames antes que acumular latencia) — usarlo en la fórmula de "degradado" generaría falsos positivos permanentes.
- **Abrir una segunda conexión WS (`/api/v2/ws`) "porque el comentario lo sugiere":** ver `## Open Questions` — es una opción válida a futuro, no una obligación de esta fase.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Backoff exponencial de reconexión WS | Un segundo algoritmo de retry | El `_wsRetry` ya implementado en `frontend/js/websocket.js:8,71-75` | D-10 ya lo fija explícitamente — reimplementarlo duplicaría lógica ya correcta |
| Detección de resize de un elemento | Polling con `setInterval` sobre `getBoundingClientRect()` | `ResizeObserver` nativo | API del navegador diseñada exactamente para esto, sin coste de polling |
| Formato de eventos WS | Un tercer formato de mensaje | Extender el `switch`/`if-else` de `onmessage` ya existente en `websocket.js:45-69` con un `case`/`else if` más | Coherente con cómo ya se añadieron `recording_started`/`recording_uploaded`/`recording_failed` en fases previas — mismo patrón, no rediseñar el dispatcher |

**Key insight:** esta fase es 100% composición de patrones ya presentes; el único código genuinamente nuevo (sin precedente en el repo) es el mapeo `object-fit:cover` del Pattern 3, porque nunca antes se dibujó sobre el vídeo en este proyecto (confirmado: `grep -rn "canvas" frontend/` solo encuentra el `<canvas>` de Chart.js, no relacionado).

## Common Pitfalls

### Pitfall 1: Asumir que sincronizar tamaño de canvas basta para alinear bboxes
**What goes wrong:** El canvas queda del tamaño correcto pero los bboxes aparecen desplazados o mal escalados.
**Why it happens:** `object-fit:cover` (ya presente en `#video-feed`, `frontend/index.html:58`) recorta el frame fuente para llenar la caja mostrada; igualar `canvas.width/height` a `clientWidth/clientHeight` no deshace ese recorte — hace falta el cálculo de `scale`+`offset` del Pattern 3.
**How to avoid:** Usar `img.naturalWidth/naturalHeight` (resolución real del frame MJPEG) + `Math.max()` para el factor de escala de `cover`, con offset centrado.
**Warning signs:** Los bboxes se ven consistentemente desplazados en una dirección, o el desajuste crece/decrece con el ancho de ventana.

### Pitfall 2: Mostrar boxes "fantasma" de personas que ya salieron de cuadro
**What goes wrong:** El overlay sigue dibujando un rectángulo verde/ámbar en la última posición conocida de alguien que ya no está en el vídeo.
**Why it happens:** `TrackRegistry.snapshot()` devuelve TODOS los tracks vivos (hasta el TTL de 30s de `prune()`), no solo los visibles en el frame actual — el `bbox` de un track no se actualiza si `DetectionWorker` deja de verlo en el frame, se queda congelado en la última posición.
**How to avoid:** Filtrar por `TrackRegistry.frame_ids()` (exacto, por-frame, ya existe para este mismo propósito en la FSM de identidad — ver `tracking.py:100-111`), no por `active_ids()`/`snapshot()` sin filtrar.
**Warning signs:** Un bbox se queda inmóvil en pantalla mientras la persona real ya no aparece en el vídeo.

### Pitfall 3: Confundir el `dropped` creciente con degradado real
**What goes wrong:** El header muestra "DEGRADADO" permanentemente aunque el sistema funcione con normalidad.
**Why it happens:** El diseño latest-frame del proyecto descarta frames deliberadamente cuando un consumidor no puede seguir el ritmo (CLAUDE.md invariante #4) — un `dropped` que crece es la prueba de que el desacoplo funciona, no de que algo falla.
**How to avoid:** Basar "degradado" en `pipeline.degraded` (worker `FAILED`) y `health.connected`/`capture_fps`, nunca en `dropped` en solitario.
**Warning signs:** El header parpadea a degradado bajo carga normal (varias pestañas abiertas, cliente lento) sin que ningún worker haya fallado.

### Pitfall 4: Añadir un módulo `.js` nuevo sin actualizar `LOCKED_JS`
**What goes wrong:** `tests/test_frontend_modules.py` puede fallar (o no detectar el módulo nuevo, según qué comprueba exactamente `TEST_*`) si el plan crea un fichero JS fuera de la lista fijada en Fase 28.
**Why it happens:** Fase 28 cerró (`status: locked`) la lista de módulos ES como parte del refactor a shell puro; ese test es la barrera mecánica que lo protege.
**How to avoid:** Preferir extender `videoCanvas.js`/`websocket.js`/`dashboard.js` (ya en `LOCKED_JS`) en vez de crear ficheros nuevos; si el plan decide crear uno nuevo, debe incluir la edición de `LOCKED_JS` en `tests/test_frontend_modules.py` como tarea explícita — verificar primero qué aserciona exactamente ese test antes de asumir que basta con añadir el nombre a la lista.
**Warning signs:** Un `TEST_*` de `test_frontend_modules.py` en rojo tras crear un fichero nuevo.

### Pitfall 5: Confundir throttle del backend (500ms) con framerate del canvas
**What goes wrong:** Se intenta "suavizar" el movimiento del overlay interpolando entre frames en el frontend, añadiendo complejidad no pedida.
**Why it happens:** 2Hz (500ms) es deliberadamente lento comparado con el MJPEG — D-07 lo fija como "cap deliberado independiente del FPS del MJPEG", coherente con el invariante latest-frame del proyecto.
**How to avoid:** Redibujar el canvas *solo* cuando llega un mensaje `tracks` (D-07) — no usar `requestAnimationFrame` ni temporizadores propios para redibujar entre mensajes.
**Warning signs:** Código de interpolación o `requestAnimationFrame` en el módulo del overlay sin que lo pida ningún criterio de éxito.

## Code Examples

### Nuevo case en el dispatcher de `websocket.js`
```javascript
// Source: patrón existente en frontend/js/websocket.js:45-69, extendido con nuevo caso
} else if (msg.type === 'tracks') {
  drawTracks(msg.tracks);   // nueva función exportada desde videoCanvas.js
}
```

### Test backend para el nuevo mensaje (patrón TestClient + WS, sin precedente exacto en el repo — ver Validation Architecture)
```python
# Source: patrón estándar de starlette.testclient.TestClient.websocket_connect
# (no hay test WS existente en tests/ para copiar literalmente — confirmado via grep)
from starlette.testclient import TestClient

def TEST_tracks_message_shape():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # init
            msg = ws.receive_json()  # primer 'tracks' tras <=500ms
            assert msg["type"] == "tracks"
            assert "camera_id" in msg
            for t in msg["tracks"]:
                assert 0.0 <= t["bbox"][0] <= 1.0
```

## State of the Art

No aplica — no hay una versión "antigua" de este mecanismo en el repo (es funcionalidad nueva, no una migración).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Reutilizar `/ws` legacy en vez de `/api/v2/ws` para `type:"tracks"` es la opción preferible pese al comentario en `main.py:859` que sugiere v2. | Summary, Standard Stack > Alternatives | Si el equipo prefiere alinear con la intención documentada de v2 (separar "compat legacy" de "canal moderno"), el plan tendría que abrir la segunda conexión y resolver la reconciliación de 2 estados de conexión en el header (D-11) — más trabajo, pero no bloqueante, ambas rutas son técnicamente viables |
| A2 | El "degradado" del header se computa en frontend combinando un fetch periódico nuevo a `/api/v2/cameras/cam1/health` + estado de WS, en vez de que el backend empuje un mensaje `type:"system"` por WS. | Architecture Patterns (diagrama), Common Pitfalls #3 | Si se prefiere push-based (evitar polling adicional), hace falta un segundo bucle asyncio análogo a `_tracks_broadcast_loop` que emita `system`/`health` — mismo patrón, coste adicional menor, decisión de diseño abierta, no técnica |
| A3 | El intervalo de fetch del health-check frontend (si se opta por polling, A2) no está fijado — se sugiere 3-5s (más rápido que `loadHealth()` a 30s, similar a `loadObservability()` a 5s) por ser la señal que alimenta un indicador crítico (<3s de reconocimiento, criterio 6). | Architecture Patterns | Un intervalo demasiado largo (p.ej. 30s) retrasaría la detección visual de degradado más allá del criterio de éxito 6 |
| A4 | `TEST_*` es el patrón de naming de test functions en todo el repo (confirmado vía `pytest.ini`: `python_functions = TEST_*`), y `asyncio_mode = auto` permite `async def TEST_*` sin decorador — aplicable también a los tests WS nuevos de esta fase. | Validation Architecture, Code Examples | Bajo riesgo — verificado directamente en `pytest.ini`, no es una suposición real sino un hecho confirmado; se deja en el log por completitud dado que ningún test WS existente lo demuestra en la práctica |

## Open Questions

1. **¿`/ws` legacy o `/api/v2/ws` para `tracks`?**
   - What we know: `/api/v2/ws` existe, documentado explícitamente para esto, pero tiene 0 clientes hoy; `/ws` ya tiene toda la infraestructura de reconexión/badges en uso.
   - What's unclear: si hay un plan a medio plazo (Fase 30+) de migrar `/ws` legacy a v2 por completo, en cuyo caso empezar a usar v2 ahora evitaría una migración doble.
   - Recommendation: usar `/ws` para esta fase (menor coste, cero migración); si Fase 30/31 confirman que v2 es el futuro del canal de eventos, revisar entonces con todo el tráfico WS junto, no solo `tracks`.

2. **¿Polling frontend de `/api/v2/cameras/{id}/health` o push-based `type:"system"` por WS para el degradado del header?**
   - What we know: el endpoint REST ya existe y ya devuelve exactamente `degraded`/`connected`/`capture_fps` sin cambios de backend.
   - What's unclear: si añadir un fetch periódico nuevo (frontend) es preferible a añadir un segundo mensaje WS (backend) en términos de la filosofía "simplicidad" de CLAUDE.md — ambos son de complejidad comparable.
   - Recommendation: polling REST cada 3-5s (Assumption A2/A3) — no requiere tocar `_broadcast`/`main.py` más que lo estrictamente necesario para `tracks`, y el endpoint ya existe probado.

3. **¿Debe "Personas ahora" reusar el mismo mensaje `tracks` o pedir su propio endpoint/mensaje?**
   - What we know: el mensaje `tracks` ya trae `track_id`/`identity_state`/`person_name` — exactamente los campos que D-05 pide para cada fila del panel.
   - What's unclear: si el plan prefiere desacoplar el overlay visual (2Hz, solo mientras el vídeo está en pantalla) del panel de lista (que podría necesitar persistir aunque el canvas no se repinte) — son consumidores distintos del mismo dato.
   - Recommendation: reusar el mismo mensaje `tracks` para ambos consumidores (un solo `case 'tracks'` en `websocket.js` que llama a `drawTracks()` y a `renderPersonList()`) — evita una segunda fuente de verdad para el mismo estado.

## Environment Availability

Fase sin dependencias externas nuevas — todo el trabajo usa librerías Python ya instaladas (`fastapi`, `websockets`, `starlette`, todas presentes en `requirements.txt` con las versiones ya usadas por `/ws`) y APIs nativas del navegador (`<canvas>`, `ResizeObserver`, `WebSocket`). No aplica tabla de disponibilidad.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=7.0 + pytest-asyncio >=0.24 (backend). **No hay framework de test JS** (confirmado: sin `package.json`, ver `tests/test_frontend_modules.py` docstring) |
| Config file | `pytest.ini` — `python_functions = TEST_*`, `asyncio_mode = auto` |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/test_main.py -k tracks -q` (ajustar nombre de fichero/patrón según dónde se coloquen los tests nuevos) |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-04 | Header refleja 3 estados (online/degradado/offline) según señales del pipeline | unit (backend: fórmula de degradado si se extrae a función pura) | `pytest tests/test_main.py::TEST_camera_health_degraded_shape -q` | ❌ Wave 0 |
| OPS-05 | Mensaje `type:"tracks"` se emite por `/ws` con bbox normalizado 0-1 | integration (WS) | `pytest tests/test_main.py::TEST_tracks_message_shape -q` | ❌ Wave 0 |
| OPS-05 | `get_person_boxes()` filtra por `frame_ids()`, no incluye tracks stale | unit (pipeline) | `pytest tests/test_manager.py::TEST_get_person_boxes_excludes_stale_tracks -q` | ❌ Wave 0 (verificar si `tests/test_manager.py` ya existe) |
| OPS-06 | Reconexión WS visible sin recargar — comportamiento de `websocket.js` | manual-only | — (sin runner JS en el repo; ver Pitfall en `test_frontend_modules.py`) | manual checklist en SUMMARY de la puerta de fase, mismo patrón que Fase 28 |
| Overlay canvas alineado con `object-fit:cover` | visual, no automatizable sin runner JS/browser | manual-only | — | manual checklist |

### Sampling Rate
- **Per task commit:** `pytest tests/test_main.py -k tracks -q` (o el fichero donde acaben los tests nuevos)
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Suite completa en verde antes de `/gsd-verify-work`, más el checklist manual de paridad visual (mismo patrón que 28-09-PLAN.md) dado que no hay runner JS/E2E en este proyecto todavía (Fase 34 lo introduce)

### Wave 0 Gaps
- [ ] Confirmar si existe `tests/test_manager.py` — si no, decidir en qué fichero van los tests de `get_person_boxes()` (candidato: mismo fichero que ya testea `manager.py`, verificar con `ls tests/`)
- [ ] No hay ningún test con `client.websocket_connect(...)` en el repo hoy — el primer test WS de esta fase es también el primer precedente; documentarlo como tal en el PLAN para que quien lo escriba sepa que no hay ejemplo previo que copiar literalmente
- [ ] Framework install: ninguno — pytest/pytest-asyncio ya instalados

## Security Domain

Proyecto de dashboard LAN, sin exposición pública (CLAUDE.md: "Red: LAN; no exposición pública"). `security_enforcement` no está presente en `.planning/config.json` (tratar como activo por defecto según la instrucción del agente), pero el propio CLAUDE.md ya fija el modelo de amenaza del proyecto — no hay indicación de que esta fase requiera ampliar ASVS más allá de lo ya implementado.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | ya cubierto, sin cambios | `verify_ws_token`/`issue_ws_token` (`backend/auth.py`) ya protege `/ws` y `/api/v2/ws` — el nuevo mensaje `tracks` viaja por una conexión ya autenticada, no requiere nada nuevo |
| V3 Session Management | ya cubierto, sin cambios | Token WS de un solo uso (`/api/ws-token`), sin cambios en esta fase |
| V4 Access Control | n/a | Dashboard de un solo operador/rol, sin cambios de superficie |
| V5 Input Validation | n/a (server→client only) | El mensaje `tracks` es unidireccional servidor→cliente; no hay input del cliente que validar en el WS más allá del `receive_text()` de keepalive ya existente |
| V6 Cryptography | ya cubierto, sin cambios | WSS vía el mismo TLS/reverse-proxy que ya cubre `/ws` (si está configurado) — esta fase no introduce datos sensibles nuevos (bboxes de personas ya visibles en el MJPEG que ya se sirve) |

### Known Threat Patterns for este stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Cliente WS no autenticado leyendo posiciones de personas en tiempo real | Information Disclosure | Ya mitigado — `verify_ws_token` en el `accept()` de `/ws`, sin cambios necesarios |
| Broadcast a un cliente desconectado (excepción no controlada) | Denial of Service (parcial) | Ya mitigado — `_broadcast()` ya captura excepciones por cliente y limpia `_ws_clients` (`backend/main.py:79-88`), el nuevo bucle de tracks reutiliza esa misma función sin cambios |

## Sources

### Primary (HIGH confidence — código del propio repo, leído directamente en esta sesión)
- `backend/pipeline/tracking.py` — estructura completa de `TrackRegistry`/`TrackState`
- `backend/pipeline/manager.py` — `CameraPipeline`, `get_object_boxes()`, `stats()`, `get_process_size()`
- `backend/pipeline/detection.py` — formato exacto de `_object_boxes` (precedente de payload)
- `backend/pipeline/streaming.py` — confirmación de que MJPEG se sirve en resolución `process_size`, no nativa
- `backend/main.py` — endpoints `/ws`, `/api/v2/ws`, `/api/v2/cameras/{id}/health`, `lifespan()`, `_broadcast()`, `_housekeeping_loop` (molde del nuevo bucle)
- `backend/camera.py` — `RESOLUTIONS` (confirma aspect ratio ~16:9 consistente)
- `frontend/js/websocket.js` — backoff, badges, dispatcher `onmessage`
- `frontend/js/components/videoCanvas.js` — sitio natural para el overlay, sin overlay hoy
- `frontend/index.html` — `object-fit:cover` en `#video-feed`, `#cam-status`/`#status-dot`/`#status-text`, grid `lg:grid-cols-5`
- `tests/test_frontend_modules.py` — `LOCKED_JS`, convención `TEST_*`
- `pytest.ini` — `python_functions = TEST_*`, `asyncio_mode = auto`
- `requirements.txt` — versiones confirmadas de fastapi/websockets/pytest-asyncio

### Secondary (MEDIUM confidence)
- Técnica `object-fit:cover` + canvas overlay (Pattern 3): técnica estándar de la plataforma web, sin librería — no verificada contra documentación externa en esta sesión (no había necesidad, es matemática de geometría 2D estándar, no una API dudosa), pero tampoco tiene precedente en el repo que la confirme empíricamente para este proyecto en concreto — de ahí que quede fuera del log de assumptions (es geometría, no una decisión de producto) pero se marca aquí como "sin precedente local".

### Tertiary (LOW confidence)
- Ninguna — no se usó WebSearch en esta investigación; todo lo determinante estaba verificable en el propio código.

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — no hay dependencias nuevas, todo verificado por grep directo en `requirements.txt` y el código
- Architecture: HIGH — cada patrón propuesto tiene un precedente literal en el repo (`get_object_boxes`, `_housekeeping_loop`, `websocket.js` dispatcher)
- Pitfalls: HIGH para los backend (verificados en código: `frame_ids()` vs `snapshot()`, invariante `dropped`); MEDIUM para el pitfall de `object-fit:cover` (es conocimiento de plataforma web estándar, sin precedente local que lo confirme empíricamente en este proyecto)

**Research date:** 2026-08-20
**Valid until:** estable mientras no cambie el pipeline de tracking (Fase 24/27) o el layout de `index.html` — sin fecha de caducidad corta, no depende de librerías de terceros con ritmo de release rápido
