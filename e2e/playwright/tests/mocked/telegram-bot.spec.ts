import { test, expect } from "@playwright/test";
import {
  mockAuthMe,
  mockBillingCatalog,
  mockBillingStatus,
  mockBondsEmpty,
  mockConfig,
  seedAuth,
} from "./fixtures";

test.describe("Telegram-бот — кабинет", () => {
  test("без подписки показывает paywall и инструкцию недоступна", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: false });
    await mockBillingCatalog(page);
    await mockAuthMe(page, {
      telegramBot: { configured: true, connected: false, username: "instrumenta_bot" },
    });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.goto("/account/notifications");
    await expect(page.getByRole("heading", { name: "Telegram-уведомления" })).toBeVisible();
    await expect(page.getByText(/Доступно по подписке Pro/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Подключить тариф" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Открыть бота/i })).toHaveCount(0);
  });

  test("с подпиской показывает инструкцию Start и deep link", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: true });
    await mockAuthMe(page, {
      telegramBot: { configured: true, connected: false, username: "instrumenta_bot" },
    });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.goto("/account/notifications");
    await expect(page.getByText(/Статус:.*не подключён/i)).toBeVisible();
    await expect(page.getByText(/Нажмите.*Start/i)).toBeVisible();
    await expect(page.getByRole("link", { name: "Открыть бота в Telegram" })).toHaveAttribute(
      "href",
      "https://t.me/instrumenta_bot",
    );
  });

  test("подключённый бот показывает статус и кнопку отключения", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: true });
    await mockAuthMe(page, {
      telegramBot: { configured: true, connected: true, username: "instrumenta_bot" },
    });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.route("**/api/v1/me/telegram-bot", async (route) => {
      if (route.request().method() === "DELETE") {
        await route.fulfill({ status: 204, body: "" });
        return;
      }
      await route.fallback();
    });

    await page.goto("/account/notifications");
    await expect(page.getByText(/Статус:.*подключён/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Отключить в приложении" })).toBeVisible();
  });
});

test.describe("Telegram support — AppShell", () => {
  test("в сайдбаре ссылка Поддержка ведёт на deep link с start=support", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: true });
    await mockAuthMe(page, {
      telegramBot: { configured: true, connected: false, username: "instrumenta_bot" },
    });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    const support = page.getByRole("link", { name: "Поддержка" });
    await expect(support).toBeVisible();
    await expect(support).toHaveAttribute("href", "https://t.me/instrumenta_bot?start=support");
  });

  test("в mobile header иконка Поддержка с тем же deep link", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: true });
    await mockAuthMe(page, {
      telegramBot: { configured: true, connected: false, username: "instrumenta_bot" },
    });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");
    const support = page.getByRole("link", { name: "Поддержка" });
    await expect(support).toBeVisible();
    await expect(support).toHaveAttribute("href", "https://t.me/instrumenta_bot?start=support");
  });

  test("без бота пункт Поддержка скрыт", async ({ page }) => {
    await mockConfig(page);
    await mockBillingStatus(page, { hasAccess: true });
    await mockAuthMe(page, {
      telegramBot: { configured: false, connected: false, username: "" },
    });
    await mockBondsEmpty(page);
    await seedAuth(page);

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Поддержка" })).toHaveCount(0);
  });
});
