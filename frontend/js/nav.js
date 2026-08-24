// frontend/js/nav.js
// Conmutador de las cuatro vistas (Operaciones / Analitica / Camara / Ajustes), D-02/D-03.
// Mecanismo minimo: cuatro role="tabpanel" hermanos y la propiedad `hidden`.
// Nunca toca el MJPEG ni el WebSocket, ambos siguen conectados con la vista
// oculta -- solo se alterna `hidden`, nunca `style.display` a mano.
//
// Fase 32 (32-07) anade 'camara' y 'ajustes' al registro existente de la Fase 31, sin
// reescribir el mecanismo: mismo hash con history.replaceState, mismo tablist, mismo
// bucle de activacion de tabs. Unica adicion de comportamiento: activar la pestana
// Camara por primera vez dispara activateCameraFeed() (32-04), que ya se protege con su
// propio flag de modulo contra reasignaciones repetidas de `src`.

import { activateCameraFeed } from './views/camera.js';

const VIEWS = ['operaciones', 'analitica', 'camara', 'ajustes'];

let _boot = null;
let _resize = null;
let _booted = false;
let _current = 'operaciones';

const $ = (id) => document.getElementById(id);

function _tabFor(view) {
  return $(`tab-${view}`);
}

function _panelFor(view) {
  return $(`view-${view}`);
}

function _resolveHash() {
  // Cualquier hash desconocido o vacio cae en operaciones (T-31-07). El hash de Ajustes
  // admite un segundo nivel opcional (#ajustes/{seccion}) que settings.js resuelve por
  // su cuenta -- aqui solo hace falta reconocer el prefijo para activar la pestana.
  const h = (location.hash || '').replace('#', '');
  if (h === 'analitica') return 'analitica';
  if (h === 'camara') return 'camara';
  if (h === 'ajustes' || h.startsWith('ajustes/')) return 'ajustes';
  return 'operaciones';
}

function activate(view) {
  _current = view;
  for (const v of VIEWS) {
    const panel = _panelFor(v);
    if (panel) panel.hidden = (v !== view);
  }

  for (const v of VIEWS) {
    const tab = _tabFor(v);
    if (!tab) continue;
    const active = v === view;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  }

  // NUNCA se asigna el hash directamente: las pestanas no son paginas y no deben llenar
  // el historial. Excepcion: si el hash ya apunta a esta vista con un segundo nivel
  // (#ajustes/{seccion}), no se pisa -- si no, initSettings() nunca vería la seccion
  // pedida por el enlace/marcador (deep-link de Ajustes, 32-06).
  const currentHash = (location.hash || '').replace('#', '');
  if (currentHash !== view && !currentHash.startsWith(`${view}/`)) {
    history.replaceState(null, '', `#${view}`);
  }

  // Activacion diferida del feed grande de la vista Camara (D-02 del UI-SPEC de la Fase
  // 32): activateCameraFeed() ya no hace nada en llamadas repetidas.
  if (view === 'camara') activateCameraFeed();

  if (view !== 'analitica') return;
  if (!_booted && _boot) {
    _booted = true;
    // D-03, caso limite: si esta activacion viene de initNav() resolviendo un hash
    // #analitica ya presente al cargar (bookmark, recarga, URL pegada), _boot() se
    // ejecutaria en el mismo tick sincrono que retirar `hidden`, y Chart.js mediria
    // el contenedor antes de que el navegador confirme el layout -- se queda en el
    // tamano de reserva 300x150 para siempre. requestAnimationFrame garantiza que
    // el recalculo de estilo y layout ya se aplico antes de que el callback se
    // ejecute. Se aplica sin condicion (tambien cuando ya funciona, p.ej. click):
    // es idempotente e inofensivo, un frame de mas no se nota.
    requestAnimationFrame(() => _boot());
  } else if (_resize) {
    _resize();
  }
}

/** 31-10 registra aqui el arranque diferido de sus graficas Chart.js. */
export function registerAnalyticsBoot(bootFn, resizeFn) {
  _boot = bootFn;
  _resize = resizeFn;
}

export function activeView() {
  return _current;
}

export function initNav() {
  const tablist = document.querySelector('[role="tablist"]');
  if (!tablist) return;

  activate(_resolveHash());

  for (const v of VIEWS) {
    const tab = _tabFor(v);
    if (!tab) continue;
    tab.addEventListener('click', () => activate(v));
  }

  // Activacion automatica: flechas cambian de pestana y mueven el foco;
  // Home/End van a la primera/ultima. Tab no se intercepta.
  tablist.addEventListener('keydown', (e) => {
    const idx = VIEWS.indexOf(_current);
    let next = null;
    if (e.key === 'ArrowRight') next = VIEWS[(idx + 1) % VIEWS.length];
    else if (e.key === 'ArrowLeft') next = VIEWS[(idx - 1 + VIEWS.length) % VIEWS.length];
    else if (e.key === 'Home') next = VIEWS[0];
    else if (e.key === 'End') next = VIEWS[VIEWS.length - 1];
    if (!next) return;
    e.preventDefault();
    activate(next);
    const tab = _tabFor(next);
    if (tab) tab.focus();
  });

  // Para que pegar una URL con #analitica/#camara/#ajustes funcione tambien sin recargar.
  window.addEventListener('hashchange', () => activate(_resolveHash()));
}
