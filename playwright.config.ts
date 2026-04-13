import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  timeout: process.env.CI ? 60_000 : 30_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['html', { outputFolder: 'test-results/html', open: 'never' }],
    ['json', { outputFile: 'test-results/results.json' }],
    ['list', { printSteps: true }],
    ['junit', { outputFile: 'test-results/junit.xml' }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'https://qa3.gps.aegm.com',
    // retain-on-failure: trace zip for post-mortem (executor attaches paths via run_playwright_tests)
    trace: process.env.CI ? 'retain-on-failure' : 'on-first-retry',
    // CI: screenshot after every test (pass + fail) so executor can upload evidence to Qase; local: failures only
    screenshot: process.env.CI
      ? { mode: 'on', fullPage: true }
      : 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // Enhanced debugging for headless mode
    launchArgs: [
      '--disable-blink-features=AutomationControlled',
      '--disable-dev-shm-usage', // Disable /dev/shm to fix memory issues
    ],
  },
  projects: [
    {
      name: 'chromium',
      use: { 
        ...devices['Desktop Chrome'],
        // Enable verbose logging
        launchArgs: [
          '--disable-blink-features=AutomationControlled',
          '--disable-dev-shm-usage',
        ],
      },
    },
  ],
  webServer: undefined,
});
