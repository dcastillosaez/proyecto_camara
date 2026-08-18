// frontend/js/views/dashboard-events.js
import { loadInitialData } from './dashboard.js';

// ── Events: delete by date range ─────────────────────
const deletePanel = document.getElementById('delete-events-panel');
const deleteMsg   = document.getElementById('delete-events-msg');

document.getElementById('btn-delete-events').addEventListener('click', () => {
  deleteMsg.classList.add('hidden');
  const now = new Date();
  const week = new Date(now - 7 * 864e5);
  const fmt = d => d.toISOString().slice(0, 16);
  document.getElementById('delete-from').value = fmt(week);
  document.getElementById('delete-to').value   = fmt(now);
  deletePanel.classList.toggle('hidden');
});

document.getElementById('delete-events-cancel').addEventListener('click', () => {
  deletePanel.classList.add('hidden');
});

document.getElementById('delete-events-confirm').addEventListener('click', async () => {
  const from = document.getElementById('delete-from').value;
  const to   = document.getElementById('delete-to').value;
  if (!from || !to) { return; }
  if (new Date(to) < new Date(from)) {
    deleteMsg.textContent = 'La fecha «Hasta» debe ser posterior a «Desde».';
    deleteMsg.className = 'text-xs text-center text-red-400';
    deleteMsg.classList.remove('hidden');
    return;
  }
  const btn = document.getElementById('delete-events-confirm');
  btn.disabled = true; btn.style.opacity = '0.5';
  try {
    const params = new URLSearchParams({ from_dt: new Date(from).toISOString(), to_dt: new Date(to).toISOString() });
    const res = await fetch(`/api/events?${params}`, { method: 'DELETE' });
    if (res.ok) {
      const d = await res.json();
      deleteMsg.textContent = `${d.deleted} evento(s) eliminado(s).`;
      deleteMsg.className = 'text-xs text-center text-green-400';
      deleteMsg.classList.remove('hidden');
      setTimeout(() => { deletePanel.classList.add('hidden'); loadInitialData(); }, 1500);
    } else {
      const d = await res.json().catch(() => ({}));
      deleteMsg.textContent = d.detail ?? 'Error al borrar.';
      deleteMsg.className = 'text-xs text-center text-red-400';
      deleteMsg.classList.remove('hidden');
    }
  } catch { deleteMsg.textContent = 'Sin respuesta.'; deleteMsg.className = 'text-xs text-center text-red-400'; deleteMsg.classList.remove('hidden'); }
  finally { btn.disabled = false; btn.style.opacity = ''; }
});

// ── Chart (Phase 5) ─────────────────────────────────────
const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}h`);
const curH  = new Date().getHours();
const actChart = new Chart(
  document.getElementById('activity-chart').getContext('2d'),
  {
    type: 'bar',
    data: {
      labels: hours,
      datasets: [{
        label: 'Personas',
        data:  new Array(24).fill(0),
        backgroundColor: hours.map((_, i) => i === curH ? 'rgba(74,222,128,0.4)' : 'rgba(51,65,85,0.3)'),
        borderColor:     hours.map((_, i) => i === curH ? 'rgba(74,222,128,0.7)' : 'rgba(71,85,105,0.5)'),
        borderWidth: 1, borderRadius: 3,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
          titleColor: '#94a3b8', bodyColor: '#f8fafc',
          titleFont: { size: 10 }, bodyFont: { size: 11 },
          callbacks: { label: c => ` ${c.parsed.y} personas` },
        },
      },
      scales: {
        x: { grid: { color: 'rgba(51,65,85,0.3)', drawTicks: false }, border: { display: false },
             ticks: { color: '#475569', font: { size: 9 }, maxTicksLimit: 8, maxRotation: 0 } },
        y: { min: 0, grid: { color: 'rgba(51,65,85,0.3)', drawTicks: false }, border: { display: false },
             ticks: { color: '#475569', font: { size: 9 }, precision: 0, maxTicksLimit: 4 } },
      },
    },
  }
);

export function updateChart(hourlyData) {
  actChart.data.datasets[0].data = hourlyData;
  actChart.update('active');
  document.getElementById('chart-placeholder').style.display = 'none';
}

export function bumpHourBar(hour) {
  // Extrae index.html:1174-1177 — websocket.js (28-07) no puede tocar actChart
  // directamente (es privado a este modulo), llama a esta funcion en su lugar.
  actChart.data.datasets[0].data[hour] = (actChart.data.datasets[0].data[hour] || 0) + 1;
  actChart.update('active');
  document.getElementById('chart-placeholder').style.display = 'none';
}

export function hourlyToArray(hourly) {
  return Array.from({ length: 24 }, (_, i) => (hourly ?? {})[String(i).padStart(2, '0')] ?? 0);
}

export function addEvent(ts, dir, total, personName, isIntrusion = false) {
  const list  = document.getElementById('events-list');
  const empty = document.getElementById('events-empty');
  if (empty) empty.style.display = 'none';
  const item = document.createElement('div');
  item.className = 'event-item';
  if (isIntrusion) item.style.borderColor = 'rgba(239,68,68,0.4)';
  const color = dir === 'in' ? 'text-blue-400' : 'text-amber-400';
  const arrow = dir === 'in'
    ? '<polyline points="18 15 12 9 6 15"/>'
    : '<polyline points="6 9 12 15 18 9"/>';
  // dir/ts/personName/total llegan del backend (WS/API) — nunca se
  // interpolan como HTML: se asignan via textContent tras montar la
  // estructura estatica, para que un person_name con marcado no pueda
  // ejecutarse en el navegador de otro operador (CodeQL js/xss).
  const nameTag = personName
    ? `<span class="ev-name text-slate-400 text-xs truncate max-w-[60px]"></span>`
    : '';
  const intrusionTag = isIntrusion ? `<span class="intrusion-badge">INTRUSIÓN</span>` : '';
  item.innerHTML = `
    <svg class="w-3.5 h-3.5 flex-shrink-0 ${color}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">${arrow}</svg>
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
  list.prepend(item);
  while (list.children.length > 50) list.lastChild.remove();
  document.getElementById('events-badge').textContent = total;
}

// ── Phase 15: event filters ───────────────────────────────────────
function _eventsFilterParams() {
  const p = new URLSearchParams();
  const dir = document.getElementById('filter-direction').value;
  const pn  = document.getElementById('filter-person').value.trim();
  const intr = document.getElementById('filter-intrusion').checked;
  const from = document.getElementById('filter-from').value;
  const to   = document.getElementById('filter-to').value;
  p.set('limit', '200');
  if (dir)  p.set('direction', dir);
  if (pn)   p.set('person_name', pn);
  if (intr) p.set('is_intrusion', 'true');
  if (from) p.set('from_dt', from + 'T00:00:00');
  if (to)   p.set('to_dt',   to   + 'T23:59:59');
  return p;
}

export async function applyFilters() {
  const params = _eventsFilterParams();
  try {
    const res = await fetch('/api/events?' + params.toString());
    if (!res.ok) return;
    const data   = await res.json();
    const events = (data.events ?? []).reverse();
    const list   = document.getElementById('events-list');
    const empty  = document.getElementById('events-empty');
    list.querySelectorAll('.event-item').forEach(el => el.remove());
    if (events.length === 0) {
      empty.style.display = '';
    } else {
      empty.style.display = 'none';
      let badge = 0;
      events.forEach(ev => {
        const ts = new Date(ev.timestamp).toLocaleTimeString('es-ES', { hour12: false });
        addEvent(ts, ev.direction, ++badge, ev.person_name ?? null, ev.is_intrusion ?? false);
      });
      document.getElementById('events-badge').textContent = events.length;
    }
  } catch {}
}

export function bindEventFilters() {
  document.getElementById('btn-apply-filters').addEventListener('click', applyFilters);

  document.getElementById('btn-clear-filters').addEventListener('click', () => {
    document.getElementById('filter-direction').value = '';
    document.getElementById('filter-person').value = '';
    document.getElementById('filter-intrusion').checked = false;
    document.getElementById('filter-from').value = '';
    document.getElementById('filter-to').value = '';
    loadInitialData();
  });

  document.getElementById('btn-export-csv').addEventListener('click', () => {
    const params = _eventsFilterParams();
    params.delete('limit');
    window.location.href = '/api/events/export?' + params.toString();
  });
}
