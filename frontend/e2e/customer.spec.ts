import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Deliberately its own seed run (E2E_CUSTOMER_ prefix, distinct from
// workspace.spec.ts's E2E_ IDs) — this spec engages a customer-wide kill
// switch, which broadcasts a SECURITY_ALERT to every member and would
// otherwise leak into workspace.spec.ts's notification-count assertions
// if both specs shared one seeded customer/workspace/session.
const SESSION_ID = requiredEnv("E2E_CUSTOMER_SESSION_ID");
const CUSTOMER_ID = requiredEnv("E2E_CUSTOMER_CUSTOMER_ID");
const SECOND_USER_ID = requiredEnv("E2E_CUSTOMER_SECOND_USER_ID");

test.describe.configure({ mode: "serial" });

test("customer page: members, notification prefs, audit, kill switch", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("log in and navigate to the customer page via the workspaces list", async () => {
    await page.goto("/login");
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
    await page.getByText("Demo Customer").click();
    await page.waitForURL(`**/customers/${CUSTOMER_ID}`);
    await expect(page.getByRole("heading", { name: "Demo Customer" })).toBeVisible();
  });

  await test.step("owner is listed as a member", async () => {
    await expect(page.getByText("Demo User")).toBeVisible();
  });

  await test.step("invite the seeded second user as auditor, then re-role and remove them", async () => {
    await page.fill('input[placeholder="User ID (UUID)"]', SECOND_USER_ID);
    await page.selectOption('form:has(input[placeholder="User ID (UUID)"]) select', "auditor");
    await page.click("button:has-text(\"Qo'shish\")");
    await expect(page.getByText("Second User")).toBeVisible();

    const memberRow = page.locator('li:has-text("Second User")');
    await memberRow.locator("select").selectOption("member");
    await expect(memberRow.locator("select")).toHaveValue("member");

    await memberRow.getByRole("button", { name: "Chiqarish" }).click();
    await expect(page.getByText("Second User")).toHaveCount(0);
  });

  await test.step("audit reflects the invite/role-change/remove sequence", async () => {
    await expect(page.getByText("customer.member_invited.v1")).toBeVisible();
    await expect(page.getByText("customer.member_role_changed.v1")).toBeVisible();
    await expect(page.getByText("customer.member_removed.v1")).toBeVisible();
  });

  await test.step("toggle a notification preference off and back on", async () => {
    const prefRow = page.locator('li:has-text("FAILED_ACTION")');
    await prefRow.getByRole("button").click();
    await expect(prefRow.getByRole("button", { name: "Yoqish" })).toBeVisible();
    await prefRow.getByRole("button", { name: "Yoqish" }).click();
    await expect(prefRow.getByRole("button", { name: "O'chirish" })).toBeVisible();
  });

  await test.step("SECURITY_ALERT preference has no toggle button", async () => {
    const alertRow = page.locator('li:has-text("SECURITY_ALERT")');
    await expect(alertRow.getByRole("button")).toHaveCount(0);
    await expect(alertRow.getByText("doim yoqilgan")).toBeVisible();
  });

  await test.step("engage and disengage the customer kill switch", async () => {
    await page.fill('input[placeholder="Sabab"]', "E2E test");
    await page.click('form:has(input[placeholder="Sabab"]) button[type="submit"]');
    await expect(page.getByText("Faol.")).toBeVisible();

    await page.click('div:has-text("Faol.") >> button:has-text("O\'chirish")');
    await expect(page.getByText("Faol.")).toHaveCount(0);
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
