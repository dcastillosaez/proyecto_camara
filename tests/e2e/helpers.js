// Helpers compartidos por los specs E2E (Fase 34).
const { expect } = require('@playwright/test');

/**
 * Registra un proxy transparente sobre el WebSocket real de la app (mismo
 * patron que ws-reconnect.spec.js) y devuelve un objeto con `send(message)`
 * para inyectar mensajes directamente al cliente, como si vinieran del
 * servidor real. Debe llamarse ANTES de gotoHome().
 *
 * `send()` espera a que la conexion real exista: websocket.js hace un fetch
 * previo (/api/ws-token) antes de abrir el WebSocket, asi que el handler de
 * routeWebSocket puede llegar bien despues de domcontentloaded -- enviar
 * antes de eso falla con "Cannot read properties of null".
 */
async function routeWsProxy(page) {
  let client = null;
  await page.routeWebSocket('**/ws**', (ws) => {
    client = ws;
    const server = ws.connectToServer();
    ws.onMessage((message) => server.send(message));
    server.onMessage((message) => ws.send(message));
  });
  return {
    async send(message) {
      await expect.poll(() => client !== null, { timeout: 10_000 }).toBe(true);
      client.send(message);
    },
    getRoute: () => client,
  };
}

/**
 * Navega a la home. Nunca uses page.goto('/') con el waitUntil por defecto
 * ('load'): #video-feed y #camera-feed apuntan a /video_feed, un stream MJPEG
 * que backend/main.py:mjpeg_generator deja pendiente para siempre cuando no
 * hay camara real conectada (nunca cierra la respuesta, solo la deja
 * esperando) -- el navegador no dispara su evento 'load' hasta que TODOS los
 * recursos terminan, así que page.goto colgaría indefinidamente.
 */
async function gotoHome(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
}

module.exports = { gotoHome, routeWsProxy };
