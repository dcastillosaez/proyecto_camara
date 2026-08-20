---
phase: 29
plan: 02
subsystem: frontend (js/components/videoCanvas.js, js/websocket.js, js/app.js, index.html)
tags: [canvas, overlay, websocket, ops-05]
dependency-graph:
  requires:
    - "backend: mensaje WS type:\"tracks\" (29-01-PLAN.md)"
  provides:
    - "canvas#tracks-overlay posicionado sobre #video-feed"
    - "drawTracks(tracks) / initTracksOverlay() en videoCanvas.js"
    - "case 'tracks' en el dispatcher onmessage de websocket.js"
  affects:
    - "29-03-PLAN.md (checkpoint visual manual de paridad del overlay)"
tech-stack:
  added: []
  patterns:
    - "Mapeo bbox normalizado 0-1 -> canvas píxeles deshaciendo object-fit:cover (scale=max()+offset centrado, sin precedente local, técnica estándar de plataforma)"
    - "ResizeObserver sobre <img> para resincronizar canvas.width/height sin polling"
    - "Redibujado dirigido por mensaje WS, nunca por requestAnimationFrame/temporizador propio"
key-files:
  created: []
  modified:
    - frontend/index.html
    - frontend/js/components/videoCanvas.js
    - frontend/js/websocket.js
    - frontend/js/app.js
decisions:
  - "Canvas insertado inmediatamente tras <img id=video-feed>, antes de #res-badge, dentro del mismo .card.relative — mismo stacking context que los demás overlays"
  - "Colores de estado (STATE_COLOR) hardcodeados en el módulo, no leídos de components.css — coherente con el resto de módulos vanilla sin sistema de tokens JS"
metrics:
  duration: "~20 min"
  completed: 2026-08-20
---

# Phase 29 Plan 02: Canvas de overlay de tracks (frontend) Summary

Nuevo `<canvas id="tracks-overlay">` posicionado sobre `#video-feed`, con `drawTracks()`/`initTracksOverlay()` en `videoCanvas.js` que mapean bboxes normalizados 0-1 a píxeles de canvas deshaciendo el recorte de `object-fit:cover`, redibujado únicamente al recibir el mensaje WebSocket `type:"tracks"` producido por 29-01-PLAN.md.

## Lo construido

**Task 1 — Canvas de overlay** (`frontend/index.html`): `<canvas id="tracks-overlay">` insertado justo tras el cierre de `<img id="video-feed">` y antes de `#res-badge`, dentro del mismo contenedor `.card.relative` (línea 53) para que `position:absolute` se resuelva contra él. `style` inline con `position:absolute; top:0; left:0; pointer-events:none; display:block` — nunca intercepta clicks ni compite con los badges existentes (D-08). `aria-hidden="true"` porque es una capa puramente decorativa/informativa redundante con el vídeo.

**Task 2 — `drawTracks()` + sincronización + wiring** (`frontend/js/components/videoCanvas.js`, `frontend/js/websocket.js`, `frontend/js/app.js`):
- `STATE_COLOR`: mapa `CONFIRMED`→verde `#22c55e`, `CANDIDATE`→ámbar `#f59e0b`, `UNKNOWN`/`TEMPORARILY_LOST`→rojo `#ef4444` (tabla semáforo D-09).
- `syncCanvasToImage(canvas, img)`: iguala `canvas.width/height` a `img.getBoundingClientRect()` (tamaño mostrado en píxeles CSS, D-06).
- `normalizedBoxToCanvasRect(box, img, canvas)`: deshace `object-fit:cover` con `scale = Math.max(cw/iw, ch/ih)` y offset centrado, usando `naturalWidth/naturalHeight` (resolución intrínseca del frame MJPEG servido), nunca `width/height` mostrados (Anti-Pattern documentado en 29-RESEARCH.md).
- `drawTracks(tracks)`: `clearRect` primero siempre, luego por cada track dibuja `strokeRect` 2px del color de estado + etiqueta `.mono` 11px sobre `rgba(0,0,0,0.6)` (nombre o "Desconocido"). Lista vacía → solo limpia, sin dibujar nada.
- `initTracksOverlay()`: sincroniza el canvas una vez al arrancar y engancha un `ResizeObserver` sobre `#video-feed` (guardia con `_tracksResizeObserver` para no duplicar el observer si se llama más de una vez).
- `websocket.js`: import extendido (`setRecBadge, drawTracks`), nuevo `else if (msg.type === 'tracks') { drawTracks(msg.tracks); }` en el dispatcher `onmessage`, mismo patrón que `recording_failed`.
- `app.js`: import extendido (`loadResolutions, initTracksOverlay`), `initTracksOverlay()` llamado tras `loadResolutions()` en `DOMContentLoaded`.

## Comportamiento esperado (sin runner JS, verificación estática + checkpoint visual de 29-03)

- `drawTracks([])` limpia el canvas, no dibuja nada.
- `drawTracks([{bbox:[0,0,1,1], identity_state:'CONFIRMED', person_name:'Ana'}])` dibuja un rectángulo verde cubriendo todo el área visible con la etiqueta "Ana".
- Llamadas sucesivas nunca acumulan tracks de la llamada anterior (`clearRect` siempre primero).
- El overlay se redibuja solo al llegar `type:"tracks"` — no hay `requestAnimationFrame` ni temporizador propio en el módulo.
- El overlay nunca toca `img.src` — ese código sigue viviendo exclusivamente en `loadResolutions()`/el listener de `resolution-select`, sin relación con el overlay.

## Deviations from Plan

### Discrepancias no funcionales en los `<verify>` automatizados del plan (documentadas, no código)

Mismo criterio que 29-01-SUMMARY.md: dos de las aserciones automatizadas del plan tienen un desajuste de redacción consigo mismas, sin implicar ningún bug de comportamiento:

1. **`grep -n "img.src" frontend/js/components/videoCanvas.js` → el plan pide "0 matches en todo el fichero", pero el propio texto del `<acceptance_criteria>` reconoce en la misma línea que "ese fichero solo lo hace desde `loadResolutions`/el listener de `resolution-select`, ya existente y sin relación con el overlay"** — es decir, el plan sabe y acepta que hay un match preexistente (línea 54, código de la Fase 28, no tocado por esta tarea) pero redactó el criterio como "0 matches" en vez de "0 matches fuera del código preexistente de resolución". No se ha modificado ese código: sigue siendo el único camino legítimo que toca `img.src` (D-08 cumplido).
2. **`grep -n "requestAnimationFrame" frontend/js/components/videoCanvas.js` → el plan pide "0 matches (Pitfall 5)", pero el propio `<action>` del plan especifica textualmente el comentario `// D-07/Pitfall 5: ... nunca requestAnimationFrame ni temporizador propio en este módulo.`** — ese comentario, copiado literalmente del plan, es el único match; no hay ninguna llamada real a `requestAnimationFrame` en el módulo (Pitfall 5 cumplido en comportamiento).

Ninguna de las dos discrepancias afecta la corrección funcional: D-07 y D-08 se cumplen en el código real, solo el patrón grep literal del plan no distingue comentarios/código preexistente de código nuevo.

## Verificación

- `node --check frontend/js/components/videoCanvas.js frontend/js/websocket.js frontend/js/app.js` → sintaxis válida en los 3 ficheros
- `pytest tests/test_frontend_modules.py -q` → 8 passed (sin regresión del contrato mecánico de la Fase 28)
- `grep -n 'id="tracks-overlay"' frontend/index.html` → 1 match, en orden `video-feed` < `tracks-overlay` < `res-badge`
- `grep -n "export function drawTracks"` / `"export function initTracksOverlay"` → 1 match cada uno
- `grep -n "ResizeObserver"` → presente
- `grep -n "naturalWidth"` → presente; `grep -n "img\.width\b"` → 0 matches
- `grep -c "#22c55e\|#f59e0b\|#ef4444"` → 4 (≥3, los 3 colores del semáforo presentes)
- `grep -n "drawTracks(msg.tracks)" frontend/js/websocket.js` → 1 match, dentro de `else if (msg.type === 'tracks')`
- `grep -n "initTracksOverlay" frontend/js/app.js` → 2 matches (import + llamada)

## Self-Check: PASSED

- FOUND: frontend/index.html contiene `id="tracks-overlay"`
- FOUND: frontend/js/components/videoCanvas.js contiene `export function drawTracks` y `export function initTracksOverlay`
- FOUND: frontend/js/websocket.js contiene `drawTracks(msg.tracks)` en `case 'tracks'`
- FOUND: frontend/js/app.js contiene `initTracksOverlay()`
- FOUND commit f4395f2: feat(29-02): canvas#tracks-overlay sobre #video-feed
- FOUND commit 1b5f887: feat(29-02): drawTracks() + sincronizacion object-fit:cover + wiring WS/app
