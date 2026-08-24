// frontend/js/views/analytics-charts.js
// Las dos graficas de Chart.js de la vista de analitica (OPS-12).
//
// (a) Las instancias se crean en la PRIMERA ACTIVACION de la pestana Analitica,
//     nunca al cargar la pagina: un canvas dentro de un contenedor `hidden` mide
//     0x0, y con `responsive: true` Chart.js se queda con ese tamano (D-03).
//     31-10 llama a createCharts() desde nav.js/registerAnalyticsBoot().
// (b) ESTE MODULO NO AGREGA (D-07/OPS-14): peak_index, min_index, chart y
//     has_previous llegan ya resueltos del servidor (31-05). Cero reduce,
//     sort, filter ni funciones de maximo/minimo sobre datos del servidor.
//
// Chart.js ya esta cargado por CDN con SRI en index.html y expuesto como
// global `Chart` — no se importa ni se anade <script> (D-01).

const SERIE_ACTUAL   = '#60a5fa';                    // blue-400, trazo 2px
const SERIE_RELLENO  = 'rgba(96,165,250,0.20)';      // area al 20 %
const SERIE_ANTERIOR = '#475569';                    // slate-600, trazo discontinuo 4x4, 1.5px, SIN relleno
const REJILLA        = 'rgba(51,65,85,0.3)';
const TICK           = '#475569';
const TICK_SIZE      = 12;                           // D-04: 12px tambien dentro del lienzo

const _TOOLTIP_BASE = {
  backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
  titleColor: '#94a3b8', bodyColor: '#f8fafc',
  titleFont: { size: 12 }, bodyFont: { size: 12 },
};

const _AXIS_BASE = {
  grid: { color: REJILLA, drawTicks: false },
  border: { display: false },
};

let hourlyChart = null;
let occupancyChart = null;
let compareOn = true;
let _lastPrevious = [];

const $ = (id) => document.getElementById(id);

export function createCharts() {
  if (hourlyChart) return;  // idempotente: llamarlo dos veces no duplica instancias

  hourlyChart = new Chart($('an-chart-hourly').getContext('2d'), {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Personas', data: [],
          borderColor: SERIE_ACTUAL, backgroundColor: SERIE_ACTUAL,
          borderWidth: 2, borderRadius: 3, tension: 0.25, pointRadius: 0,
        },
        {
          label: 'Anterior', data: [],
          borderColor: SERIE_ANTERIOR, borderDash: [4, 4], borderWidth: 1.5,
          fill: false, pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          ..._TOOLTIP_BASE, mode: 'index', intersect: false,
          callbacks: {
            label: (c) => c.datasetIndex === 0
              ? ` ${c.parsed.y} personas`
              : ` ${c.parsed.y} personas (anterior)`,
          },
        },
      },
      scales: {
        x: { ..._AXIS_BASE, ticks: { color: TICK, font: { size: TICK_SIZE }, maxRotation: 0, maxTicksLimit: 12 } },
        y: { ..._AXIS_BASE, min: 0, ticks: { color: TICK, font: { size: TICK_SIZE }, precision: 0, maxTicksLimit: 4 } },
      },
    },
  });

  occupancyChart = new Chart($('an-chart-occupancy').getContext('2d'), {
    type: 'bar',
    indexAxis: 'y',
    data: { labels: [], datasets: [{ label: 'Ocupacion', data: [], borderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      plugins: { legend: { display: false }, tooltip: { ..._TOOLTIP_BASE } },
      scales: {
        x: { ..._AXIS_BASE, min: 0, ticks: { color: TICK, font: { size: TICK_SIZE }, precision: 0, maxTicksLimit: 4 } },
        y: { ..._AXIS_BASE, ticks: { color: TICK, font: { size: TICK_SIZE } } },
      },
    },
  });
}

export function renderHourly(data) {
  if (!hourlyChart) return;
  const ds = hourlyChart.data.datasets;

  // El SERVIDOR decide el tipo de grafica (bar <=48 cubos, line >48); el
  // cliente no cuenta cubos.
  hourlyChart.config.type = data.chart;
  ds[0].fill = (data.chart === 'line');

  hourlyChart.data.labels = data.labels;
  ds[0].data = data.values;
  _lastPrevious = data.previous;
  ds[1].data = compareOn ? data.previous : [];

  // Realce del pico sin funcion de maximo: color por posicion comparando el indice
  // con data.peak_index, que ya llega calculado del servidor.
  const paint = (alpha) => `rgba(96,165,250,${alpha})`;
  ds[0].backgroundColor = data.labels.map((_, i) => paint(i === data.peak_index ? 1 : 0.55));
  if (data.chart === 'line') {
    ds[0].pointRadius = data.labels.map((_, i) => (i === data.peak_index ? 4 : 0));
  }

  // Resumen accesible regenerado en cada carga (UI-SPEC: un aria-label fijo
  // no es accesibilidad). Todo por indice, nada agregado en el cliente.
  const que = data.range.bucket === 'hour' ? 'Personas por hora' : 'Personas por día';
  const cnv = $('an-chart-hourly');
  cnv.setAttribute('aria-label', data.peak_index === null
    ? `${que}, del ${data.range.from} al ${data.range.to}: sin actividad en este rango.`
    : `${que}, del ${data.range.from} al ${data.range.to}: ${data.total} personas en total, ` +
      `máximo ${data.values[data.peak_index]} en ${data.labels[data.peak_index]}, ` +
      `mínimo ${data.values[data.min_index]} en ${data.labels[data.min_index]}.`);

  hourlyChart.update();
}

export function renderOccupancy(data) {
  if (!occupancyChart) return;
  const ds = occupancyChart.data.datasets[0];
  const n = data.labels.length;

  // Opacidad decreciente por posicion (1.00 la mas ocupada -> 0.45 la ultima).
  // El orden lo decidio SQL; aqui solo se pinta. Guarda de division por cero
  // sobre una longitud (no una agregacion de datos), pero la funcion de maximo
  // esta prohibida en el fichero por lectura literal: se escribe sin ella a proposito.
  ds.backgroundColor = data.labels.map((_, i) => {
    const paso = n > 1 ? (i / (n - 1)) : 0;
    return `rgba(96,165,250,${(1 - paso * 0.55).toFixed(2)})`;
  });

  // Valor siempre visible sin raton: se anade al final de la etiqueta de
  // categoria (texto de dato, nunca HTML — convencion anti-XSS de D-15).
  occupancyChart.data.labels = data.labels.map((l, i) => `${l} — ${data.values[i]}`);
  ds.data = data.values;

  const cnv = $('an-chart-occupancy');
  cnv.setAttribute('aria-label', n === 0
    ? 'Ocupación por zona: sin zonas definidas.'
    : `Ocupación por zona, del ${data.range.from} al ${data.range.to}: ${data.total_zones} zonas; ` +
      `la más ocupada, ${data.labels[0]}, con ${data.values[0]} entradas.`);

  occupancyChart.update();
}

export function setCompare(enabled) {
  compareOn = enabled;
  if (!hourlyChart) return;
  hourlyChart.data.datasets[1].data = compareOn ? _lastPrevious : [];
  hourlyChart.update();
}

export function resizeCharts() {
  if (hourlyChart) hourlyChart.resize();
  if (occupancyChart) occupancyChart.resize();
}
