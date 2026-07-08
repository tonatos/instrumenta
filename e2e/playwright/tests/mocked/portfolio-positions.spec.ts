/**
 * E2E: статусы позиций в trading-портфеле, YTM/скор из справочника.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "positions-lifecycle-1";

const tradingPortfolio = makeTradingPortfolio(PORTFOLIO_ID, {
  name: "Lifecycle E2E",
  positions_count: 2,
  closed_positions_count: 0,
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
        figi: "FIGI_OPEN",
        status: "active",
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
        figi: "FIGI_PEND",
        status: "pending",
      },
    ],
    closed_positions_count: 0,
  },
});

test.describe("Позиции — жизненный цикл", () => {
  test.beforeEach(async ({ page }) => {
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, tradingPortfolio, {
      plan: makeEmptyPlan({ invested_capital_rub: 100_000 }),
      advice: makeAdvice({
        holdings: [
          {
            figi: "FIGI_OPEN",
            isin: "RU000AOPEN1",
            name: "Активная облигация",
            lots: 5,
            quantity: 5,
            lot_size: 1,
          },
        ],
      }),
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({
        json: {
          bonds: [
            {
              secid: "OPEN1",
              isin: "RU000AOPEN1",
              name: "Активная облигация",
              ytm: 14.5,
              ytm_net: 12.62,
              score: 78,
              face_value: 1000,
              lot_size: 1,
              coupon_type: "fixed",
              risk_level: 2,
            },
            {
              secid: "PEND1",
              isin: "RU000APEND1",
              name: "Ожидающая покупка",
              ytm: 13.0,
              ytm_net: 11.31,
              score: 65,
              face_value: 1000,
              lot_size: 1,
              coupon_type: "fixed",
              risk_level: 2,
            },
          ],
          source: "mock",
          count: 2,
        },
      });
    });
    await gotoPortfolio(page, PORTFOLIO_ID);
    await expect(page.getByRole("tab", { name: /Позиции/ })).toBeVisible({ timeout: 15_000 });
  });

  test("показывает все позиции плана со статусами", async ({ page }) => {
    await page.getByRole("tab", { name: /Позиции/ }).click();

    await expect(page.getByTestId("position-row-RU000AOPEN1")).toBeVisible();
    await expect(page.getByTestId("position-row-RU000AOPEN1")).toHaveAttribute(
      "data-status",
      "active",
    );
    await expect(page.getByTestId("position-row-RU000APEND1")).toBeVisible();
    await expect(page.getByTestId("position-row-RU000APEND1")).toHaveAttribute(
      "data-status",
      "pending",
    );
    await expect(page.getByTestId("position-row-RU000AOPEN1")).toContainText("Активная облигация");
    await expect(page.getByTestId("position-row-RU000APEND1")).toContainText("Ожидающая покупка");
  });

  test("badge на вкладке считает позиции плана", async ({ page }) => {
    const tab = page.getByRole("tab", { name: /Позиции/ });
    await expect(tab).toContainText("2");
  });

  test("показывает YTM и скор из справочника облигаций", async ({ page }) => {
    await page.getByRole("tab", { name: /Позиции/ }).click();

    await expect(page.getByTestId("position-ytm-RU000AOPEN1")).toHaveText("12.62%");
    await expect(page.getByTestId("position-score-RU000AOPEN1")).toHaveText("78");
    await expect(page.getByTestId("position-ytm-RU000APEND1")).toHaveText("11.31%");
    await expect(page.getByTestId("position-score-RU000APEND1")).toHaveText("65");
  });
});
