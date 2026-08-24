// frontend/js/views/settings-field.js
// Fase 32 (OPS-18/19/20, SET-03/SET-04): un control DOM por tipo de campo del esquema que
// devuelve GET /api/v2/config (32-01/32-02). Contrato: renderField(field, sectionKey) ->
// .cfg-row (consumido por settings-section.js en 32-06).
// Anti-XSS (patron de timeline-row.js): createElement/textContent siempre, nunca innerHTML
// interpolando datos de servidor (label/hint/env/mensaje 422).

import { trackChange } from './settings-save.js';

const ORIGIN_BADGE = {
  runtime: { cls: 'cfg-badge--runtime', text: 'Guardado aquí' },
  env: { cls: 'cfg-badge--env', text: 'Del fichero .env' },
  default: { cls: 'cfg-badge--default', text: 'Valor por defecto' },
};

const APPLIES_BADGE = {
  hot: { cls: 'cfg-applies--hot', text: 'En caliente' },
  restart_camera: { cls: 'cfg-applies--restart', text: 'Requiere reinicio' },
  restart_server: { cls: 'cfg-applies--restart', text: 'Reinicio del servidor' },
};

// Catalogo COCO replicado de detectionClasses.js::DETECTION_CLASS_LABELS (no exportado
// alli; se evita el import cruzado con components/, mismo subconjunto que usa yolo_classes).
const COCO_CLASS_LABELS = {
  0: 'Persona', 1: 'Bicicleta', 2: 'Coche', 3: 'Moto', 24: 'Mochila', 28: 'Maleta',
};

const WEEKDAY_LABELS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];

// Tipos cuyo rango/valor por defecto tiene sentido pintar en .mono bajo la pista.
const RANGE_TYPES = new Set(['int', 'float', 'enum', 'time', 'str']);

function _span(className, text) {
  const el = document.createElement('span');
  el.className = className;
  el.textContent = text;
  return el;
}

function _fmtNum(v) {
  return typeof v === 'number' ? String(v).replace('.', ',') : String(v);
}

function _rangeText(field) {
  if (!RANGE_TYPES.has(field.type)) return '';
  const parts = [];
  if (field.min !== null && field.min !== undefined && field.max !== null && field.max !== undefined) {
    parts.push(`${_fmtNum(field.min)} – ${_fmtNum(field.max)}`);
  }
  if (field.default !== null && field.default !== undefined) {
    parts.push(`por defecto ${_fmtNum(field.default)}`);
  }
  return parts.join(' · ');
}

function _buildRowShell(field) {
  const row = document.createElement('div');
  row.className = 'cfg-row';
  row.style.flexWrap = 'wrap';
  row.dataset.fieldKey = field.key;
  row.dataset.fieldType = field.type;

  const left = document.createElement('div');
  left.className = 'flex flex-col gap-0.5 flex-1 min-w-0';
  left.append(
    _span('text-sm font-semibold text-slate-200', field.label),
    _span('mono text-xs text-slate-600', field.env ?? ''),
  );
  if (field.hint) left.appendChild(_span('text-xs text-slate-500', field.hint));
  const rangeText = _rangeText(field);
  if (rangeText) left.appendChild(_span('mono text-xs text-slate-600', rangeText));

  const right = document.createElement('div');
  right.className = 'flex flex-col gap-1.5 items-end w-[260px] flex-shrink-0';
  const controlWrap = document.createElement('div');
  controlWrap.className = 'cfg-control-wrap flex justify-end w-full';
  right.appendChild(controlWrap);

  const badges = document.createElement('div');
  badges.className = 'flex items-center gap-1.5 h-5';
  const origin = ORIGIN_BADGE[field.origin] ?? ORIGIN_BADGE.default;
  const applies = APPLIES_BADGE[field.applies] ?? APPLIES_BADGE.hot;
  badges.append(
    _span(`cfg-badge ${origin.cls}`, origin.text),
    _span(`cfg-applies ${applies.cls}`, applies.text),
  );
  right.appendChild(badges);

  row.append(left, right);
  return { row, controlWrap };
}

function _renderBool(field, controlWrap, sectionKey) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'cam-toggle w-10 h-5 rounded-full bg-slate-700 relative transition-colors duration-200 cursor-pointer border-0';
  btn.setAttribute('role', 'switch');
  btn.setAttribute('aria-checked', String(Boolean(field.value)));
  btn.setAttribute('aria-label', field.label ?? '');
  const knob = document.createElement('span');
  knob.className = 'cam-toggle-knob absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-slate-400 transition-all duration-200';
  btn.appendChild(knob);
  btn.addEventListener('click', () => {
    const next = btn.getAttribute('aria-checked') !== 'true';
    btn.setAttribute('aria-checked', String(next));
    trackChange(sectionKey, field.key, next);
  });
  controlWrap.appendChild(btn);
}

function _renderNumber(field, controlWrap, sectionKey) {
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'filter-input w-[96px]';
  input.inputMode = 'decimal';
  if (field.min !== null && field.min !== undefined) input.min = String(field.min);
  if (field.max !== null && field.max !== undefined) input.max = String(field.max);
  if (field.step !== null && field.step !== undefined) input.step = String(field.step);
  input.value = field.value ?? '';
  input.addEventListener('blur', () => {
    const n = field.type === 'int' ? parseInt(input.value, 10) : parseFloat(input.value);
    if (!Number.isNaN(n)) trackChange(sectionKey, field.key, n);
  });
  controlWrap.appendChild(input);
}

// type:"str" (tapo_host, host, yolo_model_path, detection_label...): texto libre de ancho
// completo. max_length no viaja en el FieldValue (32-02), asi que el limite real lo aplica
// el servidor en el PUT (422), no un atributo maxlength de cliente.
function _renderStr(field, controlWrap, sectionKey) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'filter-input w-full';
  input.value = field.value ?? '';
  input.addEventListener('blur', () => trackChange(sectionKey, field.key, input.value));
  controlWrap.appendChild(input);
}

function _renderEnum(field, controlWrap, sectionKey) {
  const select = document.createElement('select');
  select.className = 'filter-input filter-select w-[140px]';
  for (const v of field.enum_values ?? []) {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v;
    if (v === field.value) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => trackChange(sectionKey, field.key, select.value));
  controlWrap.appendChild(select);
}

function _renderTime(field, controlWrap, sectionKey) {
  const input = document.createElement('input');
  input.type = 'time';
  input.className = 'filter-input w-[96px]';
  input.value = field.value ?? '';
  input.addEventListener('change', () => trackChange(sectionKey, field.key, input.value));
  controlWrap.appendChild(input);
}

function _renderListInt(field, controlWrap, sectionKey) {
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-wrap gap-1 justify-end';
  const active = new Set(field.value ?? []);
  const isDays = field.key === 'schedule_days';
  const entries = isDays
    ? WEEKDAY_LABELS.map((label, id) => [id, label])
    : Object.entries(COCO_CLASS_LABELS).map(([id, label]) => [Number(id), label]);
  for (const [id, label] of entries) {
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
      trackChange(sectionKey, field.key, values);
    });
    wrap.appendChild(chip);
  }
  controlWrap.appendChild(wrap);
}

function _renderListStr(field, controlWrap, sectionKey) {
  const box = document.createElement('div');
  box.className = 'flex flex-col gap-1 items-end w-full';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'filter-input w-full';
  input.value = (field.value ?? []).join(', ');
  input.addEventListener('blur', () => {
    const values = input.value.split(',').map((s) => s.trim()).filter(Boolean);
    trackChange(sectionKey, field.key, values);
  });
  box.append(input, _span('text-xs text-slate-500', 'sepáralos con comas'));
  controlWrap.appendChild(box);
}

function _renderSecret(field, controlWrap) {
  const box = document.createElement('div');
  box.className = 'flex flex-col gap-0.5 items-end';
  box.append(
    _span('text-sm text-slate-300', field.configured ? 'Configurado' : 'Sin configurar'),
    _span('mono text-xs text-slate-500', 'Se edita en el fichero .env.'),
  );
  controlWrap.appendChild(box);
}

function _renderReadonly(field, controlWrap) {
  const text = field.value !== null && field.value !== undefined ? String(field.value) : '—';
  controlWrap.appendChild(_span('mono text-xs text-slate-400', text));
}

const RENDERERS = {
  bool: _renderBool,
  int: _renderNumber,
  float: _renderNumber,
  str: _renderStr,
  enum: _renderEnum,
  time: _renderTime,
  list_int: _renderListInt,
  list_str: _renderListStr,
  secret: _renderSecret,
  readonly: _renderReadonly,
};

export function renderField(field, sectionKey) {
  const { row, controlWrap } = _buildRowShell(field);
  const renderer = RENDERERS[field.type] ?? _renderReadonly;
  renderer(field, controlWrap, sectionKey);
  return row;
}

export function readFieldValue(rowEl) {
  const type = rowEl.dataset.fieldType;
  switch (type) {
    case 'bool':
      return rowEl.querySelector('.cam-toggle')?.getAttribute('aria-checked') === 'true';
    case 'int':
      return parseInt(rowEl.querySelector('input')?.value ?? '0', 10);
    case 'float':
      return parseFloat(rowEl.querySelector('input')?.value ?? '0');
    case 'str':
      return rowEl.querySelector('input')?.value ?? '';
    case 'enum':
      return rowEl.querySelector('select')?.value;
    case 'time':
      return rowEl.querySelector('input')?.value;
    case 'list_int':
      return [...rowEl.querySelectorAll('[aria-pressed="true"]')].map((c) => Number(c.dataset.value));
    case 'list_str':
      return (rowEl.querySelector('input')?.value ?? '').split(',').map((s) => s.trim()).filter(Boolean);
    default:
      return undefined;
  }
}

export function fieldKeyOf(rowEl) {
  return rowEl.dataset.fieldKey;
}

export function markFieldDirty(rowEl, dirty) {
  rowEl.classList.toggle('dirty', Boolean(dirty));
}

export function setFieldError(rowEl, message) {
  clearFieldError(rowEl);
  const control = rowEl.querySelector('input, select, .cam-toggle');
  const msgId = `${rowEl.dataset.fieldKey}-error`;
  const p = document.createElement('p');
  p.id = msgId;
  p.className = 'text-xs text-red-400';
  p.style.flexBasis = '100%';
  p.textContent = message;
  rowEl.appendChild(p);
  rowEl.classList.add('error');
  if (control) {
    control.setAttribute('aria-invalid', 'true');
    control.setAttribute('aria-describedby', msgId);
  }
}

export function clearFieldError(rowEl) {
  rowEl.classList.remove('error');
  rowEl.querySelectorAll('p[id$="-error"]').forEach((p) => p.remove());
  const control = rowEl.querySelector('input, select, .cam-toggle');
  if (control) {
    control.removeAttribute('aria-invalid');
    control.removeAttribute('aria-describedby');
  }
}
