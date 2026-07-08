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

  test("allows access after mocked telegram oidc callback", async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          ...MOCK_CONFIG,
          auth_enabled: true,
          telegram_oidc_configured: true,
        },
      });
    });
    await page.route("**/api/v1/auth/telegram/callback", async (route) => {
      await route.fulfill({
        status: 201,
        json: { access_token: "mock-e2e-token", token_type: "bearer" },
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

    await page.goto("/login/callback?code=mock-code&state=mock-state");
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Скринер облигаций" })).toBeVisible();
  });
});
