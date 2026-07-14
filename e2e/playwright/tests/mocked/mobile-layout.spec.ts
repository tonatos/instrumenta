/**
 * E2E smoke: mobile layout — bottom nav, filters, tabs без page-level overflow.
 */

import { test, expect } from "@playwright/test";
import {
  bondsListResponse,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  mockConfig,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "mobile-layout-1";

function makeBond() {
  return {
    secid: "BOND1",
    isin: "RU000ABOND1",
    name: "Тестовая облигация",
    figi: "FIGI1",
    maturity_date: "2028-03-15",
    offer_date: null,
    call_date: null,
    effective_date: "2028-03-15",
    days_to_maturity: 90,
    ytm: 14.5,
    ytm_net: 12.6,
    coupon_rate: 7.1,
    coupon_type: "fixed",
    last_price: 92.5,
    face_value: 1000,
    lot_size: 1,
    duration_years: 1.6,
    volume_rub: 5_000_000,
    prev_volume_rub: 5_000_000,
    credit_rating: "AAA",
    risk_level: 1,
    score: 72,
    profile_scores: { conservative: 72, normal: 72, aggressive: 72 },
    ytm_score: 80,
    risk_score: 70,
    liquidity_score: 65,
    duration_adjustment: 0,
    is_favorite: false,
    subordinated: false,
    defaulted: false,
    warnings: [],
  };
}

async function assertNoPageOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  expect(overflow).toBe(false);
}

test.describe("Mobile layout", () => {
  test("bottom nav виден и совпадает с шириной экрана", async ({ page }) => {
    await mockConfig(page);
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: bondsListResponse([makeBond()]) });
    });
    await page.route("**/api/v1/favorites", async (route) => {
      await route.fulfill({ json: { bonds: [], count: 0 } });
    });

    await page.goto("/");

    const nav = page.getByRole("navigation", { name: "Мобильная навигация" });
    await expect(nav).toBeVisible();

    const navBox = await nav.boundingBox();
    const viewport = page.viewportSize();
    expect(navBox).not.toBeNull();
    expect(viewport).not.toBeNull();
    expect(navBox!.width).toBeCloseTo(viewport!.width, 0);

    await assertNoPageOverflow(page);
  });

  test("скринер: фильтры сворачиваются и разворачиваются", async ({ page }) => {
    await mockConfig(page);
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: bondsListResponse([makeBond()]) });
    });
    await page.route("**/api/v1/favorites", async (route) => {
      await route.fulfill({ json: { bonds: [], count: 0 } });
    });

    await page.goto("/");

    const toggle = page.getByTestId("screener-filters-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByLabel("Риск-профиль")).toBeVisible();

    await page.getByRole("button", { name: "До погашения" }).click();
    await assertNoPageOverflow(page);
  });

  test("портфель: вкладки без page-level overflow", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      data: {
        positions: [
          {
            isin: "RU000AOPEN1",
            secid: "OPEN1",
            name: "Активная облигация",
            lots: 5,
            lot_size: 1,
            purchase_clean_price_pct: 100,
            purchase_dirty_price_rub: 1000,
            purchase_aci_rub: 0,
            purchase_date: "2026-01-01",
            purchase_amount_rub: 5000,
            coupon_rate: 10,
            face_value: 1000,
            maturity_date: "2027-06-01",
            offer_date: null,
            source: "initial",
            figi: "FIGI_OPEN",
            status: "active",
          },
        ],
      },
    });

    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio, {
      plan: makeEmptyPlan(),
      advice: makeAdvice({
        holdings: [
          {
            figi: "FIGI_OPEN",
            isin: "RU000AOPEN1",
            name: "Активная облигация",
            lots: 5,
            quantity: 5,
            lot_size: 1,
          },
        ],
      }),
    });

    await page.route("**/api/v1/favorites", async (route) => {
      await route.fulfill({ json: { bonds: [], count: 0 } });
    });

    await page.goto(`/portfolio/${PORTFOLIO_ID}`);

    await expect(page.getByRole("tab", { name: /Позиции/ })).toBeVisible();
    await page.getByRole("tab", { name: /Операции/ }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("tab", { name: /Операции/ })).toBeVisible();

    await assertNoPageOverflow(page);
  });

  test("калькулятор рендерится без page-level overflow", async ({ page }) => {
    await mockConfig(page);
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({ json: bondsListResponse([makeBond()]) });
    });
    await page.route("**/api/v1/favorites", async (route) => {
      await route.fulfill({ json: { bonds: [], count: 0 } });
    });

    await page.goto("/calculator");

    await expect(page.getByRole("heading", { name: "Калькулятор" })).toBeVisible();
    await assertNoPageOverflow(page);
  });
});
