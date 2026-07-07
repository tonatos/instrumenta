import { test, expect } from "@playwright/test";

test.describe("Bond Monitor webapp", () => {
  test("screener page loads bonds from API", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Скринер облигаций" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Основная навигация" })).toBeVisible();
    await expect(page.getByText("Не удалось загрузить данные")).not.toBeVisible();
    await expect(page.getByText(/\d+ бумаг ·/)).toBeVisible({ timeout: 30_000 });
  });

  test("navigate to favorites", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Избранное/ }).first().click();
    await expect(page.getByRole("heading", { name: "Избранное" })).toBeVisible();
  });

  test("navigate to portfolio", async ({ page }) => {
    await page.goto("/portfolio");
    await expect(page.getByRole("heading", { name: "Портфель" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Создать/ })).toBeVisible();
  });

  test("navigate to calculator", async ({ page }) => {
    await page.goto("/calculator");
    await expect(page.getByRole("heading", { name: "Калькулятор" })).toBeVisible();
  });

  test("settings sheet opens", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Настройки" }).first().click();
    await expect(page.getByRole("heading", { name: "Настройки" })).toBeVisible();
  });
});
