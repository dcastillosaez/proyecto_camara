// Vista Ajustes (Fase 32, puerta 32-08).
//
// Cubre los dos bugs que encontró el checkpoint visual de la fase y que ningún test
// automatizado veía:
//   1. Editar un campo nunca mostraba la barra "Guardar cambios": trackChange() solo
//      apuntaba el valor en memoria, así que no había forma de guardar desde Ajustes.
//   2. Ajustes arranca en segundo plano con cualquier hash y lo reescribía:
//      #camara acababa como #ajustes/camara y recargar llevaba a Ajustes.
const { test, expect } = require('@playwright/test');

// La API v2 limita a 60 peticiones/minuto por IP en ventana fija (backend/api/v2/deps.py)
// y cada carga del dashboard ya gasta unas 15. Tras los specs anteriores de la suite, el
// GET /api/v2/config de Ajustes recibía 429 y el árbol no se pintaba nunca. Este helper
// agota lo que quede de la ventana y espera a la siguiente, así el test arranca con el
// cupo entero sin tocar la política del servidor.
async function waitForFreshRateWindow(request) {
  for (let i = 0; i < 70; i++) {
    if ((await request.get('/api/v2/config')).status() === 429) break;
  }
  await expect.poll(async () => (await request.get('/api/v2/config')).status(), {
    timeout: 70_000, intervals: [2_000],
  }).toBe(200);
}

// Deja la sección Detección como estaba aunque el test falle a medias: la BD de E2E
// es compartida por todos los specs (workers: 1).
test.afterEach(async ({ request }) => {
  await request.post('/api/v2/config/deteccion/restore');
});

test('editar un campo muestra la barra de guardado, el 422 va junto al campo y guardar persiste', async ({ page }) => {
  await page.goto('/#ajustes/deteccion', { waitUntil: 'domcontentloaded' });

  const confRow = page.locator('.cfg-row[data-field-key="yolo_confidence"]');
  const labelRow = page.locator('.cfg-row[data-field-key="detection_label"]');
  const confInput = confRow.locator('input[type="number"]');
  const labelInput = labelRow.locator('input[type="text"]');
  const saveBar = page.locator('.cfg-savebar');

  // Pasar el foco sin cambiar nada no cuenta como cambio.
  await confInput.focus();
  await confInput.blur();
  await expect(saveBar).toHaveCount(0);

  await confInput.fill('1.5');
  await confInput.blur();
  await labelInput.fill('persona');
  await labelInput.blur();

  await expect(saveBar).toContainText('2 cambios sin guardar');
  await expect(confRow).toHaveClass(/dirty/);
  await expect(labelRow).toHaveClass(/dirty/);

  await saveBar.getByRole('button', { name: 'Guardar cambios' }).click();
  await expect(confRow).toContainText('Debe estar entre 0.05 y 0.95');
  await expect(labelRow).toHaveClass(/dirty/);   // la fila válida sigue pendiente

  await confInput.fill('0.6');
  await confInput.blur();
  await saveBar.getByRole('button', { name: 'Guardar cambios' }).click();
  await expect(saveBar).toHaveCount(0);

  const cfg = await (await page.request.get('/api/v2/config')).json();
  const fields = cfg.sections.flatMap((s) => s.groups.flatMap((g) => g.fields ?? []));
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  expect(byKey.yolo_confidence.value).toBe(0.6);
  expect(byKey.yolo_confidence.origin).toBe('runtime');
  expect(byKey.detection_label.value).toBe('persona');
});

test('volver al valor original deja la fila limpia y sin barra de guardado', async ({ page }) => {
  await page.goto('/#ajustes/deteccion', { waitUntil: 'domcontentloaded' });
  const labelRow = page.locator('.cfg-row[data-field-key="detection_label"]');
  const labelInput = labelRow.locator('input[type="text"]');
  const original = await labelInput.inputValue();

  await labelInput.fill(`${original}-x`);
  await labelInput.blur();
  await expect(page.locator('.cfg-savebar')).toContainText('1 cambio sin guardar');

  await labelInput.fill(original);
  await labelInput.blur();
  await expect(page.locator('.cfg-savebar')).toHaveCount(0);
  await expect(labelRow).not.toHaveClass(/dirty/);
});

test('Ajustes no reescribe el hash de otra vista y responde a #ajustes/{sección}', async ({ page, request }) => {
  test.setTimeout(120_000);
  await waitForFreshRateWindow(request);
  // El arbol (y la reescritura del hash que se vigila) llega tras cargar el esquema: se
  // espera a esa respuesta, no a un plazo fijo que la suite completa bajo carga agota.
  const schema = page.waitForResponse((r) => r.url().endsWith('/api/v2/config') && r.ok(), { timeout: 20_000 });
  await page.goto('/#camara', { waitUntil: 'domcontentloaded' });
  await schema;
  await expect(page.locator('#settings-tree [role="tab"]').first()).toBeAttached({ timeout: 30_000 });
  await expect.poll(() => page.evaluate(() => location.hash)).toBe('#camara');

  await page.evaluate(() => { location.hash = '#ajustes/alertas'; });
  await expect(page.locator('#settings-tree [role="tab"][aria-selected="true"]')).toHaveText('Alertas');
});
