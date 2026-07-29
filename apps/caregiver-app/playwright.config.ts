import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end config for the offline clock-in path.
 *
 * Runs against the built app served by `vite preview`, not the dev server, because the service
 * worker is only registered in a production build and a dev-server bundle would not exercise
 * the shell caching this app depends on.
 *
 * A phone viewport with touch, not a desktop window: the primary action is fixed to the bottom
 * of the viewport and its reachability is part of what is being tested.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  // Serial and single-worker on purpose. The tests share one API tenant and toggle the
  // browser's network state, which is a per-context setting that parallel tests would fight
  // over — one test going offline would break another mid-request.
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: process.env.CI ? "list" : "line",
  use: {
    ...devices["Pixel 7"],
    baseURL: "http://localhost:3001",
    // Honour a preinstalled browser when one is provided. Sandboxed environments ship a
    // Chromium whose build number will not match whatever this pinned Playwright expects, and
    // downloading a second copy to satisfy the version check is both slow and often blocked.
    // Unset — as on a normal machine or in CI after `playwright install` — this is ignored.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
      : {},
    // Grant up front so the geolocation prompt never blocks a clock-in, and set a fix so the
    // GPS path is what runs by default; the no-GPS path is tested by revoking it.
    permissions: ["geolocation"],
    geolocation: { latitude: 43.1566, longitude: -77.6088 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview",
    url: "http://localhost:3001",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
