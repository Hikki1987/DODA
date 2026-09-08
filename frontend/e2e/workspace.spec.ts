import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

const SESSION_ID = requiredEnv("E2E_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_WORKSPACE_ID");

test.describe.configure({ mode: "serial" });

test("login, workspace, task, notification, action, audit flow", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("root redirects to /login when no session is stored", async () => {
    await page.goto("/");
    await page.waitForURL("**/login");
  });

  await test.step("log in with the seeded session id", async () => {
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
    await expect(page.getByText("Demo Workspace")).toBeVisible();
  });

  await test.step("open the seeded workspace", async () => {
    await page.getByText("Demo Workspace").click();
    await page.waitForURL(`**/workspaces/${WORKSPACE_ID}`);
  });

  await test.step("seeded R3 action produced a PENDING_APPROVAL notification", async () => {
    await expect(page.getByText("PENDING_APPROVAL")).toBeVisible();
  });

  await test.step("actions section shows the seeded send_email action", async () => {
    await expect(page.getByText("send_email")).toBeVisible();
    await expect(page.getByText("risk: R3")).toBeVisible();
    // exact: true — "AWAITING_APPROVAL" (the status badge) is otherwise a
    // case-insensitive substring match of the audit section's own
    // "action.awaiting_approval.v1" event further down the same page.
    await expect(page.getByText("AWAITING_APPROVAL", { exact: true })).toBeVisible();
  });

  await test.step("create a task and advance its status", async () => {
    await page.fill('input[placeholder="Yangi task nomi"]', "E2E test task");
    await page.click("button:has-text(\"Qo'shish\")");
    await expect(page.getByText("E2E test task")).toBeVisible();

    await page.click('button:has-text("IN_PROGRESS qilish")');
    await expect(page.getByText("DONE qilish")).toBeVisible();
  });

  await test.step("task history shows the TODO -> IN_PROGRESS transition", async () => {
    const taskRow = page.locator('li:has-text("E2E test task")');
    await taskRow.getByRole("button", { name: "Tarix" }).click();
    await expect(page.getByText("TODO → IN_PROGRESS")).toBeVisible();
    await taskRow.getByRole("button", { name: "Tarixni yashirish" }).click();
  });

  await test.step("mark the notification read", async () => {
    await page.click("button:has-text(\"O'qildi deb belgilash\")");
    await expect(page.getByText("O'qildi deb belgilash")).toHaveCount(0);
  });

  await test.step("members section shows the owner", async () => {
    await expect(page.getByText("Demo User")).toBeVisible();
  });

  await test.step("audit section shows the real workspace.created.v1 event", async () => {
    await expect(page.getByText("workspace.created.v1")).toBeVisible();
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
