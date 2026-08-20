// frontend/js/components/detectionClasses.js
import { showToast } from '../views/dashboard.js';

const DETECTION_CLASS_LABELS = {
  0: 'Persona', 1: 'Bicicleta', 2: 'Coche', 3: 'Moto', 24: 'Mochila', 28: 'Maleta',
};

export function renderDetectionClasses(data) {
  const list = document.getElementById('detection-classes-list');
  list.innerHTML = '';
  const active = new Set(data.active ?? []);
  const locked = new Set(data.locked ?? []);
  for (const cls of data.available ?? []) {
    const isLocked = locked.has(cls.id) || cls.locked;
    const row = document.createElement('label');
    row.className = 'flex items-center gap-2 text-xs text-slate-300 py-0.5' +
      (isLocked ? ' opacity-60' : ' cursor-pointer');
    row.innerHTML = `
      <input type="checkbox" data-class-id="${cls.id}" class="detection-class-checkbox"
             ${active.has(cls.id) ? 'checked' : ''} ${isLocked ? 'disabled' : ''}>
      <span>${DETECTION_CLASS_LABELS[cls.id] ?? cls.name}</span>`;
    list.appendChild(row);
  }
  list.querySelectorAll('.detection-class-checkbox:not([disabled])').forEach(cb => {
    cb.addEventListener('change', saveDetectionClasses);
  });
}

export async function loadDetectionClasses() {
  try {
    const res = await fetch('/api/v2/detection/classes');
    if (!res.ok) return;
    renderDetectionClasses(await res.json());
  } catch {}
}

export async function saveDetectionClasses() {
  const msg = document.getElementById('detection-classes-msg');
  const checkboxes = document.querySelectorAll('.detection-class-checkbox');
  const classes = Array.from(checkboxes)
    .filter(cb => cb.checked)
    .map(cb => parseInt(cb.dataset.classId, 10));
  checkboxes.forEach(cb => cb.disabled = true);
  msg.classList.add('hidden');
  try {
    const res = await fetch('/api/v2/detection/classes', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classes }),
    });
    if (res.ok) {
      showToast('Clases activas actualizadas', 'success');
      renderDetectionClasses(await res.json());
    } else {
      const d = await res.json().catch(() => ({}));
      msg.textContent = d.detail ?? 'Error al guardar.';
      msg.className = 'text-xs text-center text-red-400 mt-2';
      msg.classList.remove('hidden');
      await loadDetectionClasses();  // revierte los checkboxes al estado real del servidor
    }
  } catch {
    msg.textContent = 'Sin respuesta del servidor.';
    msg.className = 'text-xs text-center text-red-400 mt-2';
    msg.classList.remove('hidden');
    await loadDetectionClasses();
  }
}
