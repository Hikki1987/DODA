import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Deliberately its own seed run (E2E_KNOWLEDGE_ prefix) — this spec
// uploads and deletes real Document rows, and a shared seed with another
// spec that lists documents (there currently is none, but the same
// "each mutating spec gets its own seed" convention as
// workspace-kill-switch.spec.ts/logout.spec.ts applies here too).
const SESSION_ID = requiredEnv("E2E_KNOWLEDGE_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_KNOWLEDGE_WORKSPACE_ID");

test.describe.configure({ mode: "serial" });

test("FR-KNW-001: upload, list, download, reject, and delete a file", async ({ page }) => {
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

  await test.step("upload a real PDF and see it in the file list", async () => {
    await page.setInputFiles('input[aria-label="Yuklanadigan fayl"]', {
      name: "report.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4\n%\xe2\xe3\xcf\xd3\nE2E test pdf body"),
    });
    await page.click('form:has(input[aria-label="Yuklanadigan fayl"]) button[type="submit"]');
    await expect(page.getByTestId("document-list").getByText("report.pdf")).toBeVisible();
  });

  await test.step("downloading it round-trips the exact bytes via the real backend", async () => {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("document-list").getByText("Yuklab olish").click(),
    ]);
    const path = await download.path();
    const fs = await import("node:fs/promises");
    const content = path ? await fs.readFile(path) : Buffer.alloc(0);
    expect(content.toString("utf-8")).toContain("E2E test pdf body");
  });

  await test.step("a Windows executable disguised as a .pdf is rejected, not stored", async () => {
    await page.setInputFiles('input[aria-label="Yuklanadigan fayl"]', {
      name: "invoice.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("MZ\x90\x00\x03\x00\x00\x00this is really an executable"),
    });
    await page.click('form:has(input[aria-label="Yuklanadigan fayl"]) button[type="submit"]');
    await expect(page.getByTestId("document-list").getByText("invoice.pdf")).toHaveCount(0);
    // The first, real upload is still the only entry.
    await expect(page.getByTestId("document-list").locator("li")).toHaveCount(1);
  });

  await test.step("delete removes it from the list", async () => {
    await page.getByTestId("document-list").getByText("O'chirish").click();
    await expect(page.getByTestId("document-list").getByText("Hali fayl yo'q.")).toBeVisible();
  });

  // The rejected-upload step above causes the browser to log the 422
  // response to console (a failed fetch, same as auditor.spec.ts's
  // expected-403 case) — that one line is expected, anything else is not.
  const unexpected = consoleErrors.filter((text) => !text.includes("422"));
  expect(unexpected).toEqual([]);
});
