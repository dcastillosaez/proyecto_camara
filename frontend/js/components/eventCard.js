// frontend/js/components/eventCard.js
import { showToast } from '../views/dashboard.js';

// ── Recordings panel ──────────────────────────────────
const STATUS_LABEL = { pending: 'Pendiente', uploading: 'Subiendo…', uploaded: 'Subido', failed: 'Error' };
const STATUS_COLOR = { pending: 'text-amber-400', uploading: 'text-blue-400', uploaded: 'text-green-400', failed: 'text-red-400' };

function _recRow(r) {
  const ts   = r.created_at ? new Date(r.created_at).toLocaleTimeString('es-ES', { hour12: false, hour: '2-digit', minute: '2-digit' }) : '—';
  const st   = r.upload_status ?? 'pending';
  const col  = STATUS_COLOR[st] ?? 'text-slate-400';
  const lbl  = STATUS_LABEL[st] ?? st;
  const row  = document.createElement('div');
  row.className = 'rec-row flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700';
  row.dataset.filename = r.filename;
  // r.filename/r.gdrive_id llegan del backend — se asignan via propiedades
  // del DOM (dataset/href/textContent), nunca interpolados en innerHTML,
  // para que un filename con marcado no se ejecute (CodeQL js/xss).
  row.innerHTML = `
    <div class="flex items-center gap-2 min-w-0">
      <button class="btn-play-clip flex-shrink-0 text-slate-500 hover:text-blue-400 transition-colors cursor-pointer" aria-label="Reproducir clip">
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      </button>
      <span class="rec-name text-xs text-slate-300 truncate max-w-[110px]"></span>
    </div>
    <div class="flex items-center gap-1 flex-shrink-0">
      <span class="rec-status text-xs ${col}"></span>
      <span class="text-slate-600 text-xs ml-1">${ts}</span>
    </div>`;
  row.querySelector('.btn-play-clip').dataset.src = `/clips/${r.filename}`;
  const nameSpan = row.querySelector('.rec-name');
  nameSpan.textContent = r.filename.replace('clip_', '');
  nameSpan.title = r.filename;
  row.querySelector('.rec-status').textContent = lbl;
  if (r.gdrive_id) {
    const link = document.createElement('a');
    link.href = `https://drive.google.com/file/d/${r.gdrive_id}/view`;
    link.target = '_blank'; link.rel = 'noopener';
    link.className = 'text-blue-400 hover:text-blue-300 text-xs ml-1';
    link.setAttribute('aria-label', 'Ver en Drive');
    link.textContent = '↗';
    row.querySelector('.rec-status').insertAdjacentElement('afterend', link);
  }
  return row;
}

export function addRecording(r) {
  const list  = document.getElementById('recordings-list');
  const empty = document.getElementById('recordings-empty');
  if (empty) empty.style.display = 'none';
  list.prepend(_recRow(r));
  while (list.querySelectorAll('.rec-row').length > 20) list.lastChild.remove();
  document.getElementById('recordings-count-badge').textContent = list.querySelectorAll('.rec-row').length;
}

export function updateRecordingStatus(filename, status, gdrive_id) {
  const row = document.querySelector(`.rec-row[data-filename="${filename}"]`);
  if (!row) return;
  const span = row.querySelector('.rec-status');
  if (span) {
    span.className = `rec-status text-xs ${STATUS_COLOR[status] ?? 'text-slate-400'}`;
    span.textContent = STATUS_LABEL[status] ?? status;
  }
  if (gdrive_id && !row.querySelector('a')) {
    const link = document.createElement('a');
    link.href = `https://drive.google.com/file/d/${gdrive_id}/view`;
    link.target = '_blank'; link.rel = 'noopener';
    link.className = 'text-blue-400 hover:text-blue-300 text-xs ml-1';
    link.textContent = '↗';
    span.insertAdjacentElement('afterend', link);
  }
}

export async function loadRecordings() {
  try {
    const res = await fetch('/api/recordings?limit=20');
    if (!res.ok) return;
    const data = await res.json();
    const recs = data.recordings ?? [];
    if (recs.length === 0) return;
    document.getElementById('recordings-empty').style.display = 'none';
    const list = document.getElementById('recordings-list');
    list.querySelectorAll('.rec-row').forEach(el => el.remove());
    recs.forEach(r => list.appendChild(_recRow(r)));
    // No usa setRecBadge (videoCanvas.js) a proposito: el original solo
    // actualiza el contador, nunca el estado visible/oculto del badge
    // (inconsistencia preexistente que esta fase preserva, ver read_first).
    document.getElementById('rec-badge').textContent = recs.length;
  } catch {}
}

// ── Recordings: delete by date range ─────────────────
const deleteRecPanel = document.getElementById('delete-recordings-panel');
const deleteRecMsg   = document.getElementById('delete-rec-msg');

// ── Phase 15: video player modal ──────────────────────────────────
export function openClipModal(src) {
  const modal = document.getElementById('clip-modal');
  const vid   = document.getElementById('clip-video');
  vid.src = src;
  modal.classList.add('open');
  vid.play().catch(() => {});
}

export function bindEventCardControls() {
  document.getElementById('btn-delete-recordings').addEventListener('click', () => {
    deleteRecMsg.classList.add('hidden');
    const now  = new Date();
    const week = new Date(now - 7 * 864e5);
    const fmt  = d => d.toISOString().slice(0, 16);
    document.getElementById('delete-rec-from').value = fmt(week);
    document.getElementById('delete-rec-to').value   = fmt(now);
    deleteRecPanel.classList.toggle('hidden');
  });

  document.getElementById('delete-rec-cancel').addEventListener('click', () => {
    deleteRecPanel.classList.add('hidden');
  });

  document.getElementById('delete-rec-confirm').addEventListener('click', async () => {
    const from = document.getElementById('delete-rec-from').value;
    const to   = document.getElementById('delete-rec-to').value;
    if (!from || !to) return;
    if (new Date(to) < new Date(from)) {
      deleteRecMsg.textContent = 'La fecha «Hasta» debe ser posterior a «Desde».';
      deleteRecMsg.className = 'text-xs text-center text-red-400';
      deleteRecMsg.classList.remove('hidden');
      return;
    }
    const btn = document.getElementById('delete-rec-confirm');
    btn.disabled = true; btn.style.opacity = '0.5';
    try {
      const params = new URLSearchParams({ from_dt: new Date(from).toISOString(), to_dt: new Date(to).toISOString() });
      const res = await fetch(`/api/recordings?${params}`, { method: 'DELETE' });
      if (res.ok) {
        const d = await res.json();
        deleteRecMsg.textContent = `${d.deleted} grabación(es) eliminada(s).`;
        deleteRecMsg.className = 'text-xs text-center text-green-400';
        deleteRecMsg.classList.remove('hidden');
        setTimeout(() => {
          deleteRecPanel.classList.add('hidden');
          document.getElementById('recordings-list').querySelectorAll('.rec-row').forEach(el => el.remove());
          document.getElementById('recordings-empty').style.display = '';
          document.getElementById('recordings-count-badge').textContent = '0';
          loadRecordings();
        }, 1500);
      } else {
        const d = await res.json().catch(() => ({}));
        deleteRecMsg.textContent = d.detail ?? 'Error al borrar.';
        deleteRecMsg.className = 'text-xs text-center text-red-400';
        deleteRecMsg.classList.remove('hidden');
      }
    } catch {
      deleteRecMsg.textContent = 'Sin respuesta.';
      deleteRecMsg.className = 'text-xs text-center text-red-400';
      deleteRecMsg.classList.remove('hidden');
    }
    finally { btn.disabled = false; btn.style.opacity = ''; }
  });

  // ── Phase 15: event delegation for clip play buttons ──────────────
  document.getElementById('recordings-list').addEventListener('click', e => {
    const btn = e.target.closest('.btn-play-clip');
    if (!btn) return;
    openClipModal(btn.dataset.src);
  });

  // clip-modal se declara en el marcado despues de donde vivia este script,
  // por eso el listener original esperaba a DOMContentLoaded; se conserva
  // igual aunque type="module" ya difiere la ejecucion (mas seguro no
  // quitarlo sin verificar — 28-PATTERNS.md).
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('clip-modal').addEventListener('click', e => {
      if (e.target === e.currentTarget || e.target.id === 'clip-modal-close') {
        const vid = document.getElementById('clip-video');
        vid.pause(); vid.src = '';
        document.getElementById('clip-modal').classList.remove('open');
      }
    });
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const vid = document.getElementById('clip-video');
      vid.pause(); vid.src = '';
      document.getElementById('clip-modal').classList.remove('open');
    }
  });
}
