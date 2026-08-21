// frontend/js/views/timeline-row.js
// Una fila de la linea temporal (OPS-07 / OPS-08) y el estado local de descartados.
//
// Patron obligatorio del repo (CodeQL js/xss, ver eventCard.js:16-18): la estructura va
// por innerHTML con elementos VACIOS y todo dato del backend entra despues por
// textContent / dataset / propiedades del DOM. El nombre de la persona y el de la regla
// los escribe el operador: interpolarlos en la plantilla seria XSS almacenado (T-30-27).

export const SEV_COLOR = { critical: '#ef4444', warning: '#f59e0b', info: '#64748b' };

// Lenguaje llano y en pasado (UI-SPEC "Copywriting Contract"): nunca el identificador
// crudo del catalogo en el texto visible; el tipo tecnico vive en el title de la fila.
// Los nombres son los de backend/events/types.py::EventType, no inventados.
const EVENT_TEXT = {
  PERSON_ENTERED:     (who) => `${who} entró en escena`,
  PERSON_EXITED:      (who) => `${who} salió de escena`,
  LINE_CROSSED:       (who) => `${who} cruzó la línea`,
  ZONE_ENTERED:       (who, z) => (z ? `${who} entró en la zona ${z}` : `${who} entró en una zona`),
  ZONE_EXITED:        (who, z) => (z ? `${who} salió de la zona ${z}` : `${who} salió de una zona`),
  PERSON_RECOGNIZED:  (who) => `${who} fue reconocido`,
  UNKNOWN_PERSON:     () => 'Persona desconocida detectada',
  IDENTITY_LOST:      (who) => `Se perdió la identidad de ${who}`,
  LOITERING:          (who, z) => (z ? `${who} lleva demasiado tiempo en la zona ${z}` : `${who} lleva demasiado tiempo rondando`),
  RUNNING:            (who) => `${who} pasó corriendo`,
  IMMOBILE:           (who) => `${who} lleva un rato sin moverse`,
  CROWD_DETECTED:     () => 'Se detectó una aglomeración',
  INTRUSION:          (_who, z) => (z ? `Intrusión detectada en la zona ${z}` : 'Intrusión detectada'),
  OBJECT_LEFT:        (_who, z) => (z ? `Se dejó un objeto en la zona ${z}` : 'Se dejó un objeto abandonado'),
  OBJECT_REMOVED:     () => 'Desapareció un objeto vigilado',
  CAMERA_OFFLINE:     () => 'La cámara se quedó sin señal',
  CAMERA_RECOVERED:   () => 'La cámara recuperó la señal',
  RECORDING_STARTED:  () => 'Empezó una grabación',
  RECORDING_FINISHED: () => 'Terminó una grabación',
  UPLOAD_FAILED:      () => 'Falló la subida de una grabación',
  CONFIG_CHANGED:     () => 'Cambió la configuración',
  DEGRADED_MODE:      () => 'El pipeline entró en modo degradado',
};

const LABEL = {
  clip: 'Ver clip',
  snapshot: 'Ver captura',
  person: 'Marcar como persona',
  dismiss: 'Descartar',
};

// Iconos de 16px. Marcado constante del modulo: no lleva ni un dato del backend.
const ACTIONS_HTML = `
  <button type="button" class="row-action" data-action="clip" aria-label="Ver clip">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>
  </button>
  <button type="button" class="row-action" data-action="snapshot" aria-label="Ver captura">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
  </button>
  <button type="button" class="row-action" data-action="person" aria-label="Marcar como persona">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
  </button>
  <button type="button" class="row-action" data-action="dismiss" aria-label="Descartar">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
  </button>`;

const THUMB_ICON = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>';

export function describe(ev, personName) {
  const who = personName || 'Desconocido';
  const fn = EVENT_TEXT[ev?.type];
  if (fn) return fn(who, ev?.zone_id ?? '');
  // Tipo fuera del catalogo conocido: se degrada, nunca revienta la fila.
  return String(ev?.type ?? 'evento').replace(/_/g, ' ').toLowerCase();
}

function placeholderThumb(time) {
  const box = document.createElement('span');
  box.className = 'tl-thumb flex items-center justify-center text-slate-600';
  box.style.background = '#1e293b';
  box.tabIndex = 0;
  box.setAttribute('role', 'button');
  box.setAttribute('aria-label', `Ver captura del evento de las ${time}`);
  box.innerHTML = THUMB_ICON;
  return box;
}

// El nombre confirmado va en verde dentro de la frase; "Desconocido" hereda el color de
// la severidad de la fila (UI-SPEC). Ambos por textContent, nunca por plantilla.
function paintDesc(desc, text, who, named) {
  if (!text.startsWith(who)) { desc.textContent = text; return; }
  const strong = document.createElement('span');
  if (named) strong.className = 'text-green-400';
  else strong.style.color = 'var(--sev)';
  strong.textContent = who;
  desc.appendChild(strong);
  desc.appendChild(document.createTextNode(text.slice(who.length)));
}

export function timelineRow(ev, media, personName) {
  const row = document.createElement('div');
  row.className = 'timeline-row';
  row.dataset.id = ev.id;
  row.dataset.trackId = ev.track_id ?? '';
  row.dataset.ts = ev.ts;
  row.style.setProperty('--sev', SEV_COLOR[ev.severity] ?? SEV_COLOR.info);
  row.title = ev.type ?? '';
  const time = new Date(ev.ts).toLocaleTimeString('es-ES', { hour12: false });
  row.innerHTML = `
    <span class="sev-bar" aria-hidden="true"></span>
    <span class="tl-time mono text-xs text-slate-400 tabular-nums flex-shrink-0"></span>
    <img class="tl-thumb" width="64" height="36" loading="lazy" alt="" role="button" tabindex="0">
    <span class="tl-desc text-xs font-semibold text-slate-200 truncate flex-1 min-w-0"></span>
    <span class="tl-zone chip" hidden></span>
    <span class="tl-rule chip rule-chip mono" hidden></span>
    <span class="tl-actions flex items-center gap-0.5 flex-shrink-0">${ACTIONS_HTML}</span>`;

  row.querySelector('.tl-time').textContent = time;
  paintDesc(row.querySelector('.tl-desc'), describe(ev, personName), personName || 'Desconocido', Boolean(personName));

  if (ev.zone_id) {
    const zone = row.querySelector('.tl-zone');
    zone.textContent = ev.zone_id;
    zone.hidden = false;
  }
  const rules = ev.payload?.rules ?? [];
  if (rules.length) {
    const chip = row.querySelector('.tl-rule');
    chip.textContent = `⚡ ${rules[0]}`;
    chip.title = rules.join(' · ');
    chip.hidden = false;
  }

  const thumb = row.querySelector('.tl-thumb');
  const src = media?.snapshot_url ?? media?.thumbnail_url;
  if (src) {
    thumb.src = src;
    thumb.setAttribute('aria-label', `Ver captura del evento de las ${time}`);
  } else {
    thumb.replaceWith(placeholderThumb(time));
  }

  row.querySelectorAll('.row-action').forEach((btn) => {
    const kind = btn.dataset.action;
    btn.setAttribute('aria-label', `${LABEL[kind]} del evento de las ${time}`);
    btn.title = LABEL[kind];
  });
  if (!media?.clip_url) {
    const clip = row.querySelector('[data-action="clip"]');
    clip.disabled = true;
    clip.title = 'Este evento no tiene grabación';
  }
  if (ev.track_id === null || ev.track_id === undefined) {
    const person = row.querySelector('[data-action="person"]');
    person.disabled = true;
    person.title = 'Este evento no tiene track asociado';
  }
  return row;
}

// ── Descartados: estado de CLIENTE ────────────────────────────────
// Descartar no borra nada de la base de datos (UI-SPEC) y el servidor no debe saber que
// ha ocultado un navegador concreto: el filtrado se aplica al pintar, jamas en la consulta.
const DISMISS_KEY = 'timeline.dismissed';
const DISMISS_CAP = 500;

function readDismissed() {
  try {
    const raw = JSON.parse(localStorage.getItem(DISMISS_KEY) ?? '[]');
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}

function writeDismissed(ids) {
  try { localStorage.setItem(DISMISS_KEY, JSON.stringify(ids)); } catch { /* modo privado o cuota */ }
}

export function isDismissed(eventId) {
  return readDismissed().includes(eventId);
}

export function dismiss(eventId) {
  const ids = readDismissed().filter((id) => id !== eventId);
  ids.push(eventId);
  writeDismissed(ids.slice(-DISMISS_CAP));   // tope FIFO: se cae el mas antiguo
}

export function undismiss(eventId) {
  writeDismissed(readDismissed().filter((id) => id !== eventId));
}
