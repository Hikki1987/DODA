import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Deliberately its own seed run (E2E_ARCHIVE_ prefix) — this spec archives
// the seeded workspace, which would break every subsequent step of
// workspace.spec.ts's serial suite (and customer.spec.ts's) if they shared
// the same workspace, the same reason customer.spec.ts already gives for
// its own independent seed.
const SESSION_ID = requiredEnv("E2E_ARCHIVE_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_ARCHIVE_WORKSPACE_ID");
const CUSTOMER_ID = requiredEnv("E2E_ARCHIVE_CUSTOMER_ID");

test.describe.configure({ mode: "serial" });

test("archiving a workspace and restoring it from the customer page", async ({ page }) => {
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

  await test.step("archiving prompts for confirmation and, once accepted, redirects to /workspaces", async () => {
    page.once("dialog", (dialog) => dialog.accept());
    await page.click('button:has-text("Workspace\'ni arxivlash")');
    await page.waitForURL("**/workspaces");
  });

  await test.step("the archived workspace no longer appears in the workspace list", async () => {
    await expect(page.getByText("Demo Workspace")).toHaveCount(0);
  });

  await test.step("it does appear, and only there, in the customer page's archived section", async () => {
    await page.goto(`/customers/${CUSTOMER_ID}`);
    await expect(page.getByRole("heading", { name: "Arxivlangan workspace'lar" })).toBeVisible();
    await expect(page.locator('li:has-text("Demo Workspace")')).toBeVisible();
  });

  await test.step("restoring it removes it from the archived section", async () => {
    await page.click('li:has-text("Demo Workspace") >> button:has-text("Tiklash")');
    await expect(page.getByRole("heading", { name: "Arxivlangan workspace'lar" })).toHaveCount(0);
  });

  await test.step("and it is visible again on /workspaces", async () => {
    await page.goto("/workspaces");
    await expect(page.getByText("Demo Workspace")).toBeVisible();
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
