import { defineConfig, devices } from '@playwright/test';

// PLAYWRIGHT_TEST_BASE_URL, when set, points the suite at a real deployed
// target (e.g. staging.madeforseconds.pages.dev) instead of a local dev
// server. In that case `webServer` must be omitted entirely — Playwright's
// `command: 'npm run dev'` always binds to localhost, so keeping it around
// while `url` points at a remote origin used to mean Playwright would wait
// forever for a local server to answer at a URL it never actually served
// (found while wiring this up for the staging target, Epic 8 story 8.5 —
// the old config had never been exercised against anything but localhost).
const remoteBaseURL = process.env.PLAYWRIGHT_TEST_BASE_URL;

export default defineConfig({
  testDir: './tests-e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: remoteBaseURL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    viewport: { width: 1280, height: 720 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  // Local dev server only — never started against a remote target. See the
  // comment on remoteBaseURL above.
  webServer: remoteBaseURL
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:5173',
        reuseExistingServer: !process.env.CI,
      },
});
