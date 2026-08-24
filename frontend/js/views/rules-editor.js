// frontend/js/views/rules-editor.js
// Fase 33 (OPS-24/RULE-05): orquestador del editor de reglas -- lista, CRUD y "Probar regla"
// contra /api/v2/rules. Ids esperados en el DOM (panel montado por camera.js en el Plan
// 33-13): #rules-panel, #rules-list, #rule-new-btn, #rule-form, #rule-test-btn,
// #rule-test-result.
// Anti-XSS: createElement/textContent siempre, nunca HTML crudo con datos de servidor
// (nombre de regla, mensaje 422, resultado de /test).

import { renderWhenFields, renderActionFields } from './rules-form.js';
import { showToast } from './dashboard.js';

let _zoneOptions = [];
let _zoneOptionsLoaded = false;
let _currentRule = null; // {id, name, enabled, when, debounce_secs, actions} | null
let _initialized = false;

function _emptyRule() {
  return {
    id: '',
    name: '',
    enabled: true,
    when: { event: 'LINE_CROSSED', camera: '*' },
    debounce_secs: 0,
    actions: [],
  };
}

async function _loadZoneOptions() {
  if (_zoneOptionsLoaded) return _zoneOptions;
  try {
    const res = await fetch('/api/v2/zones');
    if (res.ok) {
      const data = await res.json();
      _zoneOptions = (data.zones ?? []).map((z) => ({ id: z.id, name: z.name }));
    }
  } catch {
    // Sin zonas disponibles: el select de zona queda solo con "(cualquiera)".
  }
  _zoneOptionsLoaded = true;
  return _zoneOptions;
}

function _rulesList() { return document.getElementById('rules-list'); }
function _ruleForm() { return document.getElementById('rule-form'); }
function _testResult() { return document.getElementById('rule-test-result'); }

function _clearFieldErrors() {
  _ruleForm()?.querySelectorAll('.cfg-row.error').forEach((row) => {
    row.classList.remove('error');
    row.querySelectorAll('p[id$="-error"]').forEach((p) => p.remove());
  });
}

function _setFieldError(fieldName, message) {
  const row = _ruleForm()?.querySelector(`[data-when-field="${fieldName}"]`);
  if (!row) return;
  const p = document.createElement('p');
  p.id = `${fieldName}-error`;
  p.className = 'text-xs text-red-400';
  p.style.flexBasis = '100%';
  p.textContent = message;
  row.appendChild(p);
  row.classList.add('error');
}

function _ruleRow(rule) {
  const row = document.createElement('div');
  row.className = 'cfg-row';

  const left = document.createElement('div');
  left.className = 'flex flex-col gap-0.5 flex-1 min-w-0';
  const nameSpan = document.createElement('span');
  nameSpan.className = 'text-sm font-semibold text-slate-200';
  nameSpan.textContent = rule.name;
  const stateSpan = document.createElement('span');
  stateSpan.className = 'text-xs text-slate-500';
  stateSpan.textContent = rule.enabled ? 'Activa' : 'Desactivada';
  left.append(nameSpan, stateSpan);

  const actionsWrap = document.createElement('div');
  actionsWrap.className = 'flex items-center gap-1.5';
  const editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'filter-chip';
  editBtn.textContent = 'Editar';
  editBtn.addEventListener('click', () => openRuleForm(rule));
  const testBtn = document.createElement('button');
  testBtn.type = 'button';
  testBtn.className = 'filter-chip';
  testBtn.textContent = 'Probar';
  testBtn.addEventListener('click', () => testRule(rule.id));
  const delBtn = document.createElement('button');
  delBtn.type = 'button';
  delBtn.className = 'filter-chip';
  delBtn.textContent = 'Borrar';
  delBtn.addEventListener('click', () => deleteRule(rule.id, rule.name));
  actionsWrap.append(editBtn, testBtn, delBtn);

  row.append(left, actionsWrap);
  return row;
}

export async function loadRules() {
  const list = _rulesList();
  if (!list) return;
  try {
    const res = await fetch('/api/v2/rules');
    if (!res.ok) return;
    const data = await res.json();
    list.replaceChildren(...(data.rules ?? []).map((rule) => _ruleRow(rule)));
  } catch {
    showToast('No se pudieron cargar las reglas.', 'error');
  }
}

function _renderForm(zoneOptions) {
  const form = _ruleForm();
  if (!form) return;
  form.replaceChildren();
  _clearFieldErrors();

  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'filter-input w-full';
  nameInput.placeholder = 'Nombre de la regla';
  nameInput.value = _currentRule.name ?? '';
  nameInput.addEventListener('blur', () => { _currentRule.name = nameInput.value; });

  const whenFrag = renderWhenFields(_currentRule.when, zoneOptions, (field, value) => {
    _currentRule.when = { ..._currentRule.when, [field]: value };
  });
  const actionsFrag = renderActionFields(_currentRule.actions, (nextActions) => {
    _currentRule.actions = nextActions;
    _renderForm(zoneOptions); // re-pinta acciones tras anadir/quitar/cambiar tipo
  });

  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'filter-chip';
  saveBtn.textContent = 'Guardar';
  saveBtn.addEventListener('click', () => saveRule());

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'filter-chip';
  cancelBtn.textContent = 'Cancelar';
  cancelBtn.addEventListener('click', () => {
    form.classList.remove('open');
    _currentRule = null;
  });

  const btnRow = document.createElement('div');
  btnRow.className = 'flex items-center gap-1.5';
  btnRow.append(saveBtn, cancelBtn);

  form.append(nameInput, whenFrag, actionsFrag, btnRow);
}

export async function openRuleForm(rule) {
  const form = _ruleForm();
  if (!form) return;
  _currentRule = rule ? JSON.parse(JSON.stringify(rule)) : _emptyRule();
  const result = _testResult();
  if (result) result.textContent = '';
  const zoneOptions = await _loadZoneOptions();
  _renderForm(zoneOptions);
  form.classList.add('open');
}

export async function saveRule() {
  if (!_currentRule) return;
  const form = _ruleForm();
  _clearFieldErrors();
  const id = _currentRule.id || `rule-${Date.now()}`;
  const body = {
    id,
    name: _currentRule.name,
    enabled: _currentRule.enabled ?? true,
    when: _currentRule.when,
    debounce_secs: _currentRule.debounce_secs ?? 0,
    actions: _currentRule.actions ?? [],
  };

  let res;
  try {
    res = await fetch('/api/v2/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    showToast('No se pudo guardar la regla. Inténtalo de nuevo.', 'error');
    return;
  }

  if (res.status === 422) {
    const errBody = await res.json().catch(() => ({}));
    const errors = errBody.detail?.errors ?? errBody.errors ?? [];
    for (const err of errors) {
      const field = err.field?.startsWith('when.') ? err.field.slice(5) : err.field;
      _setFieldError(field, err.message);
    }
    return;
  }

  if (!res.ok) {
    showToast('No se pudo guardar la regla. Inténtalo de nuevo.', 'error');
    return;
  }

  showToast(`Regla «${_currentRule.name}» guardada.`, 'success');
  form?.classList.remove('open');
  _currentRule = null;
  await loadRules();
}

export async function testRule(ruleId) {
  const result = _testResult();
  if (!ruleId) return;
  try {
    const res = await fetch(`/api/v2/rules/${encodeURIComponent(ruleId)}/test`, { method: 'POST' });
    if (!res.ok) {
      if (result) result.textContent = 'No se pudo probar la regla.';
      return;
    }
    const data = await res.json();
    if (result) {
      result.textContent = `${data.would_fire} de ${data.total_checked} eventos recientes habrían disparado esta regla`;
    }
  } catch {
    if (result) result.textContent = 'Sin respuesta del servidor.';
  }
}

export async function deleteRule(id, name) {
  if (!confirm(`¿Eliminar la regla "${name}"?`)) return;
  try {
    const res = await fetch(`/api/v2/rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res.ok) {
      showToast(`Regla «${name}» eliminada.`, 'info');
      await loadRules();
    } else {
      showToast('No se pudo eliminar la regla.', 'error');
    }
  } catch {
    showToast('Sin respuesta del servidor.', 'error');
  }
}

export function initRulesEditor() {
  if (_initialized) return;
  _initialized = true;
  document.getElementById('rule-new-btn')?.addEventListener('click', () => openRuleForm());
  document.getElementById('rule-test-btn')?.addEventListener('click', () => {
    if (_currentRule?.id) testRule(_currentRule.id);
  });
  loadRules();
}
