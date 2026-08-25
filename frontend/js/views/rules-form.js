// frontend/js/views/rules-form.js
// Fase 33 (OPS-24/RULE-05): renderers de campo para el formulario de reglas (When/Action).
// Mismo patron que settings-field.js (Fase 32), sin importarlo: este editor vive en un
// contexto DOM distinto (#rule-form dentro del panel de reglas de la vista Camara, montado
// por el Plan 33-13) y su estado de formulario vive en rules-editor.js, no aqui — este
// fichero es puramente de renderizado.
// Anti-XSS: createElement/textContent siempre, nunca HTML crudo interpolando datos de
// servidor (nombre de zona, mensaje 422).

// Valores reales de backend/events/types.py::EventType — deben coincidir exactamente con el
// enum del servidor o cualquier valor no listado provocaria un 422 inevitable.
const EVENT_TYPES = [
  'PERSON_ENTERED', 'PERSON_EXITED', 'LINE_CROSSED', 'ZONE_ENTERED', 'ZONE_EXITED',
  'PERSON_RECOGNIZED', 'UNKNOWN_PERSON', 'IDENTITY_LOST',
  'LOITERING', 'RUNNING', 'IMMOBILE', 'CROWD_DETECTED', 'INTRUSION',
  'OBJECT_LEFT', 'OBJECT_REMOVED',
  'CAMERA_OFFLINE', 'CAMERA_RECOVERED', 'RECORDING_STARTED', 'RECORDING_FINISHED',
  'UPLOAD_FAILED', 'CONFIG_CHANGED', 'DEGRADED_MODE',
];

// Literal de Action.type — backend/events/rules.py:37-39.
const ACTION_TYPES = [
  'record', 'snapshot', 'notify', 'telegram', 'webhook', 'log', 'upload_drive', 'set_flag',
];

const WEEKDAY_LABELS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];

// Campos condicionales por tipo de accion — solo se muestran los que ese tipo usa.
const ACTION_FIELDS = {
  record: ['pre_secs', 'post_secs'],
  snapshot: [],
  notify: ['template'],
  telegram: ['template'],
  webhook: ['url_ref'],
  log: [],
  upload_drive: [],
  set_flag: [],
};

const ACTION_FIELD_LABELS = {
  pre_secs: 'Pre (s)', post_secs: 'Post (s)', template: 'Plantilla', url_ref: 'URL',
};

function _span(className, text) {
  const el = document.createElement('span');
  el.className = className;
  el.textContent = text;
  return el;
}

function _row(fieldName, labelText) {
  const row = document.createElement('div');
  row.className = 'cfg-row';
  row.style.flexWrap = 'wrap';
  row.setAttribute('data-when-field', fieldName);
  const left = document.createElement('div');
  left.className = 'flex flex-col gap-0.5 flex-1 min-w-0';
  left.appendChild(_span('text-sm font-semibold text-slate-200', labelText));
  const right = document.createElement('div');
  right.className = 'flex flex-col gap-1.5 items-end w-[260px] flex-shrink-0';
  const controlWrap = document.createElement('div');
  controlWrap.className = 'cfg-control-wrap flex justify-end w-full';
  right.appendChild(controlWrap);
  row.append(left, right);
  return { row, controlWrap };
}

function _renderEventField(when, onChange) {
  const { row, controlWrap } = _row('event', 'Evento');
  const select = document.createElement('select');
  select.className = 'filter-input filter-select w-[200px]';
  for (const v of EVENT_TYPES) {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v;
    if (v === when.event) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => onChange('event', select.value));
  controlWrap.appendChild(select);
  return row;
}

function _renderZoneField(when, zoneOptions, onChange) {
  const { row, controlWrap } = _row('zone', 'Zona');
  const select = document.createElement('select');
  select.className = 'filter-input filter-select w-[200px]';
  const optAny = document.createElement('option');
  optAny.value = '';
  optAny.textContent = '(cualquiera)';
  if (!when.zone) optAny.selected = true;
  select.appendChild(optAny);
  for (const z of zoneOptions ?? []) {
    const opt = document.createElement('option');
    opt.value = z.id;
    opt.textContent = z.name;
    if (z.id === when.zone) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => onChange('zone', select.value || null));
  controlWrap.appendChild(select);
  return row;
}

function _renderCameraField(when, onChange) {
  const { row, controlWrap } = _row('camera', 'Cámara');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'filter-input w-[140px]';
  input.value = when.camera ?? '*';
  input.addEventListener('blur', () => onChange('camera', input.value || '*'));
  controlWrap.appendChild(input);
  return row;
}

function _splitTimeRange(spec) {
  if (!spec) return ['', ''];
  const [start, end] = spec.split('-');
  return [start ?? '', end ?? ''];
}

function _renderTimeRangeField(when, onChange) {
  const { row, controlWrap } = _row('time_range', 'Horario');
  const [startVal, endVal] = _splitTimeRange(when.time_range);
  const wrap = document.createElement('div');
  wrap.className = 'flex items-center gap-1';
  const start = document.createElement('input');
  start.type = 'time';
  start.className = 'filter-input w-[96px]';
  start.value = startVal;
  const end = document.createElement('input');
  end.type = 'time';
  end.className = 'filter-input w-[96px]';
  end.value = endVal;
  const emit = () => {
    if (!start.value && !end.value) { onChange('time_range', null); return; }
    onChange('time_range', `${start.value || '00:00'}-${end.value || '00:00'}`);
  };
  start.addEventListener('change', emit);
  end.addEventListener('change', emit);
  wrap.append(start, _span('text-xs text-slate-500', '–'), end);
  controlWrap.appendChild(wrap);
  return row;
}

function _renderDaysField(when, onChange) {
  const { row, controlWrap } = _row('days', 'Días');
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-wrap gap-1 justify-end';
  const active = new Set(when.days ?? []);
  WEEKDAY_LABELS.forEach((label, id) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip';
    chip.textContent = label;
    chip.dataset.value = String(id);
    const pressed = active.has(id);
    chip.setAttribute('aria-pressed', String(pressed));
    if (pressed) chip.classList.add('active');
    chip.addEventListener('click', () => {
      const next = chip.getAttribute('aria-pressed') !== 'true';
      chip.setAttribute('aria-pressed', String(next));
      chip.classList.toggle('active', next);
      const values = [...wrap.querySelectorAll('[aria-pressed="true"]')].map((c) => Number(c.dataset.value));
      onChange('days', values.length ? values : null);
    });
    wrap.appendChild(chip);
  });
  controlWrap.appendChild(wrap);
  return row;
}

function _renderNumberField(fieldName, labelText, value, opts, onChange) {
  const { row, controlWrap } = _row(fieldName, labelText);
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'filter-input w-[96px]';
  input.step = String(opts.step);
  if (opts.min !== undefined) input.min = String(opts.min);
  if (opts.max !== undefined) input.max = String(opts.max);
  input.value = value ?? '';
  input.addEventListener('blur', () => {
    if (input.value === '') { onChange(fieldName, null); return; }
    const n = parseFloat(input.value);
    if (!Number.isNaN(n)) onChange(fieldName, n);
  });
  controlWrap.appendChild(input);
  return row;
}

function _renderPersonField(when, onChange) {
  const { row, controlWrap } = _row('person', 'Persona');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'filter-input w-full';
  input.placeholder = 'unknown o nombre';
  input.value = when.person ?? '';
  input.addEventListener('blur', () => onChange('person', input.value || null));
  controlWrap.appendChild(input);
  return row;
}

export function renderWhenFields(when, zoneOptions, onChange) {
  const frag = document.createDocumentFragment();
  frag.append(
    _renderEventField(when, onChange),
    _renderZoneField(when, zoneOptions, onChange),
    _renderCameraField(when, onChange),
    _renderTimeRangeField(when, onChange),
    _renderDaysField(when, onChange),
    _renderNumberField('min_confidence', 'Confianza mínima', when.min_confidence, { step: 0.05, min: 0, max: 1 }, onChange),
    _renderNumberField('duration_gte', 'Duración mínima (s)', when.duration_gte, { step: 0.5, min: 0 }, onChange),
    _renderPersonField(when, onChange),
  );
  return frag;
}

// ── Action fields ────────────────────────────────────────────────────────────────────────

function _renderActionConditionalField(action, fieldName, type, onFieldChange) {
  const wrap = document.createElement('div');
  wrap.className = 'flex items-center gap-1.5';
  wrap.appendChild(_span('text-xs text-slate-500', ACTION_FIELD_LABELS[fieldName] ?? fieldName));
  const input = document.createElement('input');
  input.type = type;
  input.className = 'filter-input w-[100px]';
  if (type === 'number') input.step = '0.5';
  input.value = action[fieldName] ?? '';
  input.addEventListener('blur', () => {
    if (input.value === '') { onFieldChange(fieldName, null); return; }
    onFieldChange(fieldName, type === 'number' ? parseFloat(input.value) : input.value);
  });
  wrap.appendChild(input);
  return wrap;
}

function _renderActionRow(action, index, onChange, actions) {
  const row = document.createElement('div');
  row.className = 'cfg-row';
  row.style.flexWrap = 'wrap';
  row.dataset.actionIndex = String(index);

  const select = document.createElement('select');
  select.className = 'filter-input filter-select w-[140px]';
  for (const t of ACTION_TYPES) {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    if (t === action.type) opt.selected = true;
    select.appendChild(opt);
  }

  const fieldsWrap = document.createElement('div');
  fieldsWrap.className = 'flex items-center gap-2 flex-wrap';

  const updateAction = (patch) => {
    onChange(actions.map((a, i) => (i === index ? { ...a, ...patch } : a)));
  };

  const renderConditionalFields = (actionType) => {
    fieldsWrap.replaceChildren();
    for (const fieldName of ACTION_FIELDS[actionType] ?? []) {
      const type = fieldName.endsWith('_secs') ? 'number' : 'text';
      fieldsWrap.appendChild(
        _renderActionConditionalField(action, fieldName, type, (f, v) => updateAction({ [f]: v })),
      );
    }
  };
  renderConditionalFields(action.type);

  select.addEventListener('change', () => {
    updateAction({ type: select.value });
    renderConditionalFields(select.value);
  });

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'filter-chip';
  removeBtn.textContent = 'Quitar';
  removeBtn.addEventListener('click', () => onChange(actions.filter((_, i) => i !== index)));

  row.append(select, fieldsWrap, removeBtn);
  return row;
}

export function renderActionFields(actions, onChange) {
  const frag = document.createDocumentFragment();
  const list = document.createElement('div');
  list.className = 'flex flex-col gap-2';
  (actions ?? []).forEach((action, index) => {
    list.appendChild(_renderActionRow(action, index, onChange, actions));
  });
  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'filter-chip';
  addBtn.textContent = '+ Añadir acción';
  addBtn.addEventListener('click', () => onChange([...(actions ?? []), { type: 'log' }]));
  frag.append(list, addBtn);
  return frag;
}
