import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Deliberately its own seed run (E2E_ATTACH_ prefix) — this spec uploads
// and deletes a real Document row (same "each mutating spec gets its own
// seed" convention as knowledge.spec.ts/workspace-kill-switch.spec.ts),
// and creates its own task rather than reusing workspace.spec.ts's
// "E2E test task" so the two specs' task lists never collide.
const SESSION_ID = requiredEnv("E2E_ATTACH_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_ATTACH_WORKSPACE_ID");

test.describe.configure({ mode: "serial" });

test("FR-TASK-006: attaching a document, then deleting it, marks the link broken rather than dropping it", async ({
  page,
}) => {
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

  await test.step("upload a document and create a task", async () => {
    await page.setInputFiles('input[aria-label="Yuklanadigan fayl"]', {
      name: "evidence.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4\n%\xe2\xe3\xcf\xd3\nE2E attachment evidence"),
    });
    await page.click('form:has(input[aria-label="Yuklanadigan fayl"]) button[type="submit"]');
    await expect(page.getByTestId("document-list").getByText("evidence.pdf")).toBeVisible();

    await page.fill('input[placeholder="Yangi task nomi"]', "E2E attachment task");
    await page.click("button:has-text(\"Qo'shish\")");
    await expect(
      page.getByTestId("task-list").locator('li:has-text("E2E attachment task")'),
    ).toBeVisible();
  });

  const taskRow = page.locator('[data-testid="task-list"] li:has-text("E2E attachment task")');

  await test.step("attaching the document shows it linked, not broken", async () => {
    await taskRow.getByRole("button", { name: "Bog'langan fayllar" }).click();
    await taskRow.getByLabel("Bog'lanadigan fayl").selectOption({ label: "evidence.pdf" });
    await taskRow.getByRole("button", { name: "Bog'lash" }).click();

    const attachmentList = taskRow.getByTestId("attachment-list");
    await expect(attachmentList.getByText("evidence.pdf")).toBeVisible();
    await expect(attachmentList.getByText("Uzilgan havola")).toHaveCount(0);
  });

  await test.step("deleting the linked document marks the attachment broken, not missing", async () => {
    await page.getByTestId("document-list").getByText("O'chirish").click();
    await expect(page.getByTestId("document-list").getByText("Hali fayl yo'q.")).toBeVisible();

    // The open attachment panel doesn't auto-refresh on an unrelated
    // document delete - close and reopen it to force a fresh read,
    // proving the backend's own state, not a stale client cache.
    await taskRow.getByRole("button", { name: "Fayllarni yashirish" }).click();
    await taskRow.getByRole("button", { name: "Bog'langan fayllar" }).click();

    const attachmentList = taskRow.getByTestId("attachment-list");
    await expect(attachmentList.getByText("Uzilgan havola")).toBeVisible();
    // The link itself is still there (not vanished) - it just no longer
    // shows the now-deleted document's filename.
    await expect(attachmentList.getByText("evidence.pdf")).toHaveCount(0);
  });

  await test.step("detaching removes the link entirely", async () => {
    const attachmentList = taskRow.getByTestId("attachment-list");
    await attachmentList.getByRole("button", { name: "Uzish" }).click();
    await expect(attachmentList.getByText("Hech qanday fayl bog'lanmagan.")).toBeVisible();
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
