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

// ── Tracks overlay canvas (OPS-05) ─────────────────────
// D-09: colores del semáforo de identidad, 2px, sin esquinas redondeadas.
const STATE_COLOR = {
  CONFIRMED: '#22c55e',
  CANDIDATE: '#f59e0b',
  UNKNOWN: '#ef4444',
  TEMPORARILY_LOST: '#ef4444',
};

function syncCanvasToImage(canvas, img) {
  const rect = img.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;
}

// D-06/Pitfall 1: object-fit:cover recorta el frame fuente para llenar la
// caja mostrada — hay que deshacer ese recorte con scale=max()+offset centrado,
// usando naturalWidth/naturalHeight (resolución intrínseca), nunca width/height
// (esos reflejan el tamaño mostrado, no el fuente — ver Anti-Patterns).
function normalizedBoxToCanvasRect(box, img, canvas) {
  const iw = img.naturalWidth, ih = img.naturalHeight;
  const cw = canvas.width, ch = canvas.height;
  if (!iw || !ih || !cw || !ch) return null;
  const scale = Math.max(cw / iw, ch / ih);
  const drawW = iw * scale, drawH = ih * scale;
  const offsetX = (cw - drawW) / 2;
  const offsetY = (ch - drawH) / 2;
  const [x1, y1, x2, y2] = box;
  return {
    x: offsetX + x1 * iw * scale,
    y: offsetY + y1 * ih * scale,
    w: (x2 - x1) * iw * scale,
    h: (y2 - y1) * ih * scale,
  };
}

// D-07/Pitfall 5: redibuja SOLO cuando se le llama (mensaje 'tracks' a 2Hz) —
// nunca requestAnimationFrame ni temporizador propio en este módulo.
export function drawTracks(tracks) {
  const canvas = document.getElementById('tracks-overlay');
  const img = document.getElementById('video-feed');
  if (!canvas || !img) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  (tracks || []).forEach(t => {
    const rect = normalizedBoxToCanvasRect(t.bbox, img, canvas);
    if (!rect) return;
    const color = STATE_COLOR[t.identity_state] || STATE_COLOR.UNKNOWN;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

    const label = t.person_name || 'Desconocido';
    ctx.font = '11px "JetBrains Mono", monospace';
    const textW = ctx.measureText(label).width;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(rect.x, Math.max(0, rect.y - 16), textW + 8, 16);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText(label, rect.x + 4, Math.max(11, rect.y - 4));
  });
}

let _tracksResizeObserver = null;
export function initTracksOverlay() {
  const canvas = document.getElementById('tracks-overlay');
  const img = document.getElementById('video-feed');
  if (!canvas || !img || _tracksResizeObserver) return;
  syncCanvasToImage(canvas, img);
  _tracksResizeObserver = new ResizeObserver(() => syncCanvasToImage(canvas, img));
  _tracksResizeObserver.observe(img);
}
