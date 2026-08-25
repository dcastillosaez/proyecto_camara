// Escenario "evento nuevo" (TEST-02, 4/10).
//
// Sin camara real no hay detecciones que disparen un evento de verdad. Se
// inyecta el mensaje {"type":"event", "event": {...}, "media": {...}} que
// backend/main.py:_broadcast_event manda por /ws (formato real, Fase 30
// OPS-10) directamente al cliente via page.routeWebSocket -- misma tecnica
// que ws-reconnect.spec.js, pero para inyectar en vez de cortar.
//
// No se asume que la linea temporal arranque vacia: backend/main.py trae un
// watchdog real (_camera_watchdog, cada 10s) que emite un CAMERA_OFFLINE de
// verdad en cuanto detecta la camara inalcanzable -- exactamente lo que pasa
// en la base de e2e. Pasados esos 10s el resto de tests de esta suite YA
// tienen ese evento real en la base, asi que la unica invariante fiable es
// "el evento inyectado aparece primero", no "la lista estaba vacia antes".
const { test, expect } = require('@playwright/test');
const { gotoHome, routeWsProxy } = require('./helpers');

function fakeLineCrossedMessage() {
  const now = new Date().toISOString();
  return JSON.stringify({
    type: 'event',
    event: {
      id: 'e2e-fake-line-crossed-1',
      type: 'LINE_CROSSED',
      camera_id: 'cam1',
      ts: now,
      severity: 'info',
      track_id: 42,
      person_id: null,
      person_name: null,
      zone_id: null,
      confidence: null,
      bbox: null,
      snapshot_path: null,
      recording_id: null,
      payload: { direction: 'in', is_intrusion: false, line_id: 'l1', line_name: 'Línea 1' },
    },
    media: { recording_id: null, clip_url: null, thumbnail_url: null, snapshot_url: null },
  });
}

test('un evento nuevo por WebSocket entra en la parte superior de la línea temporal', async ({ page }) => {
  const ws = await routeWsProxy(page);
  await gotoHome(page);
  await ws.send(fakeLineCrossedMessage());

  const firstRow = page.locator('#timeline-list .timeline-row').first();
  await expect(firstRow).toBeVisible({ timeout: 5_000 });
  await expect(firstRow).toHaveAttribute('data-id', 'e2e-fake-line-crossed-1');
  await expect(page.locator('#timeline-empty')).toBeHidden();
});
