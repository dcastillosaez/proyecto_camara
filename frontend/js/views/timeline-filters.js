// frontend/js/views/timeline-filters.js
// Barra de filtros de la linea temporal: lectura de los controles, chips activos y limpieza.
//
// Todo filtro se resuelve en SERVIDOR (OPS-09 / T-30-30): aqui solo se construye el
// querystring que viaja a GET /api/v2/events. Nunca se filtra el array ya descargado.
import { describe } from './timeline-row.js';

const TYPE_CHIPS = [
  ['INTRUSION', 'Intrusión'], ['UNKNOWN_PERSON', 'Desconocido'], ['LINE_CROSSED', 'Cruce'],
  ['ZONE_ENTERED', 'Entrada'], ['LOITERING', 'Merodeo'], ['OBJECT_LEFT', 'Objeto'],
];

const $ = (id) => document.getElementById(id);

// Foco puesto desde el centro de alertas ("Ver en la linea temporal"). Vive aqui, con el
// resto del estado de filtros, porque `rule` no tiene control propio en la barra: el
// operador no puede teclear un nombre de regla, solo llegar a el desde una alerta.
let _focusRule = null;
let _focusType = null;

/** Deja como unico filtro la regla de la alerta (o su tipo, si el grupo no tiene regla). */
export function setFocusFilter(ruleName, eventType) {
  clearAllFilters();
  if (ruleName) { _focusRule = ruleName; return; }
  if (!eventType) return;
  // Si el tipo tiene chip propio en la barra, se enciende: asi la barra refleja el filtro.
  // Se compara por dataset, nunca montando un selector con texto del servidor.
  const chip = [...document.querySelectorAll('#tl-filter-types .filter-chip')]
    .find((c) => c.dataset.type === eventType);
  if (chip) chip.classList.add('active');
  else _focusType = eventType;
}

function personIdFor(persons, name) {
  const target = name.trim().toLowerCase();
  for (const [id, n] of persons) if (String(n).toLowerCase() === target) return id;
  return null;
}

/** -> { params, chips: [[key, label]], hasFilters } */
export function filterParams(persons, pageSize) {
  const p = new URLSearchParams();
  const chips = [];
  document.querySelectorAll('#tl-filter-types .filter-chip.active').forEach((c) => {
    p.append('type', c.dataset.type);
    chips.push([`type:${c.dataset.type}`, c.textContent]);
  });
  if (_focusRule) { p.set('rule', _focusRule); chips.push(['rule', `Regla: ${_focusRule}`]); }
  if (_focusType) { p.append('type', _focusType); chips.push(['focus-type', describe({ type: _focusType })]); }
  const sev = document.querySelector('#tl-filter-severity .filter-chip.active');
  if (sev) { p.set('severity', sev.dataset.severity); chips.push(['severity', sev.textContent]); }
  const zone = $('tl-filter-zone')?.value ?? '';
  if (zone) { p.set('zone_id', zone); chips.push(['zone', `Zona: ${zone}`]); }
  const person = ($('tl-filter-person')?.value ?? '').trim();
  if (person) {
    const id = personIdFor(persons, person);
    // Sin coincidencia no se manda el parametro: el chip lo dice en vez de fingir que filtra.
    if (id !== null) { p.set('person_id', String(id)); chips.push(['person', `Persona: ${person}`]); }
    else chips.push(['person', `Persona: ${person} (sin coincidencia)`]);
  }
  const from = $('tl-filter-from')?.value ?? '';
  const to = $('tl-filter-to')?.value ?? '';
  if (from) { p.set('from', `${from}T00:00:00`); chips.push(['from', `Desde ${from}`]); }
  if (to) { p.set('to', `${to}T23:59:59`); chips.push(['to', `Hasta ${to}`]); }
  p.set('limit', String(pageSize));
  return { params: p, chips, hasFilters: chips.length > 0 };
}

export function clearFilter(key) {
  if (key === 'rule') { _focusRule = null; }
  else if (key === 'focus-type') { _focusType = null; }
  else if (key.startsWith('type:')) {
    document.querySelector(`#tl-filter-types .filter-chip[data-type="${key.slice(5)}"]`)?.classList.remove('active');
  } else if (key === 'severity') {
    document.querySelector('#tl-filter-severity .filter-chip.active')?.classList.remove('active');
  } else {
    const el = $({ zone: 'tl-filter-zone', person: 'tl-filter-person', from: 'tl-filter-from', to: 'tl-filter-to' }[key]);
    if (el) el.value = '';
  }
}

export function clearAllFilters() {
  _focusRule = null;
  _focusType = null;
  document.querySelectorAll('#tl-filter-types .filter-chip, #tl-filter-severity .filter-chip')
    .forEach((c) => c.classList.remove('active'));
  ['tl-filter-zone', 'tl-filter-person', 'tl-filter-from', 'tl-filter-to']
    .forEach((id) => { const el = $(id); if (el) el.value = ''; });
}

/** Chips azules encima de la lista, cada uno con su "x" (unico uso de azul de la fase). */
export function paintActiveChips(chips, onRemove) {
  const box = $('tl-active-filters');
  if (!box) return;
  box.textContent = '';
  chips.forEach(([key, label]) => {
    const chip = document.createElement('span');
    chip.className = 'chip bg-blue-600/20 border-blue-600/40 text-blue-300';
    const text = document.createElement('span');
    text.textContent = label;          // label puede llevar un nombre escrito por el operador
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'ml-1 cursor-pointer';
    x.textContent = '×';
    x.setAttribute('aria-label', `Quitar filtro ${label}`);
    x.addEventListener('click', () => onRemove(key));
    chip.append(text, x);
    box.appendChild(chip);
  });
}

export function bindFilterChips() {
  const types = $('tl-filter-types');
  TYPE_CHIPS.forEach(([value, label]) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip';
    chip.dataset.type = value;
    chip.textContent = label;
    types?.appendChild(chip);
  });
  types?.addEventListener('click', (e) => {
    const chip = e.target.closest('.filter-chip');
    if (chip) chip.classList.toggle('active');                 // multi-seleccion
  });
  $('tl-filter-severity')?.addEventListener('click', (e) => {
    const chip = e.target.closest('.filter-chip');
    if (!chip) return;
    const on = chip.classList.contains('active');
    document.querySelectorAll('#tl-filter-severity .filter-chip').forEach((c) => c.classList.remove('active'));
    chip.classList.toggle('active', !on);                      // excluyentes
  });
}
