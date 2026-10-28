import { defineConfig, devices } from "@playwright/test";

// The browser tests run against a whole stack: the api serving the built
// web client, a worker and the synthetic library (tools/smoke-compose.sh).
// They build on each other (the first creates the admin), so they run in
// order in one worker.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.KODEX_WEB_URL ?? "http://127.0.0.1:8000",
    locale: "sv-SE",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
