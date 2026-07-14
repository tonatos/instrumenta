import { test, expect } from "@playwright/test";
import {
  makeTradingPortfolio,
  mockConfig,
  seedAuth,
} from "./fixtures";

const PORTFOLIO_ID = "p-radar-e2e";
const HELD_ISIN = "RU000A109874";

const MOCK_RADAR = {
  scanned_at: "2026-07-14T18:00:00Z",
  universe_scanned: 842,
  sectors: [
    {
      sector: "energy",
      change_7d_pct: -16.2,
      anomaly_count: 12,
      dip_idea_count: 4,
      bond_count: 45,
      in_portfolios: [PORTFOLIO_ID],
    },
    {
      sector: "financial",
      change_7d_pct: -3.1,
      anomaly_count: 2,
      dip_idea_count: 0,
      bond_count: 80,
    },
  ],
  anomalies: [
    {
      isin: HELD_ISIN,
      secid: "TEST1",
      name: "Test Energy Bond",
      sector: "energy",
      spread_pp: 18.5,
      expected_spread_pp: 8.2,
      delta_pp: 10.3,
      z_score: 2.4,
      peers: 8,
      in_portfolios: [PORTFOLIO_ID],
    },
    {
      isin: "RU000A999999",
      secid: "TEST2",
      name: "Other Bond",
      sector: "financial",
      spread_pp: 12.0,
      expected_spread_pp: 7.0,
      delta_pp: 5.0,
      z_score: 1.8,
      peers: 10,
      in_portfolios: [],
    },
  ],
  dip_ideas: [
    {
      isin: HELD_ISIN,
      secid: "TEST1",
      name: "Test Energy Bond",
      sector: "energy",
      bond_change_7d_pct: -22.1,
      sector_change_7d_pct: -15.3,
      idiosyncratic_excess_pct: -6.8,
      score: 71,
      interpretation: "sector_panic_overshoot",
      in_portfolios: [PORTFOLIO_ID],
    },
  ],
};

test.describe("Market Radar page", () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockConfig(page);

    await page.route("**/api/v1/bonds/**", async (route) => {
      await route.fulfill({
        json: {
          bonds: [],
          source: "mock",
          count: 0,
          total: 0,
          page: 1,
          page_size: 50,
        },
      });
    });

    await page.route("**/api/v1/favorites/**", async (route) => {
      await route.fulfill({ json: { bonds: [], count: 0, total: 0, page: 1, page_size: 50 } });
    });

    await page.route("**/api/v1/market-radar**", async (route) => {
      await route.fulfill({ json: MOCK_RADAR });
    });

    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      data: {
        positions: [{ isin: HELD_ISIN, name: "Test Energy Bond", lots: 1 }],
      },
    });

    await page.route("**/api/v1/portfolios/", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ json: [portfolio] });
        return;
      }
      await route.continue();
    });
  });

  test("shows heatmap, filters by sector, and portfolio actions", async ({ page }) => {
    await page.goto("/radar");

    await expect(page.getByTestId("radar-page")).toBeVisible();
    await expect(page.getByTestId("radar-heatmap")).toBeVisible();
    await expect(page.getByTestId("radar-sector-energy")).toBeVisible();

    await page.getByTestId("radar-sector-energy").click();
    await expect(page.getByTestId("radar-anomaly-TEST1").filter({ visible: true })).toBeVisible();
    await expect(page.getByTestId("radar-anomaly-TEST2").filter({ visible: true })).toHaveCount(0);

    await page.getByRole("button", { name: "Показать все секторы" }).click();
    await expect(page.getByTestId("radar-anomaly-TEST2").filter({ visible: true })).toBeVisible();

    await page.getByTestId("radar-mine-first-toggle").click();
    await expect(page.getByTestId("radar-anomaly-TEST1").filter({ visible: true })).toBeVisible();

    const openPortfolio = page.getByTestId("radar-open-portfolio-TEST1");
    await expect(openPortfolio).toBeVisible();
    await expect(openPortfolio).toHaveAttribute("href", `/portfolio/${PORTFOLIO_ID}`);
  });
});
