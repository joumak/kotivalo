import { defineConfig, devices } from '@playwright/test'

// End-to-end tests against a real `kotivalo serve --fake` (in-memory lamps, no radio).
// Needs the Python venv (../.venv) and a UI build (npm run build).
const PORT = 8098

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${PORT}`, locale: 'fi-FI', colorScheme: 'dark' },
  projects: [
    { name: 'phone', use: { ...devices['Pixel 7'] } },
    { name: 'tablet', use: { viewport: { width: 1180, height: 820 }, hasTouch: true } },
  ],
  webServer: {
    command: `rm -rf test-results/e2e-state && ../.venv/bin/kotivalo --state-dir test-results/e2e-state serve --fake --fake-lamps 3 --fake-sensors 1 --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/state`,
    reuseExistingServer: false,
  },
})
