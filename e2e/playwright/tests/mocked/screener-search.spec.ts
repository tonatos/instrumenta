/**
 * E2E: поиск в скринере по названию, SECID и ISIN.
 */

import { test, expect } from "@playwright/test";
import { mockConfig } from "./fixtures";

function makeBond(
  overrides: Partial<{
    secid: string;
    isin: string;
    name: string;
  }> = {},
) {
  return {
    secid: "SU26238",
    isin: "RU000A106VN0",
    name: "ОФЗ 26238",
    figi: "FIGI26238",
    maturity_date: "2028-03-15",
    offer_date: null,
    call_date: null,
    effective_date: "2028-03-15",
    days_to_maturity: 600,
    ytm: 14.5,
    ytm_net: 12.6,
    coupon_rate: 7.1,
    coupon_type: "fixed",
    last_price: 92.5,
    face_value: 1000,
    lot_size: 1,
    volume_rub: 5_000_000,
    prev_volume_rub: 4_000_000,
    credit_rating: "AAA",
    risk_level: 1,
    score: 72,
    ytm_score: 80,
    risk_score: 90,
    liquidity_score: 70,
    is_favorite: false,
    has_warnings: false,
    warnings: [],
    tinvest_enriched: true,
    issuer_name: "Минфин РФ",
    instrument_full_name: "ОФЗ 26238",
    sector: "Государственный",
    description: "",
    ...overrides,
  };
}

const bonds = [
  makeBond(),
  makeBond({
    secid: "OTHER1",
    isin: "RU000AOTHER1",
    name: "Другая облигация",
  }),
];

test.describe("Скринер — поиск", () => {
  test.beforeEach(async ({ page }) => {
    await mockConfig(page);
    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({
        json: { bonds, source: "mock", count: bonds.length },
      });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });
    await page.route("**/api/v1/portfolios/", async (route) => {
      await route.fulfill({ json: [] });
    });
  });

  test("поиск по ISIN оставляет только совпадающую бумагу", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("2 из 2")).toBeVisible({ timeout: 15_000 });

    const searchInput = page.getByPlaceholder("Поиск по названию, SECID или ISIN…");
    await searchInput.fill("RU000A106VN0");

    await expect(page.getByRole("button", { name: "ОФЗ 26238" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Другая облигация" })).not.toBeVisible();
    await expect(page.getByText("1 бумаг")).toBeVisible();
  });
});
