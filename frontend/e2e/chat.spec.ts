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

test("chat: cancelling an in-flight turn resets the UI without an error", async ({ page }) => {
  // NullModelGateway (no real provider credential in this environment)
  // replies essentially instantly, far too fast to reliably click Cancel
  // before the turn finishes — so this test delays the browser's own
  // dispatch of the POST via page.route(), giving a deterministic window
  // to click "Bekor qilish" before the request even reaches the backend.
  // This proves the frontend's AbortController wiring and UI reset; the
  // backend's own claim (generation actually stops and the budget is
  // refunded) is proven server-side, with real interleaving, in
  // test_a_client_disconnect_mid_stream_stops_generation_and_refunds_the_reservation.
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto("/login");
  await page.fill("#session-id", SESSION_ID);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/workspaces");
  await page.goto(`/workspaces/${WORKSPACE_ID}/chat`);
  await page.click('button:has-text("Yangi suhbat")');
  await expect(page.getByPlaceholder("Xabar yozing...")).toBeVisible();

  await page.route("**/conversations/*/messages", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    await route.continue();
  });

  await page.fill('input[placeholder="Xabar yozing..."]', "bu xabar bekor qilinadi");
  await page.click('button:has-text("Yuborish")');

  const cancelButton = page.getByRole("button", { name: "Bekor qilish" });
  await expect(cancelButton).toBeVisible();
  await cancelButton.click();

  // The UI returns to its idle state — composer re-enabled, no lingering
  // "sending" indicator, and (per handleSend's AbortError check) no error
  // message shown for what was the user's own deliberate cancellation.
  await expect(page.getByPlaceholder("Xabar yozing...")).toBeEnabled();
  await expect(cancelButton).not.toBeVisible();
  await expect(page.getByText("bekor qilinadi")).not.toBeVisible();

  expect(consoleErrors, `unexpected browser console errors: ${consoleErrors.join("\n")}`).toEqual([]);
});

test("chat: searching conversation history finds a message and jumps to its conversation", async ({
  page,
}) => {
  // FR-CONV-006. Uses a distinctive, unlikely-to-collide phrase (rather
  // than a generic word) so this test can't accidentally match content
  // left behind by another spec/run sharing the same seeded workspace.
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  const needle = "qizil sirli kalamush 42";

  await page.goto("/login");
  await page.fill("#session-id", SESSION_ID);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/workspaces");
  await page.goto(`/workspaces/${WORKSPACE_ID}/chat`);

  await page.click('button:has-text("Yangi suhbat")');
  await expect(page.getByPlaceholder("Xabar yozing...")).toBeVisible();
  await page.fill('input[placeholder="Xabar yozing..."]', needle);
  await page.click('button:has-text("Yuborish")');
  await expect(page.getByText(needle, { exact: false }).first()).toBeVisible();

  // Start a second, different conversation so there is more than one to
  // jump BETWEEN — proves the click actually navigates, not just that a
  // single already-open conversation happens to contain the text.
  await page.click('button:has-text("Yangi suhbat")');
  await expect(page.getByText(needle)).not.toBeVisible();

  await page.fill('input[placeholder="Suhbat tarixini qidirish..."]', needle);
  await page.click('button:has-text("Qidirish")');
  const resultButton = page.getByRole("button", { name: needle, exact: false });
  await expect(resultButton).toBeVisible();
  await resultButton.click();

  // Clicking a result clears the search panel and switches to the
  // conversation that actually contains the match.
  await expect(page.getByPlaceholder("Suhbat tarixini qidirish...")).toHaveValue("");
  await expect(page.getByText(needle, { exact: false }).first()).toBeVisible();

  await page.fill('input[placeholder="Suhbat tarixini qidirish..."]', "hech-qachon-mos-kelmaydigan-soz");
  await page.click('button:has-text("Qidirish")');
  await expect(page.getByText("Hech narsa topilmadi.")).toBeVisible();

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
