// frontend/js/views/dashboard.js
import { updateChart, hourlyToArray } from './dashboard-events.js';

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

// ── Header pipeline status: 3 estados (online/degraded/offline) — OPS-04, D-03 ──
const STATUS_STYLES = {
  online:   { wrap: 'bg-green-500/10 border-green-500/30 text-green-400', dot: 'bg-green-400 pulse', text: 'SISTEMA ONLINE' },
  degraded: { wrap: 'bg-amber-500/10 border-amber-500/30 text-amber-400', dot: 'bg-amber-400 pulse', text: 'SISTEMA DEGRADADO' },
  offline:  { wrap: 'bg-red-500/10 border-red-500/30 text-red-400',       dot: 'bg-red-400',         text: 'SISTEMA OFFLINE' },
};
let _camState = null;
export function setCamStatus(state) {
  if (state === _camState) return;
  _camState = state;
  const wrap = document.getElementById('cam-status');
  const dot  = document.getElementById('status-dot');
  const txt  = document.getElementById('status-text');
  const s = STATUS_STYLES[state] || STATUS_STYLES.offline;
  wrap.className = `flex items-center gap-1.5 px-3 py-1.5 rounded-full border ${s.wrap} text-xs font-medium`;
  dot.className  = `w-1.5 h-1.5 rounded-full ${s.dot}`;
  txt.textContent = s.text;
  if (state === 'offline') showToast('Cámara sin señal — reintentando…', 'warn');
}

// ── Estado combinado: pipeline health + WebSocket (D-11) ──────────────
let _wsConnected = true;
let _wsCloseCount = 0;
let _pipelineHealth = { connected: true, degraded: false };

export function setWsConnected(connected, closeCount = 0) {
  _wsConnected = connected;
  _wsCloseCount = closeCount;
  computeHeaderState();
}

export async function loadPipelineHealth() {
  try {
    const res = await fetch('/api/v2/cameras/cam1/health');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    _pipelineHealth = { connected: !!d.connected, degraded: !!d.degraded };
  } catch {
    _pipelineHealth = { connected: false, degraded: true };
  }
  computeHeaderState();
}
setInterval(loadPipelineHealth, 4000);

function computeHeaderState() {
  // D-11: un WS caido mas de 1 ciclo de reconexion (>=2 intentos fallidos, _wsCloseCount > 1)
  // cuenta como degradado. Nunca se usa `dropped`/`frames_dropped_total` aqui (Pitfall 3).
  const wsDegraded = !_wsConnected && _wsCloseCount > 1;
  let state;
  if (!_pipelineHealth.connected) {
    state = 'offline';
  } else if (_pipelineHealth.degraded || wsDegraded) {
    state = 'degraded';
  } else {
    state = 'online';
  }
  setCamStatus(state);
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
  } catch {}
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
    // La lista de eventos la carga ahora timeline.js (30-08) contra /api/v2/events;
    // aqui solo queda la grafica horaria y el contador de la Fase 5.
    const statsRes = await fetch('/api/stats');
    if (statsRes.ok) {
      const stats = await statsRes.json();
      updateChart(hourlyToArray(stats.hourly));
      updateStat('stat-total', stats.total_today ?? 0);
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

// ── Filas compactas compartidas por Personas ahora / Alertas activas (D-04/D-05) ──
function _statusRow(dotClass, mainText, sideText, sideClass = 'text-slate-600') {
  const row = document.createElement('div');
  row.className = 'flex items-center gap-2.5 py-1';
  const dot = document.createElement('span');
  dot.className = `w-1.5 h-1.5 rounded-full ${dotClass} flex-shrink-0`;
  dot.setAttribute('aria-hidden', 'true');
  const main = document.createElement('span');
  main.className = 'text-xs text-slate-300 flex-1 truncate';
  main.textContent = mainText;
  const side = document.createElement('span');
  side.className = `text-xs ${sideClass}`;
  side.textContent = sideText;
  row.append(dot, main, side);
  return row;
}

// ── Personas ahora (D-05) — misma fuente que el overlay, sin segunda vía ──
const IDENTITY_LABEL = { CONFIRMED: 'confirmado', CANDIDATE: 'verificando', UNKNOWN: 'desconocido', TEMPORARILY_LOST: 'desconocido' };
const IDENTITY_DOT   = { CONFIRMED: 'bg-green-400', CANDIDATE: 'bg-amber-400', UNKNOWN: 'bg-red-400', TEMPORARILY_LOST: 'bg-red-400' };

export function renderPersonList(tracks) {
  const list  = document.getElementById('persons-now-list');
  const empty = document.getElementById('persons-now-empty');
  const count = document.getElementById('persons-now-count');
  if (!list || !empty || !count) return;
  const items = tracks || [];
  count.textContent = items.length;
  list.innerHTML = '';
  empty.style.display = items.length ? 'none' : '';
  items.forEach(t => {
    const dotClass = IDENTITY_DOT[t.identity_state] || IDENTITY_DOT.UNKNOWN;
    const label = IDENTITY_LABEL[t.identity_state] || IDENTITY_LABEL.UNKNOWN;
    list.appendChild(_statusRow(dotClass, t.person_name || 'Desconocido', label));
  });
}

// ── Alertas activas: top-3 por severidad (D-04) ────────────────────────
const SEVERITY_RANK = { critical: 2, warning: 1, info: 0 };
export async function loadActiveAlerts() {
  const panel = document.getElementById('alerts-active-list');
  const empty = document.getElementById('alerts-active-empty');
  const checkedAt = document.getElementById('alerts-active-checked-at');
  if (!panel || !empty) return;
  try {
    const res = await fetch('/api/v2/events?limit=10');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const alerts = (data.events || [])
      .filter(e => e.severity && e.severity !== 'info')
      .sort((a, b) => (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0))
      .slice(0, 3);
    panel.innerHTML = '';
    empty.style.display = alerts.length ? 'none' : '';
    alerts.forEach(ev => {
      const sevClass = ev.severity === 'critical' ? 'bg-red-400' : 'bg-amber-400';
      const ts = new Date(ev.ts).toLocaleTimeString('es-ES', { hour12: false });
      panel.appendChild(_statusRow(sevClass, ev.type.replace(/_/g, ' '), ts, 'text-slate-600 mono'));
    });
  } catch {
    empty.style.display = '';
  }
  if (checkedAt) checkedAt.textContent = new Date().toLocaleTimeString('es-ES', { hour12: false });
}
setInterval(loadActiveAlerts, 5000);
