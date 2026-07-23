import { expect, test } from "@playwright/test";
import { mockBillingCatalog, MOCK_CONFIG, seedAuth } from "./fixtures";

test.describe("landing page", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: {
          ...MOCK_CONFIG,
          auth_enabled: true,
          telegram_oidc_configured: true,
        },
      });
    });
    await mockBillingCatalog(page);
  });

  test("guest sees strategy pitch, portfolio mock, and pricing with yearly discount", async ({
    page,
  }) => {
    await page.goto("/landing");

    await expect(page.getByTestId("landing-page")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /Облигационная стратегия/i,
      }),
    ).toBeVisible();
    await expect(page.getByTestId("product-mock")).toBeVisible();
    await expect(page.getByTestId("product-mock")).toContainText("Портфель");
    await expect(page.getByTestId("hero-play")).toBeVisible();

    await page.getByRole("heading", { name: /Простой прайс/i }).scrollIntoViewIfNeeded();
    await expect(page.getByTestId("pricing-free")).toContainText("0 ₽");
    await expect(page.getByTestId("pricing-pro-year")).toBeVisible();
    await expect(page.getByTestId("pricing-year-savings")).toContainText("%");
  });

  test("offer consent gates Telegram login", async ({ page }) => {
    await page.goto("/landing");
    await page.locator("#cta").scrollIntoViewIfNeeded();

    const loginBtn = page.getByTestId("telegram-login-button").last();
    await expect(loginBtn).toBeDisabled();

    await page.getByTestId("offer-consent").last().check();
    await expect(loginBtn).toBeEnabled();

    await expect(page.getByTestId("offer-link").last()).toHaveAttribute("href", "/offer");
  });

  test("offer page shows requisites", async ({ page }) => {
    await page.goto("/offer");
    await expect(page.getByTestId("offer-page")).toBeVisible();
    await expect(page.getByTestId("offer-requisites")).toContainText("Семячкин Виталий Юрьевич");
    await expect(page.getByTestId("offer-requisites")).toContainText("660608518305");
    await expect(page.getByTestId("offer-requisites")).toContainText("tonatossn@gmail.com");
  });

  test("landing advertises open source and links to GitHub in footer", async ({ page }) => {
    await page.goto("/landing");

    const teaser = page.getByTestId("oss-teaser");
    await teaser.scrollIntoViewIfNeeded();
    await expect(teaser).toContainText(/Open source friendly|исходник/i);
    await expect(teaser).toContainText(/некоммерческ|личн/i);

    const teaserGithub = page.getByTestId("oss-teaser-github");
    await expect(teaserGithub).toHaveAttribute("href", "https://github.com/tonatos/instrumenta");

    const footerGithub = page.getByTestId("footer-github");
    await expect(footerGithub).toBeVisible();
    await expect(footerGithub).toHaveAttribute("href", "https://github.com/tonatos/instrumenta");
    await expect(footerGithub).toContainText(/GitHub/i);
  });

  test("security page explains keys, storage, revoke, and links to GitHub", async ({ page }) => {
    await page.goto("/landing");
    await page.locator(".footer").getByRole("link", { name: "Безопасность" }).click();

    await expect(page).toHaveURL(/\/security/);
    await expect(page.getByTestId("security-page")).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 1, name: /Безопасность/i }),
    ).toBeVisible();

    await expect(page.getByTestId("security-why")).toContainText(/T‑Invest|T-Invest/i);
    await expect(page.getByTestId("security-why")).toContainText(/портфел/i);
    await expect(page.getByTestId("security-storage")).toContainText(/шифр/i);
    await expect(page.getByTestId("security-revoke")).toContainText(/удал/i);
    await expect(page.getByTestId("security-revoke")).toContainText(/T‑Банк|T-Банк|T‑Invest|T-Invest/i);

    const github = page.getByTestId("security-github");
    await expect(github).toBeVisible();
    await expect(github).toHaveAttribute("href", "https://github.com/tonatos/instrumenta");
    await expect(github).toContainText(/GitHub|исходник/i);
  });

  test("authenticated user is redirected from landing to terminal", async ({ page }) => {
    await seedAuth(page);
    await page.route("**/api/v1/auth/me", async (route) => {
      await route.fulfill({
        json: { telegram_id: 42, display_name: "E2E User", credentials: {} },
      });
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0, total: 0, page: 1, page_size: 50 } });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0, total: 0, page: 1, page_size: 50 } });
    });

    await page.goto("/landing");
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Скринер облигаций" })).toBeVisible();
  });

  test("protected routes redirect guests to landing", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/landing/);
    await expect(page.getByTestId("landing-page")).toBeVisible();
  });

  test("mobile viewport has no page-level horizontal overflow", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "mobile project only");

    await page.goto("/landing");
    const overflow = await page.evaluate(() => {
      const doc = document.documentElement;
      return {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
      };
    });
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
  });
});
