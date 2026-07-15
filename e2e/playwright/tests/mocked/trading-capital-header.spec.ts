/**
 * E2E: trading-капитал в шапке из плана, даже если portfolio.invested_capital_rub = 0
 * (holdings только на брокерском счёте, data.positions пустой).
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "trading-capital-from-plan";

test.describe("Trading — капитал в шапке", () => {
  test("показывает invested_capital из plan при нуле в portfolio", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Capital From Plan",
      invested_capital_rub: 0,
      cash_balance_rub: 0,
      positions_count: 0,
      data: {
        positions: [],
        cash_balance_rub: 0,
      },
    });

    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan({
        invested_capital_rub: 409_522.42,
        total_invested_rub: 409_522.42,
      }),
      advice: makeAdvice({
        money_rub: 3_447.4,
        available_money_rub: 3_447.4,
        holdings: [
          {
            figi: "FIGI_A",
            isin: "RU000A1",
            name: "МВ ФИН 1Р5",
            lots: 213,
            quantity: 213,
            lot_size: 1,
            current_price_pct: 98.8,
            current_nkd_rub: 0.5,
            ytm: 18,
            maturity_date: "2026-08-06",
            offer_date: null,
            market_value_rub: 211_000,
          },
        ],
      }),
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText(/капитал.*409/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/свободно.*3[\s\u00a0]?447/)).toBeVisible();
  });
});
