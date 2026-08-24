// frontend/js/components/zoneEditor.js
// Fase 33 (OPS-21/OPS-23): editor visual de zonas sobre <canvas>, sustituye al
// formulario JSON de /api/zones v1. CRUD exclusivamente contra /api/v2/zones (D-02);
// coordenadas siempre en fraccion [0,1] (canvasClickToFrac, D-06 33-RESEARCH.md).
//
// Contrato de ids que el Plan 33-13 debe crear en index.html, tabpanel Camara:
// #zone-line-canvas (sobre #camera-feed) #zone-mode-toggle (activa captura de clicks)
// #zone-list (click en nombre = editar) #zone-new-btn #zone-form-kind (select)
// #zone-kind-locked-label (texto si kind=exclude_objects) #zone-form-days (chips 0-6)
// #zone-form-time-start / #zone-form-time-end #zone-save-btn #zone-cancel-btn #zone-error
//
// initZoneEditor() la llama initCamera() (Plan 33-13), mismo patron que initSettings().

import { showToast } from '../views/dashboard.js';
import { canvasClickToFrac, syncCanvasToImage } from './videoCanvas.js';

const WEEKDAY_LABELS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
const VERTEX_RADIUS = 5;
const HIT_RADIUS = 8;
const KIND_VALUES = ['counting', 'restricted', 'exclusion'];

let _canvas = null;
let _img = null;
let _editMode = false;
let _zonesLoaded = false;
// Trazado en curso ({x_frac,y_frac}[], se conserva tras un 422); id/kind en edicion.
let _polygonPoints = [];
let _draggingIndex = -1;
let _editingZoneId = null; // null = zona nueva
let _lockedKind = null; // kind heredado (exclude_objects) que no se puede tocar

function _byId(id) { return document.getElementById(id); }

function _canvasPos(evt) {
  const rect = _canvas.getBoundingClientRect();
  return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
}

// Inversa aproximada de canvasClickToFrac (naturalWidth/Height, nunca width/height).
function _fracToCanvasPx(pt) {
  const iw = _img.naturalWidth, ih = _img.naturalHeight;
  const cw = _canvas.width, ch = _canvas.height;
  if (!iw || !ih || !cw || !ch) return null;
  const scale = Math.max(cw / iw, ch / ih);
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2, offsetY = (ch - drawH) / 2;
  return { x: offsetX + pt.x_frac * drawW, y: offsetY + pt.y_frac * drawH };
}
function _hitTestVertex(x, y) {
  for (let i = 0; i < _polygonPoints.length; i++) {
    const px = _fracToCanvasPx(_polygonPoints[i]);
    if (px && Math.hypot(px.x - x, px.y - y) <= HIT_RADIUS) return i;
  }
  return -1;
}
function _redraw() {
  if (!_canvas) return;
  const ctx = _canvas.getContext('2d');
  ctx.clearRect(0, 0, _canvas.width, _canvas.height);
  const pxPoints = _polygonPoints.map(_fracToCanvasPx).filter(Boolean);
  if (pxPoints.length === 0) return;
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pxPoints[0].x, pxPoints[0].y);
  for (let i = 1; i < pxPoints.length; i++) ctx.lineTo(pxPoints[i].x, pxPoints[i].y);
  if (pxPoints.length >= 3) ctx.closePath();
  ctx.stroke();
  pxPoints.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, VERTEX_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = i === _draggingIndex ? '#f59e0b' : '#3b82f6';
    ctx.fill();
  });
}
function _onMouseDown(evt) {
  if (!_editMode) return;
  const { x, y } = _canvasPos(evt);
  const hit = _hitTestVertex(x, y);
  if (hit !== -1) { _draggingIndex = hit; return; }
  const frac = canvasClickToFrac(x, y, _img, _canvas);
  if (!frac) return;
  _polygonPoints.push(frac);
  _redraw();
}
function _onMouseMove(evt) {
  if (!_editMode || _draggingIndex === -1) return;
  const { x, y } = _canvasPos(evt);
  const frac = canvasClickToFrac(x, y, _img, _canvas);
  if (!frac) return;
  _polygonPoints[_draggingIndex] = frac;
  _redraw();
}
function _applyKindLock(kind) {
  _lockedKind = kind === 'exclude_objects' ? kind : null;
  const sel = _byId('zone-form-kind');
  if (sel) { sel.disabled = !!_lockedKind; if (!_lockedKind) sel.value = kind ?? KIND_VALUES[0]; }
  const label = _byId('zone-kind-locked-label');
  if (label) label.textContent = _lockedKind ? 'Exclusión de objetos — heredado de la Fase 27' : '';
}
function _clearForm() {
  _polygonPoints = [];
  _draggingIndex = -1;
  _editingZoneId = null;
  _applyKindLock(null);
  const errEl = _byId('zone-error');
  if (errEl) errEl.classList.add('hidden');
  _byId('zone-form-days')?.querySelectorAll('[aria-pressed]').forEach((chip) => {
    chip.setAttribute('aria-pressed', 'false');
    chip.classList.remove('active');
  });
  const startEl = _byId('zone-form-time-start');
  const endEl = _byId('zone-form-time-end');
  if (startEl) startEl.value = '';
  if (endEl) endEl.value = '';
  _redraw();
}

// Carga una zona existente (click en #zone-list) en el trazado/formulario en curso.
function _loadZoneIntoForm(z) {
  _editingZoneId = z.id;
  _polygonPoints = (z.polygon || []).map(([x, y]) => ({ x_frac: x, y_frac: y }));
  _draggingIndex = -1;
  _applyKindLock(z.kind);
  if (z.schedule) {
    const [start, end] = (z.schedule.time_range || '').split('-');
    if (_byId('zone-form-time-start')) _byId('zone-form-time-start').value = start ?? '';
    if (_byId('zone-form-time-end')) _byId('zone-form-time-end').value = end ?? '';
    const days = new Set(z.schedule.days ?? []);
    _byId('zone-form-days')?.querySelectorAll('[aria-pressed]').forEach((chip) => {
      const active = days.has(Number(chip.dataset.value));
      chip.setAttribute('aria-pressed', String(active));
      chip.classList.toggle('active', active);
    });
  }
  _redraw();
}
function _renderKindSelect() {
  const sel = _byId('zone-form-kind');
  if (!sel || sel.dataset.built) return;
  sel.dataset.built = '1';
  KIND_VALUES.forEach((v) => {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v;
    sel.appendChild(opt);
  });
}
function _renderDayChips() {
  const wrap = _byId('zone-form-days');
  if (!wrap || wrap.dataset.built) return;
  wrap.dataset.built = '1';
  WEEKDAY_LABELS.forEach((label, id) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip';
    chip.textContent = label;
    chip.dataset.value = String(id);
    chip.setAttribute('aria-pressed', 'false');
    chip.addEventListener('click', () => {
      const next = chip.getAttribute('aria-pressed') !== 'true';
      chip.setAttribute('aria-pressed', String(next));
      chip.classList.toggle('active', next);
    });
    wrap.appendChild(chip);
  });
}
function _showError(msg) {
  const el = _byId('zone-error');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}
function _buildSchedule() {
  const start = _byId('zone-form-time-start')?.value;
  const end = _byId('zone-form-time-end')?.value;
  const wrap = _byId('zone-form-days');
  const days = wrap ? [...wrap.querySelectorAll('[aria-pressed="true"]')].map((c) => Number(c.dataset.value)) : [];
  if (!start || !end || days.length === 0) return null;
  return { time_range: `${start}-${end}`, days };
}
async function _saveZone() {
  if (_polygonPoints.length < 3) {
    _showError('Poligono invalido: se necesitan al menos 3 vertices.');
    return;
  }
  const kindSel = _byId('zone-form-kind');
  const kind = _lockedKind ?? kindSel?.value ?? null;
  const body = {
    id: _editingZoneId ?? `zone-${Date.now()}`,
    name: _editingZoneId ?? `Zona ${new Date().toLocaleTimeString('es-ES', { hour12: false })}`,
    polygon: _polygonPoints.map((p) => [p.x_frac, p.y_frac]),
    kind,
    schedule: _buildSchedule(),
    enabled: true,
  };
  const btn = _byId('zone-save-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/v2/zones', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      showToast(`Zona "${body.name}" guardada`, 'success');
      _clearForm();
      await loadZones();
    } else if (res.status === 422) {
      const d = await res.json().catch(() => ({}));
      // Router de zonas (33-03): body param Pydantic tipado -> d.detail es el shape
      // NATIVO de FastAPI (lista de {loc,msg,type}), no {errors:[...]} de config/rules.
      _showError(Array.isArray(d.detail) ? d.detail.map((e) => e.msg).join(', ') : String(d.detail));
    } else {
      _showError('Error al guardar la zona.');
    }
  } catch {
    _showError('Sin respuesta del servidor.');
  } finally {
    if (btn) btn.disabled = false;
  }
}
async function _deleteZone(id, name) {
  if (!confirm(`¿Eliminar la zona "${name}"?`)) return;
  try {
    const r = await fetch(`/api/v2/zones/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (r.ok) { showToast(`Zona "${name}" eliminada`, 'info'); loadZones(); }
    else showToast('Error al eliminar zona', 'error');
  } catch { showToast('Sin respuesta', 'error'); }
}
export async function loadZones() {
  const list = _byId('zone-list');
  if (!list) return;
  try {
    const res = await fetch('/api/v2/zones');
    if (!res.ok) return;
    const data = await res.json();
    const zones = data.zones ?? [];
    list.querySelectorAll('.zone-row').forEach((el) => el.remove());
    zones.forEach((z) => {
      const row = document.createElement('div');
      row.className = 'zone-row flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700';
      const nameSpan = document.createElement('span');
      nameSpan.className = 'text-xs text-slate-200 truncate';
      nameSpan.textContent = z.name;
      const kindSpan = document.createElement('span');
      kindSpan.className = 'text-xs text-slate-600 mono';
      kindSpan.textContent = z.kind ?? '';
      const info = document.createElement('div');
      info.className = 'flex items-center gap-2 min-w-0 cursor-pointer';
      info.addEventListener('click', () => _loadZoneIntoForm(z));
      info.append(nameSpan, kindSpan);
      const delBtn = document.createElement('button');
      delBtn.className = 'btn-del-zone text-slate-600 hover:text-red-400 transition-colors cursor-pointer flex-shrink-0';
      delBtn.setAttribute('aria-label', `Eliminar zona ${z.name}`);
      delBtn.textContent = '✕';
      delBtn.addEventListener('click', () => _deleteZone(z.id, z.name));
      row.append(info, delBtn);
      list.appendChild(row);
    });
  } catch { /* la lista simplemente no se actualiza; sin ruido para el operador */ }
}
function _toggleEditMode() {
  _editMode = !_editMode;
  const toggle = _byId('zone-mode-toggle');
  if (toggle) toggle.setAttribute('aria-pressed', String(_editMode));
  if (_canvas) _canvas.classList.toggle('zone-editor-canvas', _editMode);
  if (_editMode && !_zonesLoaded) {
    _zonesLoaded = true;
    loadZones();
  }
}

// Punto de entrada unico (llamado por initCamera(), Plan 33-13). Solo engancha
// listeners: no dispara red hasta que el operador entra en modo edicion.
export function initZoneEditor() {
  _canvas = _byId('zone-line-canvas');
  _img = _byId('camera-feed');
  if (!_canvas || !_img) return;

  syncCanvasToImage(_canvas, _img);
  new ResizeObserver(() => { syncCanvasToImage(_canvas, _img); _redraw(); }).observe(_img);

  _canvas.addEventListener('mousedown', _onMouseDown);
  _canvas.addEventListener('mousemove', _onMouseMove);
  _canvas.addEventListener('mouseup', () => { _draggingIndex = -1; });
  // Doble click cierra el trazado (>=3 puntos) sin anadir un vertice extra en el punto.
  _canvas.addEventListener('dblclick', (evt) => { evt.preventDefault(); _redraw(); });

  _renderKindSelect();
  _renderDayChips();

  _byId('zone-mode-toggle')?.addEventListener('click', _toggleEditMode);
  _byId('zone-new-btn')?.addEventListener('click', _clearForm);
  _byId('zone-cancel-btn')?.addEventListener('click', _clearForm);
  _byId('zone-save-btn')?.addEventListener('click', _saveZone);
}
