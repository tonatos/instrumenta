import { test, expect } from "@playwright/test";
import {
  mockAuthMe,
  mockBillingCatalog,
  mockBillingStatus,
  mockBondsEmpty,
  mockConfig,
  seedAuth,
} from "./fixtures";

test.describe("Подписка — paywall", () => {
  test("без подписки кабинет открывает paywall вместо полей ключей", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: false });
    await mockBillingCatalog(page);
    await mockAuthMe(page, { sandbox: false, production: false });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();
    await expect(page.getByText(/Сохранение ключей доступно по подписке/)).toBeVisible();
    await expect(page.getByPlaceholder("Вставьте production-токен")).toHaveCount(0);

    await page.getByRole("button", { name: "Подключить тариф" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: /Instrumenta Pro/i })).toBeVisible();
    await expect(dialog.getByText(/795/)).toBeVisible();
    await expect(dialog.getByRole("button", { name: /Оплатить месяц/i })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /Оплатить год/i })).toBeVisible();
  });

  test("страница тарифа показывает цены и ROI-калькулятор", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: false });
    await mockBillingCatalog(page);
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.goto("/account/plan");
    await expect(page.getByRole("heading", { name: "Instrumenta Pro" })).toBeVisible();
    await expect(page.getByText(/795/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Когда подписка окупается" })).toBeVisible();
    await expect(page.getByText(/28[,.]46%/)).toBeVisible();
    await expect(page.getByLabel("Размер капитала для инвестиций")).toBeVisible();
    await expect(page.getByText(/ключевой ставкой \(16%\)/)).toBeVisible();
    await expect(page.getByText(/Уведомления в Telegram/i)).toBeVisible();
  });

  test("финансы показывают пустой ledger", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: true });
    await mockBondsEmpty(page);
    await seedAuth(page);
    await page.route("**/api/v1/billing/ledger**", async (route) => {
      await route.fulfill({ json: { entries: [] } });
    });

    await page.goto("/account/finance");
    await expect(page.getByRole("heading", { name: "Списания и начисления" })).toBeVisible();
    await expect(page.getByText("Пока нет операций")).toBeVisible();
  });

  test("без подписки «Перевести в торговлю» открывает paywall с тарифами", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: false });
    await mockBillingCatalog(page);
    await mockAuthMe(page, { sandbox: true, production: false });
    await mockBondsEmpty(page);
    await seedAuth(page);

    const portfolio = {
      id: "p-paywall",
      name: "Paywall PF",
      initial_amount_rub: 100_000,
      horizon_date: "2027-01-01",
      risk_profile: "normal",
      cash_balance_rub: 100_000,
      mode: "simulation",
      account_id: null,
      account_kind: null,
      positions_count: 0,
      closed_positions_count: 0,
      invested_capital_rub: 0,
      access_locked: false,
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
      },
    };

    await page.route("**/api/v1/portfolios/**", async (route) => {
      const { pathname } = new URL(route.request().url());
      if (route.request().method() === "GET" && pathname === "/api/v1/portfolios/") {
        await route.fulfill({ json: [portfolio] });
        return;
      }
      if (pathname.endsWith("/plan")) {
        await route.fulfill({
          json: {
            total_net_profit_rub: 0,
            total_net_profit_with_held_rub: 0,
            invested_capital_rub: 0,
            total_invested_rub: 0,
            final_cash_balance: 100_000,
            final_portfolio_value: 100_000,
            initial_cash_rub: 100_000,
            expected_xirr_pct: null,
            weighted_duration_years: null,
            notes: [],
            cashflow: [],
            value_timeline: [],
            held_positions: [],
            slots: [],
            upcoming_put_offers: [],
          },
        });
        return;
      }
      await route.fulfill({ json: portfolio });
    });

    await page.goto("/portfolio");
    await page.getByRole("button", { name: "Перевести в торговлю" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: /Привязка счёта — в Instrumenta Pro/i }),
    ).toBeVisible();
    await expect(dialog.getByText(/795/)).toBeVisible();
    await expect(dialog.getByRole("button", { name: /Оплатить месяц/i })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /Оплатить год/i })).toBeVisible();
  });
});
