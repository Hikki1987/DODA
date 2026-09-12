import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

const AUDITOR_SESSION_ID = requiredEnv("E2E_AUDITOR_AUDITOR_SESSION_ID");
const CUSTOMER_ID = requiredEnv("E2E_AUDITOR_CUSTOMER_ID");
const WORKSPACE_ID = requiredEnv("E2E_AUDITOR_WORKSPACE_ID");

test.describe.configure({ mode: "serial" });

// A CustomerRole.AUDITOR is read-only (10.2) and therefore holds no workspace
// role at all, which makes them the one identity whose whole experience runs
// through the customer page. Until GET /v1/me/customers existed they had no
// route to it: /v1/me/workspaces is workspace-shaped and returns nothing for
// them, so the app offered a logged-in auditor a blank screen and no link.
test("a read-only auditor can reach their customer page and nothing else", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("log in as the auditor", async () => {
    await page.goto("/login");
    await page.fill("#session-id", AUDITOR_SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
  });

  await test.step("no workspaces are listed, but the customer is", async () => {
    await expect(page.locator("a[href^='/workspaces/']")).toHaveCount(0);
    const section = page.locator("section", { hasText: "Customer'larim" });
    await expect(section.getByRole("link", { name: "Demo Customer" })).toBeVisible();
    await expect(section.getByText("auditor")).toBeVisible();
  });

  await test.step("the customer page opens, named, with the audit view they are entitled to", async () => {
    await page
      .locator("section", { hasText: "Customer'larim" })
      .getByRole("link", { name: "Demo Customer" })
      .click();
    await page.waitForURL(`**/customers/${CUSTOMER_ID}`);
    // The heading comes from /v1/me/customers: sourcing it from
    // /v1/me/workspaces (as this page first did) left it reading "Customer"
    // for exactly this user, since they have no workspace row to read it from.
    await expect(page.getByRole("heading", { name: "Demo Customer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Audit" })).toBeVisible();
    // workspace.created.v1 is the seed's own first customer-scoped event, so
    // it is there for every seeded customer regardless of what else ran.
    await expect(page.getByText("workspace.created.v1").first()).toBeVisible();
  });

  await test.step("the workspace itself stays closed to them", async () => {
    // Checked against the backend directly rather than through the UI: the
    // point is that authorization denies it, not that no link is rendered.
    const response = await page.request.get(
      `http://localhost:8000/v1/workspaces/${WORKSPACE_ID}/tasks`,
      { headers: { Authorization: `Bearer ${AUDITOR_SESSION_ID}` } },
    );
    expect(response.status()).toBe(403);
    expect((await response.json()).code).toBe("DENY");
  });

  // One 403 is expected and not a defect: the customer page fetches
  // .../workspaces/archived unconditionally, which is CustomerOwner-only
  // (authorize_view_archived_workspaces), and swallows the rejection. That is
  // this app's deliberate convention — no role-based UI gating, the backend
  // decides — and a browser logs every 403 response to the console whatever
  // the page does with it. Everything else must still be clean.
  const unexpected = consoleErrors.filter((text) => !text.includes("403 (Forbidden)"));
  expect(unexpected).toEqual([]);
});
