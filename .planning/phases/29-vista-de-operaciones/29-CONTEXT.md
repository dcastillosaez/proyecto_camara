# Phase 29: Vista de operaciones - Context

**Gathered:** 2026-08-20
**Status:** Ready for planning
**Source:** Generado directamente por el orquestador a partir de ROADMAP.md, REQUIREMENTS.md, 29-UI-SPEC.md (ya aprobado) y una inspección del backend actual — sin sesión interactiva de `/gsd-discuss-phase` (suficiente contexto ya disponible).

<domain>
## Phase Boundary

Rediseñar la pantalla principal del dashboard para que responda en 3 segundos a las tres preguntas del operador: ¿está todo bien?, ¿qué ocurre ahora?, ¿ha pasado algo importante? Cubre: barra de estado del pipeline con 3 estados (online/degradado/offline), overlay de tracks sobre canvas alimentado por WebSocket a 2Hz sin re-renderizar el MJPEG, panel "Personas ahora" con identidades activas, panel compacto de alertas activas (top-3), y visibilidad de reconexión WebSocket. La línea temporal completa de eventos y el centro de alertas accionable (agrupar/silenciar por regla) son la Fase 30 — fuera de alcance aquí.

</domain>

<decisions>
## Implementation Decisions

### Diseño visual (ya fijado por 29-UI-SPEC.md — aprobado, no volver a preguntar)
- **D-01:** Sin frameworks/dependencias nuevas. Reutilizar Tailwind CDN, `components.css`, Chart.js CDN ya existentes (Fase 28). Ver `29-UI-SPEC.md` para tokens de spacing/tipografía/color completos.
- **D-02:** Anchor visual primario = panel de vídeo en directo (3/5 del grid), donde se dibuja el overlay de canvas. Los demás paneles son lectura secundaria, nunca compiten en atención.
- **D-03:** Barra de estado del pipeline extiende el triplete existente `#cam-status`/`#status-dot`/`#status-text` de binario (online/offline) a 3 estados (online/degradado/offline), usando la tabla semáforo de `29-UI-SPEC.md` (verde/ámbar/rojo). No añadir un cuarto estado.
- **D-04:** Panel "Alertas activas" muestra como máximo el top-3 por severidad — la línea temporal completa es Fase 30 (OPS-07/08/09), no construir aquí un centro de alertas completo.
- **D-05:** Panel "Personas ahora" lista identidades activas desde `TrackRegistry` (no desde histórico de eventos), cada fila con punto de estado semáforo + nombre o "Desconocido" + etiqueta de confirmación ("confirmado"/"verificando"/"desconocido").

### Overlay de tracks vía WebSocket (OPS-05, criterio de éxito 4)
- **D-06:** Nuevo `<canvas>` posicionado absolutamente sobre `#video-feed`, `width`/`height` sincronizados con `clientWidth`/`clientHeight` del `<img>` renderizado (NO con la resolución fuente del MJPEG) — escalar coordenadas de bbox en consecuencia.
- **D-07:** Redibujado dirigido por un **nuevo tipo de mensaje WebSocket** (`type: "tracks"`) a **2 Hz exactos** — no más rápido, es un cap deliberado independiente del FPS del MJPEG, coherente con el invariante de desacoplo latest-frame del proyecto (ver CLAUDE.md invariantes 1-4).
- **D-08:** El canvas NUNCA debe re-renderizar ni recargar `#video-feed` — `img.src` solo lo tocan los caminos existentes de cambio de resolución / reintento de conexión, nunca el código del overlay.
- **D-09:** Color de trazo de cada bbox sigue la tabla semáforo de identidad (verde=CONFIRMED, ámbar=CANDIDATE, rojo=UNKNOWN/intrusión), 2px, rectángulo sin esquinas redondeadas. Etiqueta `.mono` 11px sobre fondo `rgba(0,0,0,0.6)` (copiar patrón exacto del badge de detección existente).

### WebSocket y reconexión (OPS-06, criterio de éxito 5)
- **D-10:** El backoff exponencial (`_wsRetry` 1s→30s) YA existe en `frontend/js/websocket.js` (canal legacy `/ws`) — no reimplementar el algoritmo, solo reutilizarlo/extenderlo.
- **D-11:** El badge de estado del header (no solo la card de WS) debe reflejar también una desconexión WS prolongada (>1 ciclo de reconexión) como parte del cómputo de degradado/offline — visible arriba, donde mira primero el operador (criterio 6, reconocer en <3s).

### Claude's Discretion
- Qué canal WebSocket usar para el nuevo mensaje `tracks`: el legacy `/ws` (ya usado por `websocket.js` para eventos/init) o el `/api/v2/ws` (canal unificado v2, actualmente documentado en `backend/main.py:859` como "currently emits {"kind": "event", ...}; metrics/tracks/system follow later phases" — este comentario sugiere que `/api/v2/ws` es el canal pensado para `tracks`, pero verificar coste de mantener 2 conexiones WS simultáneas vs añadir el nuevo tipo de mensaje al canal legacy).
- Qué worker del backend empuja el mensaje `tracks` a 2Hz: candidatos son un nuevo loop periódico en `CameraPipeline`/`manager.py` que lea `TrackRegistry.active_ids()`/`frame_ids()` (mismo patrón que `get_object_boxes()` en `manager.py:346`, que ya existe para objetos pero no hay equivalente `get_person_boxes()` para personas) y publique al set de clientes WS suscritos, con throttle a 500ms independiente del ritmo del `DetectionWorker`.
- Formato exacto del payload `type: "tracks"` (lista de bboxes normalizados vs. píxeles absolutos, inclusión de `identity_state`/`person_name`/`track_id`) — el researcher debe proponerlo basándose en lo que `TrackRegistry`/`get_object_boxes()` ya exponen, para minimizar transformación adicional en el backend.
- Detalles exactos de cómo el header computa "degradado" (qué combinación de: WS caído, `capture_fps` bajo, `dropped` creciente, etc. — ver `/api/v2/cameras/{id}/health` ya existente) — no hay una fórmula fijada, es decisión técnica de la fase.

</decisions>

<specifics>
## Specific Ideas

- El wireframe de referencia es SPEC_v2.md §8.3 (ver `<canonical_refs>`), pero es orientativo — el UI-SPEC ya lo refinó (p.ej. escopó el panel de alertas a top-3, no la lista completa del wireframe).
- "Un observador no familiarizado identifica si hay alerta activa en menos de 3 s" (criterio 6) es el criterio más estricto de la fase — cualquier ambigüedad de diseño debe resolverse a favor de la legibilidad inmediata del estado, no de la densidad de información.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contrato visual (fuente de verdad para UI)
- `.planning/phases/29-vista-de-operaciones/29-UI-SPEC.md` — contrato de diseño completo, aprobado (6/6 dimensiones), sustituye cualquier decisión visual no explícita en este CONTEXT.md

### Alcance funcional y criterios de éxito
- `.planning/ROADMAP.md` § Phase 29 (líneas 539-550) — goal, dependencias, requisitos OPS-04/05/06, 6 criterios de éxito
- `.planning/REQUIREMENTS.md` líneas 246-248 — descripción completa de OPS-04, OPS-05, OPS-06

### Especificación técnica
- `propuesta_mejora/SPEC_v2.md` §8.3 — wireframe de referencia del layout de operaciones (orientativo, ya refinado por UI-SPEC)
- `propuesta_mejora/SPEC_v2.md` §8.4 — catálogo de métricas de observabilidad (`capture_fps`, `frames_dropped_total`, `active_tracks`, etc.) relevante para calcular el estado "degradado" del header

### Convenciones del proyecto
- `CLAUDE.md` — invariantes críticos 1-4 (captura nunca espera a la IA, latest-frame, sin colas ilimitadas), stack cerrado (sin frameworks nuevos), estructura de `backend/pipeline/`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `frontend/js/websocket.js` (78 líneas): backoff exponencial ya implementado (`_wsRetry` 1000→30000ms, doblando en cada `onclose`), badges `#ws-badge`/`#ws-label`/`#ws-icon` ya conectados. Extender el `onmessage` con un nuevo `case` para `type: "tracks"`, no reescribir la conexión.
- `frontend/js/components/videoCanvas.js` (65 líneas): actualmente solo gestiona badges de grabación/resolución, NO tiene overlay de canvas — el `<canvas>` y su lógica de dibujo son nuevos en esta fase, pero el fichero es el sitio natural para añadirlos (mismo patrón de export de funciones puras que consumen `websocket.js`).
- `backend/pipeline/manager.py:346` — `get_object_boxes()` ya existe (Fase 27) y expone bboxes de objetos vía pull desde `CameraPipeline`; es el precedente directo a replicar para tracks de personas, incluyendo cómo sobrevive a un reinicio del worker (método bound, no estado cerrado sobre una instancia efímera).
- `backend/pipeline/streaming.py` — ya acepta callables tipo `object_boxes: Callable[[], list[dict]]` inyectados por `manager.py` para overlay en el MJPEG (patrón "pull", Fase 27-08); un patrón análogo (pull cada 500ms desde un loop nuevo) es el candidato más directo para publicar `tracks` al WS.

### Established Patterns
- Invariante "la captura nunca espera a la IA" (CLAUDE.md #1) y "ningún hilo hace await, ninguna corrutina ejecuta inferencia" (#5/#6) — el nuevo loop de publicación de tracks a 2Hz debe ser una corrutina asyncio que solo LEE estado ya calculado (pull desde `TrackRegistry`/`get_object_boxes()`-like), nunca invoca inferencia ni bloquea el pipeline.
- `backend/main.py:857-871` — canal `/api/v2/ws` ya existe con el comentario explícito "metrics/tracks/system follow later phases", confirmando que esta fase es donde se espera implementarlo.

### Integration Points
- `frontend/js/app.js` (44 líneas, bootstrap real desde Fase 28) es donde se registran los listeners de arranque — cualquier inicialización del canvas overlay (crear el elemento, engancharlo a `#video-feed`) se conecta aquí.
- `frontend/index.html` — shell puro tras la Fase 28, el grid `main.grid.grid-cols-1.lg:grid-cols-5.gap-4` y el triplete `#cam-status`/`#status-dot`/`#status-text` ya existen y deben extenderse, no reemplazarse.

</code_context>

<deferred>
## Deferred Ideas

- Línea temporal de eventos completa, filtros combinables en servidor, paginación por cursor, agrupación/silenciado de alertas por regla — Fase 30 (OPS-07..OPS-11), explícitamente fuera de alcance del wireframe SPEC_v2 §8.3 en esta fase.
- Vista de analítica (heatmap, ranking, tendencias) — Fase 31.
- Vista de cámara y árbol de configuración visual — Fase 32.

</deferred>

---

*Phase: 29-vista-de-operaciones*
*Context gathered: 2026-08-20*
