// frontend/js/views/analytics-range.js
// Selector de rango de la vista de analitica (OPS-13/OPS-14): cuatro presets + personalizado.
//
// Este modulo solo EMITE un rango; nunca agrega ni interpreta la respuesta del servidor.
// La aritmetica de fechas de aqui abajo es legitima: construye la peticion (que from/to
// pedir), no agrega lo que el servidor ya devolvio resuelto.

const $ = (id) => document.getElementById(id);

const LS_KEY = 'analytics.range';
const KNOWN_PRESETS = ['today', '7d', '30d', 'custom'];
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

// Las dos cadenas son literalmente las que devuelve el 422 de _resolve_range() en el
// servidor (31-05). Si divergen, el operador ve un texto distinto segun quien rechace.
const ERR_ORDEN = 'La fecha «Hasta» debe ser posterior a «Desde».';
const ERR_LARGO = 'El rango máximo es de 90 días.';

let state = { preset: 'today', from: null, to: null };
let notify = null;

// El metodo nativo de fecha-hora en UTC da el dia equivocado por la noche al este de
// Greenwich. Fecha local sin hora, siempre YYYY-MM-DD.
function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d;
}

function fmt(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${d} ${MESES[m - 1]}`;
}

// Rangos inclusivos en los dos extremos, igual que los interpreta el servidor.
function resolve(preset) {
  const today = ymd(new Date());
  if (preset === 'today') return { from: today, to: today };
  if (preset === '7d') return { from: ymd(daysAgo(6)), to: today };
  if (preset === '30d') return { from: ymd(daysAgo(29)), to: today };
  return { from: $('an-from')?.value ?? '', to: $('an-to')?.value ?? '' };
}

function showError(msg) {
  const el = $('an-range-error');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError() {
  $('an-range-error')?.classList.add('hidden');
}

function paintSubtitle() {
  const el = $('an-subtitle');
  if (el && state.from && state.to) el.textContent = `${fmt(state.from)} → ${fmt(state.to)}`;
}

function persist() {
  // localStorage puede lanzar en modo privado o con la cuota agotada.
  try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch { /* modo privado o cuota */ }
}

function setActiveChip(preset) {
  document.querySelectorAll('#an-range [data-range]').forEach((chip) => {
    const active = chip.dataset.range === preset;
    chip.classList.toggle('active', active);
    chip.setAttribute('aria-pressed', String(active));
  });
  $('an-custom')?.classList.toggle('hidden', preset !== 'custom');
}

function emit(preset, range) {
  state = { preset, from: range.from, to: range.to };
  persist();
  paintSubtitle();
  if (notify) notify(currentRange());
}

// Validacion, solo en el camino custom y solo al pulsar #an-apply.
// Esto es cortesia para el operador, no seguridad: la autoridad es el 422 del servidor.
function applyCustomRange() {
  const from = $('an-from')?.value ?? '';
  const to = $('an-to')?.value ?? '';
  if (!from || !to) return; // formulario a medio rellenar, no es un error del operador
  if (to < from) { showError(ERR_ORDEN); return; }
  const days = Math.round((new Date(to) - new Date(from)) / 86400000) + 1;
  if (days > 90) { showError(ERR_LARGO); return; }
  hideError();
  emit('custom', { from, to });
}

function restore() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(LS_KEY) ?? 'null'); } catch { saved = null; }
  // Lista blanca, no confianza: localStorage es entrada del usuario.
  const preset = saved && KNOWN_PRESETS.includes(saved.preset) ? saved.preset : 'today';
  if (preset === 'custom' && saved?.from && saved?.to) {
    if ($('an-from')) $('an-from').value = saved.from;
    if ($('an-to')) $('an-to').value = saved.to;
    state = { preset: 'custom', from: saved.from, to: saved.to };
  } else {
    const r = resolve(preset);
    state = { preset, from: r.from, to: r.to };
  }
  setActiveChip(preset);
  paintSubtitle();
}

/** Engancha chips, fechas y localStorage. No llama a onChange al arrancar: solo restaura
 * el estado visual y el subtitulo. Quien dispara la primera carga es el orquestador de 31-10. */
export function initRange(onChange) {
  notify = onChange;
  document.querySelectorAll('#an-range [data-range]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const preset = chip.dataset.range;
      setActiveChip(preset);
      hideError();
      if (preset === 'custom') return; // espera al boton Aplicar rango
      emit(preset, resolve(preset));
    });
  });
  // Los inputs de fecha no llevan listener de input/change (D-09): un date a medio
  // teclear no dispara nada. Solo el boton Aplicar rango evalua y emite.
  $('an-apply')?.addEventListener('click', applyCustomRange);
  restore();
}

/** {preset, from, to} con from/to ya resueltos: today/7d/30d se recalculan en el momento. */
export function currentRange() {
  if (state.preset === 'custom') return { preset: 'custom', from: state.from, to: state.to };
  const r = resolve(state.preset);
  return { preset: state.preset, from: r.from, to: r.to };
}
