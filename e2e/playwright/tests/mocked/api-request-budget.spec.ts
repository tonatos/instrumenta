/**
 * E2E: бюджет API-запросов — без лишних refetch и lazy-load истории операций.
 */

import { test, expect } from "@playwright/test";
import {
  makeAdvice,
  makeEmptyPlan,
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

const buySuggestion = {
  id: "suggestion-cancel-1",
  kind: "buy",
  isin: "RU000ATEST1",
  name: "Тестовая облигация",
  lots: 3,
  figi: "FIGI_TEST",
  suggested_price_pct: 100.5,
  due_date: null,
  reason: "Свободный кэш",
  urgency: "normal",
  chat_template: null,
};

const activeOrder = {
  order_id: "order-cancel-1",
  request_uid: "req-cancel-1",
  figi: "FIGI_TEST",
  direction: "BUY",
  lots_requested: 3,
  lots_executed: 0,
  status: "EXECUTION_REPORT_STATUS_NEW",
  price_pct: 100.5,
  total_order_amount_rub: 3030,
  initial_commission_rub: 5,
};

test.describe("Бюджет API-запросов", () => {
  test("страница торговли не грузит account-operations до открытия вкладки", async ({
    page,
  }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID);
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      advice: makeAdvice({ suggestions: [buySuggestion] }),
    });

    const counter = countApiRequests(page);
    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });

    expect(counter.get(/account-operations/)).toBe(0);
    expect(counter.get(/\/trading-state$/)).toBeGreaterThanOrEqual(1);
    expect(counter.get(/\/plan$/)).toBe(0);
    expect(counter.get(/\/advice$/)).toBe(0);

    await page.getByRole("tab", { name: /История операций/i }).click();
    await expect(page.getByRole("table")).toBeVisible({ timeout: 10_000 });
    expect(counter.get(/account-operations/)).toBe(1);
  });

  test("отмена заявки не перезапрашивает plan", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID);
    let tradingStateCalls = 0;

    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan({ invested_capital_rub: 100_000 }),
      advice: makeAdvice({
        suggestions: [buySuggestion],
        active_orders: [activeOrder],
      }),
    });

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/orders/${activeOrder.order_id}/cancel`,
      async (route) => {
        await route.fulfill({
          json: { order_id: activeOrder.order_id, status: "EXECUTION_REPORT_STATUS_CANCELLED" },
        });
      },
    );

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      tradingStateCalls += 1;
      const activeOrders = tradingStateCalls > 1 ? [] : [activeOrder];
      await route.fulfill({
        json: {
          plan: makeEmptyPlan({ invested_capital_rub: 100_000 }),
          advice: makeAdvice({
            suggestions: [buySuggestion],
            active_orders: activeOrders,
          }),
        },
      });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Отменить заявку" })).toBeVisible();

    const counter = countApiRequests(page);
    counter.reset();

    await page.getByRole("button", { name: "Отменить заявку" }).click();

    await expect(page.getByRole("button", { name: "Отменить заявку" })).not.toBeVisible({
      timeout: 10_000,
    });

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
