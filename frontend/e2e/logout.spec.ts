import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Its own seed (E2E_LOGOUT_) — this spec revokes the seeded session, which
// would break every other spec's remaining steps if they shared it.
const SESSION_ID = requiredEnv("E2E_LOGOUT_SESSION_ID");

test.describe.configure({ mode: "serial" });

test("logging out actually revokes the session server-side, not just locally", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("log in with the seeded session id", async () => {
    await page.goto("/login");
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
  });

  await test.step("this session works over the API before logging out", async () => {
    const response = await page.request.get("http://localhost:8000/v1/sessions", {
      headers: { Authorization: `Bearer ${SESSION_ID}` },
    });
    expect(response.status()).toBe(200);
  });

  await test.step("click Chiqish and land on /login", async () => {
    await page.click('button:has-text("Chiqish")');
    await page.waitForURL("**/login");
  });

  await test.step("the same session id is now rejected by the backend itself", async () => {
    // Not a UI check — this proves logOut() actually called DELETE
    // /v1/sessions/{id} server-side, rather than only clearing
    // localStorage and leaving the raw session token (Authorization:
    // Bearer <id>) usable via a direct API call.
    const response = await page.request.get("http://localhost:8000/v1/sessions", {
      headers: { Authorization: `Bearer ${SESSION_ID}` },
    });
    expect(response.status()).toBe(401);
    const body = await response.json();
    expect(body.code).toBe("UNAUTHENTICATED");
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
