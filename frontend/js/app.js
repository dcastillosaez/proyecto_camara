// frontend/js/app.js
import { connectWS } from './websocket.js';
import { loadInitialData, loadCamStatus, loadPipelineHealth } from './views/dashboard.js';
import { bindPtzControls } from './views/dashboard-ptz.js';
import { bindEventExport } from './views/dashboard-events.js';
import { loadHealth, loadObservability } from './views/dashboard-observability.js';
import { loadResolutions, initTracksOverlay } from './components/videoCanvas.js';
import { loadRecordings, bindEventCardControls } from './components/eventCard.js';
import { loadDetectionClasses } from './components/detectionClasses.js';
import { loadPersons, bindPersonGallery } from './components/personGallery.js';
import { loadAlerts, bindAlertCenter } from './components/alertCenter.js';
import { bindMarkPerson } from './components/markPerson.js';
import { initTimeline, refreshPersonNames } from './views/timeline.js';
import { initAnalytics } from './views/analytics.js';
import { initNav } from './nav.js';
import { initCamera } from './views/camera.js';
import { initCameraQuick } from './views/camera-quick.js';
import { initSettings } from './views/settings.js';

document.addEventListener('DOMContentLoaded', () => {
  // Wiring de listeners — el orden entre si no importa (no hay llamadas de red aqui,
  // solo addEventListener). bindPtzControls() ya invoca loadPresets() internamente
  // (28-03), igual que el script original lo hacia en linea con el resto del bloque PTZ.
  bindPtzControls();
  bindEventCardControls();
  bindPersonGallery();
  bindEventExport();
  bindAlertCenter();
  bindMarkPerson();
  // initAnalytics() ANTES de initNav(): registra el boot diferido que initNav puede
  // disparar al instante si la pagina se abre directamente en #analitica.
  initAnalytics();
  initNav();

  // Carga inicial — mismo orden que index.html:1362-2023 en el script original, para
  // minimizar diferencias de comportamiento observable (28-PATTERNS.md).
  loadResolutions();
  initTracksOverlay();
  loadCamStatus();
  loadInitialData();
  // initTimeline() antes de connectWS(): el observer y los controles tienen que existir
  // cuando lleguen los primeros mensajes type:"event" por el socket.
  initTimeline();
  connectWS();

  loadRecordings();
  setInterval(loadRecordings, 30000);

  loadPersons();
  setInterval(loadPersons, 30000);
  // person_name no viaja persistido en el evento: la timeline lo resuelve contra su
  // Map<person_id, name>, que se refresca al mismo ritmo que la galeria (Hallazgo 5).
  setInterval(refreshPersonNames, 30000);

  loadDetectionClasses();

  loadHealth();
  setInterval(loadHealth, 30000);
  loadPipelineHealth();
  loadAlerts();

  loadObservability();
  setInterval(loadObservability, 5000);

  // Fase 32 (32-07): las tres vistas nuevas -- seguras de llamar aunque su pestana no
  // este activa (initCamera arma el timer de la tarjeta RTSP pero no activa
  // #camera-feed hasta que nav.js llame activateCameraFeed(); initSettings carga el
  // esquema una vez y lo deja en memoria).
  initCamera();
  initCameraQuick();
  initSettings();
});
