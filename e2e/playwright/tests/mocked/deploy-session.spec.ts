/**
 * E2E: deploy session — freeze plan, partial buy keeps remaining items stable.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  makeTradingState,
  mockConfig,
  seedAuth,
} from "./fixtures";

const PORTFOLIO_ID = "deploy-session-portfolio";

const buySuggestions = [
  {
    id: "deploy-item-1",
    kind: "buy" as const,
    isin: "RU000BUY01",
    name: "Bond Alpha",
    lots: 5,
    figi: "FIGI-1",
    suggested_price_pct: 100.5,
    market_price_pct: 100,
    due_date: null,
    reason: "Свободный кэш — Bond Alpha",
    urgency: "normal" as const,
    chat_template: null,
  },
  {
    id: "deploy-item-2",
    kind: "buy" as const,
    isin: "RU000BUY02",
    name: "Bond Beta",
    lots: 3,
    figi: "FIGI-2",
    suggested_price_pct: 101.0,
    market_price_pct: 100,
    due_date: null,
    reason: "Свободный кэш — Bond Beta",
    urgency: "normal" as const,
    chat_template: null,
  },
  {
    id: "deploy-item-3",
    kind: "buy" as const,
    isin: "RU000BUY03",
    name: "Bond Gamma",
    lots: 2,
    figi: "FIGI-3",
    suggested_price_pct: 99.5,
    market_price_pct: 100,
    due_date: null,
    reason: "Свободный кэш — Bond Gamma",
    urgency: "normal" as const,
    chat_template: null,
  },
];

const portfolio = makeTradingPortfolio(PORTFOLIO_ID, { name: "Deploy Session E2E" });
const planMock = makeEmptyPlan();

type SessionPhase = "live" | "frozen" | "partial";

function sessionItems(phase: SessionPhase) {
  return buySuggestions.map((s, idx) => ({
    ...s,
    estimated_amount_rub: 20_000,
    status: phase === "partial" && idx === 0 ? "placed" : "pending",
    order_id: phase === "partial" && idx === 0 ? "ord-1" : null,
  }));
}

function buildDeploySession(phase: SessionPhase) {
  const items = sessionItems(phase);
  const pending = items.filter((i) => i.status === "pending").length;
  const placed = items.filter((i) => i.status === "placed").length;
  return {
    id: "session-e2e-1",
    status: "active" as const,
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    cash_snapshot_rub: 80_000,
    progress: {
      total: 3,
      pending,
      placed,
      filled: 0,
      skipped: 0,
      stale: 0,
    },
    items,
    warnings: [] as string[],
  };
}

function pendingSuggestions(phase: SessionPhase) {
  return sessionItems(phase)
    .filter((item) => item.status === "pending")
    .map((item) => ({
      id: item.id,
      kind: item.kind,
      isin: item.isin,
      name: item.name,
      lots: item.lots,
      figi: item.figi,
      suggested_price_pct: item.suggested_price_pct,
      market_price_pct: item.market_price_pct,
      due_date: item.due_date,
      reason: item.reason,
      urgency: item.urgency,
      chat_template: item.chat_template,
    }));
}

async function setupDeploySessionMocks(
  page: import("@playwright/test").Page,
  options: { initialPhase?: SessionPhase } = {},
) {
  let phase: SessionPhase = options.initialPhase ?? "live";

  await seedAuth(page);
  await mockConfig(page);

  await page.route("**/api/v1/bonds/**", async (route) => {
    await route.fulfill({
      json: {
        bonds: buySuggestions.map((s, i) => ({
          secid: `SEC${i}`,
          isin: s.isin,
          name: s.name,
          figi: s.figi,
          last_price: 100,
        })),
        source: "mock",
        count: 3,
      },
    });
  });

  await page.route("**/api/v1/portfolios/", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [portfolio] });
      return;
    }
    await route.continue();
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/plan**`, async (route) => {
    await route.fulfill({ json: planMock });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/notifications**`, async (route) => {
    await route.fulfill({ json: { notifications: [] } });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/account-operations**`, async (route) => {
    await route.fulfill({ json: { operations: [], from_date: null } });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/deploy-sessions**`, async (route) => {
    const url = route.request().url();
    const method = route.request().method();

    if (method === "POST" && url.endsWith("/deploy-sessions")) {
      if (phase !== "live") {
        await route.fulfill({
          status: 409,
          json: { detail: "Уже есть активный план закупки — завершите или отмените его" },
        });
        return;
      }
      phase = "frozen";
      await route.fulfill({ status: 201, json: buildDeploySession("frozen") });
      return;
    }
    if (method === "DELETE") {
      phase = "live";
      await route.fulfill({ json: { ...buildDeploySession("frozen"), status: "cancelled" } });
      return;
    }
    await route.continue();
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
    const deploySession = phase === "live" ? null : buildDeploySession(phase);
    const suggestions =
      phase === "live" ? buySuggestions : pendingSuggestions(phase);

    await route.fulfill({
      json: makeTradingState({
        plan: planMock,
        advice: makeAdvice({
          suggestions,
          deploy_session: deploySession,
          available_money_rub: phase === "partial" ? 60_000 : 80_000,
          money_rub: phase === "partial" ? 60_000 : 80_000,
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
        money_rub: 80_000,
        sufficient_cash: true,
        preview_source: "broker",
        market_price_pct: 100,
        face_value_rub: 1000,
      },
    });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/orders/place**`, async (route) => {
    phase = "partial";
    await route.fulfill({
      json: {
        order_id: "ord-1",
        status: "EXECUTION_REPORT_STATUS_NEW",
        request_uid: "uid-1",
        lots_requested: 5,
        lots_executed: 0,
        total_order_amount_rub: 5060,
        initial_commission_rub: 10,
      },
    });
  });

  return {
    setPhase: (next: SessionPhase) => {
      phase = next;
    },
  };
}

test.describe("Deploy session", () => {
  test("buy confirm disabled until plan frozen", async ({ page }) => {
    await setupDeploySessionMocks(page);
    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("freeze-plan-required-hint")).toBeVisible();
    await expect(page.getByTestId("confirm-buy-deploy-item-1")).toBeDisabled();

    await page.getByTestId("freeze-deploy-plan").click();
    await expect(page.getByTestId("deploy-session-banner")).toBeVisible();
    await expect(page.getByTestId("confirm-buy-deploy-item-1")).toBeEnabled();
  });

  test("freeze plan then partial buy keeps remaining ISINs and lots", async ({ page }) => {
    await setupDeploySessionMocks(page);
    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByText("Очередь действий")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("freeze-deploy-plan")).toBeVisible();
    await page.getByTestId("freeze-deploy-plan").click();

    await expect(page.getByTestId("deploy-session-banner")).toBeVisible();
    await expect(page.getByTestId("suggestion-bond-title-deploy-item-1")).toBeVisible();
    await expect(page.getByTestId("suggestion-bond-title-deploy-item-2")).toBeVisible();
    await expect(page.getByTestId("suggestion-bond-title-deploy-item-3")).toBeVisible();

    await page.getByRole("button", { name: "Отправить заявку BUY" }).first().click();
    await expect(page.getByRole("heading", { name: "Отправить заявку BUY" })).toBeVisible();
    await page.getByRole("button", { name: "Отправить заявку" }).click();

    await expect(page.getByTestId("suggestion-bond-title-deploy-item-1")).toHaveCount(0, {
      timeout: 10_000,
    });
    await expect(page.getByTestId("suggestion-bond-title-deploy-item-2")).toBeVisible();
    await expect(page.getByTestId("suggestion-bond-title-deploy-item-3")).toBeVisible();
    await expect(page.locator("#suggestion-deploy-item-2")).toContainText("3 лот.");
    await expect(page.locator("#suggestion-deploy-item-3")).toContainText("2 лот.");
  });

  test("create conflict shows hint when active plan blocks new session", async ({ page }) => {
    await setupDeploySessionMocks(page);
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/deploy-sessions`, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 409,
          json: { detail: "Уже есть активный план закупки — завершите или отмените его" },
        });
        return;
      }
      await route.continue();
    });
    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByTestId("freeze-deploy-plan")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("freeze-deploy-plan").click();
    await expect(page.getByTestId("deploy-session-conflict")).toBeVisible();
    await expect(page.getByTestId("deploy-session-conflict")).toContainText(
      /завершите покупки|обновите|отмените/i,
    );
  });

  test("cancel plan returns freeze button", async ({ page }) => {
    const mocks = await setupDeploySessionMocks(page, { initialPhase: "frozen" });
    await gotoPortfolio(page, PORTFOLIO_ID);

    await expect(page.getByTestId("deploy-session-banner")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("cancel-deploy-plan").click();
    mocks.setPhase("live");
    await page.getByRole("button", { name: "Обновить счёт" }).click();
    await expect(page.getByTestId("freeze-deploy-plan")).toBeVisible({ timeout: 10_000 });
  });
});
