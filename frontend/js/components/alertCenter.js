// frontend/js/components/alertCenter.js
// Centro de alertas (OPS-11): badge de la campana, cajon lateral con los grupos que
// devuelve GET /api/v2/alerts y el top-3 del panel "Alertas activas" de la Fase 29.
//
// La agrupacion, el orden por severidad y el estado de silenciado los resuelve el
// SERVIDOR (30-06): aqui no hay ni un .filter() ni un .sort() sobre la respuesta.
// Patron obligatorio del repo (CodeQL js/xss, timeline-row.js:4-7): la estructura va
// por innerHTML con elementos VACIOS y todo dato del backend entra despues por
// textContent. El nombre de la regla lo escribe el operador en rules.yaml (T-30-31).

import { apiFetch } from '../api.js';
import { describe, SEV_COLOR } from '../views/timeline-row.js';

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 5000;
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
const DOT = { critical: 'bg-red-400', warning: 'bg-amber-400', info: 'bg-slate-500' };

const hhmmss = (d) => d.toLocaleTimeString('es-ES', { hour12: false });
const hhmm = (d) => d.toLocaleTimeString('es-ES', { hour12: false, hour: '2-digit', minute: '2-digit' });

let _lastFocus = null;

// ── Grupo del cajon ───────────────────────────────────────────────────
const GROUP_HTML = `
  <span class="sev-dot" aria-hidden="true"></span>
  <div class="flex-1 min-w-0 flex flex-col gap-1.5">
    <div class="flex items-center gap-1.5">
      <span class="chip rule-chip mono" data-slot="rule"></span>
      <span class="chip mono text-amber-400 border-amber-500/40 hidden" data-slot="muted"></span>
    </div>
    <p class="text-xs font-semibold text-slate-200 truncate" data-slot="desc"></p>
    <div class="flex items-center gap-2">
      <span class="text-xs text-slate-500 mono" data-slot="count"></span>
      <span class="text-xs text-slate-500 mono" data-slot="time"></span>
      <button type="button" class="filter-chip ml-auto hidden" data-slot="mute"></button>
      <button type="button" class="text-xs font-semibold text-blue-400 cursor-pointer" data-slot="goto">Ver en la línea temporal</button>
    </div>
  </div>`;

function buildGroup(entry) {
  const rule = entry.rule_name;
  const type = entry.event_type;
  const until = entry.muted_until;
  const el = document.createElement('div');
  el.className = until ? 'alert-group muted' : 'alert-group';
  el.style.setProperty('--sev', SEV_COLOR[entry.severity] ?? SEV_COLOR.info);
  el.innerHTML = GROUP_HTML;
  const slot = (name) => el.querySelector(`[data-slot="${name}"]`);
  // Sin regla (grupo type:*) el chip lleva el tipo en lenguaje llano, nunca el
  // identificador crudo del catalogo (UI-SPEC, regla de estilo del copy).
  slot('rule').textContent = rule ? `⚡ ${rule}` : describe({ type });
  slot('desc').textContent = describe({ type, zone_id: entry.zone_id });
  slot('count').textContent = `×${entry.count}`;
  slot('time').textContent = hhmmss(new Date(entry.last_ts));
  if (until) {
    const chip = slot('muted');
    chip.textContent = `silenciada hasta ${hhmm(new Date(until))}`;
    chip.classList.remove('hidden');
  }
  // Los grupos silenciados NO se ocultan: quedan atenuados y con "Reactivar regla",
  // para que el operador vea de un vistazo que se esta callando (T-30-33).
  if (entry.mutable) {
    const btn = slot('mute');
    btn.textContent = until ? 'Reactivar regla' : 'Silenciar';
    btn.dataset.rule = rule;
    btn.dataset.act = until ? 'unmute' : 'mute';
    btn.classList.remove('hidden');
  }
  slot('goto').addEventListener('click', () => gotoTimeline(rule, type));
  return el;
}

function gotoTimeline(ruleName, eventType) {
  closeAlertDrawer();
  // timeline.js no importa este modulo ni al reves: se hablan por un evento del DOM.
  document.dispatchEvent(new CustomEvent('timeline:filter-rule', { detail: { ruleName, eventType } }));
  $('timeline-list')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ── Top-3 de la Fase 29: mismo marcado que generaba _statusRow en dashboard.js ──
const ROW_HTML = '<span class="w-1.5 h-1.5 rounded-full flex-shrink-0" aria-hidden="true" data-slot="dot"></span>'
  + '<span class="text-xs text-slate-300 flex-1 truncate" data-slot="main"></span>'
  + '<span class="text-xs text-slate-600 mono" data-slot="side"></span>';

function paintTop3(groups, checked) {
  const list = $('alerts-active-list');
  const empty = $('alerts-active-empty');
  if (!list || !empty) return;
  list.textContent = '';
  let shown = 0;
  for (const entry of groups) {
    if (shown === 3) break;
    if (entry.muted_until) continue;      // una regla silenciada sale del top-3
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2.5 py-1';
    row.innerHTML = ROW_HTML;
    row.querySelector('[data-slot="dot"]').classList.add(DOT[entry.severity] ?? DOT.info);
    row.querySelector('[data-slot="main"]').textContent =
      entry.rule_name ?? describe({ type: entry.event_type });
    row.querySelector('[data-slot="side"]').textContent = hhmmss(new Date(entry.last_ts));
    list.appendChild(row);
    shown += 1;
  }
  empty.style.display = shown ? 'none' : '';
  const at = $('alerts-active-checked-at');
  if (at) at.textContent = checked;
}

function paintBadge(data) {
  const badge = $('alert-badge');
  const bell = $('btn-alert-center');
  const n = data.active_count;
  if (badge) {
    badge.textContent = n === 0 ? '' : (n >= 10 ? '9+' : String(n));
    badge.classList.toggle('hidden', n === 0);
    badge.classList.toggle('bg-red-500', data.critical_count > 0);
    badge.classList.toggle('bg-amber-500', data.critical_count === 0);
  }
  if (bell) bell.setAttribute('aria-label', `Centro de alertas, ${n} activas`);
}

/** Relee el estado real del servidor y repinta badge, cajon y top-3. */
export async function loadAlerts() {
  const box = $('alert-groups');
  const empty = $('alert-empty');
  if (!box || !empty) return;
  let data;
  try {
    data = await apiFetch('/api/v2/alerts?hours=24');
  } catch (e) {
    // Sin datos frescos se muestra el estado vacio, pero el badge anterior se
    // queda: es la ultima verdad conocida y borrarlo diria "no hay alertas".
    empty.style.display = '';
    console.warn('No se pudieron cargar las alertas:', e.message);
    return;
  }
  paintBadge(data);
  const hero = $('alert-count-hero');
  if (hero) hero.textContent = data.active_count;
  const checked = hhmmss(new Date(data.checked_at));
  box.textContent = '';
  data.groups.forEach((entry) => box.appendChild(buildGroup(entry)));
  empty.style.display = data.groups.length ? 'none' : '';
  const footer = $('alert-footer-count');
  if (footer) {
    footer.textContent = data.groups.length
      ? `${data.groups.length} grupos · ${data.muted_count} silenciados · ${checked}`
      : '';
  }
  const at = $('alert-checked-at');
  if (at) at.textContent = checked;
  paintTop3(data.groups, checked);
}

// ── Cajon lateral ─────────────────────────────────────────────────────
export function openAlertDrawer() {
  const drawer = $('alert-drawer');
  if (!drawer || drawer.classList.contains('open')) return;
  _lastFocus = document.activeElement;
  drawer.classList.add('open');
  $('btn-alert-close')?.focus();
  loadAlerts();
}

export function closeAlertDrawer() {
  const drawer = $('alert-drawer');
  if (!drawer || !drawer.classList.contains('open')) return;
  drawer.classList.remove('open');
  ($('btn-alert-center') ?? _lastFocus)?.focus();   // el foco vuelve a la campana
  _lastFocus = null;
}

function trapTab(e) {
  const drawer = $('alert-drawer');
  const items = [...drawer.querySelectorAll(FOCUSABLE)]
    .filter((el) => !el.disabled && el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

export function bindAlertCenter() {
  const drawer = $('alert-drawer');
  $('btn-alert-center')?.addEventListener('click', openAlertDrawer);
  $('btn-alerts-view-all')?.addEventListener('click', openAlertDrawer);
  $('btn-alert-close')?.addEventListener('click', closeAlertDrawer);
  drawer?.addEventListener('click', (e) => { if (e.target === drawer) closeAlertDrawer(); });
  document.addEventListener('keydown', (e) => {
    if (!drawer?.classList.contains('open')) return;
    if (e.key === 'Escape') closeAlertDrawer();
    else if (e.key === 'Tab') trapTab(e);
  });
}

setInterval(loadAlerts, REFRESH_MS);
