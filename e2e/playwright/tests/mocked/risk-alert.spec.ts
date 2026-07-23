/**
 * E2E: risk escalation sell suggestion and acknowledge flow.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "trading-portfolio-risk";
const POSITION_ISIN = "RU000ARISK1";

const riskSellSuggestion = {
  id: "risk-sell-1",
  kind: "sell",
  isin: POSITION_ISIN,
  name: "Рисковая облигация",
  lots: 2,
  figi: "FIGI_RISK",
  suggested_price_pct: 95.5,
  market_price_pct: 96,
  due_date: null,
  reason:
    "Ухудшение риск-профиля эмитента: Эмитент в дефолте по данным MOEX. Сигнал модели: отклонение эмитента от параметров стратегии.",
  urgency: "critical",
  chat_template: null,
  risk_acknowledgeable: true,
};

test.describe("Риск-алерт эмитента", () => {
  test("показывает sell-сигнал и кнопку «Принять риск»", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Risk Alert E2E",
      positions_count: 1,
      invested_capital_rub: 50_000,
      cash_balance_rub: 0,
      data: {
        positions: [
          {
            isin: POSITION_ISIN,
            secid: "RISK1",
            name: "Рисковая облигация",
            lots: 2,
            lot_size: 1,
            purchase_clean_price_pct: 96,
            purchase_dirty_price_rub: 960,
            purchase_aci_rub: 0,
            purchase_date: "2026-01-01",
            purchase_amount_rub: 1920,
            coupon_rate: 12,
            face_value: 1000,
            maturity_date: "2027-06-01",
            offer_date: null,
            source: "adopted",
            figi: "FIGI_RISK",
          },
        ],
        cash_balance_rub: 0,
      },
    });

    let stateCount = 0;
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan({ invested_capital_rub: 50_000 }),
      advice: makeAdvice({ suggestions: [] }),
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      stateCount += 1;
      const suggestions = stateCount === 1 ? [riskSellSuggestion] : [];
      await route.fulfill({
        json: {
          plan: makeEmptyPlan({ invested_capital_rub: 50_000 }),
          advice: makeAdvice({ suggestions }),
        },
      });
    });

    let acknowledged = false;
    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/risk-alerts/${POSITION_ISIN}/acknowledge`,
      async (route) => {
        acknowledged = true;
        await route.fulfill({ status: 204, body: "" });
      },
    );

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Ухудшение риск-профиля эмитента")).toBeVisible();
    await expect(page.getByTestId(`acknowledge-risk-${POSITION_ISIN}`)).toBeVisible();

    await page.getByTestId(`acknowledge-risk-${POSITION_ISIN}`).click();
    expect(acknowledged).toBe(true);

    await expect(page.getByText("Ухудшение риск-профиля эмитента")).toHaveCount(0);
  });
});
