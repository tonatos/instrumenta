import { expect, test } from "@playwright/test";
import { MOCK_CONFIG } from "./fixtures";

test.describe("auth login", () => {
  test("redirects to login when auth is enabled and user is not authenticated", async ({
    page,
  }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          ...MOCK_CONFIG,
          auth_enabled: true,
          telegram_oidc_configured: true,
        },
      });
    });

    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("Войдите через Telegram")).toBeVisible();
  });

  test("allows access after backend redirect with access_token", async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          ...MOCK_CONFIG,
          auth_enabled: true,
          telegram_oidc_configured: true,
        },
      });
    });
    await page.route("**/api/v1/auth/me", async (route) => {
      await route.fulfill({
        json: { telegram_id: 42, display_name: "E2E User" },
      });
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });

    await page.goto("/login/callback?access_token=mock-e2e-token");
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Скринер облигаций" })).toBeVisible();
  });
});
