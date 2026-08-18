// frontend/js/views/dashboard-ptz.js
import { showToast } from './dashboard.js';

// ── PTZ: steps slider ────────────────────────────────
const stepsInput = document.getElementById('ptz-steps');
const stepsLabel = document.getElementById('ptz-steps-val');
stepsInput.addEventListener('input', () => { stepsLabel.textContent = stepsInput.value; });

// ── PTZ: move ────────────────────────────────────────
async function ptzMove(dir) {
  const steps = parseInt(stepsInput.value, 10);
  const btn   = document.querySelector(`.ptz-btn[data-dir="${dir}"]`);
  if (btn) btn.classList.add('busy');
  try {
    const res = await fetch('/ptz/move', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ direction: dir, steps }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      showToast(`PTZ: ${err.detail ?? res.statusText}`, 'error');
    }
  } catch (e) {
    showToast(`PTZ sin respuesta: ${e.message}`, 'error');
  } finally {
    if (btn) btn.classList.remove('busy');
  }
}

// ── PTZ: stop ────────────────────────────────────────
async function ptzStop() {
  try {
    const res = await fetch('/ptz/stop', { method: 'POST' });
    if (res.ok) showToast('Movimiento detenido', 'info');
    else showToast('Error al detener la cámara', 'error');
  } catch {
    showToast('Sin respuesta del servidor PTZ', 'error');
  }
}

// ── PTZ: presets ─────────────────────────────────────
export async function loadPresets() {
  const container = document.getElementById('presets-container');
  container.innerHTML = '<span class="text-xs text-slate-700 italic">Cargando…</span>';
  try {
    const res = await fetch('/ptz/presets');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data    = await res.json();
    const entries = Object.entries(data ?? {});
    if (!entries.length) {
      container.innerHTML = '<span class="text-xs text-slate-700 italic">Sin presets guardados en la cámara</span>';
      return;
    }
    container.innerHTML = '';
    entries.forEach(([id, name]) => {
      const btn = document.createElement('button');
      btn.className = 'preset-btn';
      btn.textContent = name || `Preset ${id}`;
      btn.setAttribute('aria-label', `Ir al preset: ${name || id}`);
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.style.opacity = '0.5';
        try {
          const r = await fetch(`/ptz/preset/${id}`, { method: 'POST' });
          if (r.ok) showToast(`Preset "${name || id}" activado`, 'success');
          else showToast('Error al activar preset', 'error');
        } catch { showToast('Sin respuesta del servidor', 'error'); }
        finally { btn.disabled = false; btn.style.opacity = ''; }
      });
      container.appendChild(btn);
    });
  } catch {
    container.innerHTML = '<span class="text-xs text-slate-600 italic">No se pudo conectar con la cámara</span>';
  }
}

export function bindPtzControls() {
  document.querySelectorAll('.ptz-btn[data-dir]').forEach(btn =>
    btn.addEventListener('click', () => ptzMove(btn.dataset.dir))
  );
  document.getElementById('ptz-stop-btn').addEventListener('click', ptzStop);

  document.addEventListener('keydown', e => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    const dirMap = { ArrowUp:'up', ArrowDown:'down', ArrowLeft:'left', ArrowRight:'right' };
    if (dirMap[e.key]) { e.preventDefault(); ptzMove(dirMap[e.key]); }
    if (e.key === ' ')  { e.preventDefault(); ptzStop(); }
  });

  document.getElementById('load-presets-btn').addEventListener('click', loadPresets);
  loadPresets();

  document.getElementById('save-preset-btn').addEventListener('click', async () => {
    const input = document.getElementById('preset-name-input');
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    const btn = document.getElementById('save-preset-btn');
    btn.disabled = true; btn.style.opacity = '0.5';
    try {
      const res = await fetch('/ptz/save_preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (res.ok) {
        showToast(`Preset "${name}" guardado`, 'success');
        input.value = '';
        loadPresets();
      } else {
        const d = await res.json().catch(() => ({}));
        showToast(d.detail ?? 'Error al guardar preset', 'error');
      }
    } catch { showToast('Sin respuesta del servidor', 'error'); }
    finally { btn.disabled = false; btn.style.opacity = ''; }
  });
}
