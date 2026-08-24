// frontend/js/views/settings.js
// Fase 32 (OPS-18/19/20, SET-03/SET-04): orquestador de la vista Ajustes. Carga el esquema
// de GET /api/v2/config UNA vez, pinta el arbol de las 8 secciones fijas como tablist
// vertical (mismo mecanismo de teclado que el tablist horizontal de vistas de la Fase 31,
// aplicado en vertical) y delega el pintado de cada seccion a
// settings-section.js::renderSection(). El diff pendiente vive en settings-save.js (nunca
// aqui ni en el DOM): cambiar de seccion con cambios sin guardar no lo pierde ni muestra
// confirm() -- el punto azul del arbol es la unica senal (D-09).
//
// #settings-tree y #settings-panel los crea 32-07 -- este modulo tolera su ausencia con
// `?.`, igual que camera.js/camera-quick.js en 32-04 y settings-field.js/settings-save.js
// en 32-05, para poder verificarse por import/sintaxis antes de que exista el marcado real.

import { renderSection } from './settings-section.js';
import { isDirty, setOnSectionSaved } from './settings-save.js';

const SECTION_SKELETON_ROWS = 8;   // 8 secciones fijas del UI-SPEC, ancho conocido de antemano

let _schema = null;   // respuesta completa de GET /api/v2/config
let _activeSection = 'camara';
let _keydownBound = false;

export async function initSettings() {
  setOnSectionSaved((sectionKey, freshFields, requiresRestart) => {
    _mergeFreshFields(sectionKey, freshFields);
    _refreshTreeDirtyDots();
    if (sectionKey === _activeSection) _openSection(sectionKey, requiresRestart ?? []);
  });
  await _loadSchema();
  _bootFromHashOrDefault();
}

async function _loadSchema() {
  _renderSkeleton();
  try {
    const res = await fetch('/api/v2/config');
    if (!res.ok) throw new Error(String(res.status));
    _schema = await res.json();
    _renderTree();
  } catch {
    _renderLoadError();
  }
}

function _bootFromHashOrDefault() {
  const hashSection = _sectionFromHash();
  _openSection(hashSection || 'camara');
}

function _tree() {
  return document.getElementById('settings-tree');
}

function _sections() {
  return _schema?.sections ?? [];
}

function _sectionForKey(key) {
  return _sections().find((s) => s.key === key) ?? null;
}

// Un hash de sección desconocida (o sin esquema cargado todavía) cae en null -> 'camara'.
function _sectionFromHash() {
  const m = /^#ajustes\/(.+)$/.exec(location.hash);
  if (!m) return null;
  const key = decodeURIComponent(m[1]);
  return _sectionForKey(key) ? key : null;
}

function _renderSkeleton() {
  const tree = _tree();
  if (!tree) return;
  tree.replaceChildren();
  for (let i = 0; i < SECTION_SKELETON_ROWS; i++) {
    const row = document.createElement('div');
    row.className = 'cfg-node animate-pulse';
    tree.appendChild(row);
  }
}

function _renderLoadError() {
  const tree = _tree();
  if (!tree) return;
  tree.replaceChildren();
  const msg = document.createElement('p');
  msg.className = 'text-sm text-slate-400 px-1';
  msg.textContent = 'No se pudo cargar la configuración.';
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'filter-chip mt-2';
  retry.textContent = 'Reintentar carga';
  retry.addEventListener('click', async () => {
    await _loadSchema();
    _bootFromHashOrDefault();
  });
  tree.append(msg, retry);
}

function _renderTree() {
  const tree = _tree();
  if (!tree) return;
  tree.replaceChildren();
  tree.setAttribute('role', 'tablist');
  tree.setAttribute('aria-orientation', 'vertical');
  for (const section of _sections()) {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'cfg-node w-full';
    tab.setAttribute('role', 'tab');
    tab.dataset.sectionKey = section.key;
    const active = section.key === _activeSection;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    const label = document.createElement('span');
    label.className = 'flex-1 text-left truncate';
    label.textContent = section.label;   // servidor -> textContent, nunca innerHTML
    tab.appendChild(label);
    tab.addEventListener('click', () => _openSection(section.key));
    tree.appendChild(tab);
  }
  if (!_keydownBound) {
    tree.addEventListener('keydown', _onTreeKeydown);
    _keydownBound = true;
  }
  _refreshTreeDirtyDots();
}

// Navegacion ARIA tab estandar, un unico listener delegado en el contenedor: las flechas
// mueven el foco sin activar la seccion, Enter/Space activa la pestana enfocada -- mismo
// mecanismo que el tablist horizontal de vistas de la Fase 31, aplicado en vertical.
function _onTreeKeydown(e) {
  const tabs = [...(_tree()?.querySelectorAll('[role="tab"]') ?? [])];
  if (tabs.length === 0) return;
  const idx = tabs.findIndex((t) => t === document.activeElement);
  if (e.key === 'Enter' || e.key === ' ') {
    if (idx < 0) return;
    e.preventDefault();
    _openSection(tabs[idx].dataset.sectionKey);
    return;
  }
  let next = -1;
  if (e.key === 'ArrowDown') next = idx < 0 ? 0 : (idx + 1) % tabs.length;
  else if (e.key === 'ArrowUp') next = idx < 0 ? tabs.length - 1 : (idx - 1 + tabs.length) % tabs.length;
  else if (e.key === 'Home') next = 0;
  else if (e.key === 'End') next = tabs.length - 1;
  if (next < 0) return;
  e.preventDefault();
  for (const t of tabs) t.tabIndex = -1;
  tabs[next].tabIndex = 0;
  tabs[next].focus();
}

function _openSection(key, requiresRestart = []) {
  const section = _sectionForKey(key);
  if (!section) return;
  _activeSection = key;
  for (const tab of _tree()?.querySelectorAll('[role="tab"]') ?? []) {
    const active = tab.dataset.sectionKey === key;
    tab.setAttribute('aria-selected', String(active));
    tab.setAttribute('aria-current', String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  renderSection(section, key, requiresRestart);
  history.replaceState(null, '', `#ajustes/${key}`);
}

// Se recalcula tras cada saveSection/discardChanges exitoso -- el callback vive aqui,
// no en 32-05, porque settings-save.js no conoce el arbol (isDirty ya lo expone).
function _refreshTreeDirtyDots() {
  const tree = _tree();
  if (!tree) return;
  for (const tab of tree.querySelectorAll('[role="tab"]')) {
    const dirty = isDirty(tab.dataset.sectionKey);
    let dot = tab.querySelector('.cfg-node-dot');
    if (dirty && !dot) {
      dot = document.createElement('span');
      dot.className = 'cfg-node-dot ml-auto';
      tab.appendChild(dot);
    } else if (!dirty && dot) {
      dot.remove();
    }
  }
}

// data.fields de saveSection/restoreSection (32-02: _section_fields_payload) es una lista
// PLANA de payloads de campo -- se reinyecta por key en los grupos del esquema en memoria
// para que el repintado tras guardar/restaurar no revierta visualmente los valores que el
// servidor acaba de confirmar (badges de origen/aplicación incluidos).
function _mergeFreshFields(sectionKey, freshFields) {
  if (!freshFields) return;
  const section = _sectionForKey(sectionKey);
  if (!section) return;
  const byKey = new Map(freshFields.map((f) => [f.key, f]));
  for (const group of section.groups) {
    if (!group.fields?.length) continue;
    group.fields = group.fields.map((f) => byKey.get(f.key) ?? f);
  }
}
