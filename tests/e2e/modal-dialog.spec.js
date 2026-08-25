// Escenario "modales" (TEST-02, 7/10).
//
// Mecanica generica de dialogo (no la logica de negocio de clips.spec.js):
// role="dialog" + aria-modal, cierre con Escape y cierre al hacer click en el
// fondo (backdrop), sobre el mismo #clip-modal por ser el mas simple de
// abrir sin datos sembrados en la base (eventCard.js:openClipModal solo
// necesita una URL, sin llamada al servidor).
const { test, expect } = require('@playwright/test');
const { gotoHome } = require('./helpers');

test('el modal de clip es un dialogo accesible que se cierra con Escape', async ({ page }) => {
  await gotoHome(page);

  await page.evaluate(() => {
    const modal = document.getElementById('clip-modal');
    const vid = document.getElementById('clip-video');
    vid.src = '/clips/e2e-fake-clip.mp4';
    modal.classList.add('open');
  });

  const modal = page.locator('#clip-modal');
  await expect(modal).toHaveAttribute('role', 'dialog');
  await expect(modal).toHaveAttribute('aria-modal', 'true');
  await expect(modal).toHaveClass(/open/);

  await page.keyboard.press('Escape');
  await expect(modal).not.toHaveClass(/open/);
  await expect(page.locator('#clip-video')).toHaveAttribute('src', '');
});

test('el modal de clip se cierra al hacer click en el fondo', async ({ page }) => {
  await gotoHome(page);

  await page.evaluate(() => {
    const modal = document.getElementById('clip-modal');
    document.getElementById('clip-video').src = '/clips/e2e-fake-clip.mp4';
    modal.classList.add('open');
  });

  const modal = page.locator('#clip-modal');
  await expect(modal).toHaveClass(/open/);

  // Click en el propio contenedor (el fondo), no en el <video> que tiene dentro --
  // eventCard.js solo cierra si e.target === e.currentTarget.
  await modal.click({ position: { x: 2, y: 2 } });
  await expect(modal).not.toHaveClass(/open/);
});
