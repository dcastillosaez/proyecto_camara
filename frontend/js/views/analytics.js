// frontend/js/views/analytics.js
// Orquestador de la vista de analitica (OPS-12..OPS-15). Tres reglas lo gobiernan:
//   D-08: las cuatro peticiones de una tanda van en paralelo, cada una con su propio
//         catch — nunca un combinador que descarte las tres buenas por la cuarta mala.
//   D-09: un controlador de cancelacion por tanda. Cambiar de rango con peticiones en
//         vuelo las cancela, y una respuesta rezagada (nombre de error de cancelacion)
//         nunca pinta nada.
//   D-07: cero agregacion de cliente (OPS-14) — todo lo que se pinta ya llega resuelto
//         del servidor (31-04/31-05/31-06/31-09). Este modulo solo pide y coloca.
import * as nav from '../nav.js'; // import por namespace: la llamada real es la unica cita literal
import { apiFetch } from '../api.js';
import { createCharts, renderHourly, renderOccupancy, setCompare, resizeCharts } from './analytics-charts.js';
import { initRange, currentRange } from './analytics-range.js';
import { renderCards, renderRanking } from './analytics-ranking.js';
import { initExport, setExportEnabled } from './analytics-export.js';
import { isSafeMediaUrl } from './timeline-row.js';

const $ = (id) => document.getElementById(id);

// Estados por panel: los tres overlays que se alternan con `hidden`/`flex` (mismo patron
// que timeline.js::_show, porque el marcado los declara "hidden flex-col ...", sin la
// clase `flex` que activa el display) y, si aplica, el id de su contenido propio.
// `summary` no tiene marcado de estado (las cuatro tarjetas siempre estan en su sitio),
// asi que su entrada vacia hace que setPanelState() no toque el DOM para ese nombre.
const PANEL_STATES = {
  summary: {},
  hourly: { overlays: ['loading', 'empty', 'error'], content: 'an-chart-hourly' },
  occupancy: { overlays: ['loading', 'empty', 'error'], content: 'an-chart-occupancy' },
  persons: { overlays: ['loading', 'empty', 'error'], content: 'an-rank-list' },
  heatmap: { overlays: ['loading', 'empty', 'offline'] },
};

let ctrl = null;
let pending = 0;
let okPanels = 0;
let lastRange = null;
let heatmapPending = null;

function _show(id, on) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('hidden', !on);
  el.classList.toggle('flex', on);
}

function setPanelState(name, state) {
  const cfg = PANEL_STATES[name];
  if (!cfg) return;
  (cfg.overlays || []).forEach((s) => _show(`an-${name}-${s}`, s === state));
  if (cfg.content) {
    const el = $(cfg.content);
    if (el) el.classList.toggle('hidden', state !== 'ok');
  }
}

// Se sella cuando TODOS los de la tanda han resuelto (exito o error), nunca en la
// primera respuesta. Una peticion abortada NO llama a settle() (ver loadPanel): si lo
// hiciera, decrementaria el contador de la tanda NUEVA que ya reinicio `pending`.
function settle() {
  pending -= 1;
  if (pending > 0) return;
  const el = $('an-updated');
  if (el) el.textContent = `Actualizado a las ${new Date().toLocaleTimeString('es-ES')}`;
}

async function loadPanel(name, range, signal) {
  setPanelState(name, 'loading');
  setExportEnabled(name, false);
  let data;
  try {
    data = await apiFetch(
      `/api/v2/analytics/${name}?camera_id=cam1&from=${range.from}&to=${range.to}`,
      { signal },
    );
  } catch (err) {
    if (err.name === 'AbortError') return; // tanda vieja: ni DOM ni settle()
    setPanelState(name, 'error');
    settle();
    return;
  }

  let ok = true;
  if (name === 'summary') {
    renderCards(data);
    const peak = $('an-hourly-peak');
    if (peak) peak.textContent = data.peak ? `Pico ${data.peak.label} · ${data.peak.value}` : '';
  } else if (name === 'hourly') {
    const title = $('an-hourly-title');
    if (title) title.textContent = data.range.bucket === 'hour' ? 'Personas por hora' : 'Personas por día';
    renderHourly(data);
    const compare = $('an-compare');
    if (compare) {
      compare.disabled = !data.has_previous;
      compare.title = data.has_previous ? '' : 'No hay suficientes datos del periodo anterior para comparar.';
    }
    ok = data.total > 0;
  } else if (name === 'occupancy') {
    renderOccupancy(data);
    const foot = $('an-occupancy-foot');
    if (foot) foot.classList.toggle('hidden', !data.truncated);
    ok = data.labels.length > 0;
  } else if (name === 'persons') {
    renderRanking(data);
    ok = data.persons.length > 0;
  }

  setPanelState(name, ok ? 'ok' : 'empty');
  setExportEnabled(name, ok); // exportar cero filas es una descarga inutil
  if (ok) {
    okPanels += 1;
    if (okPanels === 4) setExportEnabled('json', true); // los cuatro paneles, no el heatmap
  }
  settle();
}

// Pinta la URL del heatmap si la pestana esta activa; si no, la guarda para cuando
// vuelva (resizeAnalytics). Un <img loading="lazy"> dentro de un contenedor oculto no
// dispara la peticion por si solo, asi que aplicar la URL con la vista oculta la
// perderia sin este paso intermedio.
function paintHeatmap(url) {
  const img = $('an-heatmap-img');
  if (img && isSafeMediaUrl(url)) img.src = url;
  setPanelState('heatmap', 'ok');
}

function applyHeatmap(scale) {
  // Tres constantes: la rampa se normaliza por el maximo, la escala siempre es
  // relativa. El valor absoluto (con su unidad, que manda el servidor) va en el
  // title de la leyenda — nunca inventar una cifra de personas aqui (D-12).
  const mark0 = $('an-heatmap-mark-0');
  if (mark0) mark0.textContent = '0';
  const markMid = $('an-heatmap-mark-mid');
  if (markMid) markMid.textContent = '50 %';
  const markPeak = $('an-heatmap-mark-peak');
  if (markPeak) markPeak.textContent = 'pico';
  const legend = $('an-heatmap-legend');
  if (legend) legend.title = `Escala relativa. Pico ${scale.peak} y media ${scale.mean} ${scale.unit}.`;

  // Sin el ?t= el navegador serviria de cache y el mapa parece congelado; el servidor
  // ignora el parametro. Sigue empezando por '/', asi que isSafeMediaUrl la acepta.
  const url = `/api/v2/analytics/heatmap?camera_id=cam1&t=${Date.now()}`;
  if (nav.activeView() !== 'analitica') { heatmapPending = url; return; }
  paintHeatmap(url);
}

async function loadHeatmap() {
  setPanelState('heatmap', 'loading');
  let res;
  // fetch crudo y no apiFetch A PROPOSITO: apiFetch lanza y pierde el codigo, y aqui
  // el codigo ES el dato (404 = sin actividad, 503 = sin senal). No "unificar" esto.
  try {
    res = await fetch('/api/v2/analytics/heatmap/scale?camera_id=cam1');
  } catch (e) {
    setPanelState('heatmap', 'offline');
    settle();
    return;
  }
  if (res.status === 404) { setPanelState('heatmap', 'empty'); settle(); return; }
  if (!res.ok) { setPanelState('heatmap', 'offline'); settle(); return; }
  applyHeatmap(await res.json());
  settle();
}

function load(range) {
  lastRange = range;
  if (ctrl) ctrl.abort(); // D-09: aborta la tanda anterior antes de empezar la nueva
  ctrl = new AbortController();
  pending = 5; // summary + hourly + occupancy + persons + heatmap
  okPanels = 0;
  setExportEnabled('json', false);
  ['summary', 'hourly', 'occupancy', 'persons'].forEach((p) => loadPanel(p, range, ctrl.signal));
  loadHeatmap();
}

function bindPanelButtons() {
  ['hourly', 'occupancy', 'persons'].forEach((name) => {
    const btn = $(`an-${name}-retry`);
    if (btn) btn.addEventListener('click', () => loadPanel(name, lastRange, ctrl.signal));
  });
  const compare = $('an-compare');
  if (compare) {
    compare.addEventListener('click', () => {
      if (compare.disabled) return;
      const active = !compare.classList.contains('active');
      compare.classList.toggle('active', active);
      compare.setAttribute('aria-pressed', String(active));
      setCompare(active); // datos del periodo anterior ya estan en memoria: sin red
    });
  }
}

function bootAnalytics() {
  createCharts();
  initRange(load);
  initExport(currentRange);
  bindPanelButtons();
  load(currentRange());
}

function resizeAnalytics() {
  resizeCharts();
  if (heatmapPending) {
    paintHeatmap(heatmapPending);
    heatmapPending = null;
  }
}

/** Registra el arranque diferido. No pide nada: quien no abre la pestana no paga nada. */
export function initAnalytics() {
  nav.registerAnalyticsBoot(bootAnalytics, resizeAnalytics);
}
