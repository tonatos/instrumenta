/**
 * E2E: пут-оферта — watch vs urgent, решение exercise/hold.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  makeTradingState,
  mockConfig,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "put-offer-portfolio";

const samoletPortfolio = makeTradingPortfolio(PORTFOLIO_ID, {
  name: "Put Offer E2E",
  positions_count: 1,
  data: {
    positions: [
      {
        isin: "RU000A109874",
        secid: "RU000A109874",
        name: "СамолетP15",
        lots: 10,
        lot_size: 1,
        purchase_clean_price_pct: 99,
        purchase_dirty_price_rub: 990,
        purchase_aci_rub: 0,
        purchase_date: "2026-01-01",
        purchase_amount_rub: 9900,
        coupon_rate: 12,
        face_value: 1000,
        maturity_date: "2027-07-30",
        offer_date: "2026-08-07",
        offer_price_pct: 100,
        offer_window_status: "unknown",
        put_offer_decision: "pending",
        source: "adopted",
        figi: "FIGI_SAM",
      },
    ],
    slots: [],
    cash_balance_rub: 100_000,
    initial_amount_rub: 100_000,
    horizon_date: "2027-01-01",
    frozen_forecast: null,
  },
});

const planMock = makeEmptyPlan();

const samoletHolding = {
  figi: "FIGI_SAM",
  isin: "RU000A109874",
  name: "СамолетP15",
  lots: 10,
  quantity: 10,
  lot_size: 1,
  current_price_pct: 99,
  current_nkd_rub: 0,
  ytm: 12,
  maturity_date: "2027-07-30",
  offer_date: "2026-08-07",
  market_value_rub: 9900,
};

test.describe("Пут-оферта", () => {
  test("без окна подачи — на контроле, не срочно", async ({ page }) => {
    const watchSuggestion = {
      id: "suggestion-put-watch",
      kind: "put_offer_watch",
      isin: "RU000A109874",
      name: "СамолетP15",
      lots: 10,
      figi: "FIGI_SAM",
      suggested_price_pct: 100.0,
      due_date: "2026-08-07",
      reason: "Пут-оферта 07.08.2026 — окно подачи ещё не объявлено эмитентом",
      urgency: "normal",
      offer_window_status: "unknown",
      submission_start: null,
      submission_end: null,
      chat_template: null,
    };

    await mockConfig(page);
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, samoletPortfolio, {
      plan: planMock,
      tradingState: makeTradingState({
        plan: planMock,
        advice: makeAdvice({
          holdings: [samoletHolding],
          suggestions: [watchSuggestion],
          money_rub: 100_000,
          available_money_rub: 100_000,
        }),
      }),
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("На контроле", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/окно подачи ещё не объявлено/i)).toBeVisible();
    await expect(page.getByText(/\d+ срочных/)).not.toBeVisible();
  });

  test("решение exercise сохраняется через API", async ({ page }) => {
    const openPortfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Put Offer E2E",
      positions_count: 1,
      data: {
        positions: [
          {
            ...samoletPortfolio.data.positions[0],
            offer_submission_start: "2026-07-27",
            offer_submission_end: "2026-07-31",
            offer_window_status: "open",
          },
        ],
        slots: [],
        cash_balance_rub: 100_000,
        initial_amount_rub: 100_000,
        horizon_date: "2027-01-01",
        frozen_forecast: null,
      },
    });

    await mockConfig(page);
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, openPortfolio, {
      plan: planMock,
      tradingState: makeTradingState({
        plan: planMock,
        advice: makeAdvice({
          holdings: [samoletHolding],
          money_rub: 100_000,
          available_money_rub: 100_000,
        }),
      }),
    });

    let patchedDecision: string | null = null;
    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/positions/RU000A109874/put-offer-decision**`,
      async (route) => {
        const body = route.request().postDataJSON() as { decision: string };
        patchedDecision = body.decision;
        await route.fulfill({
          json: {
            ...openPortfolio,
            data: {
              ...openPortfolio.data,
              positions: [
                {
                  ...openPortfolio.data.positions[0],
                  put_offer_decision: body.decision,
                },
              ],
            },
          },
        });
      },
    );

    await gotoPortfolio(page, PORTFOLIO_ID);

    const exerciseButton = page.getByTestId("put-offer-exercise-RU000A109874");
    await expect(exerciseButton).toBeVisible({ timeout: 15_000 });
    await exerciseButton.click();
    await expect.poll(() => patchedDecision).toBe("exercise");
  });
});
