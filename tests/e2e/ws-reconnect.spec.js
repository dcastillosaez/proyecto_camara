// Escenario "reconexion WS" (TEST-02, 3/10).
//
// context.setOffline() NO sirve aqui: bloquea peticiones de red nuevas pero
// no cierra un WebSocket ya establecido, asi que el badge nunca se movia de
// "Activo" (probado, confirmado por la propia ejecucion). page.routeWebSocket
// (Playwright >= 1.48) intercepta la conexion real y deja cerrarla desde el
// lado del cliente para simular una caida real de la LAN -- mismo evento
// onclose que dispara websocket.js con el backoff real (1s -> 30s).
const { test, expect } = require('@playwright/test');
const { gotoHome, routeWsProxy } = require('./helpers');

test('el badge de eventos en vivo pasa a "Reconectando" y vuelve a "Activo" tras un corte de red', async ({ page }) => {
  const ws = await routeWsProxy(page);
  await gotoHome(page);

  const badge = page.locator('#ws-badge');
  await expect(badge).toHaveText('Activo', { timeout: 15_000 });

  ws.getRoute().close();
  await expect(badge).toHaveText('Reconectando', { timeout: 10_000 });

  // websocket.js reintenta sola (backoff desde 1s) -- una nueva conexion pasa
  // otra vez por el mismo handler de routeWebSocket y vuelve a proxiarse.
  await expect(badge).toHaveText('Activo', { timeout: 15_000 });
});
