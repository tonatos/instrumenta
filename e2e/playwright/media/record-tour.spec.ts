import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
import {
  bondsListResponse,
  makeAdvice,
  makeEmptyPlan,
  makeTradingPortfolio,
  mockBillingCatalog,
  mockConfig,
  seedAuth,
} from "../tests/mocked/fixtures";
import {
  dwell,
  installTourCursor,
  smoothScroll,
  smoothScrollTo,
  tourClick,
  tourFill,
  tourMove,
  tourNav,
} from "./tour-helpers";
import { startHqScreencast } from "./hq-screencast";

const OUT_DIR = path.resolve(__dirname, "../../../frontend/public/media");
const RAW_DIR = path.join(__dirname, "test-results", "raw");
const FRAMES_DIR = path.join(RAW_DIR, "frames");
const PORTFOLIO_ID = "demo-tour-1";

const MOCK_BONDS = [
  {
    secid: "SU26238",
    isin: "RU000A105XYZ",
    name: "ОФЗ 26238",
    sector: "government",
    ytm: 14.2,
    ytm_net: 12.35,
    score: 91,
    rating: "AAA",
    days_to_maturity: 118,
    volume_rub: 2_100_000_000,
    risk_level: "LOW",
  },
  {
    secid: "SBER002P",
    isin: "RU000A106ABC",
    name: "Сбербанк 002P",
    sector: "financial",
    ytm: 16.8,
    ytm_net: 14.62,
    score: 88,
    rating: "ruAAA",
    days_to_maturity: 94,
    volume_rub: 890_000_000,
    risk_level: "LOW",
  },
  {
    secid: "GAZP004P",
    isin: "RU000A107DEF",
    name: "Газпром 004P",
    sector: "energy",
    ytm: 15.4,
    ytm_net: 13.4,
    score: 84,
    rating: "ruAA",
    days_to_maturity: 156,
    volume_rub: 640_000_000,
    risk_level: "MEDIUM",
  },
];

function buildValueTimeline() {
  const points: Array<{
    date: string;
    cash_rub: number;
    positions_value_rub: number;
    total_value_rub: number;
  }> = [];
  let value = 275_200;
  for (let i = 0; i < 18; i++) {
    const month = ((6 + i) % 12) + 1;
    const year = 2026 + Math.floor((6 + i) / 12);
    value = Math.round(value * 1.012 + (i % 3 === 0 ? 4_200 : 800));
    points.push({
      date: `${year}-${String(month).padStart(2, "0")}-01`,
      cash_rub: 24_800,
      positions_value_rub: value - 24_800,
      total_value_rub: value,
    });
  }
  return points;
}

const VALUE_TIMELINE = buildValueTimeline();

const composedPositions = [
  {
    isin: "RU000A105XYZ",
    secid: "SU26238",
    name: "ОФЗ 26238",
    lots: 12,
    lot_size: 1,
    purchase_clean_price_pct: 98.5,
    purchase_dirty_price_rub: 1000,
    purchase_aci_rub: 12,
    purchase_date: "2026-07-01",
    purchase_amount_rub: 118_400,
    coupon_rate: 12,
    face_value: 1000,
    maturity_date: "2026-11-01",
    offer_date: null,
    source: "initial",
    figi: "FIGI_OFZ",
    status: "active",
  },
  {
    isin: "RU000A106ABC",
    secid: "SBER002P",
    name: "Сбербанк 002P",
    lots: 8,
    lot_size: 1,
    purchase_clean_price_pct: 99.1,
    purchase_dirty_price_rub: 1010,
    purchase_aci_rub: 8,
    purchase_date: "2026-07-01",
    purchase_amount_rub: 80_800,
    coupon_rate: 14,
    face_value: 1000,
    maturity_date: "2026-10-15",
    offer_date: "2026-08-10",
    source: "initial",
    figi: "FIGI_SBER",
    status: "active",
  },
];

const composedPortfolio = {
  id: PORTFOLIO_ID,
  name: "Стратегия Demo",
  initial_amount_rub: 300_000,
  horizon_date: "2027-12-01",
  risk_profile: "normal",
  cash_balance_rub: 24_800,
  mode: "planning",
  positions_count: 2,
  closed_positions_count: 0,
  invested_capital_rub: 275_200,
  data: {
    positions: composedPositions,
    cash_balance_rub: 24_800,
    initial_amount_rub: 300_000,
    horizon_date: "2027-12-01",
    mode: "planning",
  },
};

const tradingPortfolio = makeTradingPortfolio(PORTFOLIO_ID, {
  name: "Стратегия Demo",
  initial_amount_rub: 300_000,
  positions_count: 2,
  invested_capital_rub: 300_000,
  data: {
    ...composedPortfolio.data,
    mode: "trading",
    account_id: "acc-demo",
    account_kind: "sandbox",
  },
});

function richPlan(withPositions: boolean) {
  const positions = withPositions ? composedPositions : [];
  return makeEmptyPlan({
    invested_capital_rub: positions.length ? 275_200 : 0,
    total_invested_rub: positions.length ? 275_200 : 0,
    expected_xirr_pct: positions.length ? 18.4 : null,
    total_net_profit_rub: positions.length ? 42_600 : 0,
    total_net_profit_with_held_rub: positions.length ? 42_600 : 0,
    final_portfolio_value: positions.length ? 318_000 : 300_000,
    final_cash_balance: positions.length ? 24_800 : 300_000,
    weighted_duration_years: positions.length ? 0.9 : null,
    held_positions: positions.map((p) => ({
      isin: p.isin,
      name: p.name,
      lots: p.lots,
      estimated_value_rub: p.purchase_amount_rub,
      maturity_date: p.maturity_date,
    })),
    value_timeline: positions.length ? VALUE_TIMELINE : [],
    cashflow: positions.length
      ? [
          {
            date: "2026-08-15",
            kind: "coupon",
            amount_rub: 3_200,
            label: "Купон · ОФЗ 26238",
            is_projected: true,
          },
          {
            date: "2026-10-15",
            kind: "maturity",
            amount_rub: 80_800,
            label: "Погашение · Сбербанк 002P",
            is_projected: true,
          },
        ]
      : [],
  });
}

const tradingAdvice = makeAdvice({
  money_rub: 24_800,
  available_money_rub: 24_800,
  holdings: [
    {
      figi: "FIGI_OFZ",
      isin: "RU000A105XYZ",
      name: "ОФЗ 26238",
      lots: 12,
      quantity: 12,
      lot_size: 1,
    },
    {
      figi: "FIGI_SBER",
      isin: "RU000A106ABC",
      name: "Сбербанк 002P",
      lots: 8,
      quantity: 8,
      lot_size: 1,
    },
  ],
  suggestions: [
    {
      id: "sug-put-1",
      kind: "put_offer_reminder",
      isin: "RU000A106ABC",
      name: "Сбербанк 002P",
      lots: 8,
      figi: "FIGI_SBER",
      suggested_price_pct: 100,
      market_price_pct: 100,
      due_date: "2026-08-10",
      reason: "Окно приёма заявок открыто",
      urgency: "critical",
      chat_template: null,
      actionable: true,
    },
    {
      id: "sug-buy-1",
      kind: "buy",
      isin: "RU000A105XYZ",
      name: "ОФЗ 26238",
      lots: 2,
      figi: "FIGI_OFZ",
      suggested_price_pct: 98.5,
      market_price_pct: 98.2,
      due_date: null,
      reason: "План закупок — свободный кэш",
      urgency: "normal",
      chat_template: null,
      actionable: true,
    },
  ],
});

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
      in_portfolios: [PORTFOLIO_ID],
    },
    {
      sector: "government",
      change_7d_pct: 1.2,
      anomaly_count: 0,
      dip_idea_count: 0,
      bond_count: 120,
      in_portfolios: [PORTFOLIO_ID],
    },
  ],
  anomalies: [
    {
      isin: "RU000A106ABC",
      secid: "SBER002P",
      name: "Сбербанк 002P",
      sector: "financial",
      spread_pp: 18.5,
      expected_spread_pp: 8.2,
      delta_pp: 10.3,
      z_score: 2.4,
      peers: 8,
      in_portfolios: [PORTFOLIO_ID],
    },
  ],
  dip_ideas: [
    {
      isin: "RU000A106ABC",
      secid: "SBER002P",
      name: "Сбербанк 002P",
      sector: "financial",
      bond_change_7d_pct: -12.1,
      sector_change_7d_pct: -8.3,
      idiosyncratic_excess_pct: -3.8,
      score: 64,
      interpretation: "sector_panic_overshoot",
      in_portfolios: [PORTFOLIO_ID],
    },
  ],
};

test.describe.configure({ mode: "serial" });

test("record product tour screencast", async ({ page }) => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.mkdirSync(RAW_DIR, { recursive: true });

  page.on("pageerror", (err) => {
    console.error("pageerror:", err.message);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") console.error("console.error:", msg.text());
  });

  let portfolioState: "empty" | "created" | "composed" | "trading" = "empty";

  const emptyCreated = {
    ...composedPortfolio,
    data: { ...composedPortfolio.data, positions: [] as unknown[] },
    positions_count: 0,
    cash_balance_rub: 300_000,
    invested_capital_rub: 0,
  };

  await seedAuth(page);
  await installTourCursor(page);
  await mockConfig(page);
  await mockBillingCatalog(page);

  await page.route("**/api/v1/bonds/**", async (route) => {
    await route.fulfill({ json: bondsListResponse(MOCK_BONDS) });
  });
  await page.route("**/api/v1/favorites/**", async (route) => {
    await route.fulfill({ json: bondsListResponse([]) });
  });
  await page.route("**/api/v1/market-radar**", async (route) => {
    await route.fulfill({ json: MOCK_RADAR });
  });

  await page.route("**/api/v1/accounts**", async (route) => {
    await route.fulfill({
      json: [
        {
          id: "acc-demo",
          name: "Sandbox Demo",
          kind: "sandbox",
          linked_portfolio: null,
        },
      ],
    });
  });

  await page.route("**/api/v1/portfolios/", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      if (portfolioState === "empty") {
        await route.fulfill({ json: [] });
        return;
      }
      const p =
        portfolioState === "trading"
          ? tradingPortfolio
          : portfolioState === "composed"
            ? composedPortfolio
            : emptyCreated;
      await route.fulfill({ json: [p] });
      return;
    }
    if (method === "POST") {
      portfolioState = "created";
      await route.fulfill({ status: 201, json: emptyCreated });
      return;
    }
    await route.continue();
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const p =
      portfolioState === "trading"
        ? tradingPortfolio
        : portfolioState === "composed"
          ? composedPortfolio
          : emptyCreated;
    await route.fulfill({ json: p });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/auto-compose**`, async (route) => {
    portfolioState = "composed";
    await route.fulfill({ json: composedPortfolio });
  });

  await page.route(
    `**/api/v1/portfolios/${PORTFOLIO_ID}/account-preview**`,
    async (route) => {
      await route.fulfill({
        json: {
          money_rub: 300_000,
          bond_positions: [],
          other_instruments: [],
          has_securities: false,
          can_attach: true,
          blockers: [],
          warnings: [],
          linked_portfolio: null,
        },
      });
    },
  );

  await page.route(
    (url) =>
      url.pathname === `/api/v1/portfolios/${PORTFOLIO_ID}/attach` ||
      url.pathname.endsWith(`/portfolios/${PORTFOLIO_ID}/attach`),
    async (route) => {
      if (route.request().method() === "POST") {
        portfolioState = "trading";
        await route.fulfill({ status: 200, json: tradingPortfolio });
        return;
      }
      await route.continue();
    },
  );

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/plan**`, async (route) => {
    const withPositions =
      portfolioState === "composed" || portfolioState === "trading";
    await route.fulfill({ json: richPlan(withPositions) });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/trading-state**`, async (route) => {
    await route.fulfill({
      json: {
        plan: richPlan(true),
        advice: tradingAdvice,
      },
    });
  });

  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/notifications**`, async (route) => {
    await route.fulfill({
      json: {
        notifications: [
          {
            id: "n1",
            fingerprint: "fp-n1",
            kind: "put_offer_action",
            payload: {
              isin: "RU000A106ABC",
              name: "Пут-оферта · Сбербанк 002P",
              reason: "Окно OPEN — подайте заявку вовремя",
            },
            urgency: "soon",
            created_at: "2026-07-14T10:00:00Z",
            read_at: null,
            dismissed_at: null,
            portfolio_id: PORTFOLIO_ID,
            is_unread: true,
          },
          {
            id: "n2",
            fingerprint: "fp-n2",
            kind: "spread_anomaly",
            payload: {
              isin: "RU000A106ABC",
              name: "Аномалия спреда",
              reason: "Спред заметно выше peers",
            },
            urgency: "normal",
            created_at: "2026-07-14T09:00:00Z",
            read_at: null,
            dismissed_at: null,
            portfolio_id: PORTFOLIO_ID,
            is_unread: true,
          },
        ],
      },
    });
  });

  // ——— Warm-up (not recorded): load screener before HQ capture ———
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Скринер/i })).toBeVisible({
    timeout: 20_000,
  });
  await dwell(page, 800);

  const destWebm = path.join(OUT_DIR, "product-tour.webm");
  const screencast = await startHqScreencast(page, {
    outputPath: destWebm,
    framesDir: FRAMES_DIR,
    fps: 12,
  });

  // ——— Scene 1: screener ———
  await dwell(page, 1600);

  const bondRow = page.getByText("ОФЗ 26238").first();
  if (await bondRow.isVisible().catch(() => false)) {
    await tourMove(page, bondRow, 22);
    await dwell(page, 900);
  }
  await smoothScroll(page, { deltaY: 280, steps: 1, pauseMs: 700 });
  await dwell(page, 1000);

  // ——— Scene 2: create portfolio ———
  await tourNav(page, "Портфель");
  await expect(page.getByRole("button", { name: /Создать портфель/i })).toBeVisible({
    timeout: 15_000,
  });
  await dwell(page, 1100);
  await tourClick(page, page.getByRole("button", { name: /Создать портфель/i }));
  await expect(page.getByPlaceholder("Мой портфель")).toBeVisible();
  await tourFill(page, page.getByPlaceholder("Мой портфель"), "Стратегия Demo");
  await tourClick(page, page.getByRole("button", { name: /^Создать$/ }));
  await expect(page.getByRole("heading", { name: "Стратегия Demo" })).toBeVisible({
    timeout: 15_000,
  });
  await dwell(page, 1400);

  // ——— Scene 3: auto-compose ———
  await tourClick(page, page.getByRole("button", { name: /Автосостав/i }));
  await expect(page.getByText(/ОФЗ 26238|Сбербанк/i).first()).toBeVisible({
    timeout: 15_000,
  });
  await dwell(page, 1600);

  // ——— Scene 4: scroll planning portfolio ———
  await smoothScroll(page, { deltaY: 360, steps: 2, pauseMs: 800 });
  const metricsOrChart = page.locator("text=/XIRR|доходност|прогноз/i").first();
  if (await metricsOrChart.isVisible().catch(() => false)) {
    await smoothScrollTo(page, metricsOrChart, 900);
  }
  await dwell(page, 1200);
  await smoothScroll(page, { deltaY: 420, steps: 1, pauseMs: 850 });
  await dwell(page, 1000);

  // Scroll back up for trading CTA
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await dwell(page, 900);

  // ——— Scene 5: attach wizard (no page.goto) ———
  const tradingBtn = page.getByRole("button", { name: /Перевести в торговлю/i });
  await expect(tradingBtn).toBeVisible({ timeout: 10_000 });
  await tourClick(page, tradingBtn);
  await expect(page.getByText(/Выберите счёт/i)).toBeVisible({ timeout: 10_000 });
  await dwell(page, 700);

  await tourClick(page, page.getByRole("button", { name: /Sandbox Demo/i }));
  await dwell(page, 600);
  const nextBtn = page.getByRole("button", { name: /Далее/i });
  await expect(nextBtn).toBeEnabled({ timeout: 10_000 });
  await tourClick(page, nextBtn);
  const attachBtn = page.getByRole("button", { name: /Привязать/i });
  await expect(attachBtn).toBeVisible({ timeout: 10_000 });
  await expect(attachBtn).toBeEnabled({ timeout: 10_000 });
  await dwell(page, 700);

  const attachResponse = page.waitForResponse(
    (res) =>
      res.request().method() === "POST" &&
      res.url().includes(`/portfolios/${PORTFOLIO_ID}/attach`) &&
      res.ok(),
  );
  await tourClick(page, attachBtn);
  await attachResponse;
  await expect(page.getByText("Торговля").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Срочно|Покупки|Пут-оферта/i).first()).toBeVisible({
    timeout: 15_000,
  });
  await dwell(page, 1600);

  // ——— Scene 6: trading UI scroll + signals ———
  await smoothScroll(page, { deltaY: 380, steps: 2, pauseMs: 750 });
  const signalsTab = page.getByRole("tab", { name: /Сигналы/i });
  if (await signalsTab.isVisible().catch(() => false)) {
    await tourClick(page, signalsTab);
    await dwell(page, 1800);
  }
  await smoothScroll(page, { deltaY: 320, steps: 1, pauseMs: 700 });
  await dwell(page, 1000);

  // ——— Scene 7: market radar ———
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await dwell(page, 600);
  await tourNav(page, "Radar");
  await expect(page.getByTestId("radar-page")).toBeVisible({ timeout: 15_000 });
  await dwell(page, 1800);
  await smoothScroll(page, { deltaY: 360, steps: 1, pauseMs: 800 });
  await dwell(page, 1600);

  const posterPath = path.join(OUT_DIR, "product-tour-poster.jpg");
  await page.screenshot({
    path: posterPath,
    type: "jpeg",
    quality: 95,
    scale: "device",
  });

  await screencast.stop();
  await page.close();

  expect(fs.existsSync(destWebm), "HQ screencast did not produce a video").toBeTruthy();
  console.log(`Wrote ${destWebm}`);
  console.log(`Wrote ${posterPath}`);
});
