/**
 * E2E: attach к счёту с уже существующими бумагами — live plan и позиции.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "attach-holdings-1";
const HOLDING_ISIN = "RU000AHOLD1";

test.describe("Attach — счёт с бумагами", () => {
  test("после attach показывает позиции со счёта и cashflow в плане", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Attach Holdings",
      mode: "trading",
      account_id: "acc-holdings",
      account_kind: "sandbox",
      positions_count: 0,
      data: {
        positions: [],
        mode: "trading",
        account_id: "acc-holdings",
        account_kind: "sandbox",
      },
    });

    const advice = makeAdvice({
      holdings: [
        {
          figi: "FIGI_HOLD",
          isin: HOLDING_ISIN,
          name: "Облигация со счёта",
          lots: 5,
          quantity: 5,
          lot_size: 1,
          current_price_pct: 96,
          current_nkd_rub: 10,
          ytm: 14,
          maturity_date: "2027-06-01",
          offer_date: null,
          market_value_rub: 4800,
        },
      ],
    });

    const plan = {
      total_net_profit_rub: 12_000,
      total_net_profit_with_held_rub: 15_000,
      invested_capital_rub: 54_800,
      total_invested_rub: 4800,
      final_cash_balance: 50_000,
      final_portfolio_value: 54_800,
      expected_xirr_pct: 13.5,
      notes: [],
      cashflow: [
        {
          date: "2026-08-01",
          kind: "coupon",
          amount_rub: 250,
          label: "Купон · Облигация со счёта",
          is_projected: true,
        },
      ],
      value_timeline: [],
      held_positions: [],
      slots: [],
    };

    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, { advice, plan });

    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({
        json: {
          bonds: [
            {
              secid: "HOLD1",
              isin: HOLDING_ISIN,
              name: "Облигация со счёта",
              ytm: 14.5,
              ytm_net: 12.6,
              score: 72,
              face_value: 1000,
              lot_size: 1,
              coupon_type: "fixed",
              risk_level: 2,
            },
          ],
          source: "mock",
          count: 1,
        },
      });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await page.getByRole("tab", { name: /Позиции/ }).click();
    await expect(page.getByTestId(`position-row-${HOLDING_ISIN}`)).toBeVisible();
    await expect(page.getByTestId(`position-row-${HOLDING_ISIN}`)).toHaveAttribute(
      "data-status",
      "active",
    );

    await page.getByRole("tab", { name: /Cashflow/ }).click();
    await expect(
      page.getByRole("cell", { name: "Купон · Облигация со счёта" }),
    ).toBeVisible();
  });
});
