// frontend/js/views/timeline.js
// Linea temporal: filtros en servidor, paginacion por cursor y scroll infinito (OPS-07..10).
//
// El array `_all` guarda TODOS los eventos ya descargados (10.000 x ~250B ~= 2,5MB,
// aceptable) y el DOM es solo una ventana de MAX_ROWS sobre el. Asi el recorte por arriba
// y el volver a subir se resuelven repintando desde memoria, sin red y sin cursor inverso:
// un parametro menos de API y una clase entera de bugs menos (paginas hacia atras
// desalineadas con inserciones nuevas) — 30-RESEARCH.md Hallazgo 1.
import { apiFetch } from '../api.js';
import { openClipModal } from '../components/eventCard.js';
import { showToast } from './dashboard.js';
import { timelineRow, isDismissed, dismiss, undoToast, isSafeMediaUrl } from './timeline-row.js';
import { paintWindow } from './timeline-virtualize.js';
import { filterParams, clearFilter, clearAllFilters, paintActiveChips, bindFilterChips, setFocusFilter } from './timeline-filters.js';

const PAGE_SIZE = 50;
const MAX_ROWS = 400;   // plan B si el salto al recortar se nota: subir a 1000 y no recortar
const ROW_H = 60;       // 52px de fila + 8px de gap (altura fija en components.css)

let _all = [];             // eventos descargados, mas recientes primero
let _media = {};           // event_id -> media
let _cursor = null;
let _loading = false;
let _exhausted = false;
let _hasFilters = false;
let _total = null;
let _start = 0;            // indice de la primera fila pintada
let _persons = new Map();  // person_id -> name (Hallazgo 5: person_name no viaja en la respuesta)
let _pending = [];         // eventos en vivo no insertados (pildora)
let _io = null;

const $ = (id) => document.getElementById(id);

function _show(id, on) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('hidden', !on);
  el.classList.toggle('flex', on);
}

// ── Pintado ───────────────────────────────────────────────────────
function _row(ev) {
  const name = ev.person_id != null ? _persons.get(ev.person_id) : ev.person_name;
  return timelineRow(ev, _media[ev.id], name ?? '');
}

function render(opts = {}) {
  const list = $('timeline-list');
  if (!list) return;
  const visible = _all.filter((e) => !isDismissed(e.id));   // unico filtrado en cliente
  const maxStart = Math.max(0, visible.length - MAX_ROWS);
  const prev = _start;
  _start = Math.min(Math.max(0, opts.start ?? _start), maxStart);
  paintWindow({ list, before: $('timeline-sentinel'), items: visible, start: _start, max: MAX_ROWS, makeRow: _row });
  // Recorte por arriba: se compensa scrollTop con la altura exacta eliminada para que el
  // contenido no salte. La fila es de altura fija precisamente para poder hacer esta resta.
  if (_start !== prev) list.scrollTop -= (_start - prev) * ROW_H;
  const top = list.querySelector('.tl-top-sentinel');
  if (top && _io) _io.observe(top);
  _paintStates(visible.length);
}

function _paintStates(count) {
  _show('timeline-empty', count === 0 && !_hasFilters && !_loading);
  _show('timeline-empty-filtered', count === 0 && _hasFilters && !_loading);
  $('timeline-end')?.classList.toggle('hidden', !(_exhausted && count > 0));
  const label = _total == null ? `${count} evento${count === 1 ? '' : 's'}` : `${count} de ${_total}`;
  const badge = $('timeline-count');
  if (badge) badge.textContent = label;
}

// ── Carga ─────────────────────────────────────────────────────────
async function loadPage({ reset }) {
  if (_loading) return;
  _loading = true;
  const { params, hasFilters } = filterParams(_persons, PAGE_SIZE);
  _hasFilters = hasFilters;
  if (reset) {
    _all = []; _media = {}; _cursor = null; _exhausted = false; _total = null; _pending = [];
    $('timeline-newpill')?.classList.add('hidden');
    render({ start: 0 });                 // la lista se vacia ANTES de pedir la primera pagina
  } else if (_cursor) {
    params.set('cursor', _cursor);
  }
  _show('timeline-loading', true);
  _show('timeline-error', false);
  try {
    const data = await apiFetch(`/api/v2/events?${params.toString()}`);
    _all = reset ? (data.events ?? []) : _all.concat(data.events ?? []);
    Object.assign(_media, data.media ?? {});
    _cursor = data.cursor ?? null;
    _exhausted = _cursor === null;
    if (data.total !== null && data.total !== undefined) _total = data.total;
    _loading = false;
    render({ start: reset ? 0 : Infinity });
  } catch (err) {
    if (reset) _all = [];
    _loading = false;
    render();
    _show('timeline-error', true);         // el error se muestra, nunca se traga
    _show('timeline-empty', false);
    _show('timeline-empty-filtered', false);
    // El aviso visible es #timeline-error con la copy del UI-SPEC; el detalle del backend
    // va a consola para diagnostico, no a un toast que duplique el mismo mensaje.
    console.error('timeline: fallo al cargar eventos —', err.message);
  } finally {
    _loading = false;
    _show('timeline-loading', false);
  }
}

export async function applyTimelineFilters() {
  const { chips } = filterParams(_persons, PAGE_SIZE);
  paintActiveChips(chips, (key) => { clearFilter(key); applyTimelineFilters(); });
  await loadPage({ reset: true });
}

// ── Acciones de fila ──────────────────────────────────────────────
function _openSnapshot(media) {
  const url = media?.snapshot_url ?? media?.thumbnail_url;
  if (!url || !isSafeMediaUrl(url)) { showToast('Este evento no tiene captura.', 'info'); return; }
  // #clip-modal solo contiene un <video>: la imagen se abre aparte, sin inventar otro modal.
  window.open(url, '_blank', 'noopener');
}

function _onListClick(e) {
  const row = e.target.closest('.timeline-row');
  if (!row) return;
  const id = row.dataset.id;
  const media = _media[id] ?? {};
  if (e.target.closest('.tl-thumb')) { _openSnapshot(media); return; }
  const action = e.target.closest('.row-action')?.dataset.action;
  if (!action) return;
  if (action === 'clip') { if (media.clip_url) openClipModal(media.clip_url); }
  else if (action === 'snapshot') { _openSnapshot(media); }
  else if (action === 'dismiss') { dismiss(id); render(); undoToast(id, () => render()); }
  else if (action === 'person') {
    // 30-11 escucha este evento: asi la timeline no depende del modal de enrolado.
    document.dispatchEvent(new CustomEvent('timeline:mark-person', {
      detail: { eventId: id, trackId: row.dataset.trackId, snapshotUrl: media.snapshot_url ?? null },
    }));
  }
}

// ── Catalogos ─────────────────────────────────────────────────────
async function _loadZones() {
  try {
    const data = await apiFetch('/api/v2/zones');
    const select = $('tl-filter-zone');
    (data.zones ?? []).forEach((z) => {
      const opt = document.createElement('option');
      opt.value = z.id ?? z.name ?? '';
      opt.textContent = z.name ?? z.id ?? '';
      select?.appendChild(opt);
    });
  } catch (err) { console.warn('timeline: zonas no disponibles', err.message); }
}

async function _loadPersons() {
  try {
    const data = await apiFetch('/persons');
    _persons = new Map((data.persons ?? []).map((p) => [p.id, p.name]));
    const options = $('tl-person-options');
    if (!options) return;
    options.textContent = '';
    _persons.forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;                    // value/textContent, nunca innerHTML
      options.appendChild(opt);
    });
    render();
  } catch (err) { console.warn('timeline: personas no disponibles', err.message); }
}

export function refreshPersonNames() {
  return _loadPersons();
}

// Repintado en sitio tras "Marcar como persona" (30-11): el backend ya aplico la identidad
// al bloque del track y aqui solo se sincroniza el modelo. Recargar costaria el scroll.
export function applyPersonAssignment(eventIds, personId, name) {
  if (name) _persons.set(personId, name);
  const ids = new Set(eventIds ?? []);
  for (const ev of _all) {
    if (!ids.has(ev.id)) continue;
    ev.person_id = personId;
    if (ev.type === 'UNKNOWN_PERSON') ev.severity = 'info';   // mismo criterio que el UPDATE
  }
  const list = $('timeline-list');
  const keep = list ? list.scrollTop : 0;
  render();
  if (list) list.scrollTop = keep;
}

// ── Arranque ──────────────────────────────────────────────────────
function _onSentinel(entries) {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    if (entry.target.id === 'timeline-sentinel') {
      if (_cursor && !_loading) loadPage({ reset: false });
    } else if (_start > 0) {
      render({ start: _start - PAGE_SIZE });   // volver a subir: se repinta desde memoria
    }
  }
}

export function initTimeline() {
  const list = $('timeline-list');
  if (!list) return;
  bindFilterChips();
  $('btn-tl-apply')?.addEventListener('click', () => applyTimelineFilters());
  $('btn-tl-clear')?.addEventListener('click', () => { clearAllFilters(); applyTimelineFilters(); });
  $('btn-tl-clear-empty')?.addEventListener('click', () => { clearAllFilters(); applyTimelineFilters(); });
  $('btn-tl-retry')?.addEventListener('click', () => loadPage({ reset: true }));
  $('timeline-newpill')?.addEventListener('click', (e) => {
    list.scrollTo({ top: 0, behavior: 'smooth' });
    _pending = [];
    e.currentTarget.classList.add('hidden');
    render({ start: 0 });
  });
  // "Ver en la linea temporal" del centro de alertas: alertCenter.js despacha y aqui se
  // escucha, sin que ninguno de los dos modulos importe al otro (30-09).
  document.addEventListener('timeline:filter-rule', (e) => {
    setFocusFilter(e.detail?.ruleName, e.detail?.eventType);
    applyTimelineFilters();
  });
  list.addEventListener('click', _onListClick);
  list.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('tl-thumb')) {
      e.preventDefault();
      e.target.click();
    }
  });
  // Centinela de 1px al final: pide la pagina siguiente antes de llegar al fondo.
  // Nunca un listener de scroll (UI-SPEC).
  _io = new IntersectionObserver(_onSentinel, { root: list, rootMargin: '200px' });
  _io.observe($('timeline-sentinel'));
  _loadZones();
  _loadPersons();
  loadPage({ reset: true });
}

// ── Evento en vivo (OPS-10, criterio 4) ───────────────────────────
// Unica comprobacion de filtros que vive en el navegador, y solo para lo que llega por
// WebSocket: la lista descargada JAMAS se filtra aqui, eso es cosa del servidor (OPS-09).
function _matchesActiveFilters(ev) {
  const { params } = filterParams(_persons, PAGE_SIZE);
  const types = params.getAll('type');
  if (types.length && !types.includes(ev.type)) return false;
  const sev = params.get('severity');
  if (sev && ev.severity !== sev) return false;
  // El filtro `rule` casa contra payload.rules en servidor (json_each); aqui se replica esa
  // misma pertenencia para que un evento en vivo de otra regla no se cuele en la lista.
  const rule = params.get('rule');
  if (rule && !(ev.payload?.rules ?? []).includes(rule)) return false;
  const zone = params.get('zone_id');
  if (zone && ev.zone_id !== zone) return false;
  const person = params.get('person_id');
  if (person && String(ev.person_id ?? '') !== person) return false;
  const from = params.get('from');
  const to = params.get('to');
  if (from && new Date(ev.ts) < new Date(from)) return false;
  if (to && new Date(ev.ts) > new Date(to)) return false;
  return true;
}

export function onLiveEvent(event, media) {
  if (!event || !_matchesActiveFilters(event)) return;
  if (_all.some((e) => e.id === event.id)) return;      // idempotente ante reconexiones
  _all.unshift(event);
  if (media) _media[event.id] = media;
  const list = $('timeline-list');
  if (!list) return;
  if (list.scrollTop < 8) {
    render({ start: 0 });                               // inserta arriba, nada mas se mueve
    const first = list.querySelector('.timeline-row');
    if (first) {
      first.classList.add('slide-in');
      const bar = first.querySelector('.sev-bar');
      if (bar) { bar.style.filter = 'brightness(1.8)'; setTimeout(() => { bar.style.filter = ''; }, 2000); }
    }
  } else {
    _pending.push(event.id);                            // no se toca el scroll del operador
    const pill = $('timeline-newpill');
    if (!pill) return;
    const n = _pending.length;
    pill.textContent = `${n} evento${n === 1 ? '' : 's'} nuevo${n === 1 ? '' : 's'}`;
    pill.classList.remove('hidden');
  }
}

export function setTimelineOffline(offline) {
  const bar = $('timeline-offline');
  if (!bar) return;
  const wasOffline = !bar.classList.contains('hidden');
  bar.classList.toggle('hidden', !offline);
  // Al reconectar, la lista se sincroniza sola: sin recargar la pagina (OPS-06, criterio 4).
  if (wasOffline && !offline) loadPage({ reset: true });
}
