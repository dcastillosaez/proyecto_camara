// Escenario "PTZ" (TEST-02, 8/10).
//
// Sin una Tapo real, backend/ptz.py:_get_tapo() intenta conectar de verdad
// (constructor sincrono de pytapo, sin timeout propio configurado) antes de
// que FastAPI pueda devolver el 502 de backend/ptz.py:77 -- puede tardar
// mucho mas que cualquier timeout razonable de test. Lo que SI es
// determinista y es lo que de verdad protege el escenario "PTZ" (el
// cableado del frontend, no el comportamiento de pytapo sin red) es que el
// boton envia la direccion y los pasos correctos a POST /ptz/move.
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('mover la camara envia la direccion y los pasos correctos a POST /ptz/move', async ({ page }) => {
  await gotoHome(page);

  const [request] = await Promise.all([
    page.waitForRequest((req) => req.url().endsWith('/ptz/move') && req.method() === 'POST'),
    page.locator('.ptz-btn[data-dir="up"]').click(),
  ]);
  expect(request.postDataJSON()).toEqual({ direction: 'up', steps: expect.any(Number) });

  // El boton queda "busy" mientras la peticion sigue en vuelo -- confirma que
  // la UI sabe que la accion esta pendiente, sin esperar a que pytapo desista.
  await expect(page.locator('.ptz-btn[data-dir="up"]')).toHaveClass(/busy/);
});

// Fase 8: las flechas y el Espacio sobre un control (aqui, una pestana) son del
// control, no del PTZ. Con el foco en la pagina, la flecha sigue moviendo la camara.
test('las flechas sobre una pestana no mueven la camara; sobre la pagina si', async ({ page }) => {
  await gotoHome(page);
  const moves = [];
  page.on('request', (req) => {
    if (req.url().endsWith('/ptz/move')) moves.push(req.postDataJSON());
  });

  await page.locator('#tab-operaciones').focus();
  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(300);
  expect(moves).toEqual([]);

  await page.locator('#tab-operaciones').click();   // vuelve a Operaciones si la flecha cambio de pestana
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await page.keyboard.press('ArrowUp');
  await expect.poll(() => moves.length).toBe(1);
  expect(moves[0].direction).toBe('up');
});
