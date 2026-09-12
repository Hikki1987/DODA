import { defineConfig, devices } from "@playwright/test";

// Deliberately no `webServer` here: a real run needs the backend up
// *and* seeded (backend/scripts/seed_e2e_demo.py) before the frontend can
// show anything real — Playwright's webServer option has no seeding hook,
// so orchestrating that lives in CI (.github/workflows/ci.yml, "e2e" job)
// and in the `npm run e2e` instructions in README.md instead.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    // Unset in CI, where `npx playwright install chromium` provides the
    // browser Playwright expects. Set locally to point at a pre-installed
    // Chromium whose revision doesn't match what this Playwright version
    // would otherwise try (and fail) to resolve on its own.
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
