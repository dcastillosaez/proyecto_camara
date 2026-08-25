// Escenario "alertas" (TEST-02, 9/10).
//
// No se asume badge/cajon vacios: backend/main.py:_camera_watchdog dispara un
// CAMERA_OFFLINE real (severidad CRITICAL, backend/events/types.py) en cuanto
// detecta la camara configurada inalcanzable, y GET /api/v2/alerts cuenta
// eventos por SEVERIDAD (backend/api/v2/alerts.py), no solo los que casan
// alguna regla -- asi que segun cuanto lleve corriendo el webServer al llegar
// a este test, puede haber 0 o 1 alertas activas de verdad. Lo que si es
// determinista y es lo que este escenario protege es la mecanica de foco del
// cajon (30-09): foco al boton de cerrar al abrir, foco de vuelta a la
// campana al cerrar con Escape -- funciona igual con el cajon vacio o no.
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('el centro de alertas abre y devuelve el foco a la campana al cerrar con Escape', async ({ page }) => {
  await gotoHome(page);

  await page.locator('#btn-alert-center').click();

  const drawer = page.locator('#alert-drawer');
  await expect(drawer).toHaveClass(/open/);
  await expect(page.locator('#btn-alert-close')).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(drawer).not.toHaveClass(/open/);
  await expect(page.locator('#btn-alert-center')).toBeFocused();
});
