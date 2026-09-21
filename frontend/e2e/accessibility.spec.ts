import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { requiredEnv } from "./env";

// NFR-ACC-001 ("WCAG 2.2 AA... Avtomatik + qo'lda audit") had zero coverage
// — no automated accessibility check had ever run against this frontend.
// Own seed prefix, per the established "independent specs must not share
// mutable seed state" lesson (see customer.spec.ts).
const SESSION_ID = requiredEnv("E2E_A11Y_SESSION_ID");
const WORKSPACE_ID = requiredEnv("E2E_A11Y_WORKSPACE_ID");
const CUSTOMER_ID = requiredEnv("E2E_A11Y_CUSTOMER_ID");

test.describe.configure({ mode: "serial" });

async function scan(page: import("@playwright/test").Page) {
  return new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
}

test("every real authenticated page has zero serious/critical WCAG 2.2 AA violations", async ({
  page,
}) => {
  const violationsByPage: Record<string, unknown> = {};

  await test.step("/login (unauthenticated)", async () => {
    await page.goto("/login");
    const results = await scan(page);
    violationsByPage["/login"] = results.violations;
  });

  await test.step("log in", async () => {
    await page.fill("#session-id", SESSION_ID);
    await page.click('button[type="submit"]');
    await page.waitForURL("**/workspaces");
  });

  await test.step("/workspaces", async () => {
    const results = await scan(page);
    violationsByPage["/workspaces"] = results.violations;
  });

  await test.step(`/workspaces/${WORKSPACE_ID}`, async () => {
    await page.goto(`/workspaces/${WORKSPACE_ID}`);
    await expect(page.getByText("Task'lar")).toBeVisible();
    const results = await scan(page);
    violationsByPage[`/workspaces/[id]`] = results.violations;
  });

  await test.step(`/customers/${CUSTOMER_ID}`, async () => {
    await page.goto(`/customers/${CUSTOMER_ID}`);
    await expect(page.getByText("Kill switch")).toBeVisible();
    const results = await scan(page);
    violationsByPage[`/customers/[id]`] = results.violations;
  });

  await test.step("/sessions", async () => {
    await page.goto("/sessions");
    await expect(page.getByText("Sessiyalar")).toBeVisible();
    const results = await scan(page);
    violationsByPage["/sessions"] = results.violations;
  });

  const seriousOrWorse = (impact: string | null | undefined) => impact === "serious" || impact === "critical";

  const failures = Object.entries(violationsByPage).flatMap(([url, violations]) =>
    (violations as { id: string; impact?: string; help: string; nodes: { html: string }[] }[])
      .filter((v) => seriousOrWorse(v.impact))
      .map((v) => `${url}: [${v.impact}] ${v.id} — ${v.help} (${v.nodes.length} node(s))`),
  );

  expect(failures, `serious/critical accessibility violations found:\n${failures.join("\n")}`).toEqual([]);
});
