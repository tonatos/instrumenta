/**
 * Shared Playwright fixtures for mocked API routes.
 */

import type { Page } from "@playwright/test";

export const MOCK_CONFIG = {
  key_rate: 16,
  tax_rate: 13,
  max_days: 120,
  min_volume_rub: 500_000,
  tinkoff_configured: true,
  sandbox_configured: true,
  production_configured: false,
  auth_enabled: false,
  telegram_oidc_configured: false,
};

export function bondsListResponse(
  bonds: unknown[],
  overrides: Record<string, unknown> = {},
) {
  const total = (overrides.total as number | undefined) ?? bonds.length;
  const page = (overrides.page as number | undefined) ?? 1;
  const pageSize = (overrides.page_size as number | undefined) ?? 50;
  return {
    bonds,
    source: "mock",
    count: bonds.length,
    total,
    page,
    page_size: pageSize,
    ...overrides,
  };
}

export async function seedAuth(page: Page, token = "mock-e2e-token"): Promise<void> {
  await page.addInitScript((authToken) => {
    localStorage.setItem("instrumenta_auth_token", authToken);
  }, token);
}

export async function mockConfig(page: Page): Promise<void> {
  await page.route("**/api/v1/config/", async (route) => {
    await route.fulfill({ json: MOCK_CONFIG });
  });
  await mockAuthMe(page, {
    sandbox: MOCK_CONFIG.sandbox_configured,
    production: MOCK_CONFIG.production_configured,
  });
  await mockBillingStatus(page, { hasAccess: true });
}

export async function mockBillingStatus(
  page: Page,
  opts: { hasAccess?: boolean; complimentary?: boolean } = {},
): Promise<void> {
  const hasAccess = opts.hasAccess ?? false;
  const complimentary = opts.complimentary ?? false;
  const entitlements = hasAccess || complimentary
    ? [
        "broker_credentials.write",
        "portfolio.attach",
        "trading_portfolio.access",
      ]
    : [];
  await page.unroute("**/api/v1/billing/status").catch(() => undefined);
  await page.route("**/api/v1/billing/status", async (route) => {
    await route.fulfill({
      json: {
        complimentary,
        payment_enabled: false,
        entitlements,
        has_active_access: hasAccess || complimentary,
        subscription: hasAccess && !complimentary
          ? {
              status: "active",
              period: "month",
              amount_kopecks: 79500,
              current_period_end: "2027-01-01T00:00:00Z",
              cancel_at_period_end: false,
              features: entitlements,
            }
          : null,
      },
    });
  });
}

export async function mockBillingCatalog(page: Page): Promise<void> {
  await page.route("**/api/v1/billing/catalog", async (route) => {
    await route.fulfill({
      json: {
        payment_enabled: false,
        plans: [
          {
            period: "month",
            amount_kopecks: 79500,
            monthly_kopecks: 79500,
            savings_kopecks: 0,
            savings_percent: 0,
            features: [
              "broker_credentials.write",
              "portfolio.attach",
              "trading_portfolio.access",
            ],
            plan_version_id: "pro_month_v1",
          },
          {
            period: "year",
            amount_kopecks: 594000,
            monthly_kopecks: 49500,
            savings_kopecks: 360000,
            savings_percent: 37.73584905660377,
            features: [
              "broker_credentials.write",
              "portfolio.attach",
              "trading_portfolio.access",
            ],
            plan_version_id: "pro_year_v1",
          },
        ],
      },
    });
  });
}

export async function mockAuthMe(
  page: Page,
  flags: {
    sandbox?: boolean;
    production?: boolean;
    telegramBot?: { configured?: boolean; connected?: boolean; username?: string };
  } = {},
): Promise<void> {
  await page.unroute("**/api/v1/auth/me").catch(() => undefined);
  const credentials: Record<string, { fingerprint: string; updated_at: string }> = {};
  if (flags.sandbox) {
    credentials.sandbox = { fingerprint: "mocksand", updated_at: "2026-01-01T00:00:00Z" };
  }
  if (flags.production) {
    credentials.production = { fingerprint: "mockprod", updated_at: "2026-01-01T00:00:00Z" };
  }
  const botConfigured = flags.telegramBot?.configured ?? true;
  const botConnected = flags.telegramBot?.connected ?? false;
  const botUsername = flags.telegramBot?.username ?? "instrumenta_bot";
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      json: {
        telegram_id: 1,
        display_name: "E2E User",
        credentials,
        telegram_bot: {
          configured: botConfigured,
          connected: botConnected,
          bot_username: botUsername,
          deep_link: botConfigured ? `https://t.me/${botUsername}` : "",
        },
      },
    });
  });
}

export async function mockBondsEmpty(page: Page): Promise<void> {
  await page.route("**/api/v1/bonds/**", async (route) => {
    await route.fulfill({ json: bondsListResponse([]) });
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
    weighted_duration_years: null,
    notes: [],
    cashflow: [],
    value_timeline: [],
    held_positions: [],
    slots: [],
    upcoming_put_offers: [],
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

export async function mockTradingStateRoute(
  page: Page,
  portfolioId: string,
  handler: (
    route: import("@playwright/test").Route,
    state: ReturnType<typeof makeTradingState>,
  ) => Promise<void> | void,
  initialState?: ReturnType<typeof makeTradingState>,
): Promise<void> {
  const state = initialState ?? makeTradingState();
  await page.route(`**/api/v1/portfolios/${portfolioId}/trading-state**`, async (route) => {
    await handler(route, state);
  });
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

  await page.route(`**/api/v1/portfolios/${portfolioId}/trading-state**`, async (route) => {
    await route.fulfill({ json: tradingState });
  });

  await page.route(`**/api/v1/portfolios/${portfolioId}/plan**`, async (route) => {
    await route.fulfill({ json: tradingState.plan });
  });

  const advicePayload = tradingState.advice;
  await page.route(`**/api/v1/portfolios/${portfolioId}/advice**`, async (route) => {
    await route.fulfill({ json: advicePayload });
  });

  await page.route(
    `**/api/v1/portfolios/${portfolioId}/account-operations**`,
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
