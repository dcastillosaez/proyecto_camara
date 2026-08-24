// frontend/js/views/settings-save.js
// Fase 32 (OPS-18/19/20, SET-03/SET-04): motor de guardado por seccion de la vista Ajustes.
// Diff en memoria (nunca en el DOM), PUT /api/v2/config, mapeo de errores 422 a filas y
// "Restaurar valores por defecto" con popover (nunca confirm(), D-07 de la Fase 30).
//
// Convencion de marcado que 32-06 (settings-section.js) debe respetar para que este modulo
// pueda localizar el DOM de una seccion solo con su sectionKey (contrato de <interfaces>: los
// exports no reciben nodos, solo strings):
//   - panel de seccion:      [data-cfg-section="<sectionKey>"] , con data-section-label="<label>"
//   - filas de campo:        .cfg-row[data-field-key] (ya las produce settings-field.js)
//   - boton "Guardar":       [data-cfg-action="save"]    dentro del panel
//   - boton "Restaurar":     [data-cfg-action="restore"] dentro del panel
//   - popover de restaurar (unico, fuera de los paneles): #restore-config-popover con
//     #restore-popover-title, #restore-popover-body, [data-restore-confirm], [data-restore-cancel]

import { setFieldError, clearFieldError, markFieldDirty } from './settings-field.js';
import { showToast } from './dashboard.js';

const _pending = new Map();     // sectionKey -> Map(fieldKey -> value)
let _onSectionSaved = null;     // callback(sectionKey, freshFields) inyectado por settings.js
let _restoreTarget = null;      // { sectionKey, count } | null -- nunca en el DOM

export function setOnSectionSaved(cb) {
  _onSectionSaved = cb;
}

function _mapFor(sectionKey) {
  if (!_pending.has(sectionKey)) _pending.set(sectionKey, new Map());
  return _pending.get(sectionKey);
}

export function trackChange(sectionKey, fieldKey, value) {
  _mapFor(sectionKey).set(fieldKey, value);
}

export function pendingCount(sectionKey) {
  return _pending.get(sectionKey)?.size ?? 0;
}

export function discardChanges(sectionKey) {
  _pending.delete(sectionKey);
}

export function isDirty(sectionKey) {
  return pendingCount(sectionKey) > 0;
}

function _panel(sectionKey) {
  return document.querySelector(`[data-cfg-section="${sectionKey}"]`);
}

function _rowsOf(panel) {
  return panel ? [...panel.querySelectorAll('.cfg-row')] : [];
}

function _setBusy(panel, busy) {
  panel?.querySelector('[data-cfg-action="save"]')?.classList.toggle('busy', busy);
  for (const row of _rowsOf(panel)) {
    row.querySelectorAll('input, select, button').forEach((el) => { el.disabled = busy; });
  }
}

export async function saveSection(sectionKey) {
  const diff = _pending.get(sectionKey);
  if (!diff || diff.size === 0) return;
  const panel = _panel(sectionKey);
  const changes = Object.fromEntries(diff);

  _setBusy(panel, true);
  for (const row of _rowsOf(panel)) clearFieldError(row);

  let res;
  try {
    res = await fetch('/api/v2/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section: sectionKey, changes }),
    });
  } catch {
    _setBusy(panel, false);
    showToast('No se pudo guardar la configuración. Los cambios siguen aquí, inténtalo de nuevo.', 'error');
    return;
  }

  if (res.status === 422) {
    _setBusy(panel, false);
    const body = await res.json().catch(() => ({}));
    const errors = body.detail?.errors ?? body.errors ?? [];
    let firstErrorRow = null;
    for (const err of errors) {
      const row = panel?.querySelector(`.cfg-row[data-field-key="${err.field}"]`);
      if (!row) continue;
      setFieldError(row, err.message);
      if (!firstErrorRow) firstErrorRow = row;
    }
    // Las filas sin error entre los cambios pendientes NO se tocan: siguen .dirty (D-10).
    firstErrorRow?.scrollIntoView({ block: 'center' });
    firstErrorRow?.querySelector('input, select, .cam-toggle')?.focus();
    return;
  }

  if (!res.ok) {
    _setBusy(panel, false);
    showToast('No se pudo guardar la configuración. Los cambios siguen aquí, inténtalo de nuevo.', 'error');
    return;
  }

  const data = await res.json();
  _setBusy(panel, false);
  const savedCount = Object.keys(changes).length;
  discardChanges(sectionKey);
  for (const row of _rowsOf(panel)) markFieldDirty(row, false);
  _onSectionSaved?.(sectionKey, data.fields);
  const msg = (data.requires_restart?.length ?? 0) > 0
    ? `Configuración guardada. ${savedCount} valores se aplicarán al reiniciar.`
    : `Configuración guardada. ${savedCount} valores actualizados.`;
  showToast(msg, 'success');
}

// ── Restaurar valores por defecto: popover, nunca confirm() (D-07) ─────────────────────
function _closeRestorePopover() {
  _restoreTarget = null;
  document.getElementById('restore-config-popover')?.classList.remove('open');
}

function _openRestorePopover(sectionKey, sectionLabel, count) {
  const pop = document.getElementById('restore-config-popover');
  const title = document.getElementById('restore-popover-title');
  const body = document.getElementById('restore-popover-body');
  const confirmBtn = pop?.querySelector('[data-restore-confirm]');
  if (!pop || !title || !body || !confirmBtn) return;   // 32-06 aun no monto el popover
  _restoreTarget = { sectionKey, count };
  title.textContent = `Restaurar «${sectionLabel}»`;
  body.textContent = `Se borrarán ${count} valores personalizados. Los que vinieran del `
    + 'fichero .env volverán a su valor de .env; el resto, al del código. No se puede deshacer.';
  confirmBtn.textContent = `Restaurar ${count} valores`;
  pop.classList.add('open');
  confirmBtn.focus();
}

export async function restoreSection(sectionKey, fieldCountRuntime) {
  if (!fieldCountRuntime) {
    const btn = _panel(sectionKey)?.querySelector('[data-cfg-action="restore"]');
    if (btn) btn.title = 'Esta sección no tiene ningún valor personalizado.';
    return;
  }
  const label = _panel(sectionKey)?.dataset.sectionLabel ?? sectionKey;
  _openRestorePopover(sectionKey, label, fieldCountRuntime);
}

async function _confirmRestore() {
  const target = _restoreTarget;
  _closeRestorePopover();
  if (!target) return;
  const panel = _panel(target.sectionKey);
  try {
    const res = await fetch(`/api/v2/config/${target.sectionKey}/restore`, { method: 'POST' });
    if (!res.ok) throw new Error('restore failed');
    const data = await res.json();
    discardChanges(target.sectionKey);
    for (const row of _rowsOf(panel)) markFieldDirty(row, false);
    _onSectionSaved?.(target.sectionKey, data.fields);
    showToast(`«${panel?.dataset.sectionLabel ?? target.sectionKey}» restaurada. `
      + `${data.restored_count} valores devueltos a su origen.`, 'success');
  } catch {
    showToast('No se pudo restaurar la sección. Inténtalo de nuevo.', 'error');
  }
}

document.addEventListener('click', (e) => {
  const pop = document.getElementById('restore-config-popover');
  if (!pop || !pop.classList.contains('open')) return;
  if (e.target.closest('[data-restore-confirm]')) { _confirmRestore(); return; }
  if (e.target.closest('[data-restore-cancel]')) { _closeRestorePopover(); return; }
  if (!e.target.closest('#restore-config-popover, [data-cfg-action="restore"]')) _closeRestorePopover();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && _restoreTarget) _closeRestorePopover();
});
