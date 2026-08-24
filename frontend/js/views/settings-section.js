// frontend/js/views/settings-section.js
// Fase 32 (OPS-18/19/20, SET-03/SET-04): pinta el panel de UNA seccion completa -- un
// <fieldset> por grupo (nunca un panel por subseccion, D-03), delegando cada fila a
// renderField() de settings-field.js (32-05). Resuelve bajo demanda las dos subsecciones
// de solo lectura (zonas_definidas, reglas_cargadas) que no vienen del esquema de Settings.
//
// Contrato de marcado documentado en la cabecera de settings-save.js (32-05), que este
// modulo respeta para que saveSection/restoreSection localicen el panel solo con el
// sectionKey: [data-cfg-section="<key>"] + data-section-label en el panel,
// [data-cfg-action="save"|"restore"] en los botones.

import { renderField } from './settings-field.js';
import { trackChange, pendingCount, discardChanges, saveSection, restoreSection } from './settings-save.js';

function _panel() {
  return document.getElementById('settings-panel');
}

export function renderSection(section, sectionKey, requiresRestart = []) {
  const panel = _panel();
  if (!panel) return;
  panel.replaceChildren();   // limpiar sin innerHTML=''
  panel.dataset.cfgSection = sectionKey;
  panel.dataset.sectionLabel = section.label;

  for (const group of section.groups) {
    if (group.external_source) {
      panel.appendChild(_renderExternalGroup(group));
      continue;
    }
    const fieldset = document.createElement('fieldset');
    fieldset.className = 'mb-6';
    const legend = document.createElement('legend');
    legend.className = 'text-sm font-semibold';
    legend.textContent = group.label;   // servidor -> textContent
    fieldset.appendChild(legend);
    for (const field of group.fields) fieldset.appendChild(renderField(field, sectionKey));
    panel.appendChild(fieldset);
  }

  _renderSaveBar(sectionKey, section);
  _renderRestoreButton(sectionKey, section);
  if (requiresRestart.length > 0) _renderRestartNotice(panel, requiresRestart.length);
}

// ── Subsecciones de solo lectura (zonas_definidas / reglas_cargadas, T-32-19) ──────────
function _renderExternalGroup(group) {
  const fieldset = document.createElement('fieldset');
  fieldset.className = 'mb-6';
  const legend = document.createElement('legend');
  legend.className = 'text-sm font-semibold';
  legend.textContent = group.label;   // servidor -> textContent
  fieldset.appendChild(legend);
  const body = document.createElement('div');
  body.className = 'flex flex-col gap-1.5';
  fieldset.appendChild(body);
  _loadExternalGroup(group, body);   // bajo demanda, solo al pintarse esta seccion
  return fieldset;
}

async function _loadExternalGroup(group, body) {
  let data;
  try {
    const res = await fetch(group.external_source);
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch {
    body.replaceChildren(_muted('No se pudo cargar.', 'text-sm text-slate-400'));
    return;
  }
  const isZones = group.key === 'zonas_definidas';
  const items = isZones ? (data.zones ?? []) : (data.rules ?? []);
  if (items.length === 0) {
    const [title, hint] = isZones
      ? ['Sin zonas definidas', 'Las zonas se crean y se borran desde el panel «Zonas de interés» de Operaciones.']
      : ['Sin reglas cargadas', 'Las reglas se definen en el fichero config/rules.yaml.'];
    body.replaceChildren(_muted(title, 'text-sm text-slate-300'), _muted(hint, 'text-xs text-slate-500'));
    return;
  }
  body.replaceChildren(...items.map((item) => _externalRow(isZones, item)));
}

function _muted(text, cls) {
  const p = document.createElement('p');
  p.className = cls;
  p.textContent = text;
  return p;
}

function _externalRow(isZones, item) {
  const row = document.createElement('div');
  row.className = 'flex items-center justify-between text-sm text-slate-300 py-1 border-b border-slate-800 last:border-0';
  const name = document.createElement('span');
  name.className = 'truncate';
  name.textContent = item.name;   // dato de usuario (no de Settings) -> textContent
  const meta = document.createElement('span');
  meta.className = 'mono text-xs text-slate-500 flex-shrink-0';
  meta.textContent = isZones ? (item.kind ?? '') : (item.enabled ? 'habilitada' : 'deshabilitada');
  row.append(name, meta);
  return row;
}

// ── Barra de guardado sticky (solo con cambios pendientes) ─────────────────────────────
function _renderSaveBar(sectionKey, section) {
  const panel = _panel();
  if (!panel) return;
  const count = pendingCount(sectionKey);
  if (count === 0) return;

  const bar = document.createElement('div');
  bar.className = 'cfg-savebar';

  const label = document.createElement('span');
  label.className = 'text-sm text-slate-300 mr-auto';
  label.setAttribute('aria-live', 'polite');
  label.textContent = count === 1 ? '1 cambio sin guardar' : `${count} cambios sin guardar`;

  const discardBtn = document.createElement('button');
  discardBtn.type = 'button';
  discardBtn.className = 'text-sm font-semibold text-slate-400 hover:text-slate-200';
  discardBtn.textContent = 'Descartar cambios';
  discardBtn.addEventListener('click', () => {
    discardChanges(sectionKey);
    renderSection(section, sectionKey);   // repintar desde el esquema en memoria, sin fetch
  });

  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'filter-chip active';
  saveBtn.dataset.cfgAction = 'save';
  saveBtn.textContent = 'Guardar cambios';
  saveBtn.addEventListener('click', () => saveSection(sectionKey));

  bar.append(label, discardBtn, saveBtn);
  panel.appendChild(bar);
}

// ── Botón "Restaurar valores por defecto" en la cabecera del panel (OPS-20) ────────────
function _renderRestoreButton(sectionKey, section) {
  const panel = _panel();
  if (!panel) return;

  const header = document.createElement('div');
  header.className = 'flex items-center justify-between mb-4';

  const title = document.createElement('h2');
  title.className = 'text-base font-semibold text-slate-100';
  title.textContent = section.label;   // servidor -> textContent

  const runtimeCount = section.groups
    .flatMap((g) => g.fields ?? [])
    .filter((f) => f.origin === 'runtime').length;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.dataset.cfgAction = 'restore';
  btn.className = 'text-sm font-semibold text-red-500 hover:text-red-400 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:text-red-500';
  btn.textContent = 'Restaurar valores por defecto';
  if (runtimeCount === 0) {
    btn.disabled = true;
    btn.title = 'Esta sección no tiene ningún valor personalizado.';
  } else {
    btn.addEventListener('click', () => restoreSection(sectionKey, runtimeCount));
  }

  header.append(title, btn);
  panel.insertBefore(header, panel.firstChild);
}

// ── Barra ámbar: cambios guardados que no se aplican hasta reiniciar (OPS-19) ──────────
function _renderRestartNotice(panel, count) {
  const notice = document.createElement('div');
  notice.className = 'flex items-center gap-2 text-sm bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-lg px-3 py-2 mb-3';
  notice.textContent = `${count} de estos cambios no se aplicarán hasta reiniciar la cámara. `
    + 'Se guardarán igualmente.';
  panel.appendChild(notice);
}
