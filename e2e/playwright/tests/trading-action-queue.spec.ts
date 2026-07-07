/**
 * E2E: очередь действий в режиме торговли — sync, confirm dialog, in_progress.
 */

import { test, expect } from "@playwright/test";

const PORTFOLIO_ID = "trading-portfolio-1";
const PENDING_OP_ID = "pending-op-initial-1";

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
    pending_operations: [],
  },
};

const pendingBuy = {
  id: PENDING_OP_ID,
  kind: "initial_buy",
  isin: "RU000ATEST1",
  name: "Тестовая облигация",
  lots: 5,
  figi: "FIGI_TEST",
  suggested_price_pct: 100.5,
  due_date: null,
  reason: "Стартовая покупка: 5 лот(а) из 5",
  status: "action_required",
  block_reason: null,
  estimated_amount_rub: 5050,
  face_value_rub: 1000,
  lot_size: 1,
  aci_rub_per_bond: 5,
  active_order_id: null,
  active_order_status: null,
  urgency: "normal",
  chat_template: null,
};

function syncResponse(pending = [pendingBuy], overrides: Record<string, unknown> = {}) {
  return {
    pending_operations: pending,
    drifts: [],
    money_rub: 100_000,
    last_synced_at: new Date().toISOString(),
    has_pending_top_up: false,
    pending_top_up_rub: 0,
    top_up_auto_applied: false,
    top_up_distributed_rub: 0,
    top_up_notes: [],
    notes: [],
    ...overrides,
  };
}

const topUpBuy = {
  id: "pending-op-topup-1",
  kind: "top_up_buy",
  isin: "RU000ATEST2",
  name: "Тестовая облигация 2",
  lots: 2,
  figi: "FIGI_TOPUP",
  suggested_price_pct: 101.0,
  due_date: null,
  reason: "Пополнение счёта — автораспределение",
  top_up_batch_id: "batch-e2e-1",
  status: "action_required",
  block_reason: null,
  estimated_amount_rub: 2020,
  active_order_id: null,
  active_order_status: null,
  urgency: "normal",
  chat_template: null,
};

test.describe("Очередь действий (торговля)", () => {
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

    let syncCount = 0;
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sync`, async (route) => {
      syncCount += 1;
      if (syncCount === 1) {
        await route.fulfill({ json: syncResponse() });
        return;
      }
      await route.fulfill({
        json: syncResponse([
          {
            ...pendingBuy,
            status: "in_progress",
            active_order_id: "order-e2e-123",
            active_order_status: "EXECUTION_REPORT_STATUS_NEW",
            active_order_lots: 5,
            active_order_price_pct: 100.5,
            active_order_total_rub: 5055,
            active_order_commission_rub: 5,
            active_order_lots_executed: 0,
            active_order_bonds_count: 5,
          },
        ]),
      });
    });

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/pending-operations/**/preview`,
      async (route) => {
        const body = route.request().postDataJSON() as { lots?: number; price_pct?: number };
        const lots = body.lots ?? pendingBuy.lots;
        const pricePct = body.price_pct ?? pendingBuy.suggested_price_pct;
        const aciPerBond = pendingBuy.aci_rub_per_bond ?? 0;
        const cleanAmount = (lots * 1000 * pricePct) / 100;
        const dirtyAmount = cleanAmount + aciPerBond * lots;
        const commission = 10;
        await route.fulfill({
          json: {
            order_lots: lots,
            order_bonds: lots * (pendingBuy.lot_size ?? 1),
            lot_size: pendingBuy.lot_size ?? 1,
            order_price_pct: pricePct,
            clean_amount_rub: cleanAmount,
            aci_rub_per_bond: aciPerBond,
            local_total_amount_rub: dirtyAmount,
            broker_clean_amount_rub: cleanAmount,
            broker_aci_amount_rub: aciPerBond * lots * (pendingBuy.lot_size ?? 1),
            broker_total_amount_rub: dirtyAmount + commission,
            broker_commission_rub: commission,
            money_rub: 100_000,
            sufficient_cash: true,
            preview_source: "broker",
          },
        });
      },
    );

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/pending-operations/${PENDING_OP_ID}/confirm`,
      async (route) => {
        await route.fulfill({
          json: syncResponse([
            {
              ...pendingBuy,
              status: "in_progress",
              active_order_id: "order-e2e-123",
              active_order_status: "EXECUTION_REPORT_STATUS_NEW",
              active_order_lots: 5,
              active_order_price_pct: 100.5,
              active_order_total_rub: 5055,
              active_order_commission_rub: 5,
              active_order_lots_executed: 0,
              active_order_bonds_count: 5,
            },
          ]),
        });
      },
    );
  });

  test("sync показывает покупку, confirm-диалог отправляет заявку", async ({ page }) => {
    await page.goto(`/portfolio/${PORTFOLIO_ID}?pending_confirm=${PENDING_OP_ID}`);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    const opCard = page.locator(`#pending-op-${PENDING_OP_ID}`);
    await expect(opCard).toBeVisible();

    // Deep-link opens confirm dialog after sync
    await expect(page.getByRole("heading", { name: "Подтвердить покупку" })).toBeVisible({
      timeout: 10_000,
    });
    const confirmDialog = page.getByRole("dialog", { name: "Подтвердить покупку" });
    await expect(confirmDialog.getByText(/чистой.*цене/i)).toBeVisible();
    await expect(confirmDialog.getByText("Номинал", { exact: true })).toBeVisible();
    await expect(confirmDialog.getByText("Чистая стоимость лота")).toBeVisible();
    await expect(confirmDialog.getByText("НКД за лот")).toBeVisible();
    await expect(confirmDialog.getByText("Итого (5 лот.)")).toBeVisible();
    await expect(confirmDialog.getByText(/5[\s\u00a0]050/)).toBeVisible();
    await expect(confirmDialog.getByText("Расчёт брокера")).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: "Отправить заявку" }).click();

    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("На бирже").first()).toBeVisible({ timeout: 10_000 });
    await expect(opCard.getByText(/5[\s\u00a0]055/)).toBeVisible();
    await expect(opCard.getByText("5 лот.")).toBeVisible();
    await expect(opCard.getByText("Новая")).toBeVisible();
    await opCard.getByRole("button", { name: "Детали заявки" }).click();
    await expect(opCard.getByText("order-e2e-123")).toBeVisible();
    await expect(opCard.getByText("Сумма заявки")).toBeVisible();
    await expect(opCard.getByText(/5[\s\u00a0]055/).nth(1)).toBeVisible();
  });

  test("sync с top-up показывает баннер и покупку пополнения", async ({ page }) => {
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sync`, async (route) => {
      await route.fulfill({
        json: syncResponse([topUpBuy], {
          top_up_auto_applied: true,
          top_up_distributed_rub: 20_000,
        }),
      });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Обнаружено пополнение/)).toBeVisible();
    await expect(page.getByText("Покупка (пополнение)")).toBeVisible();
    await expect(page.getByText("Отменить партию")).toBeVisible();
  });

  test("модалка покупки показывает грязную сумму с НКД по расчёту брокера", async ({ page }) => {
    const mtsBuy = {
      ...pendingBuy,
      id: "pending-op-mts",
      name: "МТС-Банк05",
      lots: 1,
      suggested_price_pct: 100.4095,
      aci_rub_per_bond: 285,
      estimated_amount_rub: 1289.1,
    };

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sync`, async (route) => {
      await route.fulfill({ json: syncResponse([mtsBuy]) });
    });

    await page.route(
      `**/api/v1/portfolios/${PORTFOLIO_ID}/pending-operations/pending-op-mts/preview`,
      async (route) => {
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
      },
    );

    await page.goto(`/portfolio/${PORTFOLIO_ID}?pending_confirm=pending-op-mts`);

    const confirmDialog = page.getByRole("dialog", { name: "Подтвердить покупку" });
    await expect(confirmDialog).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText("Лимит (чистая цена), %")).toBeVisible();
    await expect(confirmDialog.getByText("НКД за лот")).toBeVisible();
    await expect(confirmDialog.getByText(/1[\s\u00a0]294/)).toBeVisible({ timeout: 10_000 });
    await expect(confirmDialog.getByText("расчёт брокера")).toBeVisible();
  });

  test("пут-оферта в последние дни показывает срочное напоминание", async ({ page }) => {
    const putOfferOp = {
      id: "pending-op-put-urgent",
      kind: "put_offer_submit",
      isin: "RU000ATEST1",
      name: "Тестовая облигация",
      lots: 5,
      figi: "FIGI_TEST",
      suggested_price_pct: 100.0,
      due_date: "2026-07-09",
      reason:
        "Пут-оферта 2026-07-20 по цене 100.00%. Подайте заявку через чат брокера (API не умеет). " +
        "Срочно: предъявите бумаги до 2026-07-09 включительно, если ещё не подали заявку.",
      status: "action_required",
      block_reason: null,
      estimated_amount_rub: null,
      active_order_id: null,
      active_order_status: null,
      urgency: "critical",
      chat_template: "Текст для чата",
    };

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/sync`, async (route) => {
      await route.fulfill({ json: syncResponse([putOfferOp]) });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Осталось мало времени/)).toBeVisible();
    await expect(page.getByText(/предъявите бумаги/i)).toBeVisible();
    await expect(page.getByText("Я подал оферту")).toBeVisible();
  });
});
