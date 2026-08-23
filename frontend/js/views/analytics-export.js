// frontend/js/views/analytics-export.js
// Los cuatro botones de descarga de la vista de analitica (OPS-15).
//
// Mismo patron que dashboard-events.js::bindEventExport(): asignar la URL de descarga
// directamente a la navegacion, sin objeto de blob intermedio ni enlace sintetico de
// descarga. El servidor genera el CSV/JSON (D-10): serializarlo en el cliente seria
// agregar en el cliente, que rompe OPS-14. Sin toast de exito: la descarga del
// navegador ya es la confirmacion.

import { isSafeMediaUrl } from './timeline-row.js';

const BTN = {
  hourly: 'an-export-hourly',
  occupancy: 'an-export-occupancy',
  persons: 'an-export-persons',
  json: 'an-export-json',
};

function buildUrl(panel, range) {
  const base = `/api/v2/analytics/export?camera_id=cam1&from=${range.from}&to=${range.to}`;
  return panel === 'json' ? `${base}&format=json` : `${base}&format=csv&panel=${panel}`;
}

/** Engancha un click por boton. getRange() -> {from, to}, misma firma que currentRange(). */
export function initExport(getRange) {
  Object.keys(BTN).forEach((panel) => {
    const btn = document.getElementById(BTN[panel]);
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (btn.disabled) return; // defensa contra un click sintetico sobre un boton apagado
      const url = buildUrl(panel, getRange());
      if (!isSafeMediaUrl(url)) return;
      window.location.href = url;
    });
  });
}

/** panel: 'hourly'|'occupancy'|'persons'|'json'. Apaga/enciende el boton y su estilo. */
export function setExportEnabled(panel, enabled) {
  const id = BTN[panel];
  if (!id) return; // 'summary' no tiene boton propio: llamada valida, sin efecto
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.disabled = !enabled;
  btn.style.opacity = enabled ? '' : '0.25';
  btn.style.cursor = enabled ? '' : 'not-allowed';
}
