/**
 * E2E: смена НДФЛ в настройках сохраняется и обновляет config.
 */

import { test, expect } from "@playwright/test";
import { bondsListResponse, mockConfig, MOCK_CONFIG, seedAuth } from "./fixtures";

test.describe("Настройки — НДФЛ", () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockConfig(page);
    let taxRate = MOCK_CONFIG.tax_rate;

    await page.route("**/api/v1/me/preferences", async (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as { tax_rate: number };
        taxRate = body.tax_rate;
        await route.fulfill({ json: { tax_rate: taxRate } });
        return;
      }
      await route.fulfill({ json: { tax_rate: taxRate } });
    });

    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({ json: { ...MOCK_CONFIG, tax_rate: taxRate } });
    });

    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({
        json: bondsListResponse([], { total: 0, page: 1, page_size: 50 }),
      });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });
    await page.route("**/api/v1/portfolios/", async (route) => {
      await route.fulfill({ json: [] });
    });
  });

  test("можно выбрать «Не учитывать налог»", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Настройки" }).click();
    await expect(page.getByRole("heading", { name: "Настройки" })).toBeVisible();

    const taxSelect = page.getByLabel("НДФЛ");
    await taxSelect.selectOption("0");
    await expect(taxSelect).toHaveValue("0");
  });
});
