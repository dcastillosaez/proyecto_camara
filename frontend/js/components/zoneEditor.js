// frontend/js/components/zoneEditor.js
import { showToast } from '../views/dashboard.js';

const addZonePanel = document.getElementById('add-zone-panel');
const zoneMsg = document.getElementById('zone-msg');

export function bindZoneForm() {
  document.getElementById('btn-add-zone').addEventListener('click', () => {
    zoneMsg.classList.add('hidden');
    document.getElementById('zone-id-input').value = '';
    document.getElementById('zone-name-input').value = '';
    document.getElementById('zone-points-input').value = '';
    addZonePanel.classList.toggle('hidden');
  });

  document.getElementById('zone-cancel-btn').addEventListener('click', () => {
    addZonePanel.classList.add('hidden');
  });

  document.getElementById('zone-save-btn').addEventListener('click', async () => {
    const zoneId   = document.getElementById('zone-id-input').value.trim();
    const zoneName = document.getElementById('zone-name-input').value.trim();
    const zonePoints = document.getElementById('zone-points-input').value.trim();
    if (!zoneId || !zoneName || !zonePoints) {
      zoneMsg.textContent = 'Todos los campos son obligatorios.';
      zoneMsg.className = 'text-xs text-center text-red-400';
      zoneMsg.classList.remove('hidden');
      return;
    }
    let pts;
    try {
      pts = JSON.parse(zonePoints);
      if (!Array.isArray(pts) || pts.length < 3) throw new Error();
    } catch {
      zoneMsg.textContent = 'Puntos inválidos. Ejemplo: [[0.1,0.1],[0.9,0.1],[0.5,0.9]]';
      zoneMsg.className = 'text-xs text-center text-red-400';
      zoneMsg.classList.remove('hidden');
      return;
    }
    const btn = document.getElementById('zone-save-btn');
    btn.disabled = true; btn.style.opacity = '0.5';
    try {
      const res = await fetch('/api/zones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: zoneId, name: zoneName, polygon_json: JSON.stringify(pts), enabled: true }),
      });
      if (res.ok) {
        addZonePanel.classList.add('hidden');
        showToast(`Zona "${zoneName}" guardada`, 'success');
        loadZones();
      } else {
        const d = await res.json().catch(() => ({}));
        zoneMsg.textContent = d.detail ?? 'Error al guardar.';
        zoneMsg.className = 'text-xs text-center text-red-400';
        zoneMsg.classList.remove('hidden');
      }
    } catch {
      zoneMsg.textContent = 'Sin respuesta del servidor.';
      zoneMsg.className = 'text-xs text-center text-red-400';
      zoneMsg.classList.remove('hidden');
    } finally {
      btn.disabled = false; btn.style.opacity = '';
    }
  });
}

export async function loadZones() {
  try {
    const res = await fetch('/api/zones');
    if (!res.ok) return;
    const data = await res.json();
    const zones = data.zones ?? [];
    const list  = document.getElementById('zones-list');
    const empty = document.getElementById('zones-empty');
    list.querySelectorAll('.zone-row').forEach(el => el.remove());
    if (zones.length === 0) { empty.style.display = ''; return; }
    empty.style.display = 'none';
    zones.forEach(z => {
      const row = document.createElement('div');
      row.className = 'zone-row flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700';
      const enabledColor = z.enabled ? 'text-cyan-400' : 'text-slate-600';
      row.innerHTML = `
        <div class="flex items-center gap-2 min-w-0">
          <svg class="w-3 h-3 flex-shrink-0 ${enabledColor}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>
          <span class="text-xs text-slate-200 truncate">${z.name}</span>
          <span class="text-xs text-slate-600 mono">#${z.id}</span>
        </div>
        <button class="btn-del-zone text-slate-600 hover:text-red-400 transition-colors cursor-pointer flex-shrink-0" aria-label="Eliminar zona ${z.name}">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M9 6V4h6v2"/></svg>
        </button>`;
      row.querySelector('.btn-del-zone').addEventListener('click', async () => {
        if (!confirm(`¿Eliminar la zona "${z.name}"?`)) return;
        try {
          const r = await fetch(`/api/zones/${encodeURIComponent(z.id)}`, { method: 'DELETE' });
          if (r.ok) { showToast(`Zona "${z.name}" eliminada`, 'info'); loadZones(); }
          else showToast('Error al eliminar zona', 'error');
        } catch { showToast('Sin respuesta', 'error'); }
      });
      list.appendChild(row);
    });
  } catch {}
}
