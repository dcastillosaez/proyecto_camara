// frontend/js/components/personGallery.js
import { showToast } from '../views/dashboard.js';

// ── Known persons panel ────────────────────────────────
export async function loadPersons() {
  try {
    const res = await fetch('/persons');
    if (!res.ok) return;
    const data = await res.json();
    const list = document.getElementById('persons-list');
    const empty = document.getElementById('persons-empty');
    const named = data.persons.filter(p => p.name && !p.name.startsWith('Person '));
    if (named.length === 0) {
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';
    list.querySelectorAll('.person-row').forEach(el => el.remove());
    named.forEach(p => {
      const row = document.createElement('div');
      row.className = 'person-row flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700';
      const ts = p.last_seen ? new Date(p.last_seen).toLocaleDateString('es', { day:'2-digit', month:'short' }) : '—';
      row.innerHTML = `
        <div class="flex items-center gap-2 min-w-0">
          <div class="w-6 h-6 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center flex-shrink-0">
            <svg class="w-3 h-3 text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>
          </div>
          <span class="text-xs font-medium text-slate-200 truncate">${p.name}</span>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <span class="text-xs text-slate-600">${p.visit_count}×</span>
          <span class="text-xs text-slate-600">${ts}</span>
          <button class="btn-gallery text-xs text-slate-500 hover:text-blue-400 transition-colors cursor-pointer" title="Ver capturas" aria-label="Ver capturas de ${p.name}">
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          </button>
        </div>`;
      row.querySelector('.btn-gallery').addEventListener('click', () => openGallery(p.id, p.name));
      list.appendChild(row);
    });
  } catch {}
}

// Enroll modal
const enrollModal = document.getElementById('enroll-modal');
const enrollForm  = document.getElementById('enroll-form');
const enrollError = document.getElementById('enroll-error');
const uploadWrap  = document.getElementById('enroll-upload-wrap');

// Gallery modal
const galleryModal = document.getElementById('gallery-modal');

export async function openGallery(personId, personName) {
  document.getElementById('gallery-title').textContent = `Capturas — ${personName}`;
  const grid = document.getElementById('gallery-grid');
  const empty = document.getElementById('gallery-empty');
  grid.querySelectorAll('img').forEach(el => el.remove());
  empty.style.display = '';
  galleryModal.classList.remove('hidden');
  try {
    const res = await fetch(`/persons/${personId}/captures?limit=30`);
    if (!res.ok) return;
    const data = await res.json();
    const captures = data.captures ?? [];
    if (captures.length === 0) return;
    empty.style.display = 'none';
    captures.forEach(c => {
      const img = document.createElement('img');
      img.src = c.url;
      img.alt = `Captura ${c.timestamp}`;
      img.className = 'gallery-thumb';
      img.title = new Date(c.timestamp).toLocaleString('es-ES');
      img.loading = 'lazy';
      img.addEventListener('click', () => window.open(c.url, '_blank'));
      grid.insertBefore(img, empty);
    });
  } catch {}
}

export function bindPersonGallery() {
  document.getElementById('btn-enroll').addEventListener('click', async () => {
    enrollError.classList.add('hidden');
    enrollForm.reset();
    uploadWrap.classList.add('hidden');
    const knownWrap = document.getElementById('enroll-known-wrap');
    const knownList = document.getElementById('enroll-known-list');
    knownList.innerHTML = '';
    try {
      const res = await fetch('/persons');
      const data = await res.json();
      const named = (data.persons || []).filter(p => p.name && !p.name.startsWith('Person '));
      if (named.length > 0) {
        named.forEach(p => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.textContent = `${p.name} (${p.sample_count ?? 1})`;
          chip.className = 'text-xs px-2.5 py-1 rounded-lg bg-slate-700 hover:bg-blue-600 text-slate-300 hover:text-white transition-colors cursor-pointer';
          chip.addEventListener('click', () => {
            document.getElementById('enroll-name').value = p.name;
            knownList.querySelectorAll('button').forEach(b => b.classList.remove('bg-blue-600', 'text-white'));
            chip.classList.add('bg-blue-600', 'text-white');
          });
          knownList.appendChild(chip);
        });
        knownWrap.classList.remove('hidden');
      } else {
        knownWrap.classList.add('hidden');
      }
    } catch (_) { knownWrap.classList.add('hidden'); }
    enrollModal.classList.remove('hidden');
  });

  document.getElementById('enroll-close').addEventListener('click', () => {
    enrollModal.classList.add('hidden');
  });

  enrollModal.addEventListener('click', e => {
    if (e.target === enrollModal) enrollModal.classList.add('hidden');
  });

  enrollForm.querySelectorAll('input[name="enroll-source"]').forEach(radio => {
    radio.addEventListener('change', () => {
      uploadWrap.classList.toggle('hidden', radio.value !== 'upload');
    });
  });

  enrollForm.addEventListener('submit', async e => {
    e.preventDefault();
    enrollError.classList.add('hidden');
    const btn = document.getElementById('enroll-submit');
    btn.disabled = true;
    btn.textContent = 'Registrando…';

    const name   = document.getElementById('enroll-name').value.trim();
    const source = enrollForm.querySelector('input[name="enroll-source"]:checked').value;
    const fd     = new FormData();
    fd.append('name', name);

    if (source === 'frame') {
      fd.append('use_current_frame', 'true');
    } else {
      const file = document.getElementById('enroll-file').files[0];
      if (!file) {
        enrollError.textContent = 'Selecciona una imagen.';
        enrollError.classList.remove('hidden');
        btn.disabled = false; btn.textContent = 'Registrar';
        return;
      }
      fd.append('image', file);
    }

    try {
      const res = await fetch('/api/enroll_face', { method: 'POST', body: fd });
      const data = await res.json();
      if (res.ok) {
        enrollModal.classList.add('hidden');
        showToast(`"${data.name}" registrado (ID ${data.person_id})`, 'success');
        loadPersons();
      } else {
        enrollError.textContent = data.detail ?? 'Error desconocido';
        enrollError.classList.remove('hidden');
      }
    } catch (ex) {
      enrollError.textContent = `Sin respuesta: ${ex.message}`;
      enrollError.classList.remove('hidden');
    } finally {
      btn.disabled = false; btn.textContent = 'Registrar';
    }
  });

  document.getElementById('gallery-close').addEventListener('click', () => galleryModal.classList.add('hidden'));
  galleryModal.addEventListener('click', e => { if (e.target === galleryModal) galleryModal.classList.add('hidden'); });
}
