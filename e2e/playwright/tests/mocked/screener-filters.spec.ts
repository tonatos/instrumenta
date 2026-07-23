/**
 * E2E: серверные фильтры скринера, пагинация и infinite scroll.
 */

import { test, expect, type Page } from "@playwright/test";
import { bondsListResponse, MOCK_CONFIG } from "./fixtures";

function makeBond(
  overrides: Partial<{
    secid: string;
    isin: string;
    name: string;
    prev_volume_rub: number;
    subordinated: boolean;
    defaulted: boolean;
    sector: string;
  }> = {},
) {
  const warnings: string[] = [];
  if (overrides.subordinated) {
    warnings.push("Субординированная облигация: при банкротстве выплачивается последней");
  }
  if (overrides.defaulted) {
    warnings.push("Эмитент в дефолте (MOEX HASDEFAULT): купоны/номинал не выплачены");
  }
  return {
    secid: overrides.secid ?? "BOND1",
    isin: overrides.isin ?? "RU000ABOND1",
    name: overrides.name ?? "Тестовая облигация",
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
    volume_rub: overrides.prev_volume_rub ?? 5_000_000,
    prev_volume_rub: overrides.prev_volume_rub ?? 5_000_000,
    credit_rating: "AAA",
    risk_level: 1,
    score: 72,
    profile_scores: { conservative: 72, normal: 72, aggressive: 72 },
    ytm_score: 80,
    risk_score: 90,
    liquidity_score: 70,
    is_favorite: false,
    has_warnings: warnings.length > 0,
    warnings,
    tinvest_enriched: true,
    issuer_name: "Эмитент",
    instrument_full_name: "Тест",
    sector: overrides.sector ?? "corp",
    description: "",
  };
}

const allBonds = [
  makeBond({ secid: "LIQ1", isin: "RU000ALIQ1", name: "Ликвидная", prev_volume_rub: 1_000_000, sector: "financial" }),
  makeBond({ secid: "ILL1", isin: "RU000AILL1", name: "Низкий объём", prev_volume_rub: 100_000, sector: "real_estate" }),
  makeBond({ secid: "SUB1", isin: "RU000ASUB1", name: "Субординированная", subordinated: true }),
  makeBond({ secid: "DEF1", isin: "RU000ADEF1", name: "Дефолтная", defaulted: true }),
  ...Array.from({ length: 55 }, (_, i) =>
    makeBond({
      secid: `P${i}`,
      isin: `RU000APAGE${i}`,
      name: `Страница ${i}`,
      prev_volume_rub: 800_000,
    }),
  ),
];

function filterBonds(url: URL) {
  let filtered = [...allBonds];
  const maxDays = url.searchParams.get("max_days");
  if (maxDays != null && maxDays !== "") {
    const limit = Number(maxDays);
    filtered = filtered.filter((b) => (b.days_to_maturity ?? 0) <= limit);
  }
  const minVolume = url.searchParams.get("min_volume_rub");
  if (minVolume != null && minVolume !== "") {
    const threshold = Number(minVolume);
    filtered = filtered.filter((b) => (b.prev_volume_rub ?? 0) >= threshold);
  }
  if (url.searchParams.get("hide_subordinated") === "true") {
    filtered = filtered.filter((b) => !b.warnings.some((w) => w.toLowerCase().includes("субординир")));
  }
  if (url.searchParams.get("hide_default") === "true") {
    filtered = filtered.filter((b) => !b.warnings.some((w) => w.toLowerCase().includes("дефолт")));
  }
  const q = (url.searchParams.get("q") ?? "").toLowerCase();
  if (q) {
    filtered = filtered.filter(
      (b) =>
        b.name.toLowerCase().includes(q) ||
        b.secid.toLowerCase().includes(q) ||
        b.isin.toLowerCase().includes(q),
    );
  }
  const sectors = url.searchParams.get("sectors");
  if (sectors) {
    const allowed = new Set(sectors.split(",").map((s) => s.trim().toLowerCase()));
    filtered = filtered.filter((b) => allowed.has((b.sector ?? "").toLowerCase()));
  }
  return filtered;
}

function expectScreenerCount(page: Page, text: string) {
  return expect(page.getByText(`${text} · mock`)).toBeVisible({ timeout: 15_000 });
}

/** На mobile панель свёрнута — раскрываем перед «Дополнительно». */
async function ensureFiltersExpanded(page: Page) {
  const toggle = page.getByTestId("screener-filters-toggle");
  if ((await toggle.getAttribute("aria-expanded")) === "false") {
    await toggle.click();
  }
  await expect(page.getByTestId("screener-filters-advanced-toggle")).toBeVisible();
}

async function ensureAdvancedOpen(page: Page) {
  await ensureFiltersExpanded(page);
  const advanced = page.getByTestId("screener-filters-advanced-toggle");
  if ((await advanced.getAttribute("aria-expanded")) === "false") {
    await advanced.click();
  }
  await expect(page.getByRole("checkbox", { name: /субординир/i })).toBeVisible();
}

async function selectMultiOption(page: Page, testId: string, optionLabel: string) {
  await ensureAdvancedOpen(page);
  await page.getByTestId(testId).click();
  await page.getByRole("option", { name: optionLabel }).click();
  await page.keyboard.press("Escape");
}

test.describe("Скринер — серверные фильтры", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/config/", async (route) => {
      await route.fulfill({
        json: { ...MOCK_CONFIG, max_days: 120, min_volume_rub: 0 },
      });
    });
    await page.route("**/api/v1/bonds/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.includes("/bonds/by-isins")) {
        await route.fulfill({ json: bondsListResponse([]) });
        return;
      }
      const filtered = filterBonds(url);
      const exportAll = url.searchParams.get("export") === "true";
      const pageNum = Number(url.searchParams.get("page") ?? "1");
      const pageSize = exportAll ? filtered.length : Number(url.searchParams.get("page_size") ?? "50");
      const start = exportAll ? 0 : (pageNum - 1) * pageSize;
      const slice = filtered.slice(start, start + pageSize);
      await route.fulfill({
        json: bondsListResponse(slice, {
          total: filtered.length,
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

  test("мин. объём уменьшает total через новый запрос", async ({ page }) => {
    await page.goto("/");
    await expectScreenerCount(page, "50 из 58");
    await ensureAdvancedOpen(page);

    await page.getByLabel("Мин. объём торгов").fill("500000");
    await expectScreenerCount(page, "50 из 57");
  });

  test("скрыть субординированные убирает SUB1", async ({ page }) => {
    await page.goto("/");
    await expectScreenerCount(page, "50 из 58");
    await ensureAdvancedOpen(page);

    await page.getByRole("checkbox", { name: /субординир/i }).check();
    await expectScreenerCount(page, "50 из 57");
    await expect(page.getByRole("button", { name: "Субординированная" })).not.toBeVisible();
  });

  test("infinite scroll подгружает вторую страницу", async ({ page }) => {
    await page.goto("/");
    await expectScreenerCount(page, "50 из 58");

    await page.locator('[data-testid="screener-load-more"]').scrollIntoViewIfNeeded();
    await expectScreenerCount(page, "58 из 58");
  });

  test("фильтр по сектору отправляет sectors и уменьшает total", async ({ page }) => {
    await page.goto("/");
    await expectScreenerCount(page, "50 из 58");

    await selectMultiOption(page, "screener-filter-sector", "Финансы");
    await expectScreenerCount(page, "1 из 1");
    await expect(page.getByRole("button", { name: "Ликвидная" })).toBeVisible();
  });

  test("дополнительные фильтры спрятаны под раскрывалку", async ({ page }) => {
    await page.goto("/");
    await ensureFiltersExpanded(page);

    await expect(page.getByLabel("Мин. YTM нетто")).toBeVisible();
    await expect(page.getByTestId("screener-filter-coupon")).not.toBeVisible();
    await expect(page.getByRole("checkbox", { name: /субординир/i })).not.toBeVisible();

    await page.getByTestId("screener-filters-advanced-toggle").click();
    await expect(page.getByTestId("screener-filter-coupon")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /субординир/i })).toBeVisible();
    await expect(page.getByLabel("Мин. объём торгов")).toBeVisible();
  });
});
