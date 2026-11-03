// DEBT-01 / SEC-09: el dashboard funciona sin internet.
//
// Se bloquea cualquier peticion que no vaya al propio backend. Antes, sin red,
// `new Chart(...)` lanzaba al evaluar dashboard-events.js, que app.js importa de
// forma estatica, y moria toda la interfaz, video incluido. Ahora Tailwind,
// Chart.js y las fuentes vienen de frontend/vendor/.
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('sin acceso a internet la interfaz carga completa, con estilos y graficas', async ({ page, baseURL }) => {
  const external = [];
  const pageErrors = [];
  const origin = new URL(baseURL).origin;
  await page.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith(origin) || url.startsWith('data:') || url.startsWith('blob:')) {
      return route.continue();
    }
    external.push(url);
    return route.abort('internetdisconnected');
  });
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await gotoHome(page);

  // Chart.js y el runtime de Tailwind estan cargados y aplican estilos.
  await expect.poll(() => page.evaluate(() => typeof window.Chart)).toBe('function');
  const headerBg = await page.locator('header').evaluate((el) => getComputedStyle(el).position);
  expect(headerBg).toBe('sticky');               // clase Tailwind `sticky` aplicada

  // La interfaz sigue viva: la navegacion entre vistas responde.
  await page.locator('#tab-analitica').click();
  await expect(page.locator('#tab-analitica')).toHaveAttribute('aria-selected', 'true');

  expect(external, `peticiones a hosts externos: ${external.join(', ')}`).toEqual([]);
  expect(pageErrors).toEqual([]);
});
