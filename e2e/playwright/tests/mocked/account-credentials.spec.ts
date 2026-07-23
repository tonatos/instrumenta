import { test, expect } from "@playwright/test";
import { mockAuthMe, mockConfig, mockBondsEmpty, seedAuth } from "./fixtures";

test.describe("Личный кабинет — брокерские ключи", () => {
  test("GET /auth/me отправляет Bearer из localStorage", async ({ page }) => {
    await mockConfig(page);
    await mockBondsEmpty(page);
    await seedAuth(page, "account-page-jwt");

    let authorization: string | undefined;
    await page.unroute("**/api/v1/auth/me").catch(() => undefined);
    await page.route("**/api/v1/auth/me", async (route) => {
      authorization = route.request().headers()["authorization"];
      await route.fulfill({
        json: {
          telegram_id: 42,
          display_name: "Prod User",
          credentials: {
            production: { fingerprint: "abcd1234", updated_at: "2026-07-21T00:00:00Z" },
          },
        },
      });
    });

    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();
    await expect.poll(() => authorization).toBe("Bearer account-page-jwt");
    await expect(page.getByText(/сохранён · abcd1234/)).toBeVisible();
  });

  test("показывает production и sandbox под details; сохраняет/удаляет ключ", async ({
    page,
  }) => {
    await mockConfig(page);
    await mockBondsEmpty(page);
    await mockAuthMe(page, { sandbox: false, production: false });

    let putBody: unknown;
    await page.route("**/api/v1/me/broker-credentials/production", async (route) => {
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON();
        await route.fulfill({
          json: { fingerprint: "abcd1234", updated_at: "2026-07-21T00:00:00Z" },
        });
        return;
      }
      if (route.request().method() === "DELETE") {
        await route.fulfill({ status: 204, body: "" });
        return;
      }
      await route.continue();
    });

    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();
    await expect(page.getByText("Production", { exact: true })).toBeVisible();
    await expect(page.getByText("Песочница (опционально)")).toBeVisible();
    await expect(page.getByPlaceholder("Вставьте sandbox-токен")).toBeHidden();

    await page.getByPlaceholder("Вставьте production-токен").fill("t.prod.token");
    await page.getByRole("button", { name: "Сохранить production" }).click();
    await expect.poll(() => putBody).toEqual({ token: "t.prod.token" });

    await page.unroute("**/api/v1/auth/me");
    await mockAuthMe(page, { production: true });
    await page.reload();
    await expect(page.getByText(/сохранён/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Удалить" }).first()).toBeVisible();
  });

  test("без ключей кнопка торговли ведёт в кабинет", async ({ page }) => {
    await mockConfig(page);
    await mockAuthMe(page, { sandbox: false, production: false });
    await mockBondsEmpty(page);

    const portfolio = {
      id: "p-no-keys",
      name: "No Keys",
      initial_amount_rub: 100_000,
      horizon_date: "2027-01-01",
      risk_profile: "normal",
      cash_balance_rub: 100_000,
      mode: "simulation",
      account_id: null,
      account_kind: null,
      positions_count: 0,
      closed_positions_count: 0,
      positions: [],
      slots: [],
      invested_capital_rub: 0,
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
        return;
      }
      await route.fulfill({ json: portfolio });
    });

    await page.goto("/portfolio");
    await page.getByRole("link", { name: "Перевести в торговлю" }).click();
    await expect(page).toHaveURL(/\/account/);
    await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();
  });
});
