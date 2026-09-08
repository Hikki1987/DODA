import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Deliberately its own seed run (E2E_KILLSWITCH_ prefix) — this spec
// engages the workspace's own kill switch, which blocks new actions in
// that workspace; sharing a seed with workspace.spec.ts (which proposes
// an action) would make the two specs order-dependent.
const SESSION_ID = requiredEnv("E2E_KILLSWITCH_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_KILLSWITCH_WORKSPACE_ID");

test.describe.configure({ mode: "serial" });

test("workspace kill switch: engage blocks new actions, disengage reopens", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("log in and open the seeded workspace", async () => {
    await page.goto("/login");
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
    await page.getByText("Demo Workspace").click();
    await page.waitForURL(`**/workspaces/${WORKSPACE_ID}`);
  });

  await test.step("engage the workspace kill switch with a reason", async () => {
    await page.fill('input[placeholder="Sabab"]', "E2E workspace kill switch test");
    await page.click('form:has(input[placeholder="Sabab"]) button[type="submit"]');
    await expect(page.getByText("Faol.")).toBeVisible();
  });

  await test.step("this is real, not UI-only: the backend itself now blocks a new action", async () => {
    // Hitting the API directly (not through the page's own fetch) proves
    // the engage click actually persisted server-side and blocks new
    // work, not just that the banner rendered.
    const response = await page.request.post(`http://localhost:8000/v1/workspaces/${WORKSPACE_ID}/actions`, {
      headers: { Authorization: `Bearer ${SESSION_ID}`, "Idempotency-Key": "e2e-ks-blocked-check" },
      data: { tool_name: "knowledge.read", risk_level: "R1", payload: {} },
    });
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.code).toBe("KILL_SWITCH_ENGAGED");
  });

  await test.step("disengage clears the banner and reopens the workspace", async () => {
    await page.click('div:has-text("Faol.") >> button:has-text("O\'chirish")');
    await expect(page.getByText("Faol.")).toHaveCount(0);

    const response = await page.request.post(`http://localhost:8000/v1/workspaces/${WORKSPACE_ID}/actions`, {
      headers: { Authorization: `Bearer ${SESSION_ID}`, "Idempotency-Key": "e2e-ks-reopened-check" },
      data: { tool_name: "knowledge.read", risk_level: "R1", payload: {} },
    });
    expect(response.status()).toBe(200);
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
