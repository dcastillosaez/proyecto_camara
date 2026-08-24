// frontend/js/components/lineEditor.js
// Fase 33 (OPS-22, D-01): editor visual de N lineas de conteo sobre <canvas>. CRUD
// exclusivamente contra /api/v2/lines (Plan 33-07). Coordenadas siempre en fraccion
// [0,1] (canvasClickToFrac, D-06 33-RESEARCH.md) — nunca pixeles absolutos.
//
// Contrato de ids que el Plan 33-13 debe crear en index.html, tabpanel Camara:
// #zone-line-canvas (MISMO canvas que zoneEditor.js, Plan 33-10 — un unico <canvas>
//   superpuesto a #camera-feed; el Plan 33-13 debe anadir un selector "Zonas"/"Lineas"
//   que active solo el _editMode de zoneEditor.js o el de este modulo a la vez, nunca
//   ambos simultaneamente, para que los clicks de raton no compitan entre modulos)
// #line-mode-toggle (activa captura de clicks en modo linea)
// #line-list (click en el nombre = editar) #line-new-btn #line-form-name
// #line-save-btn #line-cancel-btn #line-error
//
// initLineEditor() la llama initCamera() (Plan 33-13), mismo patron que initZoneEditor().
//
// Trazado: el 1er click fija el punto de inicio, el 2o fija el punto de fin (a
// diferencia de zoneEditor.js, que acumula N vertices). Mientras se traza, cada
// mousemove redibuja un segmento "fantasma" desde el inicio hasta el raton. Al
// completarse, un triangulo perpendicular al punto medio indica la direccion —
// convencion FIJA y arbitraria (lado "derecho" del vector start->end, rotacion de
// -90 grados con formula (dy,-dx) en coordenadas de canvas donde Y crece hacia abajo):
// es una ayuda visual para el operador, NO se valida contra el servidor ni se
// persiste como campo nuevo (sv.LineZone/PersonTracker deciden in/out por su cuenta,
// ver backend/tracker.py, Plan 33-04).

import { showToast } from '../views/dashboard.js';
import { canvasClickToFrac, syncCanvasToImage } from './videoCanvas.js';

const ARROW_LEN = 14;
const ARROW_HALF = 6;

let _canvas = null;
let _img = null;
let _editMode = false;
let _linesLoaded = false;
let _lines = []; // ultima lista cargada de /api/v2/lines, para redibujar todas
let _currentStart = null; // {x_frac,y_frac} o null
let _currentEnd = null;
let _ghostPx = null; // posicion del raton en px de canvas (segmento fantasma)
let _editingLineId = null; // null = linea nueva

function _byId(id) { return document.getElementById(id); }

function _canvasPos(evt) {
  const rect = _canvas.getBoundingClientRect();
  return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
}

// Inversa de canvasClickToFrac (naturalWidth/Height, nunca width/height) — misma
// formula que zoneEditor.js:_fracToCanvasPx, D-06.
function _fracToCanvasPx(pt) {
  const iw = _img.naturalWidth, ih = _img.naturalHeight;
  const cw = _canvas.width, ch = _canvas.height;
  if (!iw || !ih || !cw || !ch) return null;
  const scale = Math.max(cw / iw, ch / ih);
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2, offsetY = (ch - drawH) / 2;
  return { x: offsetX + pt.x_frac * drawW, y: offsetY + pt.y_frac * drawH };
}

// Triangulo (3 puntos) perpendicular al segmento s->e, apuntando hacia el lado
// "derecho" del vector s->e por convencion fija (ver cabecera). Solo dibuja: no es
// una validacion ni se envia al servidor.
function _arrowPoints(s, e) {
  const dx = e.x - s.x, dy = e.y - s.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const px = uy, py = -ux; // perpendicular, lado "derecho" del vector s->e
  const mx = (s.x + e.x) / 2, my = (s.y + e.y) / 2;
  return [
    { x: mx + px * ARROW_LEN, y: my + py * ARROW_LEN },
    { x: mx - ux * ARROW_HALF, y: my - uy * ARROW_HALF },
    { x: mx + ux * ARROW_HALF, y: my + uy * ARROW_HALF },
  ];
}

function _drawSegment(ctx, s, e, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(s.x, s.y);
  ctx.lineTo(e.x, e.y);
  ctx.stroke();
  const tri = _arrowPoints(s, e);
  ctx.beginPath();
  ctx.moveTo(tri[0].x, tri[0].y);
  ctx.lineTo(tri[1].x, tri[1].y);
  ctx.lineTo(tri[2].x, tri[2].y);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

function _redraw() {
  if (!_canvas) return;
  const ctx = _canvas.getContext('2d');
  ctx.clearRect(0, 0, _canvas.width, _canvas.height);
  _lines.forEach((l) => {
    const s = _fracToCanvasPx({ x_frac: l.start_x_frac, y_frac: l.start_y_frac });
    const e = _fracToCanvasPx({ x_frac: l.end_x_frac, y_frac: l.end_y_frac });
    if (s && e) _drawSegment(ctx, s, e, l.id === _editingLineId ? '#f59e0b' : '#22d3ee');
  });
  if (_currentStart) {
    const s = _fracToCanvasPx(_currentStart);
    const e = _currentEnd ? _fracToCanvasPx(_currentEnd) : _ghostPx;
    if (s && e) _drawSegment(ctx, s, e, '#3b82f6');
    else if (s) { ctx.beginPath(); ctx.arc(s.x, s.y, 4, 0, Math.PI * 2); ctx.fillStyle = '#3b82f6'; ctx.fill(); }
  }
}

function _onMouseDown(evt) {
  if (!_editMode) return;
  const { x, y } = _canvasPos(evt);
  const frac = canvasClickToFrac(x, y, _img, _canvas);
  if (!frac) return;
  if (_currentStart && _currentEnd) {
    // Trazado ya completo: un click nuevo empieza otra linea (descarta la anterior
    // en curso si no se guardo).
    _currentStart = frac;
    _currentEnd = null;
    _editingLineId = null;
  } else if (!_currentStart) {
    _currentStart = frac;
  } else {
    _currentEnd = frac;
  }
  _redraw();
}

function _onMouseMove(evt) {
  if (!_editMode || !_currentStart || _currentEnd) return;
  _ghostPx = _canvasPos(evt);
  _redraw();
}

function _clearForm() {
  _currentStart = null;
  _currentEnd = null;
  _ghostPx = null;
  _editingLineId = null;
  const nameEl = _byId('line-form-name');
  if (nameEl) nameEl.value = '';
  const errEl = _byId('line-error');
  if (errEl) errEl.classList.add('hidden');
  _redraw();
}

// Carga una linea existente (click en #line-list) en el trazado/formulario en curso.
function _loadLineIntoForm(l) {
  _editingLineId = l.id;
  _currentStart = { x_frac: l.start_x_frac, y_frac: l.start_y_frac };
  _currentEnd = { x_frac: l.end_x_frac, y_frac: l.end_y_frac };
  const nameEl = _byId('line-form-name');
  if (nameEl) nameEl.value = l.name ?? '';
  _redraw();
}

function _showError(msg) {
  const el = _byId('line-error');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}

async function _saveLine() {
  if (!_currentStart || !_currentEnd) {
    _showError('Traza una linea: dos clicks sobre el video (inicio y fin).');
    return;
  }
  const name = _byId('line-form-name')?.value?.trim()
    || `Linea ${new Date().toLocaleTimeString('es-ES', { hour12: false })}`;
  const body = {
    id: _editingLineId ?? `line-${Date.now()}`,
    name,
    start_x_frac: _currentStart.x_frac,
    start_y_frac: _currentStart.y_frac,
    end_x_frac: _currentEnd.x_frac,
    end_y_frac: _currentEnd.y_frac,
    enabled: true,
  };
  const btn = _byId('line-save-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/v2/lines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      showToast(`Linea "${body.name}" guardada`, 'success');
      _clearForm();
      await loadLines();
    } else if (res.status === 422) {
      const d = await res.json().catch(() => ({}));
      // Router de lineas (33-07): body param Pydantic tipado -> d.detail es el shape
      // NATIVO de FastAPI (lista de {loc,msg,type}), igual que zones.py (Plan 33-10).
      _showError(Array.isArray(d.detail) ? d.detail.map((e) => e.msg).join(', ') : String(d.detail));
    } else {
      _showError('Error al guardar la linea.');
    }
  } catch {
    _showError('Sin respuesta del servidor.');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _deleteLine(id, name) {
  if (!confirm(`¿Eliminar la línea "${name}"?`)) return;
  try {
    const r = await fetch(`/api/v2/lines/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (r.ok) { showToast(`Línea "${name}" eliminada`, 'info'); loadLines(); }
    else showToast('Error al eliminar línea', 'error');
  } catch { showToast('Sin respuesta', 'error'); }
}

export async function loadLines() {
  const list = _byId('line-list');
  try {
    const res = await fetch('/api/v2/lines');
    if (!res.ok) return;
    const data = await res.json();
    _lines = data.lines ?? [];
    if (list) {
      list.querySelectorAll('.line-row').forEach((el) => el.remove());
      _lines.forEach((l) => {
        const row = document.createElement('div');
        row.className = 'line-row flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700';
        const nameSpan = document.createElement('span');
        nameSpan.className = 'text-xs text-slate-200 truncate';
        nameSpan.textContent = l.name;
        const info = document.createElement('div');
        info.className = 'flex items-center gap-2 min-w-0 cursor-pointer';
        info.addEventListener('click', () => _loadLineIntoForm(l));
        info.append(nameSpan);
        const delBtn = document.createElement('button');
        delBtn.className = 'btn-del-line text-slate-600 hover:text-red-400 transition-colors cursor-pointer flex-shrink-0';
        delBtn.setAttribute('aria-label', `Eliminar línea ${l.name}`);
        delBtn.textContent = '✕';
        delBtn.addEventListener('click', () => _deleteLine(l.id, l.name));
        row.append(info, delBtn);
        list.appendChild(row);
      });
    }
    _redraw();
  } catch { /* la lista/canvas simplemente no se actualizan; sin ruido para el operador */ }
}

function _toggleEditMode() {
  _editMode = !_editMode;
  const toggle = _byId('line-mode-toggle');
  if (toggle) toggle.setAttribute('aria-pressed', String(_editMode));
  if (_canvas) _canvas.classList.toggle('zone-editor-canvas', _editMode);
  if (_editMode && !_linesLoaded) {
    _linesLoaded = true;
    loadLines();
  }
}

// Punto de entrada unico (llamado por initCamera(), Plan 33-13). Solo engancha
// listeners: no dispara red hasta que el operador entra en modo edicion.
export function initLineEditor() {
  _canvas = _byId('zone-line-canvas');
  _img = _byId('camera-feed');
  if (!_canvas || !_img) return;

  syncCanvasToImage(_canvas, _img);
  new ResizeObserver(() => { syncCanvasToImage(_canvas, _img); _redraw(); }).observe(_img);

  _canvas.addEventListener('mousedown', _onMouseDown);
  _canvas.addEventListener('mousemove', _onMouseMove);

  _byId('line-mode-toggle')?.addEventListener('click', _toggleEditMode);
  _byId('line-new-btn')?.addEventListener('click', _clearForm);
  _byId('line-cancel-btn')?.addEventListener('click', _clearForm);
  _byId('line-save-btn')?.addEventListener('click', _saveLine);
}
