# Phase 28: Refactor del frontend a módulos ES - Context

**Gathered:** 2026-08-18
**Status:** Ready for planning
**Source:** SPEC_v2.md (ADR-08, §8.2) + ROADMAP.md Phase 28 + confirmación directa del usuario sobre alcance

<domain>
## Phase Boundary

`frontend/index.html` (2038 líneas) contiene hoy todo el marcado, los estilos
inline y un único bloque `<script>` (~1240 líneas, líneas 786-2025) con toda
la lógica del dashboard v1.2/v2.0 acumulada: reloj, toasts, estado de cámara,
contadores/detecciones, PTZ + presets, WebSocket (conexión/reconexión),
carga inicial, toggles de cámara, resoluciones, grabaciones (estado de subida
a Drive), personas reconocidas + galería, zonas (CRUD), panel de clases
detectadas (Fase 27), modal de clips, filtros de eventos, salud del pipeline
y métricas de observabilidad (Fase 21).

Esta fase **no añade funcionalidad nueva**. Es una extracción 1:1: el mismo
comportamiento observable, servido desde módulos ES en vez de un único
`<script>` inline. Las vistas nuevas del centro de operaciones (Timeline,
Analítica, Cámara, Configuración) son fuera de alcance — las construyen las
Fases 29-32 sobre la base que deja esta fase.

</domain>

<decisions>
## Implementation Decisions

### Estructura de directorios (ADR-08, SPEC_v2.md §8.2 — LOCKED)
- `frontend/css/base.css` — variables, reset, tipografía (hoy: `<style>` líneas 11-120 de index.html)
- `frontend/css/layout.css` — grid/layout de las columnas del dashboard
- `frontend/css/components.css` — tarjetas, badges, toasts, modales, toggles
- `frontend/js/app.js` — bootstrap real: `DOMContentLoaded`, orquesta la carga inicial y engancha listeners (sustituye al stub actual de 2 líneas)
- `frontend/js/api.js` — wrapper `fetch` tipado contra `/api/*` y `/api/v2/*`, manejo de errores centralizado (hoy: cada `load*`/`fetch*` repite su propio `try/catch` + `fetch`)
- `frontend/js/websocket.js` — `connectWS`, reconexión con backoff, `setWsStatus`, dispatch de mensajes por `type` a callbacks registrados por el módulo de vista
- `frontend/index.html` — solo shell: `<head>` con CDNs (Tailwind, Chart.js con SRI), contenedores con sus `id`, imports `<script type="module" src="/static/js/app.js">` y los `<link>` a los 3 CSS. Sin lógica, sin `<style>` inline.

### Alcance de `js/views/` y `js/components/` para esta fase (decisión del usuario, 2026-08-18)
SPEC_v2.md §8.2 documenta el árbol completo del bloque C (Fases 28-32), pero
el dashboard actual es una única pantalla — no existen aún las vistas
Operations/Timeline/Analytics/Camera/Settings como pantallas separadas
(las crean sus propias fases). Para esta fase:
- **Sí crear** (mapean 1:1 a secciones que ya existen en index.html hoy):
  - `frontend/js/views/dashboard.js` — vista única actual: PTZ, stats, chart, cámara, WS status, salud, observabilidad, filtros (todo lo que no tiene módulo de componente propio)
  - `frontend/js/components/videoCanvas.js` — `<img id="video-feed">` + overlay/badges de resolución/REC/detecciones
  - `frontend/js/components/zoneEditor.js` — CRUD de zonas (`loadZones` y su UI)
  - `frontend/js/components/eventCard.js` — grabaciones + modal de clip (`addRecording`, `updateRecordingStatus`, `loadRecordings`, `openClipModal`)
  - `frontend/js/components/detectionClasses.js` — panel de clases detectadas (Fase 27-10: `renderDetectionClasses`, `loadDetectionClasses`, `saveDetectionClasses`) — NO está en el árbol de §8.2 porque esa sección del spec es anterior a la Fase 27; se añade como componente nuevo siguiendo el mismo patrón
  - `frontend/js/components/personGallery.js` — personas reconocidas + galería (`loadPersons`, `openGallery`)
- **NO crear en esta fase** (pertenecen a fases futuras, se crean cuando esas vistas existan de verdad): `views/operations.js`, `views/timeline.js`, `views/analytics.js`, `views/camera.js`, `views/recordings.js`, `views/settings.js`, `components/ruleEditor.js`, `components/alertCenter.js`, `components/notifications.js`
- `frontend/js/store.js`: **no crear todavía**. El código actual no tiene un patrón de estado compartido — cada `load*` escribe directo al DOM. Introducir pub/sub sin un consumidor real (el overlay reactivo a 2 Hz llega en la Fase 29) sería estado especulativo. `websocket.js` despacha directamente a funciones de actualización de `dashboard.js`/componentes, igual que hoy `connectWS` llama funciones de UI directamente.

### Límite de 300 líneas por módulo (ROADMAP Success Criteria #3)
Si `dashboard.js` no cabe en 300 líneas tras extraer los componentes de
arriba, se divide en sub-módulos temáticos dentro de `js/views/` (p. ej.
`dashboard-ptz.js`, `dashboard-metrics.js`) — el plan decide la partición
exacta según el recuento real tras la extracción; el criterio duro es
"ningún módulo > 300 líneas", no una lista de nombres fija.

### Paridad funcional (Success Criteria #4)
La verificación es un checklist manual en el SUMMARY de la fase (no hay
framework de test JS en el repo — mismo criterio que 27-10). Debe cubrir
cada funcionalidad hoy presente: vídeo en vivo, PTZ + presets, contadores,
chart de actividad, toggles de cámara, resoluciones, grabaciones + Drive,
personas + galería, zonas CRUD, clases detectadas, filtros de eventos,
salud, observabilidad, WebSocket con reconexión.

### Servido estático y SRI (Success Criteria #5)
`backend/main.py:609` ya monta `/static` sobre `FRONTEND_DIR` completo
(incluye subcarpetas `css/` y `js/` sin cambios en el backend). El SRI de
Chart.js (`integrity="sha384-..."` en `index.html:8`) se mantiene igual;
Tailwind CDN (línea 7) no lleva SRI hoy y no se introduce en esta fase
(fuera de alcance — es una decisión de fases anteriores, no se toca).

### Resolución de la Open Question de 28-RESEARCH.md: límite de líneas de `index.html` (decisión del usuario, 2026-08-18)
28-RESEARCH.md midió con precisión que el `<body>` actual (sin `<style>` ni
`<script>`) ya ocupa 667 líneas, y que una extracción 1:1 del marcado (sin
tocarlo, como fija esta misma CONTEXT.md) deja `index.html` en ~685 líneas
— muy por encima del "menos de 300 líneas" del ROADMAP original (que además
partía de una cifra desactualizada, 1843, cuando el fichero real mide 2038).
**Decisión: redefinir el criterio, no la arquitectura.** El objetivo real de
la fase es "index.html deja de contener lógica", no un recuento arbitrario
de líneas. `ROADMAP.md` Success Criteria #1 de la Fase 28 se actualiza para
medir "cero `<script>`/`<style>` inline en `index.html`" en vez de un tope
de 300 líneas, documentando los números reales (2038 → ~685, `<body>` puro
667). No se introduce fragmentación de marcado vía `fetch()+innerHTML` ni
ningún otro mecanismo nuevo — el marcado se mueve intacto, mismos `id`,
sin motor de plantillas, tal como ya fijaba esta CONTEXT.md.

### Carga inicial < 1s en LAN (Success Criteria #6)
Los módulos ES se cargan como ficheros separados (sin bundler, por decisión
de ADR-08), por lo que la carga inicial son varias peticiones HTTP/1.1 en
paralelo sobre LAN — no debería ser un problema práctico dado el tamaño
total (unos pocos KB por módulo), pero el plan debe incluir una medición
real (DevTools Network o similar) documentada en el SUMMARY, no solo una
afirmación.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Especificación y alcance
- `propuesta_mejora/SPEC_v2.md` (ADR-08, líneas 185-188; §8.2 Estructura del frontend, líneas 692-722) — árbol de directorios objetivo y restricción "sin bundler, sin framework"
- `.planning/ROADMAP.md` (líneas 515-526) — Success Criteria de la Fase 28, dependencia declarada: Phase 21
- `.planning/REQUIREMENTS.md` (OPS-01, OPS-02, OPS-03, líneas 243-245)

### Código fuente a extraer
- `frontend/index.html` — TODO el fichero es la fuente de la extracción: `<style>` (líneas 11-120), marcado (121-784), `<script>` único (786-2025)
- `frontend/app.js` — stub actual de 2 líneas a sustituir por el entry point real
- `backend/main.py` (líneas 605-623) — montaje de `/static`, `/gallery`, `/clips` y la ruta `/` que sirve `index.html`; no requiere cambios pero el plan debe confirmarlo

</canonical_refs>

<specifics>
## Specific Ideas

- Mantener los mismos `id` de elementos DOM al mover marcado — el JS movido a
  módulos sigue usando `document.getElementById(...)` igual que hoy; no es
  necesario introducir un sistema de templates.
- `api.js` puede empezar como un wrapper fino (`async function apiFetch(path, opts)`
  con manejo de error/JSON común) sin necesidad de tipado real (no hay
  TypeScript en el proyecto) — "tipado" en el SPEC se refiere a shape de
  respuesta consistente, no a un sistema de tipos.
- El orden de carga de módulos debe respetar dependencias (`app.js` importa
  `api.js`/`websocket.js`/vista y componentes vía `import` ES; el navegador
  resuelve el grafo, no hace falta orden manual en `<head>`).

</specifics>

<deferred>
## Deferred Ideas

- `frontend/js/store.js` (pub/sub de estado) — diferido a la Fase 29, cuando
  el overlay de tracks vía WebSocket a 2 Hz necesite un consumidor real.
- `frontend/js/views/{operations,timeline,analytics,camera,recordings,settings}.js`
  y `frontend/js/components/{ruleEditor,alertCenter,notifications}.js` —
  diferidos a las Fases 29-32, cuando esas vistas se diseñen y construyan.
- SRI para el CDN de Tailwind — fuera de alcance, no se toca en esta fase.

</deferred>

---

*Phase: 28-refactor-del-frontend-a-modulos-es*
*Context gathered: 2026-08-18*
