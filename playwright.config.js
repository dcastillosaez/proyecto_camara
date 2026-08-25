// playwright.config.js -- Fase 34 (TEST-02, TEST-03).
//
// Levanta el backend real (uvicorn) contra una base SQLite propia y aislada
// (data/e2e-events.db, fuera de la que usa el desarrollador) y un puerto
// distinto del de desarrollo (8011 vs 8000) para no chocar con un servidor ya
// arrancado a mano. CAMERA_URL se deja en su valor por defecto (una Tapo real
// en la LAN del usuario, inalcanzable aqui y en CI): eso es exactamente el
// escenario "camara offline" que TEST-02 pide cubrir, no hace falta simularlo.
//
// El ejecutable de Python cambia entre este equipo (venv en .venv/, Windows)
// y GitHub Actions (ubuntu-latest, `pip install` contra el Python del runner,
// sin venv) -- de ahi la deteccion por plataforma en vez de una ruta fija.
const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const PYTHON = process.platform === 'win32'
  ? path.resolve(__dirname, '.venv/Scripts/python.exe')
  : 'python';
const PORT = 8011;
const DB_PATH = 'data/e2e-events.db';

module.exports = defineConfig({
  testDir: './tests/e2e',
  // workers: 1 siempre -- todos los tests comparten UN unico webServer (un solo
  // proceso uvicorn, un solo events.db) en vez de un backend aislado por test, asi
  // que correrlos en paralelo genera contencion real (peticiones que se pisan sobre
  // la misma conexion SQLite/loop de asyncio) y falsos negativos, no solo lentitud.
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,

  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],

  webServer: {
    command: `${PYTHON} -m uvicorn backend.main:app --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { DB_PATH },
  },
});
