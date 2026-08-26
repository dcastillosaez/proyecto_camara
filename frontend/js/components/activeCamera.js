// frontend/js/components/activeCamera.js
// Fase 36 (SCALE-06): estado compartido de "que camara esta activa" en la vista Camara.
// Modulo minimo para que camera.js (selector), camera-mosaic.js, zoneEditor.js,
// lineEditor.js y rules-form.js lean/escriban el mismo valor sin acoplarse entre si --
// import por modulo, nunca window/localStorage: es un estado de la pestana en curso,
// no configuracion que deba sobrevivir a un refresco de pagina.

let _activeCameraId = 'cam1';
const _listeners = new Set();

export function getActiveCameraId() {
  return _activeCameraId;
}

/** Cambia la camara activa y avisa a quien se haya suscrito (selector, mosaico, editores). */
export function setActiveCameraId(cameraId) {
  if (!cameraId || cameraId === _activeCameraId) return;
  _activeCameraId = cameraId;
  _listeners.forEach((cb) => cb(cameraId));
}

export function onActiveCameraChange(callback) {
  _listeners.add(callback);
}
