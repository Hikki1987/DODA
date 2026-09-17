import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

const SESSION_ID = requiredEnv("E2E_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_WORKSPACE_ID");
const CUSTOMER_ID = requiredEnv("E2E_CUSTOMER_ID");

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

  await test.step("customer-scoped access is listed separately from workspaces", async () => {
    // /v1/me/workspaces is workspace-shaped, so it cannot surface a customer
    // with no workspaces — nor a member who holds no workspace role at all,
    // such as an auditor, whose access (customer audit view, notification
    // preferences, kill switch, archived workspaces) lives entirely on the
    // customer page. Scoped to the section because the customer name also
    // appears on the workspace row above.
    const section = page.locator("section", { hasText: "Customer'larim" });
    await expect(section.getByRole("link", { name: "Demo Customer" })).toHaveAttribute(
      "href",
      `/customers/${CUSTOMER_ID}`,
    );
  });

  await test.step("open the seeded workspace", async () => {
    await page.getByText("Demo Workspace").click();
    await page.waitForURL(`**/workspaces/${WORKSPACE_ID}`);
  });

  await test.step("a hard reload does not bounce an authenticated user to /login", async () => {
    // Regression test: useSession's first client render has to report
    // sessionId as unresolved to match the server-rendered HTML, but an
    // earlier version conflated that transient state with "definitely
    // logged out" and redirected before the real localStorage value could
    // ever be read — a real reload of any authenticated page bounced the
    // user to /login even with a perfectly valid session. See useSession.ts.
    await page.reload();
    await page.waitForTimeout(1000);
    expect(page.url()).toContain(`/workspaces/${WORKSPACE_ID}`);
  });

  await test.step("seeded R3 action produced a PENDING_APPROVAL notification", async () => {
    await expect(page.getByText("PENDING_APPROVAL")).toBeVisible();
  });

  await test.step("actions section shows the seeded send_email action", async () => {
    // exact: true — FR-ACT-002's own dry-run preview for this
    // unregistered tool ("'send_email' tool'i uchun...") contains the
    // substring "send_email" too, so a non-exact getByText now matches
    // both the tool-name span and the preview paragraph (strict-mode
    // violation) — the same ambiguity class documented elsewhere in this
    // codebase, this time from the preview text itself.
    await expect(page.getByText("send_email", { exact: true })).toBeVisible();
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

  await test.step("a task with a due date appears in the daily plan (FR-TASK-002)", async () => {
    const dueSoon = new Date(Date.now() + 60 * 60 * 1000); // 1 hour from now
    const localValue = new Date(dueSoon.getTime() - dueSoon.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
    await page.fill('input[placeholder="Yangi task nomi"]', "E2E plan task");
    await page.fill('input[aria-label="Muddat (ixtiyoriy)"]', localValue);
    await page.click("button:has-text(\"Qo'shish\")");

    // Both the main task list and the "Reja" panel render this same task
    // title (confirmed failing in CI: an unscoped locator matched both
    // <li> elements, a strict-mode violation) — each assertion is scoped
    // to its own testid so they can't collide.
    const taskList = page.getByTestId("task-list");
    await expect(taskList.locator('li:has-text("E2E plan task")')).toBeVisible();

    const planPanel = page.getByTestId("task-plan");
    await expect(planPanel.getByText("E2E plan task")).toBeVisible();
  });

  await test.step("recording a task decision (FR-TASK-003) shows it, and a revised decision adds a new version rather than replacing it", async () => {
    const taskRow = page.locator('[data-testid="task-list"] li:has-text("E2E test task")');
    await taskRow.getByRole("button", { name: "Qarorlar" }).click();
    await taskRow.getByLabel("Variant").fill("Postgres vs SQLite");
    await taskRow.getByLabel("Kelishuv (tradeoff)").fill("server dependency vs no concurrent writers");
    await taskRow.getByLabel("Qaror").fill("Postgres");
    await taskRow.getByLabel("Sabab").fill("already required elsewhere");
    await taskRow.getByRole("button", { name: "Qaror yozish" }).click();
    await expect(taskRow.getByText("Postgres", { exact: true })).toBeVisible();

    // A revised decision must appear ALONGSIDE the first, not replace it —
    // this is FR-TASK-003's own acceptance criterion ("oldingi versiya
    // o'chirilmaydi"), checked here at the UI level too.
    await taskRow.getByLabel("Variant").fill("Postgres vs SQLite");
    await taskRow.getByLabel("Kelishuv (tradeoff)").fill("need cross-process pub/sub too");
    await taskRow.getByLabel("Qaror").fill("Redis");
    await taskRow.getByLabel("Sabab").fill("pub/sub requirement emerged later");
    await taskRow.getByRole("button", { name: "Qaror yozish" }).click();
    await expect(taskRow.getByText("Postgres", { exact: true })).toBeVisible();
    await expect(taskRow.getByText("Redis", { exact: true })).toBeVisible();

    await taskRow.getByRole("button", { name: "Qarorlarni yashirish" }).click();
  });

  await test.step("requesting and confirming a reminder (FR-TASK-005) shows it as CONFIRMED", async () => {
    const taskRow = page.locator('[data-testid="task-list"] li:has-text("E2E test task")');
    await taskRow.getByRole("button", { name: "Eslatmalar" }).click();

    const remindAt = new Date(Date.now() + 24 * 60 * 60 * 1000); // 1 day from now
    const localValue = new Date(remindAt.getTime() - remindAt.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
    await taskRow.getByLabel("Eslatma vaqti").fill(localValue);
    await taskRow.getByRole("button", { name: "Eslatma so'rash" }).click();

    const reminderList = taskRow.getByTestId("reminder-list");
    await expect(reminderList.getByText("PENDING_CONFIRMATION")).toBeVisible();

    await reminderList.getByRole("button", { name: "Tasdiqlash" }).click();
    // Not exact: the <li>'s full text is "<date> — CONFIRMED" (PENDING_
    // CONFIRMATION is the only other status that could collide, and it
    // doesn't share the substring "CONFIRMED").
    await expect(reminderList.getByText("CONFIRMED")).toBeVisible();

    await taskRow.getByRole("button", { name: "Eslatmalarni yashirish" }).click();
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

  await test.step("exporting my data on /sessions downloads a real file containing my own task", async () => {
    await page.goto("/sessions");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click('button:has-text("Eksport qilish")'),
    ]);
    expect(download.suggestedFilename()).toMatch(/^doda-export-\d{4}-\d{2}-\d{2}\.json$/);
    const exportedPath = await download.path();
    const fs = await import("node:fs/promises");
    const exported = JSON.parse(await fs.readFile(exportedPath!, "utf-8"));
    // The task created earlier in this same test — proves the export is a
    // real GET /v1/me/export round-trip, not a placeholder file.
    expect(exported.tasks.some((t: { title: string }) => t.title === "E2E test task")).toBe(true);
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
