// frontend/js/components/videoCanvas.js
import { showToast } from '../views/dashboard.js';

export function setRecBadge(visible, count) {
  const badge = document.getElementById('rec-badge');
  badge.classList.toggle('hidden', !visible);
  if (count != null) badge.textContent = count;
}

export function setResolutionBadge(text) {
  const badge = document.getElementById('res-badge');
  badge.textContent = text;
  badge.style.display = text ? 'block' : 'none';
}

// ── Resolution dropdown ────────────────────────────────
export async function loadResolutions() {
  try {
    const res = await fetch('/camera/resolutions');
    if (!res.ok) return;
    const data = await res.json();
    const sel  = document.getElementById('resolution-select');
    sel.innerHTML = '';
    data.options.forEach(opt => {
      const el = document.createElement('option');
      el.value = `${opt.width},${opt.height}`;
      el.textContent = opt.label;
      if (opt.width === data.current.width && opt.height === data.current.height) el.selected = true;
      sel.appendChild(el);
    });
    if (data.current.width > 0) {
      setResolutionBadge(`${data.current.width}×${data.current.height}`);
      const img = document.getElementById('video-feed');
      img.style.imageRendering = data.current.width <= 640 ? 'pixelated' : 'auto';
    }
  } catch {}
}

document.getElementById('resolution-select').addEventListener('change', async (e) => {
  const [w, h] = e.target.value.split(',').map(Number);
  const sel = e.target;
  sel.disabled = true;
  try {
    const res = await fetch('/camera/resolution', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ width: w, height: h }),
    });
    if (res.ok) {
      const d = await res.json();
      showToast(`Resolución → ${d.resolution}`, 'success');
      setResolutionBadge(d.resolution);
      const img = document.getElementById('video-feed');
      img.src = '/video_feed?t=' + Date.now();
      img.style.imageRendering = (w > 0 && w <= 640) ? 'pixelated' : 'auto';
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(`Error: ${err.detail ?? 'desconocido'}`, 'error');
    }
  } catch (ex) {
    showToast(`Sin respuesta: ${ex.message}`, 'error');
  } finally {
    sel.disabled = false;
  }
});
