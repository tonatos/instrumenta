/**
 * E2E: trading-портфель — ручной override реинвеста без ошибки бюджета (aa19dfd regression).
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  makeTradingState,
  mockConfig,
  mockBondsEmpty,
  seedAuth,
} from "./fixtures";

const PORTFOLIO_ID = "trading-reinvest-override";
const SOURCE_ISIN = "RU000A100PB0";
const TARGET_ISIN = "RU000A109TG2";

function makeZhkhrsyaSlot(confirmedIsin: string | null = null) {
  return {
    trigger_date: "2026-07-28",
    trigger_reason: "maturity",
    expected_cash_rub: 5_632,
    suggested_isin: "RU000A107G22",
    suggested_name: "КОРПСАН 01",
    confirmed_isin: confirmedIsin,
    gap_days: 2,
    source_position_isin: SOURCE_ISIN,
    selection_mode: confirmedIsin ? "manual" : "strategy",
    status: "ok",
    failure_reason: null,
    eligible_candidates: [
      {
        isin: TARGET_ISIN,
        name: "iКарРус1P4",
        score: 90,
        ytm_net: 24,
      },
      {
        isin: "RU000A107G22",
        name: "КОРПСАН 01",
        score: 85,
        ytm_net: 21,
      },
    ],
  };
}

const tradingPortfolio = makeTradingPortfolio(PORTFOLIO_ID, {
  name: "Trading Reinvest Override",
  invested_capital_rub: 210_000,
  data: {
    positions: [
      {
        isin: SOURCE_ISIN,
        secid: "ЖКХРСЯ",
        name: "ЖКХРСЯ БО1",
        lots: 5,
        lot_size: 1,
        purchase_clean_price_pct: 99.5,
        purchase_dirty_price_rub: 1039.74,
        purchase_aci_rub: 44.74,
        purchase_date: "2026-07-07",
        purchase_amount_rub: 5198.7,
        coupon_rate: 23,
        face_value: 1000,
        maturity_date: "2026-07-28",
        offer_date: null,
        source: "initial",
        put_offer_decision: "pending",
        figi: null,
        actual_lots: 5,
      },
    ],
  },
});

test.describe("Trading — override реинвеста", () => {
  test.beforeEach(async ({ page }) => {
    let confirmedIsin: string | null = null;

    await seedAuth(page);
    await mockConfig(page);
    await mockBondsEmpty(page);

    await page.route("**/api/v1/portfolios/", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ json: [tradingPortfolio] });
        return;
      }
      await route.continue();
    });

    const buildState = () =>
      makeTradingState({
        plan: makeEmptyPlan({
          initial_cash_rub: 632.14,
          invested_capital_rub: 210_000,
          slots: [makeZhkhrsyaSlot(confirmedIsin)],
        }),
        advice: makeAdvice(),
      });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      await route.fulfill({ json: buildState() });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/plan**`, async (route) => {
      await route.fulfill({ json: buildState().plan });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/slots/override**`, async (route) => {
      const body = route.request().postDataJSON() as {
        source_position_isin: string;
        confirmed_isin: string | null;
      };
      if (body.confirmed_isin === TARGET_ISIN) {
        confirmedIsin = body.confirmed_isin;
        await route.fulfill({
          status: 200,
          json: tradingPortfolio,
        });
        return;
      }
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        json: {
          detail: "ожидаемого кэша (-84544 ₽) не хватает на 1 лот (977 ₽)",
          extra: { code: "invalid_replacement" },
        },
      });
    });
  });

  test("ручной выбор iКарРус1P4 сохраняется без ошибки бюджета", async ({ page }) => {
    await gotoPortfolio(page, PORTFOLIO_ID);
    await page.getByRole("tab", { name: /реинвестиции/i }).click();

    await expect(page.getByText("ЖКХРСЯ БО1")).toBeVisible();
    await expect(page.getByText("доступно на дату")).toBeVisible();

    await page.getByRole("button", { name: "Выбрать вручную" }).click();
    await page.getByRole("button", { name: /Выберите бумагу|КОРПСАН/i }).click();
    await page.getByText("iКарРус1P4").click();

    await expect(page.getByRole("alert")).not.toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/-84/)).not.toBeVisible();
    await expect(page.getByText("· 1 вручную")).toBeVisible({ timeout: 5000 });
  });
});
