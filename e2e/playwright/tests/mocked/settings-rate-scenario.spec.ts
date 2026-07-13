/**
 * E2E: смена сценария дюрации в настройках перезапрашивает скринер.
 */

import { test, expect } from "@playwright/test";
import { bondsListResponse, mockConfig } from "./fixtures";

function makeBond(
  overrides: Partial<{
    secid: string;
    isin: string;
    name: string;
    score: number;
    duration_years: number;
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
    duration_years: 1.6,
    volume_rub: 5_000_000,
    prev_volume_rub: 4_000_000,
    credit_rating: "AAA",
    risk_level: 1,
    score: 72,
    profile_scores: { conservative: 72, normal: 72, aggressive: 72 },
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
  makeBond({
    secid: "SHORT",
    isin: "RU000SHORT",
    name: "Короткая",
    score: 70,
    duration_years: 0.8,
  }),
  makeBond({
    secid: "LONG",
    isin: "RU000LONG",
    name: "Длинная",
    score: 80,
    duration_years: 3.5,
  }),
];

test.describe("Настройки — сценарий дюрации", () => {
  test.beforeEach(async ({ page }) => {
    await mockConfig(page);
    await page.addInitScript(() => {
      localStorage.setItem("bond_monitor_rate_scenario", "hold");
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      const url = new URL(route.request().url());
      const scenario = url.searchParams.get("rate_scenario") ?? "hold";
      const sorted =
        scenario === "cut"
          ? [...bonds].sort((a, b) => b.duration_years - a.duration_years)
          : [...bonds].sort((a, b) => b.score - a.score);
      await route.fulfill({
        json: bondsListResponse(sorted, { total: sorted.length, page: 1, page_size: 50, source: `mock:${scenario}` }),
      });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], source: "mock", count: 0 } });
    });
    await page.route("**/api/v1/portfolios/", async (route) => {
      await route.fulfill({ json: [] });
    });
  });

  test("смена сценария на cut меняет порядок бумаг в скринере", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Короткая" })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("button", { name: "Настройки" }).click();
    await page.getByLabel("Сценарий по ключевой ставке").selectOption("cut");

    await expect(page.getByText("2 из 2 · mock:cut")).toBeVisible({ timeout: 15_000 });
    const firstRow = page.locator("tbody tr").first();
    await expect(firstRow).toContainText("Длинная", { timeout: 15_000 });
  });
});
