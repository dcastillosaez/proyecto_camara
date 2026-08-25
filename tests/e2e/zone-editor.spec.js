// Escenario "editor de zonas" (TEST-02, 10/10).
//
// Dibujar un poligono real sobre el canvas depende de las dimensiones reales
// del feed (que aqui no tiene un frame real que medir), asi que en vez de
// simular clics con coordenadas de pixel se prueba la validacion que SI es
// determinista: zoneEditor.js:_saveZone() rechaza el guardado en cliente con
// menos de 3 vertices, sin llegar a golpear la red -- mismo criterio que el
// resto de la suite, preferir lo que es reproducible sin camara real.
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('activar el modo edicion de zonas y guardar sin poligono muestra el error sin llamar al servidor', async ({ page }) => {
  await gotoHome(page);
  await page.locator('#tab-camara').click();

  let zonePostFired = false;
  page.on('request', (req) => {
    if (req.url().endsWith('/api/v2/zones') && req.method() === 'POST') zonePostFired = true;
  });

  const toggle = page.locator('#zone-mode-toggle');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');

  await page.locator('#zone-save-btn').click();

  const error = page.locator('#zone-error');
  await expect(error).toBeVisible();
  await expect(error).toHaveText('Poligono invalido: se necesitan al menos 3 vertices.');
  expect(zonePostFired).toBe(false);
});
