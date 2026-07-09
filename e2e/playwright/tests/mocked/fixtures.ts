/**
 * Shared Playwright fixtures for mocked API routes.
 */

import type { Page } from "@playwright/test";

export const MOCK_CONFIG = {
  key_rate: 16,
  tax_rate: 13,
  max_days: 1825,
  min_volume_rub: 0,
  tinkoff_configured: true,
  sandbox_configured: true,
  production_configured: false,
  auth_enabled: false,
  telegram_oidc_configured: false,
};

export async function seedAuth(page: Page, token = "mock-e2e-token"): Promise<void> {
  await page.addInitScript((authToken) => {
    localStorage.setItem("bond_monitor_auth_token", authToken);
  }, token);
}

export async function mockConfig(page: Page): Promise<void> {
  await page.route("**/api/v1/config/", async (route) => {
    await route.fulfill({ json: MOCK_CONFIG });
  });
}

export async function mockBondsEmpty(page: Page): Promise<void> {
  await page.route("**/api/v1/bonds/**", async (route) => {
    await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
  });
}

export function makeEmptyPlan(overrides: Record<string, unknown> = {}) {
  return {
    total_net_profit_rub: 0,
    total_net_profit_with_held_rub: 0,
    invested_capital_rub: 100_000,
    total_invested_rub: 100_000,
    final_cash_balance: 50_000,
    final_portfolio_value: 100_000,
    expected_xirr_pct: null,
    notes: [],
    cashflow: [],
    value_timeline: [],
    held_positions: [],
    slots: [],
    ...overrides,
  };
}

export function makeAdvice(overrides: Record<string, unknown> = {}) {
  return {
    holdings: [],
    cashflow: [],
    performance: null,
    suggestions: [],
    active_orders: [],
    money_rub: 50_000,
    available_money_rub: 50_000,
    blocked_money_rub: 0,
    warnings: [],
    as_of: new Date().toISOString(),
    ...overrides,
  };
}

export function makeTradingPortfolio(
  id: string,
  overrides: Record<string, unknown> = {},
) {
  const data = (overrides.data as Record<string, unknown> | undefined) ?? {};
  return {
    id,
    name: "Trading E2E",
    initial_amount_rub: 100_000,
    horizon_date: "2028-01-01",
    risk_profile: "normal",
    cash_balance_rub: 50_000,
    mode: "trading",
    account_id: "acc-e2e",
    account_kind: "sandbox",
    positions_count: 2,
    closed_positions_count: 0,
    invested_capital_rub: 100_000,
    data: {
      positions: [],
      slots: [],
      cash_balance_rub: 50_000,
      initial_amount_rub: 100_000,
      horizon_date: "2028-01-01",
      mode: "trading",
      account_id: "acc-e2e",
      account_kind: "sandbox",
      frozen_forecast: null,
      closed_positions_count: 0,
      ...data,
    },
    ...overrides,
  };
}

export function makeTradingState(
  overrides: {
    plan?: ReturnType<typeof makeEmptyPlan>;
    advice?: ReturnType<typeof makeAdvice>;
  } = {},
) {
  return {
    plan: overrides.plan ?? makeEmptyPlan(),
    advice: overrides.advice ?? makeAdvice(),
  };
}

export async function mockTradingPortfolioRoutes(
  page: Page,
  portfolioId: string,
  portfolio: ReturnType<typeof makeTradingPortfolio>,
  options: {
    plan?: ReturnType<typeof makeEmptyPlan>;
    advice?: ReturnType<typeof makeAdvice>;
    tradingState?: ReturnType<typeof makeTradingState>;
    accountOperations?: unknown[];
  } = {},
): Promise<void> {
  await mockConfig(page);
  await mockBondsEmpty(page);

  await page.route("**/api/v1/portfolios/", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: [portfolio] });
      return;
    }
    await route.continue();
  });

  const tradingState =
    options.tradingState ??
    makeTradingState({ plan: options.plan, advice: options.advice });

  await page.route(`**/api/v1/portfolios/${portfolioId}/trading-state`, async (route) => {
    await route.fulfill({ json: tradingState });
  });

  await page.route(`**/api/v1/portfolios/${portfolioId}/plan`, async (route) => {
    await route.fulfill({ json: tradingState.plan });
  });

  const advicePayload = tradingState.advice;
  await page.route(`**/api/v1/portfolios/${portfolioId}/advice`, async (route) => {
    await route.fulfill({ json: advicePayload });
  });

  await page.route(
    `**/api/v1/portfolios/${portfolioId}/account-operations`,
    async (route) => {
      await route.fulfill({
        json: {
          operations: options.accountOperations ?? [],
          from_date: null,
        },
      });
    },
  );
}

export async function gotoPortfolio(page: Page, portfolioId: string): Promise<void> {
  await page.goto(`/portfolio/${portfolioId}`);
}
