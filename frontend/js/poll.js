// frontend/js/poll.js
// DIR-04: sondeo con cabeza. El dashboard sumaba ~75 peticiones/min a /api/v2 con la
// pestana Camara abierta y agotaba su propio limite de 60/min por IP (deps.py). Aqui:
//   - un sondeo solo corre con el documento visible y, si se indica, con SU vista activa;
//   - un 429 en cualquier fetch pausa todos los sondeos con backoff exponencial
//     (5 s, 10 s, 20 s... hasta 60 s); la primera respuesta correcta lo reinicia.
// Sin dependencias ni build: un modulo ES mas.

import { activeView } from './nav.js';

const BACKOFF_START_MS = 5000;
const BACKOFF_MAX_MS = 60000;
let _backoffMs = 0;
let _blockedUntil = 0;

const _nativeFetch = window.fetch.bind(window);

// Envoltorio de fetch: observa el estado, nunca cambia la respuesta.
window.fetch = async (...args) => {
  const res = await _nativeFetch(...args);
  if (res.status === 429) {
    _backoffMs = _backoffMs ? Math.min(_backoffMs * 2, BACKOFF_MAX_MS) : BACKOFF_START_MS;
    _blockedUntil = Date.now() + _backoffMs;
  } else if (res.ok && _backoffMs) {
    _backoffMs = 0;
    _blockedUntil = 0;
  }
  return res;
};

export function rateLimitedFor() {
  return Math.max(0, _blockedUntil - Date.now());
}

/**
 * Llama a `fn` cada `ms` milisegundos mientras tenga sentido:
 *   - nunca con la pestana del navegador oculta;
 *   - si `view` se indica, solo con esa vista activa ('operaciones', 'camara'...);
 *   - nunca durante el backoff de un 429.
 * Al volver a ser visible o activa, el siguiente tick llega en <= `ms`.
 */
export function poll(fn, ms, { view = null } = {}) {
  const tick = async () => {
    const visible = document.visibilityState !== 'hidden';
    const active = view === null || activeView() === view;
    if (visible && active && rateLimitedFor() === 0) {
      try { await fn(); } catch { /* cada fn gestiona sus propios errores */ }
    }
    setTimeout(tick, ms);
  };
  setTimeout(tick, ms);
}
