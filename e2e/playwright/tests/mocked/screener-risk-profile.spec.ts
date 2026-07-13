/**
 * E2E: переключение риск-профиля в скринере меняет ранжирование.
 */

import { test, expect } from "@playwright/test";
import { mockConfig, bondsListResponse } from "./fixtures";

function makeBond(
  overrides: Partial<{
    secid: string;
    isin: string;
    name: string;
    profile_scores: Record<string, number>;
  }> = {},
) {
  const profile_scores = overrides.profile_scores ?? {
    conservative: 70,
    normal: 70,
    aggressive: 70,
  };
  const { profile_scores: _ignored, ...rest } = overrides;
  return {
    secid: "SU26238",
    isin: "RU000A106VN0",
    name: "ОФЗ 26238",
    figi: "FIGI26238",
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
    prev_volume_rub: 4_000_000,
    credit_rating: "AAA",
    risk_level: 1,
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
    ...rest,
    profile_scores,
    score: profile_scores.normal,
  };
}

const bonds = [
  makeBond({
    secid: "VDO1",
    isin: "RU000AVDO1",
    name: "ВДО высокий YTM",
    profile_scores: { conservative: 68, normal: 72, aggressive: 91 },
  }),
  makeBond({
    secid: "IG1",
    isin: "RU000AIG01",
    name: "IG надёжная",
    profile_scores: { conservative: 82, normal: 86, aggressive: 58 },
  }),
];

test.describe("Скринер — риск-профиль", () => {
  test.beforeEach(async ({ page }) => {
    await mockConfig(page);
    await page.addInitScript(() => {
      localStorage.setItem("bond_monitor_screener_risk_profile", "conservative");
      localStorage.setItem("bond_monitor_rate_scenario", "hold");
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      const url = new URL(route.request().url());
      const profile = url.searchParams.get("risk_profile") ?? "normal";
      const path = url.pathname.replace(/\/$/, "");
      const detailSecid = path.match(/\/bonds\/([^/]+)$/)?.[1];

      if (detailSecid) {
        const bond = bonds.find((b) => b.secid === detailSecid);
        if (!bond) {
          await route.fulfill({ status: 404, json: { detail: "not found" } });
          return;
        }
        const score = bond.profile_scores[profile] ?? bond.score;
        await route.fulfill({
          json: {
            bond: { ...bond, score },
            coupons: [],
          },
        });
        return;
      }

      const ranked = [...bonds]
        .map((bond) => ({
          ...bond,
          score: bond.profile_scores[profile] ?? bond.score,
        }))
        .sort((a, b) => b.score - a.score);
      const pageNum = Number(url.searchParams.get("page") ?? "1");
      const pageSize = Number(url.searchParams.get("page_size") ?? "50");
      await route.fulfill({
        json: bondsListResponse(ranked, {
          source: `mock:${profile}`,
          total: ranked.length,
          page: pageNum,
          page_size: pageSize,
        }),
      });
    });
    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: bondsListResponse([]) });
    });
    await page.route("**/api/v1/portfolios/", async (route) => {
      await route.fulfill({ json: [] });
    });
  });

  test("агрессивный профиль поднимает ВДО выше IG", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("bond_monitor_screener_risk_profile", "normal");
    });
    await page.goto("/");
    await expect(page.getByRole("button", { name: "IG надёжная" })).toBeVisible({
      timeout: 15_000,
    });

    const rows = page.locator("tbody tr");
    await expect(rows.nth(0)).toContainText("IG надёжная");

    await page.getByLabel("Риск-профиль").selectOption("aggressive");
    await expect(rows.nth(0)).toContainText("ВДО высокий YTM", { timeout: 15_000 });
  });

  test("скор в таблице совпадает с карточкой и показывает три стратегии", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "IG надёжная" })).toBeVisible({
      timeout: 15_000,
    });

    const igRow = page.locator("tbody tr").filter({ hasText: "IG надёжная" });
    await expect(igRow.getByText("82", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "IG надёжная" }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByText("Итог по стратегиям")).toBeVisible();
    await expect(sheet.getByText("Итого")).toHaveCount(0);
    await expect(sheet.getByText("Консервативный")).toBeVisible();
    await expect(sheet.getByText("Нормальный")).toBeVisible();
    await expect(sheet.getByText("Агрессивный")).toBeVisible();
    await expect(sheet.getByText("в скринере")).toBeVisible();
    await expect(sheet.locator(".text-2xl.font-semibold").filter({ hasText: "82" })).toBeVisible();
  });
});
