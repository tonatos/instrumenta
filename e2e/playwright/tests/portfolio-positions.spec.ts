/**
 * E2E: статусы позиций в trading-портфеле, фильтр закрытых, badge.
 */

import { test, expect } from "@playwright/test";

const PORTFOLIO_ID = "positions-lifecycle-1";

const tradingPortfolio = {
  id: PORTFOLIO_ID,
  name: "Lifecycle E2E",
  initial_amount_rub: 100_000,
  horizon_date: "2028-01-01",
  risk_profile: "normal",
  cash_balance_rub: 50_000,
  mode: "trading",
  account_id: "acc-pos",
  account_kind: "sandbox",
  positions_count: 2,
  closed_positions_count: 1,
  data: {
    positions: [
      {
        isin: "RU000AOPEN1",
        secid: "OPEN1",
        name: "Активная облигация",
        lots: 5,
        lot_size: 1,
        purchase_clean_price_pct: 100,
        purchase_dirty_price_rub: 1000,
        purchase_aci_rub: 0,
        purchase_date: "2026-01-01",
        purchase_amount_rub: 5000,
        coupon_rate: 10,
        face_value: 1000,
        maturity_date: "2027-06-01",
        offer_date: null,
        source: "initial",
        put_offer_decision: "pending",
        figi: "FIGI_OPEN",
        actual_lots: 5,
        closed_at: null,
        status: "active",
      },
      {
        isin: "RU000ACLOSE1",
        secid: "CLOSE1",
        name: "Погашенная облигация",
        lots: 3,
        lot_size: 1,
        purchase_clean_price_pct: 100,
        purchase_dirty_price_rub: 1000,
        purchase_aci_rub: 0,
        purchase_date: "2025-01-01",
        purchase_amount_rub: 3000,
        coupon_rate: 10,
        face_value: 1000,
        maturity_date: "2026-06-01",
        offer_date: null,
        source: "initial",
        put_offer_decision: "pending",
        figi: "FIGI_CLOSE",
        actual_lots: 0,
        closed_at: "2026-06-15",
        status: "closed",
      },
      {
        isin: "RU000APEND1",
        secid: "PEND1",
        name: "Ожидающая покупка",
        lots: 2,
        lot_size: 1,
        purchase_clean_price_pct: 100,
        purchase_dirty_price_rub: 1000,
        purchase_aci_rub: 0,
        purchase_date: "2026-07-01",
        purchase_amount_rub: 2000,
        coupon_rate: 10,
        face_value: 1000,
        maturity_date: "2027-12-01",
        offer_date: null,
        source: "initial",
        put_offer_decision: "pending",
        figi: "FIGI_PEND",
        actual_lots: 0,
        closed_at: null,
        status: "pending",
      },
    ],
    slots: [],
    cash_balance_rub: 50_000,
    initial_amount_rub: 100_000,
    horizon_date: "2028-01-01",
    mode: "trading",
    account_id: "acc-pos",
    account_kind: "sandbox",
    acknowledged_top_ups_rub: 0,
    frozen_forecast: null,
    pending_operations: [],
    closed_positions_count: 1,
  },
};

const emptyPlan = {
  total_net_profit_rub: 0,
  total_net_profit_with_held_rub: 0,
  invested_capital_rub: 100_000,
  total_invested_rub: 100_000,
  final_cash_balance: 50_000,
  final_portfolio_value: 100_000,
  expected_xirr_pct: null,
  notes: [],
  cashflow: [],
  value_timeline: [],
  held_positions: [],
  slots: [],
};

const emptySync = {
  pending_operations: [],
  drifts: [],
  money_rub: 50_000,
  last_synced_at: "2026-07-01T00:00:00+00:00",
  has_pending_top_up: false,
  pending_top_up_rub: 0,
  top_up_auto_applied: false,
  top_up_distributed_rub: 0,
  top_up_notes: [],
  notes: [],
};

test.describe("Позиции — жизненный цикл", () => {
  test.beforeEach(async ({ page }) => {
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

    await page.route("**/api/v1/portfolios/", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ json: [tradingPortfolio] });
        return;
      }
      await route.continue();
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/plan`, async (route) => {
      await route.fulfill({ json: emptyPlan });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sync`, async (route) => {
      await route.fulfill({ json: emptySync });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await expect(page.getByRole("tab", { name: /Позиции/ })).toBeVisible({ timeout: 15_000 });
  });

  test("показывает статусы открытых позиций без закрытых по умолчанию", async ({ page }) => {
    await page.getByRole("tab", { name: /Позиции/ }).click();

    await expect(page.getByTestId("position-row-RU000AOPEN1")).toBeVisible();
    await expect(page.getByTestId("position-row-RU000AOPEN1")).toHaveAttribute(
      "data-status",
      "active",
    );
    await expect(page.getByTestId("position-row-RU000APEND1")).toHaveAttribute(
      "data-status",
      "pending",
    );
    await expect(page.getByTestId("position-row-RU000ACLOSE1")).not.toBeVisible();
    await expect(page.getByText("Активная облигация")).toBeVisible();
    await expect(page.getByText("Погашенная облигация")).not.toBeVisible();
  });

  test("badge на вкладке считает только открытые позиции", async ({ page }) => {
    const tab = page.getByRole("tab", { name: /Позиции/ });
    await expect(tab).toContainText("2");
  });

  test("фильтр показывает закрытые позиции", async ({ page }) => {
    await page.getByRole("tab", { name: /Позиции/ }).click();
    await page.getByTestId("show-closed-positions").check();
    await expect(page.getByTestId("position-row-RU000ACLOSE1")).toBeVisible();
    await expect(page.getByTestId("position-row-RU000ACLOSE1")).toHaveAttribute(
      "data-status",
      "closed",
    );
    await expect(page.getByText("Погашенная облигация")).toBeVisible();
  });
});
