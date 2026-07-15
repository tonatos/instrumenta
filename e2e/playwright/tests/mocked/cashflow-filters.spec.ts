/**
 * E2E: cashflow — фильтры по типу операций и подпись даты начала журнала.
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
  initial_cash_rub: 0,
  expected_xirr_pct: 12,
  weighted_duration_years: 0.5,
  notes: [],
  cashflow_from_date: "2026-07-01",
  cashflow: [
    {
      date: "2026-07-05",
      kind: "purchase",
      amount_rub: -50_000,
      label: "Покупка 5 лот(а) — ОФЗ 26238",
      lots: 5,
      bonds_count: 5,
      balance_after_rub: -50_000,
    },
    {
      date: "2026-08-01",
      kind: "coupon",
      amount_rub: 1_200,
      label: "Купон по ОФЗ 26238",
      lots: null,
      bonds_count: 5,
      balance_after_rub: -48_800,
    },
    {
      date: "2026-09-01",
      kind: "fee",
      amount_rub: -15,
      label: "Комиссия брокера",
      lots: null,
      bonds_count: null,
      balance_after_rub: -48_815,
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
      data: {
        trading_started_at: "2026-07-01T10:00:00Z",
        created_at: "2026-06-01T10:00:00Z",
      },
    });
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, { plan });
  });

  test("показывает период с даты привязки и фильтрует по типу", async ({ page }) => {
    await gotoPortfolio(page, PORTFOLIO_ID);
    await page.getByRole("tab", { name: /Cashflow/i }).click();

    await expect(page.getByText(/С 1 июля/)).toBeVisible();
    await expect(page.getByRole("cell", { name: "Покупка", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Купон", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Комиссия", exact: true })).not.toBeVisible();
    await expect(page.getByText(/2 из 3/)).toBeVisible();

    await page.getByRole("button", { name: /Типы операций/i }).click();
    await page.getByRole("button", { name: "Покупка", exact: true }).click();

    await expect(page.getByRole("cell", { name: "Купон", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Покупка", exact: true })).not.toBeVisible();
    await expect(page.getByRole("cell", { name: "Комиссия", exact: true })).not.toBeVisible();
    await expect(page.getByText("Нет операций выбранных типов")).not.toBeVisible();
  });
});
