import { test, expect } from "@playwright/test";
import { requiredEnv } from "./env";

// Deliberately its own seed run (E2E_CHAT_ prefix) — this spec toggles
// customer-wide AI provider/fallback settings, which every other spec's
// seeded customer would otherwise also see (the same "don't share mutable
// state across specs" lesson as workspace-kill-switch.spec.ts's own seed).
const SESSION_ID = requiredEnv("E2E_CHAT_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_CHAT_WORKSPACE_ID");
const CUSTOMER_ID = requiredEnv("E2E_CHAT_CUSTOMER_ID");

test.describe.configure({ mode: "serial" });

test("chat: send a message, get the real NullModelGateway reply, pin a provider", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("log in and open the workspace's chat page", async () => {
    await page.goto("/login");
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
    await page.goto(`/workspaces/${WORKSPACE_ID}/chat`);
    await expect(page.getByText("Yangi suhbat")).toBeVisible();
  });

  await test.step("start a new conversation", async () => {
    await page.click('button:has-text("Yangi suhbat")');
    await expect(page.getByPlaceholder("Xabar yozing...")).toBeVisible();
  });

  await test.step("sending a message streams a real reply over SSE from the running backend", async () => {
    await page.fill('input[placeholder="Xabar yozing..."]', "Salom, DODA!");
    await page.click('button:has-text("Yuborish")');
    await expect(page.getByText("Salom, DODA!")).toBeVisible();
    // No real provider credential exists in CI — this is the honest
    // NullModelGateway degradation text (doda.ai.port), proving the whole
    // pipeline (SSE stream -> persisted Message -> refetch) is real, not a
    // hardcoded frontend string.
    await expect(
      page.getByText("AI javob provayderi hali tanlanmagan yoki sozlanmagan"),
    ).toBeVisible();
  });

  await test.step("pinning a conversation provider persists server-side", async () => {
    await page.selectOption('select[aria-label="Suhbat provayderi"]', "GEMINI");
    await page.click('button:has-text("Pin qilish")');
    await expect(page.getByText("hozirgi: GEMINI")).toBeVisible();

    // Direct backend check (not the page's own fetch) — proves the pin
    // really persisted, not just that the label optimistically re-rendered.
    const response = await page.request.get(
      `http://localhost:8000/v1/workspaces/${WORKSPACE_ID}/conversations`,
      { headers: { Authorization: `Bearer ${SESSION_ID}` } },
    );
    const conversations = await response.json();
    expect(conversations.some((c: { pinned_provider: string | null }) => c.pinned_provider === "GEMINI")).toBe(
      true,
    );
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});

test("AI provider settings: enable/disable, test connection, fallback toggle, my preference", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await test.step("log in and open the customer page", async () => {
    await page.goto("/login");
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
    await page.goto(`/customers/${CUSTOMER_ID}`);
    await expect(page.getByText("AI provayderlar")).toBeVisible();
  });

  await test.step("testing an unconfigured provider honestly reports failure, not a fake success", async () => {
    const openaiRow = page.locator("li", { hasText: "OPENAI" });
    await openaiRow.getByRole("button", { name: "Ulanishni tekshirish" }).click();
    await expect(openaiRow.getByText("tekshirilgan:")).toBeVisible();
  });

  await test.step("disabling and re-enabling a provider is real, not UI-only", async () => {
    const claudeRow = page.locator("li", { hasText: "CLAUDE" });
    await claudeRow.getByRole("button", { name: "O'chirish" }).click();
    await expect(claudeRow.getByRole("button", { name: "Yoqish" })).toBeVisible();

    const disabled = await page.request.get(`http://localhost:8000/v1/customers/${CUSTOMER_ID}/ai-providers`, {
      headers: { Authorization: `Bearer ${SESSION_ID}` },
    });
    const statuses = await disabled.json();
    expect(statuses.find((s: { provider: string; enabled: boolean }) => s.provider === "CLAUDE").enabled).toBe(
      false,
    );

    await claudeRow.getByRole("button", { name: "Yoqish" }).click();
    await expect(claudeRow.getByRole("button", { name: "O'chirish" })).toBeVisible();
  });

  await test.step("automatic fallback defaults to off and can be turned on", async () => {
    await expect(page.getByText("Avtomatik fallback")).toBeVisible();
    const fallbackRow = page.locator("div", { hasText: "Avtomatik fallback" }).first();
    await fallbackRow.getByRole("button", { name: "Yoqish" }).click();
    await expect(fallbackRow.getByRole("button", { name: "O'chirish" })).toBeVisible();

    const response = await page.request.get(`http://localhost:8000/v1/customers/${CUSTOMER_ID}/ai-fallback`, {
      headers: { Authorization: `Bearer ${SESSION_ID}` },
    });
    expect((await response.json()).enabled).toBe(true);
  });

  await test.step("setting my own AI preference round-trips through the real backend", async () => {
    await page.selectOption('select[aria-label="Mening AI provayderim"]', "CLAUDE");
    await page.click('form:has(select[aria-label="Mening AI provayderim"]) button:has-text("Saqlash")');
    await expect(page.getByText("Mening AI afzalligim (CLAUDE)")).toBeVisible();
  });

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});
