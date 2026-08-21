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

// El export CSV sigue apuntando al endpoint v1 (/api/events/export, tabla crossing_events):
// no esta en OPS-07..11 y se deja intacto, ya sin filtros porque la barra vieja
// desaparecio con el card de eventos (30-RESEARCH.md Open Question 2 -> anotado para OPS-15).
export function bindEventExport() {
  const btn = document.getElementById('btn-export-csv');
  if (btn) btn.addEventListener('click', () => { window.location.href = '/api/events/export'; });
}
