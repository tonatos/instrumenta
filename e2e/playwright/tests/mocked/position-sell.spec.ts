/**
 * E2E: продажа через очередь manual_sell в песочнице.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeEmptyPlan,
  makeEmptySync,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "sell-portfolio-1";
const POSITION_ISIN = "RU000ATEST1";

const sellQuoteResponse = {
  market_price_pct: 99.5,
  suggested_price_pct: 99.0025,
  available_lots: 3,
  sell_buffer_label: "0.5%",
};

const manualSellOp = {
  id: "manual-sell-op-1",
  kind: "manual_sell",
  isin: POSITION_ISIN,
  name: "Тестовая облигация",
  lots: 2,
  figi: "FIGI_TEST",
  suggested_price_pct: 99.0,
  due_date: null,
  reason: "Продажа 2 лот(а) из 3 на счёте",
  status: "action_required",
  block_reason: null,
  estimated_amount_rub: 1990,
  face_value_rub: 1000,
  lot_size: 1,
  aci_rub_per_bond: 5,
  active_order_id: null,
  active_order_status: null,
  urgency: "normal",
  chat_template: null,
};

test.describe("Продажа позиции (песочница)", () => {
  test.beforeEach(async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      positions_count: 1,
      data: {
        positions: [
          {
            isin: POSITION_ISIN,
            secid: "TEST1",
            name: "Тестовая облигация",
            lots: 3,
            lot_size: 1,
            purchase_clean_price_pct: 100,
            purchase_dirty_price_rub: 1000,
            purchase_aci_rub: 0,
            purchase_date: "2026-01-01",
            purchase_amount_rub: 3000,
            coupon_rate: 10,
            face_value: 1000,
            maturity_date: "2027-06-01",
            offer_date: null,
            source: "initial",
            put_offer_decision: "pending",
            figi: "FIGI_TEST",
            actual_lots: 3,
            status: "active",
          },
        ],
      },
    });

    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan({ invested_capital_rub: 3000 }),
      sync: makeEmptySync({ money_rub: 50_000 }),
    });

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/positions/${POSITION_ISIN}/sell-quote`,
      async (route) => {
        await route.fulfill({ json: sellQuoteResponse });
      },
    );
  });

  test("кнопка «Продать» ставит manual_sell в очередь", async ({ page }) => {
    let queuePosted = false;

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/positions/${POSITION_ISIN}/queue-sell`,
      async (route) => {
        queuePosted = true;
        const body = route.request().postDataJSON() as { lots: number; price_pct: number };
        expect(body.lots).toBe(2);
        expect(body.price_pct).toBe(99.0025);
        await route.fulfill({
          json: makeEmptySync({
            pending_operations: [manualSellOp],
          }),
        });
      },
    );

    await gotoPortfolio(page, PORTFOLIO_ID);

    await page.getByTestId(`sell-position-${POSITION_ISIN}`).click();
    await expect(page.getByRole("dialog")).toContainText("Поставить продажу в очередь");
    await expect(page.getByTestId("sell-price-input")).toHaveValue("99.0025");

    await page.getByTestId("sell-lots-input").fill("2");
    await page.getByTestId("sell-position-submit").click();

    await expect.poll(() => queuePosted).toBe(true);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByText("Продажи")).toBeVisible();
    await expect(page.getByText("Подтвердить продажу")).toBeVisible();
    await expect(page.getByTestId(`sell-pending-badge-${POSITION_ISIN}`)).toBeVisible();
    await expect(page.getByTestId(`sell-position-${POSITION_ISIN}`)).toBeDisabled();
    await expect(page.getByTestId(`sell-position-${POSITION_ISIN}`)).toContainText("В очереди");
  });
});
