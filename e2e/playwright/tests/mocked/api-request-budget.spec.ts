/**
 * E2E: бюджет API-запросов — без лишних refetch и lazy-load истории операций.
 */

import { test, expect } from "@playwright/test";
import {
  makeEmptyPlan,
  makeEmptySync,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "perf-portfolio-1";

function countApiRequests(page: import("@playwright/test").Page) {
  const counts = new Map<string, number>();
  const handler = (url: string, method: string) => {
    if (!url.includes("/api/v1/")) return;
    const path = new URL(url).pathname.replace(/\/api\/v1/, "");
    const key = `${method} ${path}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  };

  page.on("request", (req) => handler(req.url(), req.method()));
  return {
    get: (pattern: RegExp) =>
      [...counts.entries()]
        .filter(([key]) => pattern.test(key))
        .reduce((sum, [, n]) => sum + n, 0),
    snapshot: () => Object.fromEntries(counts),
    reset: () => counts.clear(),
  };
}

const pendingBuy = {
  id: "pending-cancel-1",
  kind: "initial_buy",
  isin: "RU000ATEST1",
  name: "Тестовая облигация",
  lots: 3,
  figi: "FIGI_TEST",
  suggested_price_pct: 100.5,
  due_date: null,
  reason: "Стартовая покупка",
  status: "action_required",
  block_reason: null,
  estimated_amount_rub: 3030,
  face_value_rub: 1000,
  lot_size: 1,
  aci_rub_per_bond: 0,
  active_order_id: null,
  active_order_status: null,
  urgency: "normal",
  chat_template: null,
};

test.describe("Бюджет API-запросов", () => {
  test("страница торговли не грузит account-operations до открытия вкладки", async ({
    page,
  }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID);
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      sync: makeEmptySync({ pending_operations: [pendingBuy] }),
    });

    const counter = countApiRequests(page);
    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });

    expect(counter.get(/account-operations/)).toBe(0);
    expect(counter.get(/\/sync$/)).toBeGreaterThanOrEqual(1);
    expect(counter.get(/\/plan$/)).toBeGreaterThanOrEqual(1);

    await page.getByRole("tab", { name: /История операций/i }).click();
    await expect(page.getByRole("table")).toBeVisible({ timeout: 10_000 });
    expect(counter.get(/account-operations/)).toBe(1);
  });

  test("отмена заявки не перезапрашивает plan", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID);
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan({ invested_capital_rub: 100_000 }),
      sync: makeEmptySync({
        pending_operations: [
          {
            ...pendingBuy,
            status: "in_progress",
            active_order_id: "order-cancel-1",
            active_order_status: "EXECUTION_REPORT_STATUS_NEW",
            active_order_lots: 3,
            active_order_price_pct: 100.5,
            active_order_total_rub: 3030,
            active_order_lots_executed: 0,
            active_order_bonds_count: 3,
          },
        ],
      }),
    });

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/pending-operations/${pendingBuy.id}/cancel-order`,
      async (route) => {
        await route.fulfill({
          json: makeEmptySync({
            pending_operations: [
              { ...pendingBuy, status: "action_required", active_order_id: null },
            ],
          }),
        });
      },
    );

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });

    const counter = countApiRequests(page);
    counter.reset();

    const opCard = page.locator(`#pending-op-${pendingBuy.id}`);
    await opCard.getByRole("button", { name: "Отменить заявку" }).click();

    await expect(opCard.getByText("Требует действия")).toBeVisible({ timeout: 10_000 });

    expect(counter.get(/\/plan$/)).toBe(0);
    expect(counter.get(/GET \/portfolios\/$/)).toBeLessThanOrEqual(1);
  });

  test("smoke: основные маршруты укладываются в бюджет запросов", async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          key_rate: 16,
          tax_rate: 13,
          max_days: 1825,
          min_volume_rub: 0,
          tinkoff_configured: true,
          sandbox_configured: true,
          production_configured: false,
        },
      });
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });
    await page.route("**/api/v1/portfolios/", async (route) => {
      await route.fulfill({ json: [] });
    });

    const counter = countApiRequests(page);

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Скринер облигаций" })).toBeVisible({
      timeout: 15_000,
    });
    const screenerCalls = Object.keys(counter.snapshot()).length;
    expect(screenerCalls).toBeLessThanOrEqual(4);

    counter.reset();
    await page.goto("/favorites");
    await expect(page.getByRole("heading", { name: "Избранное" })).toBeVisible({
      timeout: 15_000,
    });
    expect(Object.keys(counter.snapshot()).length).toBeLessThanOrEqual(4);

    counter.reset();
    await page.goto("/calculator");
    await expect(page.getByRole("heading", { name: /калькулятор/i })).toBeVisible({
      timeout: 15_000,
    });
    expect(Object.keys(counter.snapshot()).length).toBeLessThanOrEqual(3);
  });
});
