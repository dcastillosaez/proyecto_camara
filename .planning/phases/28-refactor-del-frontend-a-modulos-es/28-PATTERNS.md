# Phase 28: Refactor del frontend a módulos ES - Pattern Map

**Mapped:** 2026-08-18
**Files analyzed:** 16 (3 CSS + app.js + api.js + websocket.js + 4 sub-módulos de vista + 5 componentes + index.html)
**Analogs found:** 15 / 16 (extracción 1:1 desde `frontend/index.html`) — 1 sin analog real (`api.js`, abstracción nueva)

**Nota de alcance:** esta fase no es "buscar un fichero similar en el repo" — es extraer un único
`<script>` monolítico (`frontend/index.html:786-2025`, verificado por lectura directa) a módulos.
Por eso el "analog" de cada fichero nuevo es su propio rango de líneas de origen en `index.html`,
no otro fichero del proyecto. Todas las líneas citadas abajo están verificadas contra el fichero
real en esta sesión (no copiadas sin comprobar de 28-RESEARCH.md); donde difieren en 1-2 líneas del
recuento de RESEARCH.md se usa el número verificado aquí.

**Corrección de límite verificada:** el `<style>` cierra en la línea **117** (`</style>`), `</head>`
en 118, `<body>` en 119, línea 120 en blanco, marcado desde 121. `CONTEXT.md` dice "11-120" (aproximado,
incluye el cierre de `<head>`); el límite exacto del propio bloque `<style>` es **11-117**.

**Hallazgo nuevo no cubierto en RESEARCH.md:** el marcado del `<body>` no es un único bloque continuo.
El modal `#clip-modal` (líneas **2027-2035**) vive **después** del `<script>` (786-2025), fuera del
rango "121-784" que tanto CONTEXT.md como RESEARCH.md citan como "todo el marcado". Al reconstruir
`index.html`, ese bloque de 9 líneas debe preservarse igual (puede quedar donde está, después del
nuevo `<script type="module">`, o subirse junto al resto de modales — cualquiera de las dos funciona,
es marcado plano con su propio `id`).

## File Classification

| New File | Role | Data Flow | Source Range (`frontend/index.html`) | Match Quality |
|----------|------|-----------|----------------------------------------|----------------|
| `frontend/css/base.css` | config | static | líneas 12, 14-22, 24, 26-28, 30-34 | exact (extracción 1:1) |
| `frontend/css/layout.css` | config | static | ninguna — no existe CSS de layout hoy (Tailwind utility-driven) | sin contenido real que mover |
| `frontend/css/components.css` | config | static | líneas 36-50, 52-56, 58, 60-66, 68-77, 79-84, 86-90, 92-96, 97-99, 101-108, 110-116 | exact |
| `frontend/js/app.js` | provider (bootstrap) | event-driven | reemplaza `frontend/app.js` (stub 2 líneas) + llamadas de arranque dispersas (1362-1366, 1454-1455, 1654-1655, 1789, 1856, 1976-1977, 2022-2023) | exact, pero reestructurado (ver abajo) |
| `frontend/js/api.js` | service | request-response | sin bloque único — patrón `fetch`+`try/catch` repetido ~25 veces en todo el script | **sin analog** — abstracción nueva |
| `frontend/js/websocket.js` | service | event-driven / pub-sub | líneas 1121-1201 | exact |
| `frontend/js/views/dashboard.js` (core) | component/view | request-response | 787-873, 1203-1301 | exact |
| `frontend/js/views/dashboard-ptz.js` | component | request-response | 874-985 | exact |
| `frontend/js/views/dashboard-events.js` | component | CRUD + transform | 987-1119, 1896-1953 | exact |
| `frontend/js/views/dashboard-observability.js` | component | request-response (polling) | 1955-2023 | exact |
| `frontend/js/components/videoCanvas.js` | component | streaming + request-response | 1303-1361 (+ badges tocados desde WS y `eventCard`) | exact |
| `frontend/js/components/zoneEditor.js` | component | CRUD | 1690-1789 | exact |
| `frontend/js/components/eventCard.js` | component | CRUD + file-I/O | 1368-1515, 1858-1894 | exact |
| `frontend/js/components/detectionClasses.js` | component | CRUD | 1791-1856 | exact |
| `frontend/js/components/personGallery.js` | component | CRUD + file-I/O | 1518-1687 | exact |
| `frontend/index.html` (reescrito) | route/shell | request-response | mismo fichero, marcado 121-784 + 2027-2035 intacto | exact (recorte de `<style>`/`<script>`) |

## Shared Pattern: convención de estructura de cada módulo nuevo

Ningún módulo debe ejecutar `fetch()`, `addEventListener()` de arranque, ni `loadX()` como efecto
lateral de nivel superior al ser importado (import-time side effect). Hoy el script funciona así
porque es un único scope que se ejecuta una vez, en orden, al final del `<body>`. Al dividir en
módulos ES, cada uno debe exportar sus funciones y **`app.js` es quien decide cuándo se ejecutan**,
dentro de `DOMContentLoaded` — así lo describe CONTEXT.md ("`app.js`: orquesta la carga inicial y
engancha listeners") y así lo modela el `Code Example` de 28-RESEARCH.md:

```javascript
// frontend/js/app.js — patrón de bootstrap (ver 28-RESEARCH.md líneas 292-309)
import { connectWS } from './websocket.js';
import { loadInitialData, bindPtzControls, loadCamStatus, loadResolutions } from './views/dashboard.js';
// ...
document.addEventListener('DOMContentLoaded', () => {
  loadInitialData();
  bindPtzControls();
  loadZones();
  loadRecordings();
  loadPersons();
  loadDetectionClasses();
  connectWS();
});
```

Esto significa que llamadas hoy sueltas a nivel de script como `loadZones();` (línea 1789),
`loadDetectionClasses();` (línea 1856), `loadPersons(); setInterval(loadPersons, 30000);`
(líneas 1654-1655), `loadResolutions(); loadCamStatus(); loadInitialData(); connectWS();`
(líneas 1362-1366), `loadHealth(); setInterval(loadHealth, 30000);` (líneas 1976-1977) y
`loadObservability(); setInterval(loadObservability, 5000);` (líneas 2022-2023) **se convierten en
`export function loadX() {...}`** y su invocación se mueve a `app.js`. Los `addEventListener` de
botones/inputs de cada sección (p. ej. líneas 912-915, 1264-1289, 1693-1751) se agrupan en una
función exportada tipo `bindZoneForm()`/`bindPtzControls()` que también invoca `app.js`. El `setInterval`
de polling puede quedarse dentro de la propia función `loadX` (se registra la primera vez que
`app.js` la llama) — no hace falta moverlo aparte.

## Shared Pattern: estado hoy compartido por closures — qué exportar y desde dónde importar

Tabla verificada contra el código real (coincide con 28-RESEARCH.md, confirmada aquí con los usos concretos encontrados):

| Estado/función | Definido en (línea) | Usado por | Patrón recomendado |
|---|---|---|---|
| `showToast`, `TOAST_STYLES` | 795-811 | PTZ (892,895,905...), zonas (1735,1739...), grabaciones (1735...), enrolamiento (1640,1643...), clases detectadas (1839,1843...), toggles cámara (1256,1279...) — prácticamente todos los módulos | `export function showToast(...)` desde `views/dashboard.js` (core); `TOAST_STYLES` queda privado. Resto de módulos: `import { showToast } from '../views/dashboard.js'` |
| `updateStat` | 833-842 | `fetchCounts` (850-852, mismo módulo), `websocket.js` (1168,1172) | `export function updateStat(...)` desde `views/dashboard.js` |
| `setCamStatus` | 814-831 | `fetchCounts` (854,856), `connectWS` (1161) | `export function setCamStatus(...)` desde `views/dashboard.js`; `websocket.js` importa |
| `_ws`, `_wsRetry` | 1122-1123 | Solo dentro de `connectWS`/`onclose` (1196-1197) | Privado en `websocket.js`, no se exporta |
| `hourlyToArray` | 1125-1127 | `connectWS` (1167), `loadInitialData` (1212) | **Sigue el Code Example de RESEARCH:** exportar desde `views/dashboard-events.js` (vive junto a `updateChart`, que también la consume conceptualmente). `websocket.js` y `views/dashboard.js` (core) la importan de ahí |
| `window.dashboardAPI` (`updateChart`, `addEvent`, `setOnline`) | 1077-1119 | Todo el script (WS, `loadInitialData`, `applyFilters`) — **`[VERIFICADO: único fichero con `dashboardAPI` es index.html]`** | Deja de ser objeto global. `updateChart` y `addEvent` pasan a ser `export function` normales en `views/dashboard-events.js`. `setOnline` desaparece como alias — quien lo necesite importa `setCamStatus` directo de `views/dashboard.js` |
| `STATUS_LABEL`, `STATUS_COLOR` | 1369-1370 | Solo `_recRow`/`updateRecordingStatus` (mismo módulo) | Privados en `components/eventCard.js` |
| `DETECTION_CLASS_LABELS` | 1791-1793 | Solo `renderDetectionClasses` (mismo módulo) | Privado en `components/detectionClasses.js` |
| `loadInitialData` | 1204-1235 (core) | `delete-events-confirm` (línea 1026, en el rango que pasa a `dashboard-events.js`), `btn-clear-filters` (línea 1945, también en `dashboard-events.js`) | **Ciclo real de import, verificado línea a línea:** `views/dashboard-events.js` necesita `import { loadInitialData, showToast, updateStat } from './dashboard.js'`, y `views/dashboard.js` (core) necesita `import { updateChart, addEvent, hourlyToArray } from './dashboard-events.js'`. Es un ciclo de 2 módulos — permitido en ES modules (bindings en vivo, ver 28-RESEARCH.md "Todo el modo estricto..."), pero el plan debe saberlo de antemano, no descubrirlo al romper una referencia |

## Shared Pattern: badges de vídeo (`#rec-badge`, `#res-badge`) — 3 sitios que los tocan hoy

Verificado por lectura directa, `#rec-badge` se toca desde:
- `connectWS` → `onmessage`, tres ramas: líneas **1183, 1187, 1190** (`recording_started`/`_uploaded`/`_failed`)
- `loadRecordings()` en el rango que pasa a `eventCard.js` → línea **1450** (`textContent = recs.length`, no toggle de visibilidad — inconsistencia ya existente en el código actual, no introducida por esta fase)

`#res-badge` se toca solo desde la sección de resolución (líneas 1318-1321, 1341-1343), que pasa
íntegra a `videoCanvas.js`.

**Patrón recomendado** (igual que 28-RESEARCH.md, código verificado como no existente hoy — es una
extracción a función, no una copia literal):
```javascript
// frontend/js/components/videoCanvas.js
export function setRecBadge(visible, count) {
  const badge = document.getElementById('rec-badge');
  badge.classList.toggle('hidden', !visible);
  if (count != null) badge.textContent = count;
}

export function setResolutionBadge(text) {
  const badge = document.getElementById('res-badge');
  badge.textContent = text;
  badge.style.display = text ? 'block' : 'none';
}
```
`websocket.js` importa `setRecBadge` de `videoCanvas.js` en vez de las líneas 1183/1187/1190
actuales; `eventCard.js` la importa para la línea 1450.

## Shared Pattern: XSS-safe DOM (mantener al copiar, no perder)

`views/dashboard-events.js`, función `addEvent` (líneas 1083-1117, comentario explícito en
1094-1097 citando CodeQL `js/xss`): construye el nodo con `innerHTML` solo para la estructura
estática (SVG/spans vacíos) y asigna **todo** dato que viene del backend (`dir`, `ts`, `personName`,
`total`) vía `.textContent` después de montar el nodo. **Este patrón debe copiarse tal cual**, no
simplificarse a un único `innerHTML` con template string aunque sea "más cómodo".

```javascript
// líneas 1102-1113 — patrón a preservar exacto
item.innerHTML = `
  <svg ...>${arrow}</svg>
  <span class="ev-dir ${color} font-semibold uppercase text-xs w-6"></span>
  <span class="ev-ts text-slate-400 flex-1 mono text-xs"></span>
  ${nameTag}
  ${intrusionTag}
  <span class="ev-total text-slate-600 text-xs tabular-nums"></span>
`;
item.querySelector('.ev-dir').textContent = dir;
item.querySelector('.ev-ts').textContent = ts;
item.querySelector('.ev-total').textContent = `#${total}`;
if (personName) item.querySelector('.ev-name').textContent = personName;
```

**Nota (no bloqueante, no forma parte del alcance de esta fase):** `loadPersons()` (líneas 1542,
1545-1546, en `personGallery.js`) y `loadZones()` (línea 1770-1771, en `zoneEditor.js`) sí
interpolan `p.name`/`z.name` directo en `innerHTML` — es el patrón preexistente, cópiese igual;
endurecerlo no está pedido por CONTEXT.md ni es parte de esta extracción 1:1.

---

## Pattern Assignments

### `frontend/css/base.css` (config, static)

**Fuente:** `frontend/index.html:12,14-22,24,26-28,30-34`

```css
*, *::before, *::after { box-sizing: border-box; }

body {
  font-family: 'Inter', system-ui, sans-serif;
  background: #020617;
  color: #f8fafc;
  min-height: 100svh;
  display: flex;
  flex-direction: column;
  margin: 0;
}

.mono { font-family: 'JetBrains Mono', monospace; }

::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }

@keyframes pulse-ring {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.35; transform: scale(0.75); }
}
.pulse { animation: pulse-ring 2s ease-in-out infinite; }
```
Copia literal, sin cambios — es CSS puro, no requiere imports ni exports.

---

### `frontend/css/components.css` (config, static)

**Fuente:** `frontend/index.html:36-50,52-56,58,60-66,68-77,79-84,86-90,92-96,97-99,101-108,110-116`

Bloques a mover tal cual: `.ptz-btn` (+ hover/active/focus-visible/busy), `@keyframes stat-pop` +
`.stat-pop`, `.card`, `.preset-btn` (+ hover/active), `.event-item` + `@keyframes slide-in`,
`.toast` (+ `.toast.show`), `.cam-toggle[aria-checked]` (+ knob + focus-visible + disabled),
`.intrusion-badge`, `.gallery-grid`/`.gallery-thumb` (+ hover), `.filter-input`/`.filter-select`,
`#clip-modal`/`#clip-modal.open`/`#clip-modal video`. Ningún selector depende de JS ni de otro CSS
— copia 1:1.

---

### `frontend/css/layout.css` (config, static)

**Sin contenido que mover.** Verificado: `0` coincidencias de `@media` en el `<style>` actual, y el
único grid de página (`grid grid-cols-1 lg:grid-cols-5 gap-4`, línea 151) es una clase de utilidad
Tailwind en el marcado, no CSS propio. Crear el fichero con un comentario explicando por qué está
vacío (layout gestionado 100% por clases de utilidad de Tailwind en el marcado) en vez de dejarlo
sin crear — CONTEXT.md lo fija como parte de la estructura LOCKED.

---

### `frontend/js/websocket.js` (service, event-driven)

**Fuente:** `frontend/index.html:1121-1201`

**Imports necesarios** (funciones que hoy son globals del mismo scope):
```javascript
import { updateStat, setCamStatus, showToast } from './views/dashboard.js';
import { updateChart, addEvent, hourlyToArray } from './views/dashboard-events.js';
import { addRecording, updateRecordingStatus } from './components/eventCard.js';
import { setRecBadge } from './components/videoCanvas.js';
```

**Core pattern — reconexión con backoff** (líneas 1146-1201, copiar completo, sustituyendo accesos
directos como se indica):
```javascript
async function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let wsUrl = `${proto}//${location.host}/ws`;
  try {
    const res = await fetch('/api/ws-token');
    if (res.ok) {
      const { token } = await res.json();
      if (token) wsUrl += `?token=${token}`;
    }
  } catch (_) {}
  _ws = new WebSocket(wsUrl);

  _ws.onopen = () => { _wsRetry = 1000; setWsStatus(true); setCamStatus(true); };

  _ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'init') {
      updateChart(hourlyToArray(msg.hourly));           // antes: dashboardAPI.updateChart
      updateStat('stat-total', msg.total_today ?? 0);
    } else if (msg.type === 'detection') {
      const ts = new Date(msg.timestamp).toLocaleTimeString('es-ES', { hour12: false });
      addEvent(ts, msg.direction, msg.total_today, msg.person_name ?? null, msg.is_intrusion ?? false); // antes: dashboardAPI.addEvent
      updateStat('stat-total', msg.total_today);
      // actChart vive ahora en dashboard-events.js — exponer updateCurrentHourBar(h) desde ahí
      // en vez de tocar actChart.data directamente (actChart es privado a ese módulo)
      showToast(`Cruce ${msg.direction.toUpperCase()} detectado...`, msg.is_intrusion ? 'error' : 'success', 2000);
    } else if (msg.type === 'recording_started') {
      addRecording({ id: msg.id, filename: msg.filename, upload_status: 'pending', created_at: new Date().toISOString() });
      setRecBadge(true);                                  // antes: getElementById('rec-badge').classList.remove('hidden')
      showToast(`Grabando: ${msg.filename}`, 'info', 3000);
    } else if (msg.type === 'recording_uploaded') {
      updateRecordingStatus(msg.filename, 'uploaded', msg.gdrive_id);
      setRecBadge(false);
    } else if (msg.type === 'recording_failed') {
      updateRecordingStatus(msg.filename, 'failed');
      setRecBadge(false);
    }
  };

  _ws.onclose = () => { setWsStatus(false); setTimeout(connectWS, _wsRetry); _wsRetry = Math.min(_wsRetry * 2, 30000); };
  _ws.onerror = () => _ws.close();
}
```

**Detalle no trivial encontrado al leer el código real:** la rama `detection` del `onmessage`
(líneas 1174-1177) también actualiza `actChart.data.datasets[0].data[h]` y llama
`actChart.update('active')` directamente — `actChart` es una constante privada definida en la
sección Chart (línea 1040), que pasa a `views/dashboard-events.js`. **`websocket.js` no puede tocar
`actChart` directamente** porque no es su dueño; hace falta exportar una función nueva desde
`dashboard-events.js` (p. ej. `export function bumpHourBar(hour) { actChart.data.datasets[0].data[hour]++; actChart.update('active'); document.getElementById('chart-placeholder').style.display = 'none'; }`)
que `websocket.js` importe y llame. Esto no está en el Code Example de 28-RESEARCH.md — es un
acoplamiento real encontrado al leer las líneas 1174-1177 contra la definición de `actChart` en 1040.

`export`: `connectWS`. `setWsStatus` puede quedar privado (solo lo usa `connectWS`, verificado —
única llamada en línea 1160/1195) o exportarse si `app.js` quiere leer el estado; no tiene otro
consumidor hoy.

---

### `frontend/js/views/dashboard.js` (core) (component, request-response)

**Fuente:** `frontend/index.html:787-873` (clock, toast, cam-status, stat counter, counts/detections
polling) + `1203-1301` (initial data load, camera toggles + reboot)

**Core pattern — polling con try/catch consistente** (líneas 844-858, patrón repetido en todo el
proyecto, úsese como referencia para `api.js`):
```javascript
async function fetchCounts() {
  try {
    const res = await fetch('/counts');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    updateStat('stat-total', d.total ?? 0);
    updateStat('stat-in',    d.in    ?? 0);
    updateStat('stat-out',   d.out   ?? 0);
    document.getElementById('events-badge').textContent = d.total ?? 0;
    setCamStatus(true);
  } catch {
    setCamStatus(false);
  }
}
```

**Imports necesarios:**
```javascript
import { updateChart, addEvent, hourlyToArray } from './dashboard-events.js';
```
(usados solo dentro de `loadInitialData`, líneas 1204-1235 — sustituir `dashboardAPI.updateChart`/
`dashboardAPI.addEvent` por las importaciones directas)

**Exports:** `showToast`, `updateStat`, `setCamStatus`, `loadInitialData`, `bindPtzControls` (no
existe hoy con ese nombre — es el conjunto de `addEventListener` de PTZ que **RESEARCH.md** agrupa
así en su Code Example, pero verificado contra el código real, esos listeners viven en el rango
874-985 asignado a `dashboard-ptz.js`, no en el core; el nombre `bindPtzControls` debe exportarse
desde **`dashboard-ptz.js`**, no desde `dashboard.js` — corrección al Code Example de RESEARCH, que
simplifica el import sin especificar el módulo exacto), `loadCamStatus`, `loadResolutions` (esta
última en realidad pertenece a `videoCanvas.js`, ver abajo — otra corrección al agrupamiento
implícito del ejemplo de RESEARCH).

---

### `frontend/js/views/dashboard-ptz.js` (component, request-response)

**Fuente:** `frontend/index.html:874-985` (steps slider, move, stop + listeners + shortcuts,
presets, save preset)

**Imports:** `import { showToast } from './dashboard.js';`

**Core pattern** (líneas 879-899, `ptzMove` — representativo del try/catch/finally con
busy-state que se repite en las 5 subsecciones):
```javascript
async function ptzMove(dir) {
  const steps = parseInt(stepsInput.value, 10);
  const btn   = document.querySelector(`.ptz-btn[data-dir="${dir}"]`);
  if (btn) btn.classList.add('busy');
  try {
    const res = await fetch('/ptz/move', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ direction: dir, steps }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      showToast(`PTZ: ${err.detail ?? res.statusText}`, 'error');
    }
  } catch (e) {
    showToast(`PTZ sin respuesta: ${e.message}`, 'error');
  } finally {
    if (btn) btn.classList.remove('busy');
  }
}
```

**Export:** `bindPtzControls()` — función nueva que envuelve las líneas 912-923 (listeners de
`.ptz-btn`, `ptz-stop-btn`, `keydown` de flechas/espacio) más `document.getElementById('load-presets-btn').addEventListener(...)`
(línea 959) y `document.getElementById('save-preset-btn').addEventListener(...)` (línea 963);
`loadPresets()` también se exporta y se invoca dentro de `bindPtzControls()` en vez de a nivel de
módulo (línea 960 hoy).

---

### `frontend/js/views/dashboard-events.js` (component, CRUD + transform)

**Fuente:** `frontend/index.html:987-1119` (delete-by-range, chart + `dashboardAPI`) +
`1896-1953` (filtros, export CSV)

**Imports:** `import { showToast, updateStat, loadInitialData } from './dashboard.js';` (ciclo
documentado arriba en Shared Patterns — es correcto, no un error)

**Core pattern — Chart.js init** (líneas 1040-1074, copiar completo tal cual, `actChart` queda
privado al módulo):
```javascript
const actChart = new Chart(
  document.getElementById('activity-chart').getContext('2d'),
  { type: 'bar', data: { labels: hours, datasets: [{ /* ... */ }] }, options: { /* ... */ } }
);
```

**Exports (sustituyen a `window.dashboardAPI`):**
```javascript
export function updateChart(hourlyData) {
  actChart.data.datasets[0].data = hourlyData;
  actChart.update('active');
  document.getElementById('chart-placeholder').style.display = 'none';
}
export function addEvent(ts, dir, total, personName, isIntrusion = false) { /* líneas 1083-1117, ver patrón XSS-safe arriba */ }
export function bumpHourBar(hour) { /* nueva, ver nota en websocket.js — extrae líneas 1174-1177 */ }
export function hourlyToArray(hourly) { /* líneas 1125-1127 */ }
export function applyFilters() { /* líneas 1913-1935, sustituir dashboardAPI.addEvent por addEvent local */ }
```

`btn-apply-filters`/`btn-clear-filters`/`btn-export-csv` listeners (1937, 1939-1946, 1949-1953) se
agrupan en `export function bindEventFilters()`, invocada desde `app.js`.

---

### `frontend/js/views/dashboard-observability.js` (component, request-response polling)

**Fuente:** `frontend/index.html:1955-2023`

Sin imports de otros módulos nuevos — ambas funciones (`loadHealth`, `loadObservability`) solo
tocan `document.getElementById` de sus propios paneles, verificado (no llaman `showToast` ni
`updateStat`). Copia directa:
```javascript
// líneas 1994-2020 — patrón representativo (helpers privados + fetch + textContent)
async function loadObservability() {
  try {
    const res = await fetch('/api/v2/metrics');
    if (!res.ok) return;
    const d = await res.json();
    const cam = _gaugeValue(d, 'capture_fps', "{'camera': 'cam1'}");
    // ...
    document.getElementById('obs-capture-fps').textContent = cam != null ? `${cam.toFixed(1)} FPS` : '–';
    // ...
  } catch {}
}
```
**Exports:** `loadHealth`, `loadObservability` (cada uno registra su propio `setInterval` en su
primera invocación, igual que hoy en líneas 1977/2023).

---

### `frontend/js/components/videoCanvas.js` (component, streaming + request-response)

**Fuente:** `frontend/index.html:1303-1361` (resolution dropdown) + funciones nuevas `setRecBadge`/
`setResolutionBadge` (ver Shared Pattern arriba, sin línea de origen — código nuevo)

**Imports:** `import { showToast } from '../views/dashboard.js';`

**Core pattern** (líneas 1328-1360, `resolution-select` change handler — reconecta el MJPEG tras
cambiar resolución):
```javascript
document.getElementById('resolution-select').addEventListener('change', async (e) => {
  const [w, h] = e.target.value.split(',').map(Number);
  // ...
  const res = await fetch('/camera/resolution', { method: 'POST', headers: {...}, body: JSON.stringify({ width: w, height: h }) });
  if (res.ok) {
    const d = await res.json();
    showToast(`Resolución → ${d.resolution}`, 'success');
    setResolutionBadge(d.resolution);                 // antes: tocar #res-badge directo (líneas 1341-1343)
    const img = document.getElementById('video-feed');
    img.src = '/video_feed?t=' + Date.now();
    img.style.imageRendering = (w > 0 && w <= 640) ? 'pixelated' : 'auto';
  }
  // ...
});
```
**Exports:** `loadResolutions`, `setRecBadge`, `setResolutionBadge`. `loadResolutions` se invoca
desde `app.js` (línea 1362 hoy), no a nivel de módulo.

**Nota:** los handlers `onerror`/`onclick` inline del marcado (`index.html:163,177` — recarga de
`#video-feed` y botón "Reintentar conexión") **no se tocan en esta fase** (Pitfall 3 de
28-RESEARCH.md: el CSP actual permite `'unsafe-inline'`; moverlos a `addEventListener` en
`videoCanvas.js` sería una mejora fuera de alcance que además, si se combinara con endurecer el CSP,
podría romper silenciosamente esos dos controles). Quedan en el marcado tal cual.

---

### `frontend/js/components/zoneEditor.js` (component, CRUD)

**Fuente:** `frontend/index.html:1690-1789`

**Imports:** `import { showToast } from '../views/dashboard.js';`

**Core pattern — CRUD completo** (crear/listar/borrar zona, líneas 1705-1787):
```javascript
document.getElementById('zone-save-btn').addEventListener('click', async () => {
  // valida id/name/points (JSON.parse de polígono, mínimo 3 puntos) — líneas 1706-1724
  const res = await fetch('/api/zones', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: zoneId, name: zoneName, polygon_json: JSON.stringify(pts), enabled: true }),
  });
  // ... showToast + loadZones() en éxito
});

async function loadZones() {
  const res = await fetch('/api/zones');
  // ... renderiza .zone-row con botón .btn-del-zone que hace DELETE /api/zones/{id}
}
```
**Exports:** `loadZones`, `bindZoneForm()` (agrupa los listeners de `btn-add-zone`/`zone-cancel-btn`/
`zone-save-btn`, líneas 1693-1750).

---

### `frontend/js/components/eventCard.js` (component, CRUD + file-I/O)

**Fuente:** `frontend/index.html:1368-1515` (grabaciones + borrado por rango) + `1858-1894`
(delegación de reproducción de clip + modal de vídeo)

**Imports:** `import { showToast } from '../views/dashboard.js'; import { setRecBadge } from './videoCanvas.js';`

**Core pattern — fila de grabación con enlace externo a Drive** (líneas 1372-1410, `_recRow`,
patrón XSS-safe con `dataset`/`textContent` ya presente, preservar igual):
```javascript
function _recRow(r) {
  // ...
  row.innerHTML = `<div>...<span class="rec-name"...></span></div><div><span class="rec-status"...></span>...</div>`;
  row.querySelector('.btn-play-clip').dataset.src = `/clips/${r.filename}`;
  const nameSpan = row.querySelector('.rec-name');
  nameSpan.textContent = r.filename.replace('clip_', '');   // nunca interpolado en innerHTML
  nameSpan.title = r.filename;
  if (r.gdrive_id) {
    const link = document.createElement('a');
    link.href = `https://drive.google.com/file/d/${r.gdrive_id}/view`;
    link.target = '_blank'; link.rel = 'noopener';
    // ...
  }
  return row;
}
```

**Core pattern — modal de vídeo** (líneas 1866-1894, incluye el matiz de timing ya documentado en
el propio código: el listener del modal debe esperar a `DOMContentLoaded` porque el modal está
declarado después del `<script>` en el marcado original — **al mover a un módulo ES este comentario
deja de ser 100% necesario** porque `type="module"` ya difiere la ejecución hasta que el documento
está parseado, pero **no hace daño mantenerlo** por claridad, y es más seguro no quitarlo sin
verificar):
```javascript
function openClipModal(src) {
  const modal = document.getElementById('clip-modal');
  const vid   = document.getElementById('clip-video');
  vid.src = src;
  modal.classList.add('open');
  vid.play().catch(() => {});
}
```
**Exports:** `addRecording`, `updateRecordingStatus`, `loadRecordings`, `openClipModal`,
`bindEventCardControls()` (agrupa delegación de `.btn-play-clip` en `#recordings-list` línea 1859,
cierre de modal líneas 1879-1886, `Escape` líneas 1888-1894, y los listeners de borrado por rango
1461-1515).

**Recordatorio de la Shared Pattern de arriba:** `loadRecordings` (línea 1450) y las 3 ramas de
`websocket.js` deben usar `setRecBadge(...)` en vez de tocar `#rec-badge` cada uno por su cuenta.

---

### `frontend/js/components/detectionClasses.js` (component, CRUD)

**Fuente:** `frontend/index.html:1791-1856` (sin comentario banner propio — Fase 27-10, entre
"Zones panel" y "event delegation for clip play buttons")

**Imports:** `import { showToast } from '../views/dashboard.js';`

**Core pattern — GET/PUT con revert en error** (líneas 1816-1854, ya documentado en 27-10-PLAN.md,
cópiese igual incluyendo el comentario de revert):
```javascript
async function saveDetectionClasses() {
  const msg = document.getElementById('detection-classes-msg');
  const checkboxes = document.querySelectorAll('.detection-class-checkbox');
  const classes = Array.from(checkboxes).filter(cb => cb.checked).map(cb => parseInt(cb.dataset.classId, 10));
  checkboxes.forEach(cb => cb.disabled = true);
  try {
    const res = await fetch('/api/v2/detection/classes', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ classes }),
    });
    if (res.ok) {
      showToast('Clases activas actualizadas', 'success');
      renderDetectionClasses(await res.json());
    } else {
      // ... muestra error y revierte
      await loadDetectionClasses();  // revierte los checkboxes al estado real del servidor
    }
  } catch {
    // ... y también revierte
    await loadDetectionClasses();
  }
}
```
**Exports:** `loadDetectionClasses`, `renderDetectionClasses`, `saveDetectionClasses` (el checkbox
`change` listener se ata dentro de `renderDetectionClasses`, línea 1811-1813 — se mantiene igual,
no requiere una función `bind` separada porque los checkboxes se recrean en cada render).

---

### `frontend/js/components/personGallery.js` (component, CRUD + file-I/O)

**Fuente:** `frontend/index.html:1518-1655` (personas + modal de enrolamiento) + `1657-1687`
(modal de galería)

**Imports:** `import { showToast } from '../views/dashboard.js';`

**Core pattern — enrolamiento con `FormData` (dos fuentes: frame actual o subida)** (líneas
1610-1652):
```javascript
enrollForm.addEventListener('submit', async e => {
  e.preventDefault();
  const source = enrollForm.querySelector('input[name="enroll-source"]:checked').value;
  const fd = new FormData();
  fd.append('name', name);
  if (source === 'frame') fd.append('use_current_frame', 'true');
  else fd.append('image', document.getElementById('enroll-file').files[0]);
  const res = await fetch('/api/enroll_face', { method: 'POST', body: fd });
  // ... showToast + loadPersons() en éxito
});
```
**Exports:** `loadPersons`, `openGallery`, `bindPersonGallery()` (agrupa `btn-enroll` click
(1563-1594), `enroll-close`/click-outside (1596-1602), radios de fuente (1604-1608), submit
(1610-1652), y el cierre del `gallery-modal` (1659-1660)).

---

### `frontend/js/app.js` (provider, event-driven)

**Reemplaza:** `frontend/app.js` (stub 2 líneas, "Lógica del dashboard incluida en index.html —
entry point vacío para Phase 6") — **verificado que ningún `<script>` de `index.html` referencia
hoy `frontend/app.js`** (`grep` de `<script` en el fichero: solo 2 CDN en `<head>` + 1 inline en
786; ningún `src="...app.js"`). El stub queda huérfano tras esta fase — el plan debe decidir si se
borra o se deja como archivo muerto (recomendado: borrarlo, ya que `frontend/js/app.js` es su
reemplazo funcional con una ruta distinta).

```javascript
// frontend/js/app.js
import { connectWS } from './websocket.js';
import { loadInitialData, loadCamStatus, showToast } from './views/dashboard.js';
import { bindPtzControls, loadPresets } from './views/dashboard-ptz.js';
import { bindEventFilters } from './views/dashboard-events.js';
import { loadHealth, loadObservability } from './views/dashboard-observability.js';
import { loadResolutions } from './components/videoCanvas.js';
import { loadZones, bindZoneForm } from './components/zoneEditor.js';
import { loadRecordings, bindEventCardControls } from './components/eventCard.js';
import { loadDetectionClasses } from './components/detectionClasses.js';
import { loadPersons, bindPersonGallery } from './components/personGallery.js';

document.addEventListener('DOMContentLoaded', () => {
  bindPtzControls();
  bindZoneForm();
  bindEventCardControls();
  bindPersonGallery();
  bindEventFilters();

  loadResolutions();
  loadCamStatus();
  loadInitialData();
  loadZones();
  loadRecordings();
  loadPersons();
  loadDetectionClasses();
  loadHealth();
  loadObservability();

  connectWS();
});
```
Sigue el orden real de invocación de hoy (1362-2023) para minimizar diferencias de comportamiento
observable (p. ej. `loadResolutions`/`loadCamStatus` antes que `loadInitialData`/`connectWS`, igual
que en las líneas 1362-1366 actuales).

---

### `frontend/js/api.js` (service, request-response) — SIN ANALOG DIRECTO

No existe hoy un wrapper `fetch` — cada sección repite el mismo esqueleto ~25 veces en todo el
script (`fetchCounts` líneas 845-857, `ptzMove` 884-898, `loadPresets` 929-957, `loadZones` 1753-1786,
`loadPersons` 1519-1554, etc.), siempre con la misma forma:
```javascript
try {
  const res = await fetch(url, opts);
  if (!res.ok) { /* leer detail del error, mostrar toast o texto de error */ }
  const data = await res.json();
  // usar data
} catch (e) {
  // mostrar error de "sin respuesta"
}
```
CONTEXT.md autoriza empezar simple ("wrapper fino... sin necesidad de tipado real"). Patrón
recomendado, sintetizado de la forma repetida de arriba, no copiado de ningún sitio:
```javascript
// frontend/js/api.js
export async function apiFetch(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  return res.status === 204 ? null : res.json();
}
```
**Importante:** introducir `api.js` implica reescribir las ~25 llamadas `fetch` existentes para usar
`apiFetch`, lo cual es más que una extracción 1:1 — es una decisión de cuánto se adopta en esta fase
vs. dejar `fetch` directo en los módulos y añadir `api.js` como wrapper opcional para llamadas
nuevas. CONTEXT.md no lo explicita; el plan debe decidirlo (Claude's Discretion en RESEARCH.md,
"Mecanismo concreto de export/import").

---

### `frontend/index.html` (route/shell) — qué queda y qué se elimina

**Queda (sin tocar el contenido, solo la posición):**
- Líneas 1-10: doctype, meta, title, 2 `<script>` CDN (Tailwind, Chart.js con `integrity=` — debe
  seguir en una única línea, Pitfall 4 de RESEARCH.md, verificado: es la línea 8 hoy), preconnect +
  `<link>` de fuentes.
- Marcado completo 121-784 (mismos `id`, sin cambios) + el modal `#clip-modal` 2027-2035 (ver
  hallazgo arriba sobre su posición real).
- `</body></html>` finales.

**Se añade en `<head>`:**
```html
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/layout.css">
<link rel="stylesheet" href="/static/css/components.css">
```

**Se elimina:**
- El bloque `<style>` completo, líneas 11-117 (verificado, no 11-120).
- El bloque `<script>` inline completo, líneas 786-2025.

**Se añade al final del `<body>` (sustituye al `<script>` eliminado):**
```html
<script type="module" src="/static/js/app.js"></script>
```

**No requiere cambios en `backend/main.py`** — el mount `app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")`
(línea 609, verificado) ya cubre `frontend/css/` y `frontend/js/` sin modificación, porque monta el
directorio `frontend/` completo. `FRONTEND_DIR` se define en la línea 61 como
`Path(__file__).parent.parent / "frontend"`. La ruta `/` (líneas 621-623) sigue sirviendo
`FRONTEND_DIR / "index.html"` sin cambios.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/js/api.js` | service | request-response | No existe wrapper `fetch` hoy — patrón sintetizado a partir de ~25 repeticiones del mismo esqueleto try/catch (ver Pattern Assignment arriba) |
| `frontend/css/layout.css` | config | static | No hay CSS de layout hoy — el grid de columnas es una clase de utilidad Tailwind en el marcado, no una regla propia |

## Metadata

**Analog search scope:** `frontend/index.html` (único fichero fuente, 2038 líneas, leído
completo en esta sesión), `backend/main.py` (líneas 575-624, montaje estático + CSP), `frontend/app.js`
(stub 2 líneas).
**Files scanned:** 3 (no hay más frontend previo en el repo — confirmado, `frontend/css/` y
`frontend/js/` no existen todavía: `ls frontend/` solo devuelve `app.js` e `index.html`).
**Pattern extraction date:** 2026-08-18
