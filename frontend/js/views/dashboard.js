// frontend/js/views/dashboard.js
import { updateChart, addEvent, hourlyToArray } from './dashboard-events.js';

// ── Clock ─────────────────────────────────────────────
const clockEl = document.getElementById('clock');
function tickClock() {
  clockEl.textContent = new Date().toLocaleTimeString('es-ES', { hour12: false });
}
setInterval(tickClock, 1000);
tickClock();

// ── Toast ─────────────────────────────────────────────
const TOAST_STYLES = {
  info:    'bg-slate-800 border-slate-700 text-slate-200',
  success: 'bg-green-950 border-green-800/60 text-green-300',
  error:   'bg-red-950   border-red-800/60   text-red-300',
  warn:    'bg-amber-950 border-amber-800/60 text-amber-300',
};
export function showToast(msg, type = 'info', ms = 3500) {
  const wrap = document.getElementById('toast-container');
  const el   = document.createElement('div');
  el.className = `toast ${TOAST_STYLES[type] ?? TOAST_STYLES.info} border rounded-xl px-4 py-2.5 text-xs shadow-xl pointer-events-auto max-w-xs`;
  el.setAttribute('role', 'alert');
  el.textContent = msg;
  wrap.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, ms);
}

// ── Camera online/offline ─────────────────────────────
let _isOnline = true;
export function setCamStatus(online) {
  if (online === _isOnline) return;
  _isOnline = online;
  const wrap = document.getElementById('cam-status');
  const dot  = document.getElementById('status-dot');
  const txt  = document.getElementById('status-text');
  if (online) {
    wrap.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 text-xs font-medium';
    dot.className  = 'w-1.5 h-1.5 rounded-full bg-green-400 pulse';
    txt.textContent = 'EN VIVO';
  } else {
    wrap.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-medium';
    dot.className  = 'w-1.5 h-1.5 rounded-full bg-red-400';
    txt.textContent = 'SIN SEÑAL';
    showToast('Cámara sin señal — reintentando…', 'warn');
  }
}

// ── Stat counter update (with pop animation) ──────────
export function updateStat(id, val) {
  const el = document.getElementById(id);
  if (el.textContent === String(val)) return;
  el.textContent = val;
  el.classList.remove('stat-pop');
  void el.offsetWidth;
  el.classList.add('stat-pop');
  setTimeout(() => el.classList.remove('stat-pop'), 300);
}

// ── Counts polling (/counts) ──────────────────────────
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
setInterval(fetchCounts, 2000);
fetchCounts();

// ── Detections polling (/detections) ──────────────────
async function fetchDetections() {
  try {
    const res = await fetch('/detections');
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('det-num').textContent = d.live_count ?? (d.detections ?? []).length;
  } catch {}
}
setInterval(fetchDetections, 2000);
fetchDetections();

// ── Initial data load ──────────────────────────────────
export async function loadInitialData() {
  try {
    const [statsRes, eventsRes] = await Promise.all([
      fetch('/api/stats'),
      fetch('/api/events?limit=50'),
    ]);
    if (statsRes.ok) {
      const stats = await statsRes.json();
      updateChart(hourlyToArray(stats.hourly));
      updateStat('stat-total', stats.total_today ?? 0);
    }
    if (eventsRes.ok) {
      const data   = await eventsRes.json();
      const events = (data.events ?? []).reverse();
      const list  = document.getElementById('events-list');
      const empty = document.getElementById('events-empty');
      list.querySelectorAll('.event-item').forEach(el => el.remove());
      updateStat('events-badge', 0);
      if (events.length === 0) {
        empty.style.display = '';
      } else {
        empty.style.display = 'none';
        let badge = 0;
        events.forEach(ev => {
          const ts = new Date(ev.timestamp).toLocaleTimeString('es-ES', { hour12: false });
          addEvent(ts, ev.direction, ++badge, ev.person_name ?? null, ev.is_intrusion ?? false);
        });
      }
    }
  } catch {}
}

// ── Camera settings toggles ────────────────────────────
function applyToggleState(btn, enabled) {
  btn.setAttribute('aria-checked', String(enabled));
  btn.dataset.state = String(enabled);
}

export async function loadCamStatus() {
  const toggles = ['toggle-privacy','toggle-led','toggle-motion','toggle-autotrack'];
  toggles.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = true; });
  try {
    const res = await fetch('/camera/status');
    if (!res.ok) return;
    const s = await res.json();
    applyToggleState(document.getElementById('toggle-privacy'),   s.privacy);
    applyToggleState(document.getElementById('toggle-led'),       s.led);
    applyToggleState(document.getElementById('toggle-motion'),    s.motion);
    applyToggleState(document.getElementById('toggle-autotrack'), s.autotrack);
    if (s.errors && Object.keys(s.errors).length) {
      const failed = Object.keys(s.errors).join(', ');
      showToast(`Cámara: no se pudo leer ${failed}`, 'warning');
    }
  } catch {}
  finally {
    toggles.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = false; });
  }
}

document.querySelectorAll('.cam-toggle').forEach(btn => {
  btn.addEventListener('click', async () => {
    const current = btn.dataset.state === 'true';
    const next    = !current;
    btn.disabled  = true;
    try {
      const res = await fetch(btn.dataset.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
      if (res.ok) {
        applyToggleState(btn, next);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(`Error: ${err.detail ?? res.statusText}`, 'error');
      }
    } catch (e) {
      showToast(`Sin respuesta: ${e.message}`, 'error');
    } finally {
      btn.disabled = false;
    }
  });
});

document.getElementById('cam-settings-refresh').addEventListener('click', loadCamStatus);

document.getElementById('btn-reboot').addEventListener('click', async () => {
  if (!confirm('¿Reiniciar la cámara? El stream se interrumpirá unos segundos.')) return;
  const btn = document.getElementById('btn-reboot');
  btn.disabled = true;
  try {
    const res = await fetch('/camera/reboot', { method: 'POST' });
    if (res.ok) showToast('Cámara reiniciando…', 'warn', 5000);
    else showToast('Error al reiniciar', 'error');
  } catch { showToast('Sin respuesta del servidor', 'error'); }
  finally { setTimeout(() => { btn.disabled = false; }, 8000); }
});
