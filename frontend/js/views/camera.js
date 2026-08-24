// frontend/js/views/camera.js
//
// Fase 32 (OPS-16, OPS-17): orquestador de la vista "Camara" -- activacion diferida
// del feed grande (#camera-feed), tarjeta de estado RTSP con el semaforo de 3 estados
// heredado de la cabecera de la Fase 29, y el pie de "Actualizado a las HH:MM:SS".
//
// Las seis teselas de metrica de la vista se pintan desde dashboard-observability.js
// (loadHealth/loadObservability), que esta misma plan extiende con un segundo set de
// ids (#cam-*) sobre los MISMOS valores ya resueltos por el tick de 5s -- este modulo
// no abre un segundo fetch de metricas ni un segundo intervalo de 5s para no duplicar
// peticiones que ya existen a ese ritmo (ver 32-UI-SPEC.md "Refresco: se reutiliza el
// bucle de 5s").
//
// Desviaciones documentadas frente al UI-SPEC literal (detalle en 32-04-SUMMARY.md):
//  1. El estado "Reconectando" NO enseña un countdown de segundos ("reintentando en
//     {N} s"): CaptureHealth (backend/pipeline/capture.py) y el log de backoff de
//     capture.py:185 no exponen ese valor por API, asi que no se inventa un numero en
//     el cliente.
//  2. "Frames descartados" se pinta desde /api/v2/metrics (mismo `_counterSum` que ya
//     usa dashboard-observability.js para #obs-dropped), no desde
//     /api/v2/cameras/{id}/health como sugiere la tabla de teselas del UI-SPEC -- se
//     sigue el codigo real ya establecido, no el texto del documento.

import { initZoneEditor, disableZoneEditMode } from '../components/zoneEditor.js';
import { initLineEditor, disableLineEditMode } from '../components/lineEditor.js';
import { initRulesEditor } from './rules-editor.js';

let _feedActivated = false;

/**
 * Asigna `src="/video_feed"` a `#camera-feed` la primera vez que se llama. Llamadas
 * posteriores no hacen nada: reasignar el mismo src en cada activacion de pestana
 * dispararia el `onerror` de reconexion del <img> y la vista parpadearia a "offline"
 * cada vez que el operador vuelve a la pestana Camara.
 */
export function activateCameraFeed() {
  if (_feedActivated) return;
  _feedActivated = true;
  const img = document.getElementById('camera-feed');
  if (img) img.src = '/video_feed';
}

// Mismos tres colores que el semaforo de cabecera de la Fase 29
// (#4ade80/#f59e0b/#ef4444), sin cuarto estado.
const RTSP_STATES = {
  connected: { dot: 'bg-green-400', text: 'Conectado' },
  reconnecting: { dot: 'bg-amber-500', text: 'Reconectando…' },
  offline: { dot: 'bg-red-500', text: 'Sin señal' },
};

function _paintRtspState(state) {
  const s = RTSP_STATES[state];
  const dot = document.getElementById('rtsp-dot');
  if (dot) dot.className = `w-2 h-2 rounded-full ${s.dot}`;
  const text = document.getElementById('rtsp-status-text');
  if (text) text.textContent = s.text;
}

/**
 * Pinta la tarjeta de estado RTSP: semaforo + edad de ultimo frame + reconexiones +
 * resolucion nativa (todo desde GET /api/v2/cameras/cam1/health) y la URL RTSP
 * enmascarada por el servidor (desde GET /api/v2/config, campo
 * `camara.captura.camera_url`). Nunca se reconstruye ni se enmascara la URL en el
 * navegador (T-32-12).
 */
export async function loadRtspCard() {
  try {
    const [healthRes, configRes] = await Promise.all([
      fetch('/api/v2/cameras/cam1/health'),
      fetch('/api/v2/config'),
    ]);
    if (!healthRes.ok) throw new Error('health fetch failed');
    const h = await healthRes.json();

    const state = !h.connected ? 'offline' : (h.last_frame_age_s >= 5 ? 'reconnecting' : 'connected');
    _paintRtspState(state);

    const lastFrame = document.getElementById('rtsp-last-frame');
    if (lastFrame) lastFrame.textContent = `${h.last_frame_age_s.toFixed(1)} s`;
    const reconnects = document.getElementById('rtsp-reconnects');
    if (reconnects) reconnects.textContent = `${h.reconnects}`;
    const [w, hh] = h.native_resolution || [0, 0];
    const resolution = document.getElementById('rtsp-resolution');
    if (resolution) resolution.textContent = w && hh ? `${w}×${hh}` : '–';

    if (configRes.ok) {
      const cfg = await configRes.json();
      const camara = cfg.sections.find((sec) => sec.key === 'camara');
      const captura = camara && camara.groups.find((g) => g.key === 'captura');
      const urlField = captura && captura.fields.find((f) => f.key === 'camera_url');
      const urlEl = document.getElementById('rtsp-url');
      if (urlEl) urlEl.textContent = urlField ? urlField.value : '–';
    }
  } catch {
    // El endpoint de salud falla o no responde: el panel entero sigue visible, solo
    // el semaforo cae a "Sin señal" (nunca se vacia la tarjeta, mismo criterio que el
    // resto de estados de error del UI-SPEC de esta fase).
    _paintRtspState('offline');
  }
}

/**
 * Pie de la vista: `.mono` 12px "Actualizado a las {HH:MM:SS}" (UI-SPEC), refrescado
 * cada segundo -- es un reloj de pared, no depende de ningun fetch.
 */
export function tickCameraFooter() {
  const el = document.getElementById('camera-updated');
  if (el) el.textContent = `Actualizado a las ${new Date().toLocaleTimeString('es-ES', { hour12: false })}`;
}

/**
 * Arranca la vista Camara: primera carga de la tarjeta RTSP + su propio tick de 5s
 * (combina /health y /config, dos fuentes que dashboard-observability.js no toca, asi
 * que no duplica ninguna peticion que ya exista a otro ritmo) y el reloj del pie a 1s.
 * No activa el feed grande: `activateCameraFeed()` la llama el conmutador de pestanas
 * (nav.js, extendido en 32-07) al entrar por primera vez en la pestana Camara.
 */
export function initCamera() {
  loadRtspCard();
  setInterval(loadRtspCard, 5000);
  tickCameraFooter();
  setInterval(tickCameraFooter, 1000);

  // D-03: los tres editores viven en Camara, sobre el MISMO <canvas>
  // (#zone-line-canvas). Solo enganchan listeners -- sin red hasta que el operador
  // entra en modo edicion (OPS-21/OPS-22) o abre el formulario de reglas (OPS-24).
  initZoneEditor();
  initLineEditor();
  initRulesEditor();
  // Un unico <canvas> compartido: activar un modo debe desactivar el otro para que
  // los clicks de raton no compitan entre zoneEditor.js y lineEditor.js.
  document.getElementById('zone-mode-toggle')?.addEventListener('click', disableLineEditMode);
  document.getElementById('line-mode-toggle')?.addEventListener('click', disableZoneEditMode);
}
