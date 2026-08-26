// frontend/js/views/camera-mosaic.js
// Fase 36 (SCALE-06): vista mosaico de solo lectura -- N streams a la vez, sin editar
// zonas/lineas/reglas (eso sigue en el feed grande de camera.js, sobre la camara activa
// del selector). Alterna con #camera-single-left/#camera-single-right via #mosaic-toggle;
// clicar una tesela selecciona esa camara como activa (activeCamera.js) sin salir del
// mosaico -- para pasar al feed grande el operador desactiva "Vista mosaico".

import { setActiveCameraId } from '../components/activeCamera.js';

let _mosaicOn = false;

function _tile(camera) {
  const wrap = document.createElement('div');
  wrap.className = 'card bg-slate-900 border border-slate-800 rounded-xl overflow-hidden cursor-pointer';
  const img = document.createElement('img');
  img.src = `/video_feed?camera_id=${encodeURIComponent(camera.camera_id)}`;
  img.alt = `Stream de la cámara ${camera.camera_id}`;
  img.style.cssText = 'width:100%; aspect-ratio:16/9; object-fit:cover; display:block; background:#000';
  const label = document.createElement('div');
  label.className = 'px-2 py-1.5 flex items-center justify-between text-xs';
  const name = document.createElement('span');
  name.className = 'text-slate-300 truncate';
  name.textContent = camera.camera_id;
  const dot = document.createElement('span');
  dot.className = `w-2 h-2 rounded-full ${camera.connected ? 'bg-green-400' : 'bg-red-500'}`;
  label.append(name, dot);
  wrap.append(img, label);
  wrap.addEventListener('click', () => setActiveCameraId(camera.camera_id));
  return wrap;
}

async function _renderMosaic() {
  const grid = document.getElementById('camera-mosaic-grid');
  if (!grid) return;
  try {
    const res = await fetch('/api/v2/cameras');
    if (!res.ok) return;
    const data = await res.json();
    grid.replaceChildren(...data.cameras.map(_tile));
  } catch {
    // el grid se queda con lo ultimo que tenia pintado; sin ruido para el operador
  }
}

function _setMosaicVisible(on) {
  _mosaicOn = on;
  const grid = document.getElementById('camera-mosaic-grid');
  if (grid) grid.hidden = !on;
  const left = document.getElementById('camera-single-left');
  if (left) left.hidden = on;
  const right = document.getElementById('camera-single-right');
  if (right) right.hidden = on;
  document.getElementById('mosaic-toggle')?.setAttribute('aria-pressed', String(on));
  if (on) _renderMosaic();
}

export function initCameraMosaic() {
  document.getElementById('mosaic-toggle')?.addEventListener('click', () => _setMosaicVisible(!_mosaicOn));
}
