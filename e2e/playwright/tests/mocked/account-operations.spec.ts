/**
 * E2E: вкладка «История операций» для портфеля в режиме торговли.
 */

import { test, expect } from "@playwright/test";
import { mockAuthMe } from "./fixtures";

const PORTFOLIO_ID = "ops-history-portfolio-1";

const tradingPortfolio = {
  id: PORTFOLIO_ID,
  name: "Ops History E2E",
  initial_amount_rub: 100_000,
  horizon_date: "2027-01-01",
  risk_profile: "normal",
  cash_balance_rub: 95_000,
  mode: "trading",
  account_id: "acc-ops-e2e",
  account_kind: "sandbox",
  positions_count: 1,
  data: {
    positions: [
      {
        isin: "RU000ATEST1",
        secid: "TEST1",
        name: "Тестовая облигация",
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
        figi: "FIGI_TEST",
        actual_lots: 5,
      },
    ],
    slots: [],
    cash_balance_rub: 95_000,
    initial_amount_rub: 100_000,
    horizon_date: "2027-01-01",
    mode: "trading",
    account_id: "acc-ops-e2e",
    account_kind: "sandbox",
    frozen_forecast: null,
  },
};

const accountOperations = {
  operations: [
    {
      id: "op-coupon-1",
      type: "OPERATION_TYPE_COUPON",
      type_label: "Купон",
      state: "OPERATION_STATE_EXECUTED",
      state_label: "Исполнена",
      date: "2026-06-15T08:00:00+00:00",
      figi: "FIGI_TEST",
      instrument_type: "bond",
      isin: "RU000ATEST1",
      name: "Тестовая облигация",
      payment_rub: 420,
      quantity: 0,
      price_pct: null,
      commission_rub: null,
    },
    {
      id: "op-buy-1",
      type: "OPERATION_TYPE_BUY",
      type_label: "Покупка",
      state: "OPERATION_STATE_EXECUTED",
      state_label: "Исполнена",
      date: "2026-03-10T12:00:00+00:00",
      figi: "FIGI_TEST",
      instrument_type: "bond",
      isin: "RU000ATEST1",
      name: "Тестовая облигация",
      payment_rub: -5050,
      quantity: 5,
      price_pct: 101,
      commission_rub: 5,
    },
    {
      id: "op-input-1",
      type: "OPERATION_TYPE_INPUT",
      type_label: "Пополнение",
      state: "OPERATION_STATE_EXECUTED",
      state_label: "Исполнена",
      date: "2026-01-05T09:00:00+00:00",
      figi: "",
      instrument_type: "currency",
      isin: null,
      name: null,
      payment_rub: 100_000,
      quantity: 0,
      price_pct: null,
      commission_rub: null,
    },
  ],
};

test.describe("История операций", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          key_rate: 16,
          tax_rate: 13,
          max_days: 1825,
          min_volume_rub: 0,
          tinkoff_configured: false,
          sandbox_configured: true,
          production_configured: false,
        },
      });
    });
    await mockAuthMe(page, { sandbox: true });

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
      await route.fulfill({
        json: {
          total_net_profit_rub: 0,
          total_net_profit_with_held_rub: 0,
          final_cash_balance: 95_000,
          final_portfolio_value: 100_000,
          expected_xirr_pct: 12,
          notes: [],
          cashflow: [],
          value_timeline: [],
          held_positions: [],
          slots: [],
        },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      await route.fulfill({
        json: {
          holdings: [],
          cashflow: [],
          performance: null,
          suggestions: [],
          active_orders: [],
          money_rub: 95_000,
          available_money_rub: 95_000,
          blocked_money_rub: 0,
          warnings: [],
          as_of: new Date().toISOString(),
        },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/account-operations`, async (route) => {
      await route.fulfill({ json: accountOperations });
    });
  });

  test("показывает вкладку и таблицу операций счёта", async ({ page }) => {
    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await expect(page.getByRole("tab", { name: /история операций/i })).toBeVisible();
    await page.getByRole("tab", { name: /история операций/i }).click();

    await expect(page.getByRole("heading", { name: "История операций" })).toBeVisible();
    const table = page.locator("table");
    await expect(table.getByText("Купон")).toBeVisible();
    await expect(table.getByText("Покупка")).toBeVisible();
    await expect(table.getByText("Пополнение", { exact: true })).toBeVisible();
    await expect(table.getByText("Тестовая облигация").first()).toBeVisible();
    await expect(page.getByText("3 операций")).toBeVisible();
  });
});
