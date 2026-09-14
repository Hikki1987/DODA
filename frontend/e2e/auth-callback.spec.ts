import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Its own seed (E2E_AUTHCALLBACK_) — same reasoning as every other spec
// here: avoid sharing mutable state with specs running in parallel.
const SESSION_ID = requiredEnv("E2E_AUTHCALLBACK_SESSION_ID");

// This cannot drive the real Google OAuth redirect (no live Google
// account in CI) — see backend/src/doda/infrastructure/
// google_oidc_client.py and tests/integration/test_auth_api.py for what
// IS verified end-to-end on the backend side (the full /login ->
// /callback exchange, with only the Google network leg stubbed). What
// this spec proves instead: the frontend half of the handoff the backend
// redirect hands off to — /auth/callback reading ?session_id=, validating
// it against the real backend, storing it, and landing on /workspaces —
// using a session minted the same dev/test way every other spec's login
// step does, just arriving via the callback route instead of the login
// form.
test.describe.configure({ mode: "serial" });

test("a session id arriving via the callback route is accepted and lands on /workspaces", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto(`/auth/callback?session_id=${SESSION_ID}`);
  await page.waitForURL("**/workspaces");

  // Not UI-only: confirm localStorage actually holds the session id the
  // rest of the app reads from (same contract session.ts documents).
  const stored = await page.evaluate(() => localStorage.getItem("doda.sessionId"));
  expect(stored).toBe(SESSION_ID);

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});

test("a callback with no session_id shows an error instead of crashing", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto("/auth/callback");

  await expect(page.getByText("session_id parametri topilmadi")).toBeVisible();
  await expect(page.getByRole("link", { name: "Qaytadan kirish" })).toHaveAttribute("href", "/login");

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});

test("an unknown session_id shows the backend's rejection, not a crash", async ({ page }) => {
  // Unlike the other two cases, this one deliberately makes the page's
  // own fetch() receive a real 401 — Chrome itself always logs a "Failed
  // to load resource: 401" console error for that, independent of
  // whether the app handles the response gracefully, so only uncaught
  // exceptions (pageerror) are the real "did it crash" signal here.
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto("/auth/callback?session_id=00000000-0000-0000-0000-000000000000");

  await expect(page.getByRole("link", { name: "Qaytadan kirish" })).toBeVisible();

  expect(pageErrors, `unexpected uncaught exceptions: ${pageErrors.join("\n")}`).toEqual([]);
});
