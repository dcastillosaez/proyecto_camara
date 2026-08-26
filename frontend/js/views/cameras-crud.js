// frontend/js/views/cameras-crud.js
// Fase 36 (SCALE-05): CRUD de camaras desde Ajustes -- seccion estatica "Camaras", fuera
// del arbol dinamico de GET /api/v2/config (settings.js): no es un editor de campos de
// Settings, es alta/baja/edicion de entidades, mismo espiritu que zoneEditor.js/
// rules-editor.js en la pestana Camara. Reutiliza el estilo visual de settings-section.js
// (fieldset/legend, filter-input/filter-chip) para no introducir un patron nuevo.
//
// Anti-XSS: createElement/textContent siempre, nunca HTML crudo con datos de servidor.

const API = '/api/v2/cameras/catalog';

function _panel() {
  return document.getElementById('settings-panel');
}

function _cameraRow(camera, onChanged) {
  const row = document.createElement('div');
  row.className = 'flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-xl bg-slate-800 border border-slate-700';

  const info = document.createElement('div');
  info.className = 'flex flex-col min-w-0';
  const name = document.createElement('span');
  name.className = 'text-sm text-slate-200 truncate';
  name.textContent = `${camera.id} — ${camera.name}`;
  const url = document.createElement('span');
  url.className = 'text-xs mono text-slate-500 truncate';
  url.textContent = camera.rtsp_url ?? '';
  info.append(name, url);

  const status = document.createElement('span');
  status.className = 'text-xs mono flex-shrink-0';
  status.textContent = camera.running ? 'en marcha' : (camera.enabled ? 'detenida' : 'deshabilitada');
  status.style.color = camera.running ? '#4ade80' : '#94a3b8';

  const toggleBtn = document.createElement('button');
  toggleBtn.type = 'button';
  toggleBtn.className = 'filter-chip flex-shrink-0';
  toggleBtn.textContent = camera.enabled ? 'Deshabilitar' : 'Habilitar';
  toggleBtn.addEventListener('click', async () => {
    toggleBtn.disabled = true;
    await fetch(`/api/v2/cameras/${encodeURIComponent(camera.id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !camera.enabled }),
    });
    onChanged();
  });

  const delBtn = document.createElement('button');
  delBtn.type = 'button';
  delBtn.className = 'filter-chip flex-shrink-0';
  delBtn.textContent = 'Eliminar';
  delBtn.addEventListener('click', async () => {
    if (!confirm(`¿Eliminar la cámara "${camera.name}"? Se detiene y se borra del catálogo.`)) return;
    await fetch(`/api/v2/cameras/${encodeURIComponent(camera.id)}`, { method: 'DELETE' });
    onChanged();
  });

  row.append(info, status, toggleBtn, delBtn);
  return row;
}

function _newCameraForm(onCreated) {
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-col gap-2 p-3 bg-slate-800/60 border border-slate-700 rounded-xl mt-3';

  const idInput = document.createElement('input');
  idInput.placeholder = 'id (p.ej. cam2)';
  idInput.className = 'filter-input';
  const nameInput = document.createElement('input');
  nameInput.placeholder = 'Nombre';
  nameInput.className = 'filter-input';
  const urlInput = document.createElement('input');
  urlInput.placeholder = 'rtsp://usuario:contraseña@host:puerto/ruta';
  urlInput.className = 'filter-input';

  const error = document.createElement('p');
  error.className = 'text-xs text-red-400 hidden';

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'filter-chip';
  addBtn.textContent = '+ Añadir cámara';
  addBtn.addEventListener('click', async () => {
    error.classList.add('hidden');
    addBtn.disabled = true;
    try {
      const res = await fetch('/api/v2/cameras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: idInput.value.trim(), name: nameInput.value.trim(), rtsp_url: urlInput.value.trim(),
        }),
      });
      if (res.ok) {
        idInput.value = ''; nameInput.value = ''; urlInput.value = '';
        onCreated();
      } else {
        const d = await res.json().catch(() => ({}));
        error.textContent = Array.isArray(d.detail)
          ? d.detail.map((e) => e.msg).join(', ')
          : String(d.detail ?? 'Error al crear la cámara.');
        error.classList.remove('hidden');
      }
    } catch {
      error.textContent = 'Sin respuesta del servidor.';
      error.classList.remove('hidden');
    } finally {
      addBtn.disabled = false;
    }
  });

  wrap.append(idInput, nameInput, urlInput, error, addBtn);
  return wrap;
}

export async function renderCamerasSection() {
  const panel = _panel();
  if (!panel) return;
  panel.replaceChildren();
  panel.dataset.cfgSection = 'camaras';
  panel.dataset.sectionLabel = 'Cámaras';

  const fieldset = document.createElement('fieldset');
  fieldset.className = 'mb-6';
  const legend = document.createElement('legend');
  legend.className = 'text-sm font-semibold';
  legend.textContent = 'Cámaras';
  const list = document.createElement('div');
  list.className = 'flex flex-col gap-1.5 mt-2';
  fieldset.append(legend, list);
  panel.appendChild(fieldset);

  const reload = async () => {
    list.replaceChildren();
    try {
      const cameras = (await (await fetch(API)).json()).cameras ?? [];
      if (cameras.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'text-xs text-slate-500';
        empty.textContent = 'Sin cámaras registradas.';
        list.appendChild(empty);
      } else {
        cameras.forEach((c) => list.appendChild(_cameraRow(c, reload)));
      }
    } catch {
      const err = document.createElement('p');
      err.className = 'text-xs text-red-400';
      err.textContent = 'No se pudo cargar el catálogo de cámaras.';
      list.appendChild(err);
    }
  };
  await reload();
  panel.appendChild(_newCameraForm(reload));
}
