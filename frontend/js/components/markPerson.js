// frontend/js/components/markPerson.js
// Modal "Marcar como persona" (OPS-08, D-06): precarga el recorte del evento, avisa del
// alcance retroactivo ANTES de confirmar y enrola reutilizando /api/enroll_face.
//
// El enrolado NO tiene endpoint propio a proposito: /api/enroll_face ya valida
// content_type, tamano <=10MB y max_length=100 del nombre, con tests de regresion de
// seguridad asociados (30-RESEARCH.md Hallazgo 6). Duplicar eso seria una regresion.
import { apiFetch } from '../api.js';
import { showToast } from '../views/dashboard.js';
import { applyPersonAssignment } from '../views/timeline.js';
import { isSafeMediaUrl } from '../views/timeline-row.js';

const ALLOWED_TYPES = /^image\/(jpeg|png|webp)$/;   // mismo juego que _ALLOWED_IMAGE_TYPES

let _ctx = null;   // { eventId, trackId, snapshotUrl, scopeCount }

const $ = (id) => document.getElementById(id);

function _showError(msg) {
  const el = $('mark-person-error');
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle('hidden', !msg);
}

function _open() {
  const modal = $('mark-person-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  $('mark-person-name')?.focus();
}

function close() {
  const modal = $('mark-person-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  _ctx = null;
}

function _isOpen() {
  return $('mark-person-modal')?.classList.contains('hidden') === false;
}

// ── Precarga del recorte ──────────────────────────────────────────
function _paintPreview(snapshotUrl) {
  const img = $('mark-person-preview');
  if (!img) return '';
  if (snapshotUrl) {
    img.src = snapshotUrl;
    img.classList.remove('hidden');
    return '';
  }
  // Sin recorte el enrolado cae al frame actual de la camara (use_current_frame=true):
  // se dice explicitamente, no se deja al operador adivinar que imagen se guardara.
  img.removeAttribute('src');
  img.classList.add('hidden');
  return ' Este evento no tiene recorte: se usara el frame actual de la camara.';
}

// ── Alcance retroactivo (lo calcula el servidor, el cliente solo lo muestra) ──
async function _paintScope(eventId, extra) {
  const scope = $('mark-person-scope');
  const data = await apiFetch(`/api/v2/events/${encodeURIComponent(eventId)}/track-scope`);
  const n = data.count ?? 0;
  if (_ctx) _ctx.scopeCount = n;
  // Literal exacto del UI-SPEC, con textContent: el numero viene del servidor.
  if (scope) scope.textContent = `Se aplicará también a los eventos anteriores de este track (${n}).${extra}`;
}

// ── Autocompletado con personas ya conocidas ──────────────────────
async function _paintKnownPersons() {
  const options = $('mark-person-options');
  const data = await apiFetch('/persons');
  if (!options) return;
  options.textContent = '';
  (data.persons ?? [])
    .filter((p) => p.name && !p.name.startsWith('Person '))
    .forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.name;              // por propiedad, nunca interpolado en un template
      options.appendChild(opt);
    });
}

async function onRequest(e) {
  const detail = e.detail ?? {};
  // Misma cautela que timeline-row.js/timeline.js: el backend siempre construye
  // snapshotUrl como ruta propia (/snapshots/...), pero se valida igual antes de
  // usarla en un sink de URL (img.src, fetch) — defensa en profundidad.
  const rawUrl = detail.snapshotUrl ?? null;
  _ctx = {
    eventId: detail.eventId,
    trackId: detail.trackId ?? null,
    snapshotUrl: isSafeMediaUrl(rawUrl) ? rawUrl : null,
    scopeCount: 0,
  };
  const nameInput = $('mark-person-name');
  if (nameInput) nameInput.value = '';
  _showError('');
  const extra = _paintPreview(_ctx.snapshotUrl);
  const scope = $('mark-person-scope');
  if (scope) scope.textContent = '';
  _open();                             // el modal se abre siempre: nunca a medio camino
  try {
    await Promise.all([_paintScope(_ctx.eventId, extra), _paintKnownPersons()]);
  } catch (err) {
    // El fallo se ve, no se traga: el operador puede seguir, pero sabe que no hay alcance.
    _showError(`No se pudo calcular el alcance: ${err.message}`);
  }
}

// ── Confirmacion: enrolar + asignar al bloque del track ───────────
function setBusy(on) {
  const btn = $('btn-mark-person-confirm');
  if (!btn) return;
  btn.disabled = on;                   // sin esto, un doble clic enrola dos personas
  btn.textContent = on ? 'Guardando…' : 'Marcar como persona';
}

async function _snapshotField(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error('No se pudo leer el recorte del evento.');
  const blob = await res.blob();
  const type = ALLOWED_TYPES.test(blob.type) ? blob.type : 'image/jpeg';
  return new Blob([blob], { type });
}

async function onConfirm() {
  if (!_ctx) return;
  const name = $('mark-person-name')?.value.trim() ?? '';
  if (!name) { _showError('Escribe un nombre.'); return; }
  _showError('');
  setBusy(true);
  const { eventId, snapshotUrl } = _ctx;
  try {
    const fd = new FormData();
    fd.append('name', name);
    if (snapshotUrl) {
      fd.append('image', await _snapshotField(snapshotUrl), 'snapshot.jpg');
    } else {
      fd.append('use_current_frame', 'true');
    }
    const enrolled = await apiFetch('/api/enroll_face', { method: 'POST', body: fd });
    const applied = await apiFetch(`/api/v2/events/${encodeURIComponent(eventId)}/assign-person`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ person_id: enrolled.person_id }),
    });
    applyPersonAssignment(applied.event_ids ?? [], enrolled.person_id, enrolled.name);
    showToast(`Identidad aplicada a ${applied.updated} eventos de este track.`, 'success');
    close();
  } catch (err) {
    // apiFetch ya trae el detail del backend (415/413/422 de enroll_face): se muestra ese
    // motivo concreto y solo se cae al literal generico del UI-SPEC si no hay ninguno.
    _showError(err.message || 'No se pudo guardar la identidad. Inténtalo de nuevo.');
    showToast('No se pudo guardar la identidad. Inténtalo de nuevo.', 'error');
  } finally {
    setBusy(false);
  }
}

export function bindMarkPerson() {
  const modal = $('mark-person-modal');
  if (!modal) return;
  document.addEventListener('timeline:mark-person', onRequest);
  $('btn-mark-person-cancel')?.addEventListener('click', close);
  $('btn-mark-person-confirm')?.addEventListener('click', onConfirm);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _isOpen()) close();
  });
}
