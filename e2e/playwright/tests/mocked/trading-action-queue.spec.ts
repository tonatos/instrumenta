/**
 * E2E: advisory-панель в режиме торговли — advice, confirm dialog, active orders.
 */

import { test, expect } from "@playwright/test";

const PORTFOLIO_ID = "trading-portfolio-1";
const SUGGESTION_ID = "suggestion-buy-1";

const tradingPortfolio = {
  id: PORTFOLIO_ID,
  name: "Trading E2E",
  initial_amount_rub: 100_000,
  horizon_date: "2027-01-01",
  risk_profile: "normal",
  cash_balance_rub: 100_000,
  mode: "trading",
  account_id: "acc-e2e",
  account_kind: "sandbox",
  positions_count: 1,
  invested_capital_rub: 200_000,
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
        actual_lots: 0,
      },
    ],
    slots: [],
    cash_balance_rub: 100_000,
    initial_amount_rub: 100_000,
    horizon_date: "2027-01-01",
    mode: "trading",
    account_id: "acc-e2e",
    account_kind: "sandbox",
    frozen_forecast: null,
  },
};

const buySuggestion = {
  id: SUGGESTION_ID,
  kind: "buy",
  isin: "RU000ATEST1",
  name: "Тестовая облигация",
  lots: 5,
  figi: "FIGI_TEST",
  suggested_price_pct: 100.5,
  due_date: null,
  reason: "Свободный кэш — рекомендуем докупить 5 лот(а)",
  urgency: "normal",
  chat_template: null,
};

function adviceResponse(
  suggestions = [buySuggestion],
  overrides: Record<string, unknown> = {},
) {
  return {
    holdings: [],
    cashflow: [],
    performance: null,
    suggestions,
    active_orders: [],
    money_rub: 100_000,
    available_money_rub: 100_000,
    blocked_money_rub: 0,
    warnings: [],
    as_of: new Date().toISOString(),
    ...overrides,
  };
}

const topUpBuySuggestion = {
  id: "suggestion-topup-1",
  kind: "buy",
  isin: "RU000ATEST2",
  name: "Тестовая облигация 2",
  lots: 2,
  figi: "FIGI_TOPUP",
  suggested_price_pct: 101.0,
  due_date: null,
  reason: "Свободный кэш — рекомендуем докупить",
  urgency: "normal",
  chat_template: null,
};

test.describe("Советы по торговле", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          key_rate: 16,
          tax_rate: 13,
          max_days: 1825,
          min_volume_rub: 0,
          tinkoff_configured: true,
          sandbox_configured: true,
          production_configured: false,
        },
      });
    });

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
          total_net_profit_rub: 10_000,
          total_net_profit_with_held_rub: 10_000,
          invested_capital_rub: 200_000,
          total_invested_rub: 200_000,
          final_cash_balance: 0,
          final_portfolio_value: 110_000,
          expected_xirr_pct: 12,
          notes: [],
          cashflow: [],
          value_timeline: [],
          held_positions: [],
          slots: [],
        },
      });
    });

    let adviceCount = 0;
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      adviceCount += 1;
      if (adviceCount === 1) {
        await route.fulfill({ json: adviceResponse() });
        return;
      }
      await route.fulfill({
        json: adviceResponse([], {
          active_orders: [
            {
              order_id: "order-e2e-123",
              request_uid: "req-e2e-1",
              figi: "FIGI_TEST",
              direction: "BUY",
              lots_requested: 5,
              lots_executed: 0,
              status: "EXECUTION_REPORT_STATUS_NEW",
              price_pct: 100.5,
              total_order_amount_rub: 5055,
              initial_commission_rub: 5,
            },
          ],
        }),
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/preview`, async (route) => {
      const body = route.request().postDataJSON() as { lots?: number; price_pct?: number };
      const lots = body.lots ?? buySuggestion.lots;
      const pricePct = body.price_pct ?? buySuggestion.suggested_price_pct;
      const aciPerBond = 5;
      const cleanAmount = (lots * 1000 * pricePct) / 100;
      const dirtyAmount = cleanAmount + aciPerBond * lots;
      const commission = 10;
      await route.fulfill({
        json: {
          order_lots: lots,
          order_bonds: lots,
          lot_size: 1,
          order_price_pct: pricePct,
          clean_amount_rub: cleanAmount,
          aci_rub_per_bond: aciPerBond,
          local_total_amount_rub: dirtyAmount,
          broker_clean_amount_rub: cleanAmount,
          broker_aci_amount_rub: aciPerBond * lots,
          broker_total_amount_rub: dirtyAmount + commission,
          broker_commission_rub: commission,
          money_rub: 100_000,
          sufficient_cash: true,
          preview_source: "broker",
        },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/place`, async (route) => {
      await route.fulfill({
        json: {
          order_id: "order-e2e-123",
          status: "EXECUTION_REPORT_STATUS_NEW",
          request_uid: "req-e2e-1",
          lots_requested: 5,
          lots_executed: 0,
          total_order_amount_rub: 5055,
          initial_commission_rub: 5,
        },
      });
    });
  });

  test("advice показывает покупку, confirm-диалог отправляет заявку", async ({ page }) => {
    await page.goto(`/portfolio/${PORTFOLIO_ID}?suggestion_confirm=${SUGGESTION_ID}`);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    const suggestionCard = page.locator(`#suggestion-${SUGGESTION_ID}`);
    await expect(suggestionCard).toBeVisible();

    await expect(page.getByRole("heading", { name: "Подтвердить покупку" })).toBeVisible({
      timeout: 10_000,
    });
    const confirmDialog = page.getByRole("dialog", { name: "Подтвердить покупку" });
    await expect(confirmDialog.getByText(/чистой.*цене/i)).toBeVisible();
    await expect(confirmDialog.getByText(/≈.*1.*005.*чистая.*1.*010.*с НКД за лот/)).toBeVisible();
    await expect(confirmDialog.getByText("Расчёт брокера")).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText("Итого к списанию")).toBeVisible();
    await expect(confirmDialog.getByText(/5[\s\u00a0]060/)).toBeVisible();

    await page.getByRole("button", { name: "Отправить заявку" }).click();

    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("На бирже").first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("order-e2e-123")).toBeVisible();
    await expect(page.getByText(/5[\s\u00a0]055/)).toBeVisible();
  });

  test("advice со свободным кэшем показывает баннер и рекомендацию покупки", async ({ page }) => {
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      await route.fulfill({
        json: adviceResponse([topUpBuySuggestion], {
          available_money_rub: 20_000,
          money_rub: 20_000,
        }),
      });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/старт.*100/)).toBeVisible();
    await expect(page.getByText(/капитал.*200/)).toBeVisible();
    await expect(page.getByText(/Свободный кэш.*рекомендуем/i).first()).toBeVisible();
    await expect(page.getByText("Покупка", { exact: true })).toBeVisible();
  });

  test("модалка покупки показывает грязную сумму с НКД по расчёту брокера", async ({ page }) => {
    const mtsBuy = {
      ...buySuggestion,
      id: "suggestion-mts",
      name: "МТС-Банк05",
      lots: 1,
      suggested_price_pct: 100.4095,
      reason: "Свободный кэш",
    };

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      await route.fulfill({ json: adviceResponse([mtsBuy]) });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/preview`, async (route) => {
      await route.fulfill({
        json: {
          order_lots: 1,
          order_bonds: 1,
          lot_size: 1,
          order_price_pct: 100.4095,
          clean_amount_rub: 1004.1,
          aci_rub_per_bond: 285,
          local_total_amount_rub: 1289.1,
          broker_clean_amount_rub: 1004.1,
          broker_aci_amount_rub: 285,
          broker_total_amount_rub: 1294.1,
          broker_commission_rub: 5,
          money_rub: 100_000,
          sufficient_cash: true,
          preview_source: "broker",
        },
      });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}?suggestion_confirm=suggestion-mts`);

    const confirmDialog = page.getByRole("dialog", { name: "Подтвердить покупку" });
    await expect(confirmDialog).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText("Лимит (чистая цена), %")).toBeVisible();
    await expect(confirmDialog.getByText(/≈.*1.*004.*чистая.*1.*289.*с НКД за лот/)).toBeVisible();
    await expect(confirmDialog.getByText("Цена за лот")).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText("НКД", { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText(/1[\s\u00a0]294/)).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText("Расчёт брокера")).toBeVisible();
  });

  test("пут-оферта показывает срочное напоминание", async ({ page }) => {
    const putOfferSuggestion = {
      id: "suggestion-put-urgent",
      kind: "put_offer_reminder",
      isin: "RU000ATEST1",
      name: "Тестовая облигация",
      lots: 5,
      figi: "FIGI_TEST",
      suggested_price_pct: 100.0,
      due_date: "2026-07-09",
      reason:
        "Скоро пут-оферта 20.07.2026 — предъявите бумаги до 9 июля включительно",
      urgency: "critical",
      chat_template: "Текст для чата",
    };

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      await route.fulfill({ json: adviceResponse([putOfferSuggestion]) });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/предъявите бумаги/i)).toBeVisible();
    await expect(page.getByText("Пут-оферта", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Копировать текст" })).toBeVisible();
  });

  test("в песочнице можно добавить средства для теста пополнения", async ({ page }) => {
    let adviceCalls = 0;

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sandbox-pay-in`, async (route) => {
      await route.fulfill({
        status: 201,
        json: { amount_added_rub: 50_000, money_rub: 150_000 },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      adviceCalls += 1;
      await route.fulfill({
        json: adviceResponse([topUpBuySuggestion], {
          money_rub: adviceCalls > 1 ? 150_000 : 100_000,
          available_money_rub: adviceCalls > 1 ? 150_000 : 100_000,
        }),
      });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);

    await expect(page.getByText("Песочница · добавить средства")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Добавить средства" }).click();
    await expect(page.getByText(/Свободный кэш.*₽ — рекомендуем/i).first()).toBeVisible({ timeout: 10_000 });
    expect(adviceCalls).toBeGreaterThanOrEqual(2);
  });

  test("показывает свободный и заблокированный кэш", async ({ page }) => {
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/advice`, async (route) => {
      await route.fulfill({
        json: adviceResponse([buySuggestion], {
          money_rub: 50_000,
          available_money_rub: 2_000,
          blocked_money_rub: 48_000,
        }),
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/preview`, async (route) => {
      await route.fulfill({
        json: {
          order_lots: 5,
          order_bonds: 5,
          lot_size: 1,
          order_price_pct: 100.5,
          clean_amount_rub: 5025,
          aci_rub_per_bond: 5,
          local_total_amount_rub: 5050,
          broker_clean_amount_rub: 5025,
          broker_aci_amount_rub: 25,
          broker_total_amount_rub: 5060,
          broker_commission_rub: 10,
          money_rub: 2_000,
          sufficient_cash: false,
          preview_source: "broker",
        },
      });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}?suggestion_confirm=${SUGGESTION_ID}`);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Свободно/)).toBeVisible();
    await expect(page.getByText(/заблокировано/)).toBeVisible();

    const confirmDialog = page.getByRole("dialog", { name: "Подтвердить покупку" });
    await expect(confirmDialog).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText(/может не хватить средств/i)).toBeVisible({
      timeout: 10_000,
    });
  });
});
