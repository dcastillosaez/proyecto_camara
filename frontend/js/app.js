// frontend/js/app.js
import { connectWS } from './websocket.js';
import { loadInitialData, loadCamStatus, loadPipelineHealth, loadActiveAlerts } from './views/dashboard.js';
import { bindPtzControls } from './views/dashboard-ptz.js';
import { bindEventExport } from './views/dashboard-events.js';
import { loadHealth, loadObservability } from './views/dashboard-observability.js';
import { loadResolutions, initTracksOverlay } from './components/videoCanvas.js';
import { loadZones, bindZoneForm } from './components/zoneEditor.js';
import { loadRecordings, bindEventCardControls } from './components/eventCard.js';
import { loadDetectionClasses } from './components/detectionClasses.js';
import { loadPersons, bindPersonGallery } from './components/personGallery.js';

document.addEventListener('DOMContentLoaded', () => {
  // Wiring de listeners — el orden entre si no importa (no hay llamadas de red aqui,
  // solo addEventListener). bindPtzControls() ya invoca loadPresets() internamente
  // (28-03), igual que el script original lo hacia en linea con el resto del bloque PTZ.
  bindPtzControls();
  bindZoneForm();
  bindEventCardControls();
  bindPersonGallery();
  bindEventExport();

  // Carga inicial — mismo orden que index.html:1362-2023 en el script original, para
  // minimizar diferencias de comportamiento observable (28-PATTERNS.md).
  loadResolutions();
  initTracksOverlay();
  loadCamStatus();
  loadInitialData();
  connectWS();

  loadRecordings();
  setInterval(loadRecordings, 30000);

  loadPersons();
  setInterval(loadPersons, 30000);

  loadZones();
  loadDetectionClasses();

  loadHealth();
  setInterval(loadHealth, 30000);
  loadPipelineHealth();
  loadActiveAlerts();

  loadObservability();
  setInterval(loadObservability, 5000);
});
