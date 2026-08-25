// Escenario "camara offline" (TEST-02, 2/10).
//
// CAMERA_URL apunta por defecto a una Tapo real en la LAN del usuario,
// inalcanzable desde CI y desde esta maquina -- no hace falta simularlo. La
// senal fiable es la tarjeta de salud RTSP de la vista Camara (semaforo de 3
// estados, camera.js:loadRtspCard), que lee /api/v2/cameras/cam1/health y cae
// a "Sin señal" tanto si el endpoint responde connected:false como si falla
// del todo (loadRtspCard tiene su propio catch) -- a diferencia del <img
// onerror> del feed grande, que nunca se dispara porque el generador MJPEG
// deja la respuesta pendiente en vez de cerrarla (ver video-feed.spec.js).
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('la tarjeta RTSP muestra "Sin señal" cuando la camara configurada es inalcanzable', async ({ page }) => {
  await gotoHome(page);
  await page.locator('#tab-camara').click();

  const status = page.locator('#rtsp-status-text');
  await expect(status).toHaveText('Sin señal', { timeout: 15_000 });

  const dot = page.locator('#rtsp-dot');
  await expect(dot).toHaveClass(/bg-red-500/);
});
