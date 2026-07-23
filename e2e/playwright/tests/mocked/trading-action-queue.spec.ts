/**
 * E2E: advisory-панель в режиме торговли — advice, confirm dialog, active orders.
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

const PORTFOLIO_ID = "trading-portfolio-1";
const SUGGESTION_ID = "suggestion-buy-1";

const tradingPortfolio = makeTradingPortfolio(PORTFOLIO_ID, {
  name: "Trading E2E",
  initial_amount_rub: 100_000,
  horizon_date: "2027-01-01",
  cash_balance_rub: 100_000,
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
    frozen_forecast: null,
  },
});

const planMock = makeEmptyPlan({
  total_net_profit_rub: 10_000,
  total_net_profit_with_held_rub: 10_000,
  invested_capital_rub: 200_000,
  total_invested_rub: 200_000,
  final_cash_balance: 0,
  final_portfolio_value: 110_000,
  expected_xirr_pct: 12,
});

const buySuggestion = {
  id: SUGGESTION_ID,
  kind: "buy",
  isin: "RU000ATEST1",
  name: "Тестовая облигация",
  lots: 5,
  figi: "FIGI_TEST",
  suggested_price_pct: 100.5,
  market_price_pct: 100,
  due_date: null,
  reason: "Свободный кэш — рекомендуем докупить 5 лот(а)",
  urgency: "normal",
  chat_template: null,
};

const testBondDetail = {
  secid: "TEST1",
  isin: buySuggestion.isin,
  name: buySuggestion.name,
  figi: buySuggestion.figi,
  maturity_date: "2027-06-01",
  offer_date: null,
  call_date: null,
  effective_date: "2027-06-01",
  days_to_maturity: 365,
  ytm: 14.5,
  ytm_net: 12.62,
  coupon_rate: 10,
  coupon_type: "fixed",
  last_price: 100,
  face_value: 1000,
  lot_size: 1,
  volume_rub: 1_000_000,
  prev_volume_rub: 900_000,
  credit_rating: "BBB",
  risk_level: 2,
  score: 78,
  ytm_score: 80,
  risk_score: 70,
  liquidity_score: 75,
  is_favorite: false,
  has_warnings: false,
  warnings: [],
  tinvest_enriched: true,
  issuer_name: buySuggestion.name,
  instrument_full_name: buySuggestion.name,
  sector: "",
  description: "",
};

function adviceResponse(
  suggestions = [buySuggestion],
  overrides: Record<string, unknown> = {},
) {
  return makeAdvice({
    suggestions,
    money_rub: 100_000,
    available_money_rub: 100_000,
    ...overrides,
  });
}

const diversifiedBuySuggestions = [
  {
    id: "suggestion-buy-2",
    kind: "buy",
    isin: "RU000ATEST2",
    name: "Тестовая облигация 2",
    lots: 2,
    figi: "FIGI-2",
    suggested_price_pct: 101.0,
    due_date: null,
    reason: "Свободный кэш — рекомендуем докупить по стратегии портфеля",
    urgency: "normal",
    chat_template: null,
  },
  {
    id: "suggestion-buy-3",
    kind: "buy",
    isin: "RU000ATEST3",
    name: "Тестовая облигация 3",
    lots: 3,
    figi: "FIGI-3",
    suggested_price_pct: 100.8,
    due_date: null,
    reason: "Свободный кэш — рекомендуем докупить по стратегии портфеля",
    urgency: "normal",
    chat_template: null,
  },
];

async function mockBondRoutes(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/bonds/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/\/$/, "");
    const detailSecid = path.match(/\/bonds\/([^/]+)$/)?.[1];

    if (detailSecid) {
      if (detailSecid === "TEST1" || detailSecid === buySuggestion.isin) {
        await route.fulfill({
          json: {
            bond: testBondDetail,
            coupons: [],
          },
        });
        return;
      }
    }

    await route.fulfill({
      json: {
        bonds: [testBondDetail],
        source: "mock",
        count: 1,
      },
    });
  });
}

async function setupTradingMocks(
  page: import("@playwright/test").Page,
  options: {
    adviceFactory?: (call: number) => ReturnType<typeof makeAdvice>;
  } = {},
) {
  await mockConfig(page);
  await page.route("**/api/v1/favorites/**", async (route) => {
    await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
  });
  await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, tradingPortfolio, {
    plan: planMock,
    advice: adviceResponse(),
  });
  await mockBondRoutes(page);

  let adviceCount = 0;
  const adviceFactory =
    options.adviceFactory ??
    ((call: number) => {
      if (call === 1) {
        return adviceResponse();
      }
      return adviceResponse([], {
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
      });
    });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
    adviceCount += 1;
    const advice = adviceFactory(adviceCount);
    await route.fulfill({
      json: makeTradingState({ plan: planMock, advice }),
    });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/preview**`, async (route) => {
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

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/place**`, async (route) => {
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
}

test.describe("Советы по торговле", () => {
  test.beforeEach(async ({ page }) => {
    await setupTradingMocks(page);
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
    await expect(confirmDialog.getByText(/Рынок.*100\.00%.*1.*000.*лот/i)).toBeVisible();
    await expect(confirmDialog.getByText(/лимит на 0\.50% выше рынка/i)).toBeVisible();
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

  test("advice со свободным кэшем показывает баннер и рекомендации покупки", async ({ page }) => {
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      await route.fulfill({
        json: makeTradingState({
          plan: planMock,
          advice: adviceResponse(diversifiedBuySuggestions, {
            available_money_rub: 20_000,
            money_rub: 20_000,
          }),
        }),
      });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/капитал.*200/)).toBeVisible();
    await expect(page.getByText(/Свободный кэш.*рекомендуем.*Тестовая облигация 2.*Тестовая облигация 3/i)).toBeVisible();
    await expect(page.getByText("Покупки")).toBeVisible();
    await expect(page.getByText("2", { exact: true })).toBeVisible();
  });

  test("клик по названию в секции «Покупки» открывает карточку облигации", async ({ page }) => {
    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId(`suggestion-bond-title-${SUGGESTION_ID}`).click();

    const sheet = page.getByRole("dialog");
    await expect(sheet).toBeVisible({ timeout: 10_000 });
    await expect(sheet.getByText(buySuggestion.name)).toBeVisible();
    await expect(sheet.getByText("12.62%")).toBeVisible();
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

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      await route.fulfill({
        json: makeTradingState({
          plan: planMock,
          advice: adviceResponse([mtsBuy]),
        }),
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/preview**`, async (route) => {
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

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      await route.fulfill({
        json: makeTradingState({
          plan: planMock,
          advice: adviceResponse([putOfferSuggestion]),
        }),
      });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Советы по торговле")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/предъявите бумаги/i)).toBeVisible();
    await expect(page.getByText("Пут-оферта", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Копировать текст" })).toBeVisible();
  });

  test("в песочнице можно добавить средства на счёт", async ({ page }) => {
    let adviceCalls = 0;

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sandbox-pay-in**`, async (route) => {
      await route.fulfill({
        status: 201,
        json: { amount_added_rub: 50_000, money_rub: 150_000 },
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      adviceCalls += 1;
      await route.fulfill({
        json: makeTradingState({
          plan: planMock,
          advice: adviceResponse(diversifiedBuySuggestions, {
            money_rub: adviceCalls > 1 ? 150_000 : 100_000,
            available_money_rub: adviceCalls > 1 ? 150_000 : 100_000,
          }),
        }),
      });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Песочница · добавить средства")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Добавить средства" }).click();
    await expect(page.getByText(/Свободный кэш.*₽ — рекомендуем/i).first()).toBeVisible({ timeout: 10_000 });
    expect(adviceCalls).toBeGreaterThanOrEqual(2);
  });

  test("показывает свободный и заблокированный кэш", async ({ page }) => {
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      await route.fulfill({
        json: makeTradingState({
          plan: planMock,
          advice: adviceResponse([buySuggestion], {
            money_rub: 50_000,
            available_money_rub: 2_000,
            blocked_money_rub: 48_000,
          }),
        }),
      });
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/preview**`, async (route) => {
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

  test("read-only ключ: баннер и disabled покупка/фиксация плана", async ({ page }) => {
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
      await route.fulfill({
        json: makeTradingState({
          plan: planMock,
          advice: adviceResponse([buySuggestion], { can_place_orders: false }),
        }),
      });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByTestId("readonly-token-banner")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("freeze-deploy-plan")).toHaveCount(0);
    await expect(page.getByTestId(`confirm-buy-${SUGGESTION_ID}`)).toBeDisabled();
  });
});
