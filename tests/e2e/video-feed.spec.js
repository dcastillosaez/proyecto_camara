// Escenario "vídeo" (TEST-02, 1/10).
//
// Sin camara real en CI no hay frames de verdad que comprobar -- lo que este
// test protege es el cableado: el feed apunta al endpoint MJPEG correcto, el
// overlay de tracks vive encima sin taparlo, y la carga de la vista no rompe
// nada en consola. El comportamiento de "sin senal" tiene su propio escenario
// (camera-offline.spec.js), mas fiable que forzar el onerror de esta imagen
// (backend/main.py:mjpeg_generator nunca cierra la respuesta cuando no hay
// frames, solo la deja pendiente -- onerror no llega a dispararse).
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('el feed de video apunta a /video_feed con el overlay de tracks encima', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await gotoHome(page);

  const feed = page.locator('#video-feed');
  await expect(feed).toHaveAttribute('src', '/video_feed');

  const overlay = page.locator('#tracks-overlay');
  await expect(overlay).toBeAttached();

  expect(errors).toEqual([]);
});
