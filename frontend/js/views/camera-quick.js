// frontend/js/views/camera-quick.js
//
// Fase 32 (OPS-17): barra de "Ajustes rapidos" bajo el video de la vista Camara.
// Cuatro controles independientes que escriben SIEMPRE contra el mismo
// PUT /api/v2/config del arbol de Ajustes (32-02) -- no hay endpoint paralelo ni
// almacen paralelo. Cada bindQuick* sigue el molde de
// detectionClasses.js::saveDetectionClasses: deshabilita su propio control mientras
// el PUT esta en vuelo, repinta el badge de aplicacion desde la respuesta del
// servidor en exito, y en error revierte al valor real via GET /api/v2/config +
// showToast('error') -- nunca deja el control en un valor optimista sin confirmar
// (T-32-14).
//
// Contrato de ids consumido por 32-07 (definido en esta plan, documentado en
// 32-04-SUMMARY.md porque 32-UI-SPEC.md no fija ids literales para la barra):
//   #quick-classes            contenedor de .quick-class-checkbox[data-class-id]
//   #quick-classes-badge      badge de aplicacion del control de clases
//   #quick-resolution         <select> con option value "ANCHOxALTO", ej. "1280x720"
//   #quick-resolution-badge
//   #quick-confidence         <input type="range"> 0.05-0.95 paso 0.05
//   #quick-confidence-value   texto del valor actual
//   #quick-confidence-badge
//   #quick-severity           <select> con option value info|warning|critical
//   #quick-severity-badge
//
// Todos los getElementById usan encadenamiento opcional: si 32-07 aun no ha creado
// estos ids en el DOM, initCameraQuick() no lanza (mismo criterio que camera.js).

import { showToast } from './dashboard.js';

const APPLIES_LABEL = {
  hot: 'En caliente',
  restart_camera: 'Requiere reinicio',
  restart_server: 'Reinicio del servidor',
};

function _paintBadge(id, applies) {
  const el = document.getElementById(id);
  if (el) el.textContent = APPLIES_LABEL[applies] ?? '';
}

function _findField(cfg, key) {
  for (const section of cfg.sections ?? []) {
    for (const group of section.groups ?? []) {
      const f = (group.fields ?? []).find((field) => field.key === key);
      if (f) return f;
    }
  }
  return null;
}

async function _putConfig(section, changes) {
  return fetch('/api/v2/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ section, changes }),
  });
}

async function _handleError(res, revert) {
  let msg = 'No se pudo guardar el ajuste.';
  if (res.status === 422) {
    const d = await res.json().catch(() => ({}));
    const first = d.detail?.errors?.[0];
    if (first) msg = first.message;
  }
  showToast(msg, 'error');
  await revert();
}

async function _loadConfig() {
  return fetch('/api/v2/config').then((r) => (r.ok ? r.json() : null)).catch(() => null);
}

// ── Clases detectadas ─────────────────────────────────────────────
export function bindQuickClasses() {
  const container = document.getElementById('quick-classes');
  if (!container) return;
  container.querySelectorAll('.quick-class-checkbox').forEach((cb) => {
    cb.addEventListener('change', onQuickClassesChange);
  });
}

async function onQuickClassesChange() {
  const checkboxes = document.querySelectorAll('#quick-classes .quick-class-checkbox');
  const classes = Array.from(checkboxes)
    .filter((cb) => cb.checked)
    .map((cb) => parseInt(cb.dataset.classId, 10));
  checkboxes.forEach((cb) => { cb.disabled = true; });
  try {
    const res = await _putConfig('deteccion', { yolo_classes: classes });
    if (res.ok) {
      const data = await res.json();
      const f = data.fields.find((field) => field.key === 'yolo_classes');
      if (f) _paintBadge('quick-classes-badge', f.applies);
    } else {
      await _handleError(res, reloadQuickClasses);
    }
  } catch {
    await _handleError({ status: 0 }, reloadQuickClasses);
  } finally {
    checkboxes.forEach((cb) => { cb.disabled = false; });
  }
}

async function reloadQuickClasses() {
  const cfg = await _loadConfig();
  const f = cfg && _findField(cfg, 'yolo_classes');
  if (!f) return;
  const active = new Set(f.value ?? []);
  document.querySelectorAll('#quick-classes .quick-class-checkbox').forEach((cb) => {
    cb.checked = active.has(parseInt(cb.dataset.classId, 10));
  });
}

// ── Resolucion de proceso ─────────────────────────────────────────
export function bindQuickResolution() {
  document.getElementById('quick-resolution')?.addEventListener('change', onQuickResolutionChange);
}

async function onQuickResolutionChange(e) {
  const select = e.target;
  const [w, h] = select.value.split('x').map((n) => parseInt(n, 10));
  select.disabled = true;
  try {
    const res = await _putConfig('camara', { process_width: w, process_height: h });
    if (res.ok) {
      const data = await res.json();
      const f = data.fields.find((field) => field.key === 'process_width');
      if (f) _paintBadge('quick-resolution-badge', f.applies);
    } else {
      await _handleError(res, reloadQuickResolution);
    }
  } catch {
    await _handleError({ status: 0 }, reloadQuickResolution);
  } finally {
    select.disabled = false;
  }
}

async function reloadQuickResolution() {
  const cfg = await _loadConfig();
  if (!cfg) return;
  const w = _findField(cfg, 'process_width');
  const h = _findField(cfg, 'process_height');
  const select = document.getElementById('quick-resolution');
  if (select && w && h) select.value = `${w.value}x${h.value}`;
}

// ── Confianza de deteccion (debounce 600ms) ───────────────────────
let _confidenceTimer = null;

export function bindQuickConfidence() {
  document.getElementById('quick-confidence')?.addEventListener('input', onQuickConfidenceInput);
}

function onQuickConfidenceInput(e) {
  const value = parseFloat(e.target.value);
  const valueEl = document.getElementById('quick-confidence-value');
  if (valueEl) valueEl.textContent = value.toFixed(2);
  clearTimeout(_confidenceTimer);
  _confidenceTimer = setTimeout(() => saveQuickConfidence(value), 600);
}

async function saveQuickConfidence(value) {
  const slider = document.getElementById('quick-confidence');
  if (slider) slider.disabled = true;
  try {
    const res = await _putConfig('deteccion', { yolo_confidence: value });
    if (res.ok) {
      const data = await res.json();
      const f = data.fields.find((field) => field.key === 'yolo_confidence');
      if (f) _paintBadge('quick-confidence-badge', f.applies);
    } else {
      await _handleError(res, reloadQuickConfidence);
    }
  } catch {
    await _handleError({ status: 0 }, reloadQuickConfidence);
  } finally {
    if (slider) slider.disabled = false;
  }
}

async function reloadQuickConfidence() {
  const cfg = await _loadConfig();
  const f = cfg && _findField(cfg, 'yolo_confidence');
  if (!f) return;
  const slider = document.getElementById('quick-confidence');
  const valueEl = document.getElementById('quick-confidence-value');
  if (slider) slider.value = f.value;
  if (valueEl) valueEl.textContent = Number(f.value).toFixed(2);
}

// ── Severidad minima de subida a Drive ────────────────────────────
export function bindQuickSeverity() {
  document.getElementById('quick-severity')?.addEventListener('change', onQuickSeverityChange);
}

async function onQuickSeverityChange(e) {
  const select = e.target;
  select.disabled = true;
  try {
    const res = await _putConfig('almacenamiento', { upload_min_severity: select.value });
    if (res.ok) {
      const data = await res.json();
      const f = data.fields.find((field) => field.key === 'upload_min_severity');
      if (f) _paintBadge('quick-severity-badge', f.applies);
    } else {
      await _handleError(res, reloadQuickSeverity);
    }
  } catch {
    await _handleError({ status: 0 }, reloadQuickSeverity);
  } finally {
    select.disabled = false;
  }
}

async function reloadQuickSeverity() {
  const cfg = await _loadConfig();
  const f = cfg && _findField(cfg, 'upload_min_severity');
  const select = document.getElementById('quick-severity');
  if (select && f) select.value = f.value;
}

/**
 * Enlaza los 4 controles y hace una carga inicial de sus valores reales desde
 * GET /api/v2/config (una sola llamada, sin negociar rangos ni pasos en el cliente)
 * para que no arranquen vacios.
 */
export async function initCameraQuick() {
  bindQuickClasses();
  bindQuickResolution();
  bindQuickConfidence();
  bindQuickSeverity();
  await Promise.all([
    reloadQuickClasses(),
    reloadQuickResolution(),
    reloadQuickConfidence(),
    reloadQuickSeverity(),
  ]);
}
