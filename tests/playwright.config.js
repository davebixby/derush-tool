// @ts-check
const { defineConfig, devices } = require('@playwright/test');

/**
 * Config Playwright pour Derush Tool.
 *
 * Le webServer launche le backend Python directement (mode dev), pas Electron.
 * Avantages: rapide, déterministe, pas de gestion de spawn Electron, frontend
 * identique à ce que voit l'utilisateur final puisque c'est le même HTML servi.
 *
 * Limites: ne couvre pas les specs Electron (splash, file dialogs, auto-update).
 * Pour ça, faudra un setup playwright-electron séparé plus tard.
 */
module.exports = defineConfig({
  testDir: '.',
  fullyParallel: false,        // tests touchent au même state serveur → série
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  timeout: 30000,
  reporter: process.env.CI ? 'github' : 'list',

  use: {
    baseURL: 'http://localhost:8765',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 8000,
    navigationTimeout: 15000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Spawn le backend Python directement (mode dev, sans Electron)
  webServer: {
    command: 'python ../derush_server.py --no-browser',
    url: 'http://localhost:8765',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
