/**
 * E2E: мастер перевода портфеля в режим торговли — выбор счёта.
 */

import { test, expect } from "@playwright/test";

const PORTFOLIO_ID = "sim-portfolio-1";
const LINKED_PORTFOLIO_ID = "linked-portfolio-1";

const simulationPortfolio = {
  id: PORTFOLIO_ID,
  name: "E2E Trading Wizard",
  initial_amount_rub: 100_000,
  horizon_date: "2027-01-01",
  risk_profile: "normal",
  cash_balance_rub: 100_000,
  mode: "simulation",
  account_id: null,
  account_kind: null,
  positions_count: 0,
  data: {
    positions: [],
    slots: [],
    cash_balance_rub: 100_000,
    initial_amount_rub: 100_000,
    horizon_date: "2027-01-01",
    mode: "simulation",
    account_id: null,
    account_kind: null,
    frozen_forecast: null,
    pending_operations: [],
  },
};

test.describe("Мастер режима торговли", () => {
  test.beforeEach(async ({ page }) => {
    const credFlags = { sandbox: true, production: false };

    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          key_rate: 16,
          tax_rate: 13,
          max_days: 1825,
          min_volume_rub: 1_000_000,
          tinkoff_configured: true,
          sandbox_configured: credFlags.sandbox,
          production_configured: credFlags.production,
          auth_enabled: false,
        },
      });
    });
    await page.route("**/api/v1/auth/me", async (route) => {
      const credentials: Record<string, { fingerprint: string; updated_at: string }> = {};
      if (credFlags.sandbox) {
        credentials.sandbox = { fingerprint: "mocksand", updated_at: "2026-01-01T00:00:00Z" };
      }
      if (credFlags.production) {
        credentials.production = { fingerprint: "mockprod", updated_at: "2026-01-01T00:00:00Z" };
      }
      await route.fulfill({
        json: { telegram_id: 1, display_name: "E2E User", credentials },
      });
    });
    await page.route("**/api/v1/billing/status", async (route) => {
      await route.fulfill({
        json: {
          complimentary: true,
          payment_enabled: false,
          entitlements: [
            "broker_credentials.write",
            "portfolio.attach",
            "trading_portfolio.access",
          ],
          has_active_access: true,
        },
      });
    });
    // Expose mutable flags for tests that need other credential shapes.
    (page as unknown as { __credFlags: typeof credFlags }).__credFlags = credFlags;

    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });

    await page.route("**/api/v1/portfolios/**", async (route) => {
      const { pathname } = new URL(route.request().url());
      if (route.request().method() === "GET" && pathname === "/api/v1/portfolios/") {
        await route.fulfill({ json: [simulationPortfolio] });
        return;
      }
      if (pathname.includes("/account-preview")) {
        const url = new URL(route.request().url());
        const accountId = url.searchParams.get("account_id") ?? "";
        const linked =
          accountId === "acc-linked"
            ? { id: LINKED_PORTFOLIO_ID, name: "Уже в торговле" }
            : null;
        await route.fulfill({
          json: {
            money_rub: 100_000,
            bond_positions: [],
            other_instruments: [],
            has_securities: false,
            can_attach: linked == null,
            blockers: linked ? ["Счёт уже привязан к другому портфелю"] : [],
            warnings: [],
            linked_portfolio: linked,
          },
        });
        return;
      }
      await route.continue();
    });

    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/plan`, async (route) => {
      await route.fulfill({
        json: {
          total_net_profit_rub: 0,
          total_net_profit_with_held_rub: 0,
          final_cash_balance: 100_000,
          final_portfolio_value: 100_000,
          expected_xirr_pct: null,
          notes: [],
          cashflow: [],
          value_timeline: [],
          held_positions: [],
          slots: [],
        },
      });
    });

    await page.route("**/api/v1/accounts?kind=sandbox", async (route) => {
      await route.fulfill({
        json: [
          {
            id: "acc-linked",
            name: "Sandbox linked",
            kind: "sandbox",
            linked_portfolio: {
              id: LINKED_PORTFOLIO_ID,
              name: "Уже в торговле",
            },
          },
          {
            id: "acc-free",
            name: "Sandbox free",
            kind: "sandbox",
            linked_portfolio: null,
          },
        ],
      });
    });
  });

  test("показывает, что счёт уже привязан к другому портфелю", async ({ page }) => {
    const configLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/config/") && response.ok(),
    );
    const portfoliosLoaded = page.waitForResponse((response) => {
      const { pathname } = new URL(response.url());
      return (
        pathname === "/api/v1/portfolios/" &&
        response.request().method() === "GET" &&
        response.ok()
      );
    });

    await page.goto("/portfolio");
    await Promise.all([configLoaded, portfoliosLoaded]);

    await expect(page.getByRole("heading", { name: "E2E Trading Wizard" })).toBeVisible({
      timeout: 10_000,
    });
    const tradingButton = page.getByRole("button", { name: "Перевести в торговлю" });
    await expect(tradingButton).toBeVisible({ timeout: 10_000 });
    await tradingButton.click();
    await expect(page.getByText("Выберите счёт")).toBeVisible();

    await expect(page.getByText("Привязан к портфелю «Уже в торговле»")).toBeVisible();
    await page.getByRole("button", { name: "Sandbox linked" }).click();
    await expect(
      page.getByText(
        "Этот счёт уже привязан к портфелю «Уже в торговле». Отвяжите его там или выберите другой счёт.",
      ),
    ).toBeVisible();

    const nextButton = page.getByRole("button", { name: "Далее" });
    await expect(nextButton).toBeDisabled();

    await page.getByRole("button", { name: "Sandbox free" }).click();
    await expect(nextButton).toBeEnabled();
  });

  test("удаляет счёт в песочнице после подтверждения", async ({ page }) => {
    let deleteCalled = false;

    await page.route("**/api/v1/accounts/sandbox/acc-free", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true;
        await route.fulfill({
          json: {
            account_id: "acc-free",
            deleted_portfolio_id: null,
          },
        });
        return;
      }
      await route.continue();
    });

    const configLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/config/") && response.ok(),
    );
    const portfoliosLoaded = page.waitForResponse((response) => {
      const { pathname } = new URL(response.url());
      return (
        pathname === "/api/v1/portfolios/" &&
        response.request().method() === "GET" &&
        response.ok()
      );
    });

    await page.goto("/portfolio");
    await Promise.all([configLoaded, portfoliosLoaded]);

    const tradingButton = page.getByRole("button", { name: "Перевести в торговлю" });
    await expect(tradingButton).toBeVisible({ timeout: 10_000 });
    await tradingButton.click();
    await expect(page.getByText("Выберите счёт")).toBeVisible();

    await page.getByRole("button", { name: "Удалить счёт" }).nth(1).click();
    const deleteDialog = page.getByRole("dialog", { name: "Удалить счёт в песочнице" });
    await expect(deleteDialog).toBeVisible();
    await expect(
      deleteDialog.getByText(
        "Счёт Sandbox free будет закрыт в T-Invest. Это действие нельзя отменить.",
      ),
    ).toBeVisible();

    await deleteDialog.getByRole("button", { name: "Удалить" }).click();
    await expect.poll(() => deleteCalled).toBe(true);
  });

  test("предупреждает об удалении привязанного портфеля", async ({ page }) => {
    let deleteCalled = false;

    await page.route("**/api/v1/accounts/sandbox/acc-linked", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true;
        await route.fulfill({
          json: {
            account_id: "acc-linked",
            deleted_portfolio_id: LINKED_PORTFOLIO_ID,
          },
        });
        return;
      }
      await route.continue();
    });

    const configLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/config/") && response.ok(),
    );
    const portfoliosLoaded = page.waitForResponse((response) => {
      const { pathname } = new URL(response.url());
      return (
        pathname === "/api/v1/portfolios/" &&
        response.request().method() === "GET" &&
        response.ok()
      );
    });

    await page.goto("/portfolio");
    await Promise.all([configLoaded, portfoliosLoaded]);

    const tradingButton = page.getByRole("button", { name: "Перевести в торговлю" });
    await expect(tradingButton).toBeVisible({ timeout: 10_000 });
    await tradingButton.click();
    await expect(page.getByText("Выберите счёт")).toBeVisible();

    await page.getByRole("button", { name: "Удалить счёт" }).first().click();
    const deleteDialog = page.getByRole("dialog", { name: "Удалить счёт в песочнице" });
    await expect(
      deleteDialog.getByText(
        "Портфель «Уже в торговле» также будет удалён без возможности восстановления.",
      ),
    ).toBeVisible();

    await deleteDialog.getByRole("button", { name: "Удалить" }).click();
    await expect.poll(() => deleteCalled).toBe(true);
  });

  test("при одном токене sandbox пропускает выбор контура", async ({ page }) => {
    const configLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/config/") && response.ok(),
    );
    const portfoliosLoaded = page.waitForResponse((response) => {
      const { pathname } = new URL(response.url());
      return (
        pathname === "/api/v1/portfolios/" &&
        response.request().method() === "GET" &&
        response.ok()
      );
    });

    await page.goto("/portfolio");
    await Promise.all([configLoaded, portfoliosLoaded]);

    await page.getByRole("button", { name: "Перевести в торговлю" }).click();
    await expect(page.getByText("Выберите счёт")).toBeVisible();
    await expect(page.getByText("Выберите контур T-Invest")).not.toBeVisible();
    await expect(page.getByText("Песочница (sandbox)")).not.toBeVisible();
  });

  test("при одном токене production пропускает выбор контура", async ({ page }) => {
    const flags = (page as unknown as { __credFlags: { sandbox: boolean; production: boolean } })
      .__credFlags;
    flags.sandbox = false;
    flags.production = true;

    await page.route("**/api/v1/accounts?kind=production", async (route) => {
      await route.fulfill({
        json: [
          {
            id: "prod-acc-1",
            name: "Production account",
            kind: "production",
            linked_portfolio: null,
          },
        ],
      });
    });

    const configLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/config/") && response.ok(),
    );
    const meLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/auth/me") && response.ok(),
    );
    const portfoliosLoaded = page.waitForResponse((response) => {
      const { pathname } = new URL(response.url());
      return (
        pathname === "/api/v1/portfolios/" &&
        response.request().method() === "GET" &&
        response.ok()
      );
    });

    await page.goto("/portfolio");
    await Promise.all([configLoaded, meLoaded, portfoliosLoaded]);

    await page.getByRole("button", { name: "Перевести в торговлю" }).click();
    await expect(page.getByText("Выберите счёт")).toBeVisible();
    await expect(page.getByText("Выберите контур T-Invest")).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Production account" })).toBeVisible();
    await expect(page.getByText("Создать счёт в песочнице")).not.toBeVisible();
  });

  test("при двух токенах показывает выбор контура", async ({ page }) => {
    const flags = (page as unknown as { __credFlags: { sandbox: boolean; production: boolean } })
      .__credFlags;
    flags.sandbox = true;
    flags.production = true;

    const configLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/config/") && response.ok(),
    );
    const meLoaded = page.waitForResponse(
      (response) => response.url().includes("/api/v1/auth/me") && response.ok(),
    );
    const portfoliosLoaded = page.waitForResponse((response) => {
      const { pathname } = new URL(response.url());
      return (
        pathname === "/api/v1/portfolios/" &&
        response.request().method() === "GET" &&
        response.ok()
      );
    });

    await page.goto("/portfolio");
    await Promise.all([configLoaded, meLoaded, portfoliosLoaded]);

    await page.getByRole("button", { name: "Перевести в торговлю" }).click();
    await expect(page.getByText("Выберите контур T-Invest")).toBeVisible();
    await expect(page.getByText("Песочница (sandbox)")).toBeVisible();
    await expect(page.getByText("Боевой счёт (production)")).toBeVisible();
  });
});
