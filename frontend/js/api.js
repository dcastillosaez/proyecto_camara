// frontend/js/api.js
export async function apiFetch(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

// DIR-04: GET /api/v2/config una sola vez por pagina. Ajustes, la tarjeta RTSP de
// Camara y el panel rapido lo pedian cada uno por su lado (tres veces por carga) y
// gastaban el cupo de 60/min del endpoint. Devuelve el JSON o null si falla; un fallo
// no se cachea. Quien guarda cambios llama a invalidateConfig().
let _configPromise = null;

export function getConfig() {
  if (!_configPromise) {
    _configPromise = fetch('/api/v2/config')
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
      .then((cfg) => {
        if (cfg === null) _configPromise = null;
        return cfg;
      });
  }
  return _configPromise;
}

export function invalidateConfig() {
  _configPromise = null;
}
