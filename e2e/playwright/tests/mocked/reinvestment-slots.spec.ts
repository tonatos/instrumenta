/**
 * E2E: вкладка «Реинвестиции» — режимы стратегия/вручную, валидация, сброс цепочки.
 */

import { test, expect } from "@playwright/test";

const PORTFOLIO_ID = "reinvest-portfolio-1";
const SOURCE_ISIN = "RU000ASRC01";
const SUGGESTED_ISIN = "RU000SUG01";
const ALT_ISIN = "RU000ALT01";

const simulationPortfolio = {
  id: PORTFOLIO_ID,
  name: "Reinvest E2E",
  initial_amount_rub: 500_000,
  horizon_date: "2027-06-01",
  risk_profile: "aggressive",
  cash_balance_rub: 50_000,
  mode: "simulation",
  account_id: null,
  account_kind: null,
  positions_count: 1,
  data: {
    positions: [
      {
        isin: SOURCE_ISIN,
        secid: "SRC01",
        name: "Исходная облигация",
        lots: 100,
        lot_size: 1,
        purchase_clean_price_pct: 99,
        purchase_dirty_price_rub: 990,
        purchase_aci_rub: 0,
        purchase_date: "2026-01-01",
        purchase_amount_rub: 99_000,
        coupon_rate: 12,
        face_value: 1000,
        maturity_date: "2026-12-01",
        offer_date: null,
        source: "initial",
        put_offer_decision: "pending",
        figi: null,
        actual_lots: null,
      },
    ],
    slots: [],
    cash_balance_rub: 50_000,
    initial_amount_rub: 500_000,
    horizon_date: "2027-06-01",
    mode: "simulation",
    account_id: null,
    account_kind: null,
    frozen_forecast: null,
    pending_operations: [],
  },
};

function makeSlot(confirmedIsin: string | null = null) {
  return {
    trigger_date: "2026-12-01",
    trigger_reason: "maturity",
    expected_cash_rub: 105_000,
    suggested_isin: SUGGESTED_ISIN,
    suggested_name: "Предложенная ОФЗ",
    confirmed_isin: confirmedIsin,
    gap_days: 2,
    source_position_isin: SOURCE_ISIN,
    selection_mode: confirmedIsin ? "manual" : "strategy",
    status: "ok",
    failure_reason: null,
    eligible_candidates: [
      {
        isin: SUGGESTED_ISIN,
        name: "Предложенная ОФЗ",
        score: 88,
        ytm_net: 14.2,
      },
      {
        isin: ALT_ISIN,
        name: "Альтернативная облигация",
        score: 82,
        ytm_net: 13.5,
      },
    ],
  };
}

function makePlan(confirmedIsin: string | null = null) {
  return {
    total_net_profit_rub: 20_000,
    total_net_profit_with_held_rub: 20_000,
    final_cash_balance: 10_000,
    final_portfolio_value: 520_000,
    expected_xirr_pct: 15,
    notes: [],
    cashflow: [],
    value_timeline: [],
    held_positions: [],
    slots: [makeSlot(confirmedIsin)],
  };
}

test.describe("Реинвестиции — замены в цепочке", () => {
  test.beforeEach(async ({ page }) => {
    let confirmedIsin: string | null = null;

    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          key_rate: 16,
          tax_rate: 13,
          max_days: 1825,
          min_volume_rub: 0,
          tinkoff_configured: false,
          sandbox_configured: false,
          production_configured: false,
        },
      });
    });

    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });

    await page.route("**/api/v1/portfolios/", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ json: [simulationPortfolio] });
        return;
      }
      await route.continue();
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/plan`, async (route) => {
      await route.fulfill({ json: makePlan(confirmedIsin) });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/slots/override`, async (route) => {
      const body = route.request().postDataJSON() as {
        source_position_isin: string;
        confirmed_isin: string | null;
      };
      if (body.confirmed_isin === SOURCE_ISIN) {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          json: {
            detail: "нельзя реинвестировать в ту же бумагу",
            extra: { code: "invalid_replacement" },
          },
        });
        return;
      }
      confirmedIsin = body.confirmed_isin;
      await route.fulfill({
        json: {
          ...simulationPortfolio,
          data: {
            ...simulationPortfolio.data,
            slots: [
              {
                ...makeSlot(confirmedIsin),
                trigger_date: "2026-12-01",
                expected_cash_rub: 105_000,
              },
            ],
          },
        },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/slots/reset-all`, async (route) => {
      confirmedIsin = null;
      await route.fulfill({ json: simulationPortfolio });
    });
  });

  test("показывает предложение стратегии и переключается в ручной режим", async ({ page }) => {
    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await page.getByRole("tab", { name: /реинвестиции/i }).click();

    await expect(page.getByText("Предложенная стратегией")).toBeVisible();
    await expect(page.getByText(/Предложенная ОФЗ/)).toBeVisible();

    await page.getByRole("button", { name: "Выбрать вручную" }).click();
    await expect(page.getByText("Доступны только бумаги")).toBeVisible();
    await page.getByRole("button", { name: /Предложенная ОФЗ|Выберите бумагу/i }).click();
    await expect(page.getByText("Альтернативная облигация")).toBeVisible();
  });

  test("сбрасывает ручные назначения через глобальную кнопку", async ({ page }) => {
    await page.goto(`/portfolio/${PORTFOLIO_ID}`);
    await page.getByRole("tab", { name: /реинвестиции/i }).click();

    await page.getByRole("button", { name: "Выбрать вручную" }).click();
    await page.getByRole("button", { name: /Предложенная ОФЗ|Выберите бумагу/i }).click();
    await page.getByText("Альтернативная облигация").click();

    await expect(page.getByText("· 1 вручную")).toBeVisible();

    await page.getByRole("button", { name: "Реинвестировать автоматически" }).click();
    await page.getByRole("button", { name: "Сбросить и пересчитать" }).click();

    await expect(page.getByText("· 1 вручную")).not.toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("button", { name: "Предложенная стратегией" })).toBeVisible();
  });
});
