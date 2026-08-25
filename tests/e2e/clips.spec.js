// Escenario "clips" (TEST-02, 6/10).
//
// Reutiliza la misma inyeccion de evento por WebSocket que live-event.spec.js,
// esta vez con media.clip_url relleno: la accion "Ver clip" de la fila
// (data-action="clip") solo llama a openClipModal(media.clip_url) si ese
// campo existe (timeline.js:_onListClick) -- se prueba justo esa condicion.
const { test, expect } = require('@playwright/test');
const { gotoHome, routeWsProxy } = require('./helpers');

function eventWithClipMessage() {
  return JSON.stringify({
    type: 'event',
    event: {
      id: 'e2e-fake-with-clip-1',
      type: 'LINE_CROSSED',
      camera_id: 'cam1',
      ts: new Date().toISOString(),
      severity: 'info',
      track_id: 7,
      person_id: null, person_name: null, zone_id: null, confidence: null,
      bbox: null, snapshot_path: null, recording_id: 99,
      payload: { direction: 'out', is_intrusion: false },
    },
    media: { recording_id: 99, clip_url: '/clips/e2e-fake-clip.mp4', thumbnail_url: null, snapshot_url: null },
  });
}

test('la accion "Ver clip" de una fila abre el modal con el video del clip', async ({ page }) => {
  const ws = await routeWsProxy(page);
  await gotoHome(page);
  await ws.send(eventWithClipMessage());

  const row = page.locator('#timeline-list .timeline-row[data-id="e2e-fake-with-clip-1"]');
  await expect(row).toBeVisible({ timeout: 5_000 });

  await row.locator('.row-action[data-action="clip"]').click();

  const modal = page.locator('#clip-modal');
  await expect(modal).toHaveClass(/open/);
  await expect(page.locator('#clip-video')).toHaveAttribute('src', '/clips/e2e-fake-clip.mp4');
});
