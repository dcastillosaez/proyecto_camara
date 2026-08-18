# Phase 28: Refactor del frontend a módulos ES - Research

**Researched:** 2026-08-18
**Domain:** Extracción de JS/CSS inline a módulos ES nativos servidos sin build step (FastAPI + StaticFiles)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Estructura de directorios (ADR-08, SPEC_v2.md §8.2 — LOCKED)**
- `frontend/css/base.css` — variables, reset, tipografía (hoy: `<style>` líneas 11-117 de index.html)
- `frontend/css/layout.css` — grid/layout de las columnas del dashboard
- `frontend/css/components.css` — tarjetas, badges, toasts, modales, toggles
- `frontend/js/app.js` — bootstrap real: `DOMContentLoaded`, orquesta la carga inicial y engancha listeners (sustituye al stub actual de 2 líneas)
- `frontend/js/api.js` — wrapper `fetch` tipado contra `/api/*` y `/api/v2/*`, manejo de errores centralizado
- `frontend/js/websocket.js` — `connectWS`, reconexión con backoff, `setWsStatus`, dispatch de mensajes por `type` a callbacks registrados por el módulo de vista
- `frontend/index.html` — solo shell: `<head>` con CDNs (Tailwind, Chart.js con SRI), contenedores con sus `id`, imports `<script type="module" src="/static/js/app.js">` y los `<link>` a los 3 CSS. Sin lógica, sin `<style>` inline.

**Alcance de `js/views/` y `js/components/` para esta fase**
- Sí crear: `frontend/js/views/dashboard.js` (PTZ, stats, chart, cámara, WS status, salud, observabilidad, filtros — todo lo que no tiene módulo de componente propio); `frontend/js/components/videoCanvas.js` (`<img id="video-feed">` + overlay/badges de resolución/REC/detecciones); `frontend/js/components/zoneEditor.js` (CRUD de zonas); `frontend/js/components/eventCard.js` (grabaciones + modal de clip); `frontend/js/components/detectionClasses.js` (panel de clases detectadas, Fase 27-10); `frontend/js/components/personGallery.js` (personas reconocidas + galería).
- NO crear en esta fase: `views/operations.js`, `views/timeline.js`, `views/analytics.js`, `views/camera.js`, `views/recordings.js`, `views/settings.js`, `components/ruleEditor.js`, `components/alertCenter.js`, `components/notifications.js`.
- `frontend/js/store.js`: no crear todavía. `websocket.js` despacha directamente a funciones de actualización de `dashboard.js`/componentes, igual que hoy `connectWS` llama funciones de UI directamente.

**Límite de 300 líneas por módulo (ROADMAP Success Criteria #3)**
Si `dashboard.js` no cabe en 300 líneas tras extraer los componentes de arriba, se divide en sub-módulos temáticos dentro de `js/views/` — el plan decide la partición exacta según el recuento real tras la extracción; el criterio duro es "ningún módulo > 300 líneas", no una lista de nombres fija.

**Paridad funcional (Success Criteria #4)**
Verificación mediante checklist manual en el SUMMARY (no hay framework de test JS en el repo). Debe cubrir: vídeo en vivo, PTZ + presets, contadores, chart de actividad, toggles de cámara, resoluciones, grabaciones + Drive, personas + galería, zonas CRUD, clases detectadas, filtros de eventos, salud, observabilidad, WebSocket con reconexión.

**Servido estático y SRI (Success Criteria #5)**
`backend/main.py:609` ya monta `/static` sobre `FRONTEND_DIR` completo (incluye subcarpetas `css/` y `js/` sin cambios en el backend). El SRI de Chart.js se mantiene igual; Tailwind CDN no lleva SRI hoy y no se introduce en esta fase.

**Carga inicial < 1s en LAN (Success Criteria #6)**
Los módulos ES se cargan como ficheros separados (sin bundler), el plan debe incluir una medición real (DevTools Network o similar) documentada en el SUMMARY, no solo una afirmación.

### Claude's Discretion
- Partición exacta de `dashboard.js` en sub-módulos si excede 300 líneas (nombres y fronteras).
- Mecanismo concreto de export/import para el estado hoy compartido por closures (`_ws`, `TOAST_STYLES`, `STATUS_LABEL`/`STATUS_COLOR`, `window.dashboardAPI`).
- Formato exacto de la medición de carga inicial (DevTools vs script).

### Deferred Ideas (OUT OF SCOPE)
- `frontend/js/store.js` (pub/sub de estado) — diferido a la Fase 29.
- `frontend/js/views/{operations,timeline,analytics,camera,recordings,settings}.js` y `frontend/js/components/{ruleEditor,alertCenter,notifications}.js` — diferidos a las Fases 29-32.
- SRI para el CDN de Tailwind — fuera de alcance, no se toca en esta fase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | La lógica del frontend vive en módulos ES separados por responsabilidad, no en `index.html` | Ver `Architecture Patterns` (mapa de módulos con recuento de líneas real por sección) y `Code Examples` (patrón de import sin ciclos entre `websocket.js`/`dashboard.js`/componentes) |
| OPS-02 | Ningún módulo de frontend supera las 300 líneas | Ver `Common Pitfalls → dashboard.js no cabe en 300 líneas` con desglose línea a línea de las 28 secciones del script actual y una partición candidata evidenciada |
| OPS-03 | La modularización mantiene paridad funcional completa con v1.2 y no introduce build step | Ver `Architecture Patterns → Orden de carga de módulos ES`, `Common Pitfalls → MIME type de .js en Windows` y `→ CSP y los 2 handlers inline restantes` |
</phase_requirements>

## Summary

Esta fase es una extracción mecánica de JavaScript/CSS inline a módulos ES nativos — no incorpora tecnología nueva. La investigación se centró en tres cosas: (1) verificar que no hay problemas reales de plataforma (orden de carga de módulos, tipo MIME de `.js` servido por FastAPI en Windows, CSP existente), (2) medir con precisión el código actual para dar al planificador datos reales en vez de estimaciones, y (3) detectar acoplamientos no obvios entre las funciones que hoy viven en un único `<script>` y que se romperían si se dividen ingenuamente.

El hallazgo más importante no estaba en el foco original de la investigación: **el criterio de éxito "`index.html` baja a menos de 300 líneas" es matemáticamente muy ajustado, probablemente inalcanzable, si el marcado (`<body>`) se mueve intacto como shell**. El marcado actual (sin `<style>` ni `<script>`) mide 667 líneas por sí solo — más del doble del objetivo — y CONTEXT.md no autoriza introducir un sistema de particionado de plantillas. Esto se documenta en detalle en `Open Questions` porque cambia el alcance de las tareas del plan si no se resuelve antes de planificar.

El resto de riesgos técnicos investigados (orden de módulos ES, MIME type, CSP) están **verificados y no son un problema**: Python `mimetypes` en esta máquina Windows devuelve `text/javascript` correctamente para `.js` (sin entrada de registro que lo sobreescriba), Starlette usa ese valor directamente vía `FileResponse`, y el CSP ya vigente en `backend/main.py` permite scripts `'self'` sin cambios. El riesgo real y no obvio está en el **reparto de responsabilidades sobre elementos DOM compartidos** (`#rec-badge`, `#res-badge`) que hoy se tocan desde tres secciones distintas del script, y en que `dashboard.js`, tal como lo define CONTEXT.md como "todo lo que no tiene módulo propio", mide ~560 líneas si no se subdivide — casi el doble del límite.

**Primary recommendation:** dividir el script en los módulos ya decididos en CONTEXT.md usando los límites de sección reales medidos en este documento (no reinventar los cortes), subdividir `dashboard.js` en al menos 4 sub-módulos temáticos desde la primera tarea (no como corrección posterior), enrutar las actualizaciones de `#rec-badge`/`#res-badge` a través de funciones exportadas por `videoCanvas.js`, y resolver explícitamente —antes o durante la planificación— cómo se alcanza el límite de 300 líneas en `index.html` dado que el marcado por sí solo ya lo excede.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Carga de módulos ES / bootstrap (`app.js`) | Browser / Client | — | `DOMContentLoaded`, orquesta el resto; no hay SSR ni build step |
| Servido de `/static/css`, `/static/js` | CDN / Static | API / Backend | `StaticFiles` de FastAPI ya monta `FRONTEND_DIR` completo; el backend no cambia |
| Fetch a `/api/*`, `/api/v2/*` (`api.js`) | Browser / Client | API / Backend | El cliente solo empaqueta `fetch`; toda la lógica de negocio ya vive en `backend/api/v2/*` |
| WebSocket `/ws` (`websocket.js`) | Browser / Client | API / Backend | Reconexión/backoff y dispatch por `type` son responsabilidad exclusiva del cliente; el servidor (Fase 6) no cambia |
| Overlay de vídeo (badges REC/resolución/detección) (`videoCanvas.js`) | Browser / Client | — | Manipulación de DOM/canvas pura, sin lógica de servidor |
| CRUD de zonas (`zoneEditor.js`) | Browser / Client | API / Backend | El cliente llama a `/api/zones`; la validación real ya vive en el backend |
| Panel de clases detectadas (`detectionClasses.js`) | Browser / Client | API / Backend | Llama a `GET/PUT /api/v2/detection/classes` (Fase 27); sin lógica nueva |
| Grabaciones + modal de clip (`eventCard.js`) | Browser / Client | API / Backend / CDN-Static | Lee `/api/recordings` y sirve `<video>` desde el mount `/clips` ya existente |
| Personas + galería (`personGallery.js`) | Browser / Client | API / Backend | Lee `/persons`, sirve imágenes desde el mount `/gallery` ya existente |
| Vista única del dashboard (`dashboard.js` + sub-módulos) | Browser / Client | — | Orquestación de PTZ, stats, chart, salud, observabilidad — sin backend nuevo |

No hay capacidades que toquen la capa de base de datos o requieran cambios en `backend/main.py` más allá de confirmar que el mount `/static` ya cubre `css/` y `js/` (confirmado, ver `Code Examples`).

## Standard Stack

No se introduce ninguna librería, framework ni dependencia nueva. Esta fase reorganiza JS/CSS ya escrito, ejecutándose contra las CDNs que el proyecto ya usa.

### Core (sin cambios, se mantienen tal cual)
| Recurso | Versión actual | Uso | Por qué no cambia |
|---------|-----|---------|--------------|
| Tailwind CSS (CDN) | `cdn.tailwindcss.com` (sin pin de versión, `<script>` en `index.html:7`) | Utilidades de layout/estilo en el marcado | Fuera de alcance tocar el CDN o añadirle SRI (decisión explícita en CONTEXT.md) |
| Chart.js | `4.5.1` vía `cdn.jsdelivr.net`, con `integrity=` (`index.html:8`) | Histograma de actividad | `tests/test_security_regression.py::TEST_vuln_14_chartjs_cdn_has_subresource_integrity` **[VERIFIED: lectura directa del test]** falla si esta línea deja de tener `integrity=` en una sola línea de `index.html` |

### Alternativas Consideradas
No aplica — CONTEXT.md y ADR-08 cierran la decisión (ES modules nativos, sin bundler, sin framework); no hay alternativa que investigar.

**Instalación:** ninguna — no hay `package.json` en el repo `[VERIFIED: búsqueda en el árbol del proyecto, sin resultados]` y esta fase no lo introduce (build step prohibido por CLAUDE.md y por ADR-08).

## Architecture Patterns

### Recuento real del script actual (línea a línea, base para dividir sin adivinar)

El `<script>` único ocupa las líneas 786-2025 de `index.html` (1240 líneas) y ya está organizado en 28 secciones marcadas con comentarios banner (`// ── … ──`). Este es el recuento exacto medido con esos marcadores como límites `[VERIFIED: grep de banners + lectura de frontend/index.html]`:

| # | Sección (comentario banner) | Líneas | Aprox. líneas | Destino CONTEXT.md |
|---|------|--------|--------|---------------------|
| 1 | Clock | 787-794 | 8 | `dashboard.js` (core) |
| 2 | Toast | 795-812 | 18 | `dashboard.js` (core, exportado) |
| 3 | Camera online/offline | 813-832 | 20 | `dashboard.js` (core) |
| 4 | Stat counter update | 833-843 | 11 | `dashboard.js` (core) |
| 5 | Counts polling | 844-861 | 18 | `dashboard.js` (core) |
| 6 | Detections polling | 862-873 | 12 | `dashboard.js` (core) |
| 7 | PTZ: steps slider | 874-878 | 5 | `dashboard.js` → sub-módulo PTZ |
| 8 | PTZ: move | 879-900 | 22 | `dashboard.js` → sub-módulo PTZ |
| 9 | PTZ: stop | 901-924 | 24 | `dashboard.js` → sub-módulo PTZ |
| 10 | PTZ: presets | 925-961 | 37 | `dashboard.js` → sub-módulo PTZ |
| 11 | PTZ: save preset | 962-986 | 25 | `dashboard.js` → sub-módulo PTZ |
| 12 | Events: delete by date range | 987-1036 | 50 | `dashboard.js` → sub-módulo events |
| 13 | Chart (+ `window.dashboardAPI`) | 1037-1120 | 84 | `dashboard.js` → sub-módulo events |
| 14 | WebSocket `/ws` | 1121-1202 | 82 | `websocket.js` |
| 15 | Initial data load | 1203-1236 | 34 | `dashboard.js` (core, bootstrap) |
| 16 | Camera settings toggles | 1237-1302 | 66 | `dashboard.js` (core o sub-módulo cámara) |
| 17 | Resolution dropdown | 1303-1367 | 65 | `videoCanvas.js` (toca `#res-badge`/`#video-feed`) |
| 18 | Recordings panel | 1368-1456 | 89 | `eventCard.js` |
| 19 | Recordings: delete by date range | 1457-1516 | 60 | `eventCard.js` |
| 20 | Known persons panel (incluye modal de enrolamiento) | 1517-1656 | 140 | `personGallery.js` |
| 21 | Gallery modal | 1657-1688 | 32 | `personGallery.js` |
| 22 | Zones panel | 1689-1790 | ~102 | `zoneEditor.js` |
| — | Panel "Clases detectadas" (Fase 27-10, sin banner propio) | 1791-1857 | ~67 | `detectionClasses.js` |
| 23 | Event delegation clip play | 1858-1864 | 7 | `eventCard.js` |
| 24 | Video player modal | 1865-1895 | 31 | `eventCard.js` |
| 25 | Event filters | 1896-1947 | 52 | `dashboard.js` → sub-módulo events |
| 26 | CSV export | 1948-1954 | 7 | `dashboard.js` → sub-módulo events |
| 27 | Health metrics | 1955-1978 | 24 | `dashboard.js` → sub-módulo observabilidad |
| 28 | Observabilidad (Fase 21) | 1979-2024 | 46 | `dashboard.js` → sub-módulo observabilidad |

**Totales por destino** (suma de la columna "Aprox. líneas"):
- `websocket.js`: **82** líneas — cabe holgado.
- `zoneEditor.js`: **~102** líneas — cabe holgado.
- `detectionClasses.js`: **~67** líneas — cabe holgado.
- `eventCard.js`: 89+60+7+31 = **187** líneas — cabe.
- `personGallery.js`: 140+32 = **172** líneas — cabe.
- `videoCanvas.js`: 65 líneas de la sección de resolución, más 2-3 líneas dispersas de `#rec-badge` dentro de la sección WebSocket y de Recordings (ver pitfall dedicado) — **~70** líneas — cabe.
- `dashboard.js` (todo lo no asignado arriba): 8+18+20+11+18+12+5+22+24+37+25+50+84+34+66+52+7+24+46 = **~563 líneas — casi el doble del límite de 300.**

Esta última cifra confirma, con datos reales y no una estimación, la previsión que ya hace CONTEXT.md ("si `dashboard.js` no cabe en 300 líneas... se divide"): **no cabe**, y el plan debe tratarlo como un hecho conocido desde la primera tarea de `dashboard.js`, no como un descubrimiento a mitad de ejecución.

**Partición candidata de `dashboard.js`** (evidenciada por los números de arriba; el plan tiene la última palabra según CONTEXT.md):
- `views/dashboard.js` (núcleo): clock, toast, cam-status, stat counter, counts/detections polling, initial data load, camera toggles → 8+18+20+11+18+12+34+66 = **187 líneas**
- `views/dashboard-ptz.js`: las 5 secciones de PTZ → 5+22+24+37+25 = **113 líneas**
- `views/dashboard-events.js`: delete-by-range de eventos, chart + `dashboardAPI`, filtros, export CSV → 50+84+52+7 = **193 líneas**
- `views/dashboard-observability.js`: health metrics + observabilidad Fase 21 → 24+46 = **70 líneas**

Los cuatro quedan por debajo de 300 con margen (la sección más grande, `dashboard-events.js`, tiene 193 líneas — deja ~100 líneas de margen para imports/exports/comentarios que el código actual no tiene porque vive en un único scope).

### Orden de carga de módulos ES — no hay riesgo de "usado antes de definirse"

Los módulos `type="module"` se difieren automáticamente (equivalente a `defer`) y el navegador resuelve el grafo completo de `import`/`export` de forma estática antes de ejecutar ningún módulo — a diferencia de scripts clásicos concatenados donde el orden de las etiquetas `<script>` importa. **[CITED: MDN — developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script, developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules]**: "el procesamiento del contenido de un script de módulo se difiere siempre... los módulos usan modo estricto automáticamente". Esto significa:
- No hace falta ordenar manualmente `<script>` en `index.html` — solo `app.js` se referencia ahí; el resto se resuelve por `import`.
- **Sí hay que evitar ciclos de import** entre `websocket.js` y los módulos a los que despacha. `websocket.js` necesita llamar a funciones de `dashboard.js` (core), `eventCard.js` (grabaciones) y `videoCanvas.js` (badge REC) desde su `onmessage`. La forma segura de hacerlo sin ciclo: `websocket.js` importa esas funciones (`import { updateStat, showToast } from '../views/dashboard.js'`, etc.) y **`app.js`** —no `dashboard.js`— es quien importa y llama a `connectWS()`. Si en cambio `dashboard.js` importara `connectWS` de `websocket.js` para arrancarlo, y `websocket.js` a su vez importara de `dashboard.js`, seguiría sin haber ciclo real en ES modules (los ciclos están permitidos y el motor los resuelve con bindings en vivo), pero complica el razonamiento sobre qué se ejecuta primero. Más simple y más legible: **el bootstrap (`connectWS()`, `loadInitialData()`, listeners de PTZ/zonas/etc.) vive solo en `app.js`**, que importa de todos los demás módulos; ningún módulo de "hoja" (`websocket.js`, `videoCanvas.js`, `eventCard.js`, etc.) necesita saber que existe `app.js`.

### Todo el modo estricto ya es compatible — verificado contra el código actual

Los módulos ES fuerzan modo estricto implícito. Se revisó el script actual buscando patrones que rompen en modo estricto (`with`, `arguments.callee`, asignación a variables no declaradas, octales legacy) — **ninguno aparece** `[VERIFIED: grep sobre frontend/index.html, 0 coincidencias]`. Todas las variables mutables usan `let`/`const` explícitos (`_ws`, `_wsRetry`, etc.). No se espera ninguna regresión por el cambio a modo estricto.

### Recomendado: patrón de export para el estado hoy compartido por closures

| Estado hoy compartido | Usado por (además de su dueño) | Patrón recomendado |
|---|---|---|
| `_ws`, `_wsRetry` | Nadie fuera de `connectWS`/`setWsStatus` (verificado, ver tabla de greps) | Queda privado dentro de `websocket.js`, no se exporta |
| `TOAST_STYLES`, `showToast()` | PTZ, zonas, grabaciones, enrolamiento, clases detectadas — prácticamente todos los módulos | Exportar `showToast` desde `dashboard.js` (core); el resto de módulos hacen `import { showToast } from '../views/dashboard.js'` |
| `setCamStatus()`, `updateStat()` | `loadInitialData`, WebSocket dispatch | Exportar ambas desde `dashboard.js` (core); `websocket.js` las importa |
| `window.dashboardAPI` (`updateChart`, `addEvent`, `setOnline`) | Solo se usa dentro del propio script — **[VERIFIED: grep de `dashboardAPI` en todo el repo, único fichero con coincidencias es `frontend/index.html`]** | No hace falta mantenerlo como objeto colgado de `window` — se convierte en exports nombrados normales (`updateChart`, `addEvent`) desde `dashboard-events.js`; nada externo depende del objeto global |
| `STATUS_LABEL`, `STATUS_COLOR` | Solo dentro de `_recRow`/`updateRecordingStatus` | Quedan privados dentro de `eventCard.js` |
| `DETECTION_CLASS_LABELS` | Solo dentro de `renderDetectionClasses` | Queda privado dentro de `detectionClasses.js` |

### Patrón: badges de vídeo (`#rec-badge`, `#res-badge`) tocados desde tres sitios hoy

Hoy `#rec-badge` se activa/desactiva desde tres lugares distintos del único script: el dispatch de WebSocket (`recording_started`/`recording_uploaded`/`recording_failed`), y `loadRecordings()` (cuenta de grabaciones activas). `#res-badge` se actualiza solo desde la sección de resolución. Como los `id` del DOM son globales a la página (no shadow DOM, no scoping por módulo), técnicamente **cualquier módulo puede seguir usando `document.getElementById('rec-badge')` directamente y funcionaría** — el `id` no pertenece a ningún módulo JS, pertenece al documento. Pero para cumplir la intención de CONTEXT.md de que `videoCanvas.js` sea el dueño del overlay, el patrón recomendado es:

```javascript
// videoCanvas.js
export function setRecBadge(visible, count) {
  const badge = document.getElementById('rec-badge');
  badge.classList.toggle('hidden', !visible);
  if (count != null) badge.textContent = count;
}

export function setResolutionBadge(text) {
  document.getElementById('res-badge').textContent = text;
  document.getElementById('res-badge').style.display = text ? '' : 'none';
}
```
Y `websocket.js`/`eventCard.js` importan y llaman `setRecBadge(...)` en vez de tocar `#rec-badge` directamente. Esto no es obligatorio para que funcione (el DOM es global), pero evita que tres módulos distintos dupliquen el conocimiento de las clases CSS/estructura interna del badge — si mañana cambia el marcado del badge, solo hay que tocar `videoCanvas.js`.

### `layout.css` probablemente queda casi vacío — no es un error de mapeo

Se revisó el `<style>` actual (líneas 11-117) buscando reglas de grid/layout de página: no hay ninguna — **0 coincidencias de `@media`** `[VERIFIED: grep en frontend/index.html]** y el único grid (`grid grid-cols-1 lg:grid-cols-5 gap-4`, línea 151) está expresado como clases de utilidad de Tailwind directamente en el marcado, no como CSS propio. Las reglas existentes (`.ptz-btn`, `.preset-btn`, `.event-item`, `.toast`, `.cam-toggle`, `.intrusion-badge`, `.gallery-grid`/`.gallery-thumb`, `.filter-input`, `#clip-modal`) son todas de **componentes**, no de layout. El reparto natural:
- `base.css`: reset (`*, *::before, *::after`), `body`, `.mono`, scrollbar, animación `pulse-ring`.
- `components.css`: el resto — `.ptz-btn`, `.preset-btn`, `.event-item` + `slide-in`, `.toast`, `stat-pop`, `.card`, `.cam-toggle`, `.intrusion-badge`, `.gallery-grid`/`.gallery-thumb`, `.filter-input`/`.filter-select`, `#clip-modal`.
- `layout.css`: quedará mínimo (posiblemente solo un comentario indicando que el layout de columnas es Tailwind-utility-driven) — esto es correcto, no un hueco a rellenar artificialmente.

### Servido estático y tipo MIME de `.js` en FastAPI/Starlette — verificado, no es un problema

`backend/main.py:609` monta `app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")` sobre el directorio `frontend/` completo, así que `frontend/js/app.js` queda automáticamente en `/static/js/app.js` sin ningún cambio de backend — coincide con la ruta que usa CONTEXT.md (`<script type="module" src="/static/js/app.js">`).

Se verificó la cadena completa hasta el tipo MIME real:
1. `starlette.staticfiles.StaticFiles.file_response()` construye `FileResponse(full_path, ...)` **sin pasar `media_type`** `[VERIFIED: lectura de site-packages/starlette/staticfiles.py línea 181]`.
2. `starlette.responses.FileResponse.__init__` hace `media_type = guess_type(filename or path)[0] or "text/plain"` **[VERIFIED: lectura de site-packages/starlette/responses.py línea 315]** — es decir, delega 100% en el módulo estándar `mimetypes` de Python, con `text/plain` solo como fallback si `guess_type` no reconoce la extensión.
3. En esta máquina (Windows 11, Python 3.14.6): `mimetypes.guess_type('app.js')` → **`('text/javascript', None)`**, `mimetypes.guess_type('style.css')` → `('text/css', None)` **[VERIFIED: ejecución directa]**.

`text/javascript` es el tipo MIME correcto y suficiente: los navegadores exigen *strict MIME type checking* para `<script type="module">`, aceptando `text/javascript` (el recomendado actualmente por la especificación WHATWG/IANA) y `application/javascript` (legado) — **[CITED: MDN, resultado de búsqueda]**: "para que los módulos funcionen correctamente en un navegador, hace falta que el servidor los sirva con una cabecera `Content-Type` que contenga un tipo MIME de JavaScript... si no, se produce un error de comprobación estricta de tipo MIME".

**Advertencia real, no descartable solo por esta verificación:** este resultado correcto depende de que **no exista una entrada de registro de Windows que lo sobreescriba**. Es un problema documentado y real en máquinas Windows: `HKEY_CLASSES_ROOT\.js\Content Type` puede quedar fijado a `text/plain` por instalaciones de Visual Studio o VS Code, lo que rompe `mimetypes.guess_type` en *ese* Python/máquina sin que sea un bug del proyecto — **[CITED: bugs.python.org/issue43975 / github.com/python/cpython/issues/88141]**. Se comprobó explícitamente en esta máquina que esa clave no existe (`reg query "HKEY_CLASSES_ROOT\.js" /v "Content Type"` no devuelve resultado) `[VERIFIED: comando ejecutado en esta sesión]`, así que hoy no hay problema — pero el plan **debería incluir una verificación end-to-end real** (petición HTTP contra el servidor levantado, no solo `mimetypes` en aislado) como parte de sus criterios de aceptación, porque el resultado depende de la máquina donde se ejecute, no solo del código.

### CSP existente ya permite los módulos `'self'` — no requiere cambios

`backend/main.py:577-584` ya define una `Content-Security-Policy` con `script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net 'unsafe-inline';` `[VERIFIED: lectura de backend/main.py]`. Un `<script type="module" src="/static/js/app.js">` es mismo-origen (`'self'`), así que ya está permitido sin tocar el middleware. **No se necesita ningún cambio de backend para esta fase**, más allá de confirmarlo (Success Criteria #5 ya está satisfecho por el código actual).

## Don't Hand-Roll

| Problema | No construir | Usar en su lugar | Por qué |
|---------|-------------|------------------|-----|
| Cargar módulos condicionalmente / resolver dependencias entre ficheros JS | Un loader manual o un "orquestador de scripts" propio | `import`/`export` nativos de ES modules + `<script type="module">` | El navegador ya resuelve el grafo estático; es exactamente lo que ADR-08 pide y lo que ya soportan todos los navegadores objetivo del proyecto |
| Servir `.js`/`.css` con cabeceras correctas | Middleware custom de tipos MIME | `starlette.staticfiles.StaticFiles` (ya montado) | Ya delega correctamente en `mimetypes.guess_type`, verificado en esta sesión; un middleware propio añadiría superficie de mantenimiento sin necesidad |
| Reducir las 667 líneas de marcado de `index.html` | Un motor de plantillas o "includes" en JS (aunque sea ligero) | Ninguno todavía — ver `Open Questions` | CONTEXT.md dice explícitamente "no es necesario introducir un sistema de templates"; introducir uno sin decisión explícita del usuario contradice la fuente de verdad de esta fase |

**Key insight:** todo lo que hace falta para esta fase ya existe en la plataforma web (ES modules nativos) y en el stack del proyecto (`StaticFiles`). El único punto donde "no reinventar" choca con un objetivo numérico es la reducción de `index.html`, y ahí la respuesta correcta es escalar la pregunta, no construir una solución nueva no pedida.

## Common Pitfalls

### Pitfall 1: `index.html < 300 líneas` es muy probablemente inalcanzable tal como está escrito el criterio

**Qué falla:** el marcado (`<body>`) actual, sin `<style>` ni `<script>`, mide **667 líneas** (119-785) `[VERIFIED: sed + wc -l sobre frontend/index.html]`. El `<head>` sin el bloque `<style>` inline mide ~11 líneas (doctype, meta, title, 2 `<script>` CDN, preconnect, link de fuentes) más 3 `<link>` nuevos a los CSS ≈ 14 líneas. Sumando el `<script type="module">` de cierre (1 línea) y las etiquetas de cierre, el `index.html` resultante de una extracción 1:1 sin tocar el marcado mediría **~685 líneas — más del doble del objetivo de 300**.

**Por qué pasa:** CONTEXT.md fija dos restricciones simultáneas que son difíciles de cumplir juntas con los números reales: (a) "extracción 1:1... el mismo comportamiento observable" + "no es necesario introducir un sistema de templates" + "mantener los mismos `id` de elementos DOM al mover marcado" (es decir: el marcado se queda en `index.html`, intacto), y (b) el criterio numérico del ROADMAP "`index.html` baja de 1843 a menos de 300 líneas". Además, el número de partida del ROADMAP (1843) ya no coincide con el fichero real (2038 líneas hoy) `[VERIFIED: wc -l]` — la cifra del ROADMAP se fijó antes de al menos el panel "Clases detectadas" añadido en la Fase 27-10, lo que sugiere que ese número no se ha recalculado contra el estado actual del fichero.

**Cómo evitarlo:** esto no es una alerta para "arreglar en código" sino una decisión de alcance que el plan (o una vuelta rápida a discuss-phase) debe resolver explícitamente antes de comprometer tareas, con opciones como:
1. Reformatear el marcado al moverlo (colapsar atributos multilínea a una línea, quitar los comentarios banner `══...══`) — con los datos disponibles esto podría recortar el marcado significativamente pero probablemente no lo suficiente por sí solo para bajar de 700 a 300; no se puede afirmar que sea suficiente sin probarlo.
2. Trocear el marcado en fragmentos HTML estáticos por tarjeta/panel, cargados vía `fetch()` + `innerHTML` desde el módulo de vista/componente correspondiente al arrancar (no es un motor de plantillas — es HTTP + HTML estático — pero sí es una decisión de arquitectura no mencionada en CONTEXT.md que el plan debería explicitar y justificar antes de ejecutarla).
3. Tratar el número "300" como orientativo para el marcado y verificar el criterio real por otra vía (p. ej. "cero `<script>`/`<style>` inline en `index.html`" en vez de un recuento estricto de líneas), dejando constancia expresa de la desviación en el SUMMARY.

**Señales de alerta:** si al final de la extracción `index.html` mide claramente por encima de 300 y el plan no documentó por qué ni lo remedió, el plan-checker debería marcarlo como discrepancia, no asumir que es un error de ejecución.

### Pitfall 2: `dashboard.js` tal como lo describe CONTEXT.md ("todo lo que no tiene módulo propio") no cabe en 300 líneas

**Qué falla:** medido sección por sección (ver tabla en `Architecture Patterns`), el contenido que no tiene un componente dedicado suma **~563 líneas**.

**Por qué pasa:** el dashboard actual es una única pantalla que acumuló responsabilidades de las Fases 7 a 27 (reloj, toasts, PTZ, chart, cámara, salud, observabilidad, filtros) sin ninguna separación de módulos hasta ahora.

**Cómo evitarlo:** dividir `dashboard.js` en al menos 4 sub-módulos desde la primera tarea que lo toque, usando los cortes temáticos que ya usa el propio código (comentarios banner) — ver la partición candidata en `Architecture Patterns` (núcleo ~187, PTZ ~113, eventos ~193, observabilidad ~70 líneas). No tratar esto como un ajuste posterior: si se escribe primero un `dashboard.js` monolítico y se divide después, se duplica trabajo y aumenta el riesgo de romper referencias a `showToast`/`updateStat` entre sub-módulos.

**Señales de alerta:** cualquier tarea del plan que diga "crear `dashboard.js` con toda la lógica restante" sin mencionar sub-módulos debería revisarse antes de ejecutarla.

### Pitfall 3: quitar `'unsafe-inline'` del CSP rompería 2 handlers inline que la fase no toca

**Qué falla:** el CSP actual (`backend/main.py:577-584`) incluye `'unsafe-inline'` en `script-src`. El marcado tiene 2 atributos de evento inline que dependen de eso: el `onerror` del `<img id="video-feed">` (línea 163) y el `onclick` del botón "Reintentar conexión" (línea 177) `[VERIFIED: grep de atributos `on*=` en frontend/index.html, único fichero con 1 coincidencia real (los otros 39 son `addEventListener`)]`. Ninguno de los dos llama a una función definida en el script — son JS autocontenido en el propio atributo — así que la extracción a módulos ES no los toca ni los rompe, **pero si alguien "endurece" el CSP como efecto colateral de esta fase** (quitando `'unsafe-inline'` porque "ya no hay script inline grande"), esos 2 handlers dejarán de ejecutarse sin ningún error visible salvo un aviso en la consola del navegador.

**Cómo evitarlo:** no tocar el CSP en esta fase (no está en el alcance de CONTEXT.md ni en los Success Criteria). Si en el futuro se quiere quitar `'unsafe-inline'`, esos 2 handlers deben moverse primero a `addEventListener` en `videoCanvas.js`.

**Señales de alerta:** el video no se recupera tras un error de carga, o el botón "Reintentar conexión" deja de responder, sin ningún error de red visible — síntoma clásico de un bloqueo silencioso de CSP.

### Pitfall 4: la Chart.js CDN `<script>` debe seguir en una sola línea con `integrity=`

**Qué falla:** `tests/test_security_regression.py::TEST_vuln_14_chartjs_cdn_has_subresource_integrity` **[VERIFIED: lectura directa del test]** itera línea a línea `frontend/index.html` buscando una línea que contenga `chart.js` y `cdn` (en minúsculas) y comprueba que esa misma línea contiene `integrity=`. Si al reformatear el `<head>` esa etiqueta `<script>` se divide en varias líneas (p. ej. un atributo por línea, como ya se hace en otras partes del marcado), el test falla aunque el SRI siga presente.

**Cómo evitarlo:** mantener la etiqueta `<script>` de Chart.js en una única línea al mover/reformatear el `<head>`.

### Pitfall 5: medir la carga inicial en `localhost` no valida el criterio "< 1s en LAN"

**Qué falla:** el criterio de éxito #6 exige medir en LAN, no en loopback. Una medición hecha abriendo el navegador en la misma máquina que corre `uvicorn` tendrá latencia de red ~0, lo que no demuestra nada sobre el escenario real (otro dispositivo de la LAN accediendo al dashboard).

**Cómo evitarlo:** documentar la medición desde un segundo dispositivo de la LAN (u otra pestaña apuntando a la IP de la LAN, no a `localhost`/`127.0.0.1`), con DevTools → Network → "Disable cache" desactivado para simular una recarga normal, y capturar el tiempo hasta `Load`/`DOMContentLoaded`. Si no hay acceso a un segundo dispositivo en la sesión de ejecución, dejarlo como checkpoint diferido explícito en el SUMMARY (mismo patrón que los 9 checkpoints de cámara real ya diferidos en fases anteriores — ver STATE.md).

## Code Examples

### Servido de `/static/js/*.js` — nada que cambiar en el backend

```python
# backend/main.py:609 — ya existe, no requiere modificación
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
# FRONTEND_DIR = Path(__file__).parent.parent / "frontend"  (línea 61)
# => frontend/js/app.js queda servido en /static/js/app.js
# => frontend/css/base.css queda servido en /static/css/base.css
```

### `app.js` como único punto de bootstrap (evita ciclos de import)

```javascript
// frontend/js/app.js
import { connectWS } from './websocket.js';
import { loadInitialData, bindPtzControls /* … */ } from './views/dashboard.js';
import { loadZones, bindZoneForm } from './components/zoneEditor.js';
import { loadRecordings } from './components/eventCard.js';
import { loadPersons, bindEnrollForm } from './components/personGallery.js';
import { loadDetectionClasses } from './components/detectionClasses.js';

document.addEventListener('DOMContentLoaded', () => {
  loadInitialData();
  bindPtzControls();
  loadZones();
  loadRecordings();
  loadPersons();
  loadDetectionClasses();
  connectWS(); // websocket.js no necesita saber que app.js existe
});
```

### `websocket.js` despachando a otros módulos sin ciclo

```javascript
// frontend/js/websocket.js
import { updateStat, showToast, hourlyToArray } from './views/dashboard-events.js';
import { addRecording, updateRecordingStatus } from './components/eventCard.js';
import { setRecBadge } from './components/videoCanvas.js';

export function connectWS() {
  // … igual que hoy (líneas 1146-1201 de index.html), pero llamando
  // a las funciones importadas en vez de a globals implícitos.
}
```

### Verificación defensiva de tipo MIME (opcional, barata, recomendable dado el landmine conocido de Windows)

```python
# backend/main.py — si se quiere blindar contra un registro de Windows corrupto
# en la máquina de despliegue, sin cambiar el comportamiento hoy verificado correcto:
import mimetypes
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
```

## State of the Art

| Antes | Ahora | Cuándo cambió | Impacto |
|--------------|------------------|------------------|--------|
| `application/javascript` como tipo MIME "canónico" para JS | `text/javascript` es el tipo recomendado por WHATWG/IANA | Actualización de la especificación de tipos MIME, ya reflejada en Python `mimetypes` y en los navegadores actuales | No afecta a esta fase — ambos tipos son aceptados por los navegadores para `<script type="module">`, y Python ya devuelve el recomendado |

No hay más cambios de "estado del arte" relevantes — ES modules nativos llevan siendo estables en todos los navegadores evergreen desde hace años y no ha habido cambios de comportamiento recientes que afecten a esta fase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Reformatear el marcado (colapsar atributos multilínea, quitar comentarios banner) puede recortar líneas de forma no trivial pero no se ha demostrado que baste para llegar a <300 líneas de `index.html` | Common Pitfalls → Pitfall 1 | Si el plan asume que "solo reformatear" es suficiente sin medirlo tras hacerlo, el criterio de éxito #1 puede quedar incumplido sin que nadie lo note hasta la puerta de fase |
| A2 | La cifra "1843" del ROADMAP para el `index.html` de partida es un número desactualizado (no recalculado desde al menos la Fase 27-10) y no una medición reciente | Common Pitfalls → Pitfall 1 | Bajo impacto — no cambia el análisis (el fichero real mide 2038, verificado), solo explica por qué hay una discrepancia con el ROADMAP |

## Open Questions

1. **¿Cómo se alcanza realmente "`index.html` < 300 líneas" dado que el marcado por sí solo mide 667 líneas?**
   - Qué sabemos: el recuento actual está verificado con precisión (667 líneas de marcado, ~685 en el `index.html` final si se mueve intacto). CONTEXT.md prohíbe explícitamente introducir un sistema de plantillas, y pide mantener los mismos `id` y el mismo marcado.
   - Qué es incierto: si "sin sistema de plantillas" también descarta cargar fragmentos de HTML estático vía `fetch()`+`innerHTML` (que no es un motor de plantillas, pero sí es una decisión de arquitectura nueva no mencionada en CONTEXT.md), o si el número "300" para `index.html` debe renegociarse como parte de esta fase.
   - Recomendación: antes de comprometer tareas de reestructuración de marcado, o bien el planificador escala esta pregunta explícitamente (nueva vuelta corta a discuss-phase, dado que es una decisión de arquitectura, no un detalle de implementación), o el plan documenta expresamente la desviación numérica esperada y por qué, dejando que la puerta de fase la revise con los números reales delante.

2. **¿`videoCanvas.js` debe exponer funciones (`setRecBadge`, `setResolutionBadge`) que los demás módulos importan, o basta con que cada módulo siga tocando `#rec-badge`/`#res-badge` por `id` directamente?**
   - Qué sabemos: técnicamente ambas opciones funcionan porque los `id` del DOM son globales al documento, no al módulo. CONTEXT.md nombra a `videoCanvas.js` como dueño de "overlay/badges de resolución/REC/detecciones", lo que sugiere la primera opción.
   - Qué es incierto: si "dueño" implica una API exportada obligatoria o es solo una descripción de dónde vive el código que primero pinta esos badges (el `<img>`/overlay), dejando el resto de módulos libres de tocar el DOM del badge directamente como hacen hoy.
   - Recomendación: usar el patrón de funciones exportadas (ver `Code Examples`) por ser más mantenible y no tener coste adicional relevante; no es un bloqueante si el plan decide lo contrario, pero debe ser una decisión consciente, no un descuido.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Navegador con soporte de ES modules (Chrome/Edge/Firefox recientes) | Todo el frontend tras esta fase | ✓ (asumido, LAN doméstica con navegadores modernos) | — | — |
| `StaticFiles` (Starlette, vía FastAPI) | Servir `css/`/`js/` | ✓ | Starlette instalada globalmente en esta máquina: `1.0.0`; el repo fija `fastapi>=0.115`, que resuelve una versión de Starlette compatible — el mecanismo `FileResponse`/`mimetypes` verificado es estable entre versiones recientes, no específico de la `1.0.0` observada aquí | — |
| Acceso a un segundo dispositivo en la LAN para medir carga <1s | Success Criteria #6 | Sin verificar en esta sesión de investigación | — | Documentar como checkpoint diferido en el SUMMARY si no hay acceso en la sesión de ejecución, mismo patrón que los checkpoints de cámara real ya diferidos |

No se identifican dependencias externas nuevas ni bloqueantes — esta fase no instala nada.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`pytest>=7.0`, `pytest-asyncio>=0.24`), convención `python_functions = TEST_*` en `pytest.ini` |
| Config file | `pytest.ini` (raíz del repo) |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/test_frontend_modules.py -v` (fichero nuevo, ver Wave 0 Gaps) |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -v` |

No existe framework de test JS en el repo (sin `package.json`, confirmado) — la verificación de paridad funcional sigue siendo un checklist manual en el SUMMARY, tal como fija CONTEXT.md. La parte que SÍ es automatizable con pytest son las propiedades mecánicas del refactor (líneas por fichero, tipo MIME real, SRI intacto).

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-01 | Cada módulo JS declarado en CONTEXT.md existe como fichero separado bajo `frontend/js/` | unit (fs) | `pytest tests/test_frontend_modules.py -k modules_exist -x` | ❌ Wave 0 |
| OPS-02 | Ningún fichero en `frontend/js/**/*.js` ni `frontend/css/*.css` supera 300 líneas | unit (fs) | `pytest tests/test_frontend_modules.py -k line_limit -x` | ❌ Wave 0 |
| OPS-03 | `frontend/js/app.js` se sirve con `Content-Type: text/javascript` (o `application/javascript`) vía la app ASGI real, y el SRI de Chart.js sigue en `index.html` | integration (TestClient) | `pytest tests/test_frontend_modules.py -k mime_type tests/test_security_regression.py -k chartjs -x` | Parcial — el test de Chart.js ya existe (`tests/test_security_regression.py`); el de MIME type es nuevo |
| OPS-03 | Paridad funcional completa (vídeo, PTZ, contadores, chart, toggles, resoluciones, grabaciones, personas, zonas, clases, filtros, salud, observabilidad, WS) | manual-only — sin framework de test JS en el repo | Checklist firmado en el SUMMARY | N/A por diseño (mismo criterio que 27-10) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_frontend_modules.py -q` tras cada módulo nuevo creado.
- **Per wave merge:** `pytest tests/ -q` (suite completa, 519 tests antes de esta fase).
- **Phase gate:** suite completa en verde + checklist manual de paridad firmado antes de `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_frontend_modules.py` — nuevo fichero: recuento de líneas por módulo JS/CSS (`OPS-02`), existencia de los ficheros locked por CONTEXT.md (`OPS-01`), y una petición real vía `TestClient` a `/static/js/app.js` comprobando `response.headers["content-type"]` (`OPS-03` / MIME landmine).
- [ ] Ningún fixture nuevo necesario — `tests/test_security_regression.py::TEST_vuln_14_chartjs_cdn_has_subresource_integrity` ya cubre el SRI y no requiere cambios, solo debe seguir en verde.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Sin cambios — la fase no toca `verify()`/auth de `backend/main.py` |
| V3 Session Management | No | Sin cambios |
| V4 Access Control | No | Sin cambios |
| V5 Input Validation | Parcial | Ya resuelto en el código actual: `dashboardAPI.addEvent` construye el DOM con `textContent` para datos que vienen del backend (`person_name`, timestamps) en vez de interpolarlos en `innerHTML`, con un comentario explícito en el código citando CodeQL `js/xss` — este patrón debe conservarse al mover la función, no soltarse "porque ahora es más cómodo usar template strings" |
| V6 Cryptography | No | Sin cambios — no se toca ningún flujo de credenciales/tokens |

### Known Threat Patterns for este stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS reflejado vía `person_name`/datos de eventos si se reintroduce interpolación directa en `innerHTML` al mover `addEvent`/`_recRow` a sus nuevos módulos | Tampering | Mantener el patrón ya existente de `textContent` tras montar la estructura estática (ver comentario en `index.html:1094-1097`); no es un patrón nuevo a introducir, es uno a no perder al copiar el código |
| Bloqueo silencioso de handlers inline si se toca el CSP sin darse cuenta | (no es una amenaza externa, es una regresión de disponibilidad) | No modificar `script-src`/`'unsafe-inline'` en esta fase — ver Pitfall 3 |

No se identifica superficie de ataque nueva: la fase no añade endpoints, no cambia autenticación/autorización, y no introduce ninguna dependencia nueva de terceros.

## Sources

### Primary (HIGH confidence)
- Lectura directa de `frontend/index.html`, `frontend/app.js`, `backend/main.py`, `tests/test_security_regression.py`, `.planning/phases/28-refactor-del-frontend-a-modulos-es/28-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `propuesta_mejora/SPEC_v2.md` (ADR-08, §8.2), `pytest.ini`, `requirements.txt`.
- Lectura directa de `site-packages/starlette/staticfiles.py` y `site-packages/starlette/responses.py` (mecanismo real de `FileResponse`/`guess_type`).
- Ejecución directa en esta sesión: `python -c "import mimetypes; ..."` (resultado `text/javascript` para `.js`) y `reg query "HKEY_CLASSES_ROOT\.js" /v "Content Type"` (sin entrada, confirma que no hay override de registro en esta máquina).
- [MDN — `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script) — orden de ejecución de módulos, modo estricto implícito.
- [MDN — JavaScript modules guide](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules) — comprobación estricta de tipo MIME para módulos.

### Secondary (MEDIUM confidence)
- [dev2qa.com — Fix "Failed to load module script" MIME type error](https://www.dev2qa.com/how-to-fix-failed-to-load-module-script-expected-a-javascript-module-script-but-the-server-responded-with-a-mime-type-of-text-plain-strict-mime-type-checking-is-enforced-for-module-scripts-per-h/) — confirma el mensaje de error real y su causa.
- [bugs.python.org/issue43975](https://bugs.python.org/issue43975) / [github.com/python/cpython/issues/88141](https://github.com/python/cpython/issues/88141) — landmine conocido de registro de Windows sobreescribiendo el tipo MIME de `.js`, corroborado pero no reproducido en esta máquina (se verificó que aquí no aplica).

### Tertiary (LOW confidence)
- Ninguna — todos los hallazgos técnicos de este documento están verificados directamente contra el código del repo, el entorno de ejecución, o citados de fuentes oficiales.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no hay stack nuevo, solo reorganización de código y CDNs ya fijados por decisiones previas.
- Architecture: HIGH — recuento de líneas y mapeo de secciones verificado directamente contra `frontend/index.html`; mecanismo de MIME type verificado contra el código fuente real de Starlette instalado y contra el comportamiento real de Python en esta máquina Windows.
- Pitfalls: HIGH para los verificados con grep/lectura directa (CSP, test de SRI, ausencia de patrones no-estrictos); MEDIA para la recomendación de reformateo de marcado (Pitfall 1, opción 1) ya que no se ha medido el resultado real de aplicarla.

**Research date:** 2026-08-18
**Valid until:** sin fecha de caducidad relevante — no depende de versiones de librerías que cambien rápido; revalidar solo si `frontend/index.html` cambia sustancialmente antes de que arranque la planificación (p. ej. otra fase añade contenido nuevo al monolito).
