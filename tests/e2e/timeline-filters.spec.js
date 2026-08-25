// Escenario "filtros" (TEST-02, 5/10).
//
// Los filtros de la linea temporal se resuelven en SERVIDOR (OPS-09, T-30-30):
// el test protege exactamente eso -- que aplicar un chip de tipo viaja como
// parametro real a GET /api/v2/events, no que se recorte el array ya
// descargado en cliente. Filtrar por LINE_CROSSED da un resultado vacio
// porque la base de e2e no siembra ninguno -- pero SI puede tener un
// CAMERA_OFFLINE real (backend/main.py:_camera_watchdog, cada 10s, dispara
// solo con que la camara configurada este inalcanzable), asi que el test no
// asume que la lista arranque vacia (#timeline-empty): solo que el vacio
// FILTRADO (#timeline-empty-filtered) es el que se pinta tras aplicar, que
// es la senal que UI-SPEC pide distinguir del vacio "sin filtros".
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('aplicar un chip de tipo filtra la peticion al servidor y pinta el vacio filtrado', async ({ page }) => {
  await gotoHome(page);

  await page.locator('#tl-filter-types .filter-chip', { hasText: 'Cruce' }).click();

  const [request] = await Promise.all([
    page.waitForRequest((req) => req.url().includes('/api/v2/events') && req.url().includes('type=LINE_CROSSED')),
    page.locator('#btn-tl-apply').click(),
  ]);
  expect(new URL(request.url()).searchParams.get('type')).toBe('LINE_CROSSED');

  await expect(page.locator('#timeline-empty-filtered')).toBeVisible();
  await expect(page.locator('#timeline-empty')).toBeHidden();
  await expect(page.locator('#tl-active-filters')).toContainText('Cruce');

  await page.locator('#btn-tl-clear-empty').click();
  await expect(page.locator('#timeline-empty-filtered')).toBeHidden();
  await expect(page.locator('#tl-active-filters')).toBeEmpty();
});
