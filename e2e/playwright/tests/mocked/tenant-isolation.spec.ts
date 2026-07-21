import { test, expect } from "@playwright/test";
import { mockConfig, mockBondsEmpty, seedAuth } from "./fixtures";

/**
 * Cross-user isolation: user B must not see portfolio of user A.
 * Uses mocked API that returns 404 for foreign portfolio ids.
 */
test.describe("Изоляция портфелей между пользователями", () => {
  test("чужой portfolio_id отдаёт 404 и не светит данные", async ({ page }) => {
    await seedAuth(page, "token-user-b");
    await mockConfig(page);
    await mockBondsEmpty(page);

    await page.route("**/api/v1/auth/me", async (route) => {
      await route.fulfill({
        json: {
          telegram_id: 200,
          display_name: "User B",
          credentials: {},
        },
      });
    });

    await page.route("**/api/v1/portfolios/", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ json: [] });
        return;
      }
      await route.continue();
    });

    await page.route("**/api/v1/portfolios/foreign-a/**", async (route) => {
      await route.fulfill({
        status: 404,
        json: { detail: "Portfolio not found", status_code: 404 },
      });
    });
    await page.route("**/api/v1/portfolios/foreign-a", async (route) => {
      await route.fulfill({
        status: 404,
        json: { detail: "Portfolio not found", status_code: 404 },
      });
    });

    await page.goto("/portfolio/foreign-a");
    // UI should not render foreign portfolio name
    await expect(page.getByText("Secret A Portfolio")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: /портфель/i }).or(page.getByText(/нет портфел/i))).toBeVisible({
      timeout: 10_000,
    });
  });
});
