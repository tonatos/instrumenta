/**
 * E2E: продажа позиции через place order в песочнице.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
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
            figi: "FIGI_TEST",
            status: "active",
          },
        ],
      },
    });

    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan({ invested_capital_rub: 3000 }),
      advice: makeAdvice({
        money_rub: 50_000,
        holdings: [
          {
            figi: "FIGI_TEST",
            isin: POSITION_ISIN,
            name: "Тестовая облигация",
            lots: 3,
            quantity: 3,
            lot_size: 1,
          },
        ],
      }),
    });

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/positions/${POSITION_ISIN}/sell-quote`,
      async (route) => {
        await route.fulfill({ json: sellQuoteResponse });
      },
    );
  });

  test("кнопка «Продать» отправляет SELL-заявку на биржу", async ({ page }) => {
    let placePosted = false;
    let adviceCalls = 0;

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/place`, async (route) => {
      placePosted = true;
      const body = route.request().postDataJSON() as {
        lots: number;
        price_pct: number;
        direction: string;
      };
      expect(body.lots).toBe(2);
      expect(body.price_pct).toBe(99.0025);
      expect(body.direction).toBe("SELL");
      await route.fulfill({
        json: {
          order_id: "sell-order-1",
          status: "EXECUTION_REPORT_STATUS_NEW",
          request_uid: "req-sell-1",
          lots_requested: 2,
          lots_executed: 0,
          total_order_amount_rub: 1980,
          initial_commission_rub: 5,
        },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      adviceCalls += 1;
      const activeOrders =
        adviceCalls > 1
          ? [
              {
                order_id: "sell-order-1",
                request_uid: "req-sell-1",
                figi: "FIGI_TEST",
                direction: "SELL",
                lots_requested: 2,
                lots_executed: 0,
                status: "EXECUTION_REPORT_STATUS_NEW",
                price_pct: 99.0025,
                total_order_amount_rub: 1980,
                initial_commission_rub: 5,
              },
            ]
          : [];
      await route.fulfill({
        json: makeAdvice({
          money_rub: 50_000,
          holdings: [
            {
              figi: "FIGI_TEST",
              isin: POSITION_ISIN,
              name: "Тестовая облигация",
              lots: 3,
              quantity: 3,
              lot_size: 1,
            },
          ],
          active_orders: activeOrders,
        }),
      });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await page.getByRole("tab", { name: /Позиции/ }).click();
    await page.getByTestId(`sell-position-${POSITION_ISIN}`).click();
    await expect(page.getByRole("dialog")).toContainText("Продать позицию");
    await expect(page.getByTestId("sell-price-input")).toHaveValue("99.0025");

    await page.getByTestId("sell-lots-input").fill("2");
    await page.getByTestId("sell-position-submit").click();

    await expect.poll(() => placePosted).toBe(true);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByText("Активные заявки")).toBeVisible();
    await expect(page.getByTestId(`sell-pending-badge-${POSITION_ISIN}`)).toBeVisible();
    await expect(page.getByTestId(`sell-position-${POSITION_ISIN}`)).toBeDisabled();
    await expect(page.getByTestId(`sell-position-${POSITION_ISIN}`)).toContainText("На бирже");
  });
});
