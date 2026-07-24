/**
 * E2E: cashflow — только прогноз, фильтры по типу операций.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "cashflow-filters-1";

const plan = {
  total_net_profit_rub: 10_000,
  total_net_profit_with_held_rub: 12_000,
  invested_capital_rub: 100_000,
  total_invested_rub: 100_000,
  final_cash_balance: 110_000,
  final_portfolio_value: 112_000,
  initial_cash_rub: 50_000,
  expected_xirr_pct: 12,
  weighted_duration_years: 0.5,
  notes: [],
  cashflow_from_date: "2026-07-15",
  cashflow: [
    {
      date: "2026-08-01",
      kind: "coupon",
      amount_rub: 1_200,
      label: "Купон по ОФЗ 26238",
      lots: null,
      bonds_count: 5,
      balance_after_rub: 51_200,
    },
    {
      date: "2026-09-15",
      kind: "purchase",
      amount_rub: -50_000,
      label: "Покупка 5 лот(а) — ОФЗ 26238",
      lots: 5,
      bonds_count: 5,
      balance_after_rub: 1_200,
    },
  ],
  value_timeline: [],
  held_positions: [],
  slots: [],
};

test.describe("Cashflow — фильтры и период", () => {
  test.beforeEach(async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Cashflow Filters",
    });
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, { plan });
  });

  test("показывает прогноз с сегодня и фильтрует по типу", async ({ page }) => {
    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByTestId("forecast-metrics")).toContainText("Прогнозный XIRR");
    await expect(page.getByTestId("forecast-disclaimer")).toContainText(/модель денежных потоков/i);

    await page.getByRole("tab", { name: /Cashflow/i }).click();

    await expect(page.getByText(/Прогноз с/)).toBeVisible();
    await expect(page.getByText(/Факт — вкладка «Операции»/)).toBeVisible();
    await expect(page.getByRole("cell", { name: "Покупка", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Купон", exact: true })).toBeVisible();

    await page.getByRole("button", { name: /Типы операций/i }).click();
    await page.getByRole("button", { name: "Покупка", exact: true }).click();

    await expect(page.getByRole("cell", { name: "Купон", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Покупка", exact: true })).not.toBeVisible();
    await expect(page.getByText("Нет операций выбранных типов")).not.toBeVisible();
  });
});
