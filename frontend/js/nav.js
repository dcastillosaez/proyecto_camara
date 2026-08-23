// frontend/js/nav.js
// Conmutador de las dos vistas (Operaciones / Analitica), D-02/D-03.
// Mecanismo minimo: dos role="tabpanel" hermanos y la propiedad `hidden`.
// Nunca toca el MJPEG ni el WebSocket, ambos siguen conectados con la vista
// oculta -- solo se alterna `hidden`, nunca `style.display` a mano.

const VIEWS = ['operaciones', 'analitica'];

let _boot = null;
let _resize = null;
let _booted = false;
let _current = 'operaciones';

const $ = (id) => document.getElementById(id);

function _tabFor(view) {
  return view === 'analitica' ? $('tab-analitica') : $('tab-operaciones');
}

function _resolveHash() {
  // Cualquier hash desconocido o vacio cae en operaciones (T-31-07).
  const h = (location.hash || '').replace('#', '');
  return h === 'analitica' ? 'analitica' : 'operaciones';
}

function activate(view) {
  _current = view;
  $('view-operaciones').hidden = (view !== 'operaciones');
  $('view-analitica').hidden = (view !== 'analitica');

  for (const v of VIEWS) {
    const tab = _tabFor(v);
    if (!tab) continue;
    const active = v === view;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  }

  // NUNCA se asigna el hash directamente: las pestanas no son paginas y no
  // deben llenar el historial.
  history.replaceState(null, '', `#${view}`);

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

  // Para que pegar una URL con #analitica funcione tambien sin recargar.
  window.addEventListener('hashchange', () => activate(_resolveHash()));
}
