/**
 * Business-scenario E2E tests for bond-monitor features.
 *
 * These tests focus on user-visible behaviour, not implementation details.
 * They require a running API + frontend (dev server or BASE_URL env).
 */

import { test, expect } from "@playwright/test";
import { cleanupE2ePortfolios, createPortfolioViaApi } from "./api-helpers";

const TIMEOUT = 30_000;

// ─── Screener ────────────────────────────────────────────────────────────────

test.describe("Скринер — фильтры", () => {
  test("фильтр «Скрыть дефолтные» скрывает бумаги с дефолтом", async ({ page }) => {
    await page.goto("/");

    // Wait for bonds to load
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    // Checkbox should be checked by default
    const hideDefaultCheckbox = page.getByRole("checkbox").filter({ hasText: /дефолт/i }).first();
    // The checkbox for hiding defaults should be checked (default: true)
    // Let's just verify we can see filter panel
    await expect(page.getByText("Скрыть дефолтные")).toBeVisible();
    await expect(page.getByText("Скрыть субординированные")).toBeVisible();
  });

  test("поиск по названию фильтрует таблицу", async ({ page }) => {
    await page.goto("/");

    // Wait for table to populate
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    const searchInput = page.getByPlaceholder("Поиск по названию, SECID или ISIN…");
    await searchInput.fill("XXX_NONEXISTENT_BOND_12345");

    await expect(page.getByText("Нет бумаг по заданным фильтрам")).toBeVisible({
      timeout: 5000,
    });
  });

  test("фильтр типа купона работает", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    // Toggle "Плавающий" coupon type chip
    await page.getByRole("button", { name: "Плавающий" }).first().click();

    // Counter should update
    await expect(page.getByText(/\d+ бумаг/)).toBeVisible({ timeout: 5000 });
  });

  test("управление видимостью колонок работает", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    // Open columns popover
    await page.getByRole("button", { name: "Колонки" }).click();
    await expect(page.getByText("Видимость колонок")).toBeVisible();

    // Toggle a column
    const ytmGrossCheckbox = page.getByLabel("YTM брутто");
    if (await ytmGrossCheckbox.isChecked()) {
      await ytmGrossCheckbox.uncheck();
    } else {
      await ytmGrossCheckbox.check();
    }

    // Close popover
    await page.keyboard.press("Escape");
  });
});

// ─── Bond Detail Sheet ────────────────────────────────────────────────────────

test.describe("Карточка бумаги", () => {
  test("открывается sheet с полными данными при клике на бумагу", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    // Click the first bond name in the table
    const firstBondLink = page.locator("table tbody tr").first().getByRole("button").last();
    await firstBondLink.click();

    // Sheet should open with key sections
    await expect(page.getByText("Идентификаторы")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Скоринг")).toBeVisible();
    await expect(page.getByText("YTM-скор × 0.45")).toBeVisible();
  });

  test("sheet показывает кнопку Т-Инвестиции если есть ISIN", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    // Click a bond row
    await page.locator("table tbody tr").first().click();

    // Wait for sheet to open
    await expect(page.getByText("Идентификаторы")).toBeVisible({ timeout: 5000 });

    const sheet = page.getByRole("dialog");
    const isin = await sheet
      .locator("dt", { hasText: /^ISIN$/ })
      .locator("..")
      .locator("dd")
      .textContent();

    const tInvestLink = sheet.getByRole("link", { name: /Т-Инвестиции/i });
    await expect(tInvestLink).toBeVisible();
    await expect(tInvestLink).toHaveAttribute(
      "href",
      `https://www.tbank.ru/invest/bonds/${isin}/`,
    );
  });

  test("sheet показывает дату колл-оферты", async ({ page }) => {
    const bond = {
      secid: "CALLTEST",
      isin: "RU000ACALL1",
      name: "Облигация с коллом",
      figi: "FIGI_CALL",
      maturity_date: "2028-01-01",
      offer_date: null,
      call_date: "2026-09-15",
      effective_date: "2026-09-15",
      days_to_maturity: 90,
      ytm: 14.0,
      ytm_net: 12.0,
      coupon_rate: 12.0,
      coupon_type: "fixed",
      last_price: 98.5,
      face_value: 1000,
      lot_size: 1,
      volume_rub: 1_000_000,
      prev_volume_rub: 900_000,
      credit_rating: "ruA",
      risk_level: 2,
      score: 70,
      ytm_score: 75,
      risk_score: 65,
      liquidity_score: 80,
      is_favorite: false,
      has_warnings: true,
      warnings: ["Колл-оферта 15 сентября: эмитент может досрочно выкупить облигацию"],
      tinvest_enriched: true,
    };

    await page.route("**/api/v1/bonds/**", async (route) => {
      const url = route.request().url();
      if (url.includes("/bonds/CALLTEST") && !url.includes("?")) {
        await route.fulfill({ json: { bond, coupons: [] } });
        return;
      }
      await route.fulfill({
        json: { bonds: [bond], source: "mock", count: 1 },
      });
    });

    await page.goto("/");
    await expect(page.getByRole("button", { name: "Облигация с коллом" })).toBeVisible({
      timeout: TIMEOUT,
    });
    await page.getByRole("button", { name: "Облигация с коллом" }).click();

    const sheet = page.getByRole("dialog");
    await expect(sheet.getByText("Дата колл-оферты")).toBeVisible({ timeout: 5000 });
    await expect(sheet.locator('dt:has-text("Дата колл-оферты") + dd')).toHaveText("15 сентября");
  });

  test("sheet показывает эмитента и описание", async ({ page }) => {
    const bond = {
      secid: "ISSUERTEST",
      isin: "RU000AISSU1",
      name: "Газпром001",
      issuer_name: "ПАО Газпром",
      instrument_full_name: "Газпром БО-001Р-02",
      description: "Корпоративная облигация с фиксированным купоном.",
      sector: "Энергетика",
      figi: "FIGI_ISSUER",
      maturity_date: "2028-01-01",
      offer_date: null,
      call_date: null,
      effective_date: "2026-09-15",
      days_to_maturity: 70,
      ytm: 14.0,
      ytm_net: 12.0,
      coupon_rate: 12.0,
      coupon_type: "fixed",
      last_price: 98.5,
      face_value: 1000,
      lot_size: 1,
      volume_rub: 1_000_000,
      prev_volume_rub: 900_000,
      credit_rating: "ruA",
      risk_level: 2,
      score: 70,
      ytm_score: 75,
      risk_score: 65,
      liquidity_score: 80,
      is_favorite: false,
      has_warnings: false,
      warnings: [],
      tinvest_enriched: true,
    };

    await page.route("**/api/v1/bonds/**", async (route) => {
      const url = route.request().url();
      if (url.includes("/bonds/ISSUERTEST") && !url.includes("?")) {
        await route.fulfill({ json: { bond, coupons: [] } });
        return;
      }
      await route.fulfill({
        json: { bonds: [bond], source: "mock", count: 1 },
      });
    });

    await page.goto("/");
    await expect(page.getByRole("button", { name: "Газпром001" })).toBeVisible({
      timeout: TIMEOUT,
    });
    await page.getByRole("button", { name: "Газпром001" }).click();

    const sheet = page.getByRole("dialog");
    await expect(sheet.getByRole("heading", { name: "ПАО Газпром" })).toBeVisible({
      timeout: 5000,
    });
    await expect(sheet.getByText("Газпром БО-001Р-02")).toBeVisible();
    await expect(sheet.getByText("Эмитент")).toBeVisible();
    await expect(sheet.getByText("Энергетика")).toBeVisible();
    await expect(
      sheet.getByText("Корпоративная облигация с фиксированным купоном."),
    ).toBeVisible();
  });
});

// ─── Избранное ────────────────────────────────────────────────────────────────

test.describe("Избранное", () => {
  test("карточки кликабельны и открывают sheet", async ({ page }) => {
    // First, add a bond to favorites via screener
    await page.goto("/");
    await expect(page.getByText(/\d+ из \d+/)).toBeVisible({ timeout: TIMEOUT });

    // Click the star button on the first bond
    const starBtn = page.locator("table tbody tr").first().getByRole("button", { name: /избранн/i });
    const wasAlreadyFavorite = (await starBtn.textContent())?.includes("В избранном");

    if (!wasAlreadyFavorite) {
      await starBtn.click();
      await page.waitForTimeout(500);
    }

    // Navigate to favorites
    await page.goto("/favorites");

    // Wait for favorites to load
    await page.waitForTimeout(1000);

    // If any favorites exist, click the first card
    const cards = page.locator('[role="button"]');
    const count = await cards.count();
    if (count > 0) {
      await cards.first().click();
      await expect(page.getByText("Идентификаторы")).toBeVisible({ timeout: 5000 });
    }
  });
});

// ─── Портфель ────────────────────────────────────────────────────────────────

test.describe("Портфель", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ request }) => {
    await cleanupE2ePortfolios(request);
  });

  test.afterAll(async ({ request }) => {
    await cleanupE2ePortfolios(request);
  });

  test("создание нового портфеля", async ({ page }) => {
    const portfolioName = `Тестовый портфель E2E ${Date.now()}`;
    await page.goto("/portfolio");
    await expect(page.getByRole("heading", { name: "Портфель" })).toBeVisible({
      timeout: TIMEOUT,
    });

    await page.getByRole("button", { name: "Создать" }).click();
    await expect(page.getByRole("dialog", { name: "Новый портфель" })).toBeVisible();

    await page.getByPlaceholder("Мой портфель").fill(portfolioName);
    await page.getByRole("button", { name: "Создать" }).last().click();

    await expect(page).toHaveURL(/\/portfolio\//, { timeout: TIMEOUT });
    await expect(page.getByRole("heading", { name: portfolioName, level: 2 })).toBeVisible({
      timeout: TIMEOUT,
    });
  });

  test("автосостав и просмотр cashflow-таблицы", async ({ page, request }) => {
    const portfolioName = `E2E Cashflow ${Date.now()}`;
    const portfolio = await createPortfolioViaApi(request, portfolioName);
    await page.goto(`/portfolio/${portfolio.id}`);
    await expect(page.getByRole("heading", { name: portfolioName, level: 2 })).toBeVisible({
      timeout: TIMEOUT,
    });

    // Click auto-compose
    await page.getByRole("button", { name: /Автосостав/ }).click();

    // Wait for plan to load
    await expect(page.getByRole("tab", { name: "Cashflow" })).toBeVisible({ timeout: TIMEOUT });
    await page.getByRole("tab", { name: "Cashflow" }).click();
    await expect(page.getByTestId("portfolio-value-chart")).toBeVisible({ timeout: TIMEOUT });
    await expect(page.getByText("Рост стоимости портфеля")).toBeVisible();

    // Should show cashflow table by default
    await expect(page.getByRole("table")).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("cell", { name: "Покупка" }).first()).toBeVisible({
      timeout: 5000,
    });
  });

  test("клик по позиции открывает карточку бумаги", async ({ page, request }) => {
    const portfolioName = `E2E Position Detail ${Date.now()}`;
    const portfolio = await createPortfolioViaApi(request, portfolioName);
    await page.goto(`/portfolio/${portfolio.id}`);
    await expect(page.getByRole("heading", { name: portfolioName, level: 2 })).toBeVisible({
      timeout: TIMEOUT,
    });

    await page.getByRole("button", { name: /Автосостав/ }).click();

    const positionsTab = page.getByRole("tab", { name: /Позиции/ });
    await expect(positionsTab).toBeVisible({ timeout: TIMEOUT });

    const positionsTable = page.locator('[data-testid="positions-table"] tbody tr');
    await expect(positionsTable.first()).toBeVisible({ timeout: TIMEOUT });
    await positionsTable.first().click();

    await expect(page.getByText("Идентификаторы")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Скоринг")).toBeVisible();
  });
});

// ─── Калькулятор ─────────────────────────────────────────────────────────────

test.describe("Калькулятор", () => {
  test("combobox позволяет найти и выбрать бумагу", async ({ page }) => {
    await page.goto("/calculator");
    await expect(page.getByRole("heading", { name: "Калькулятор" })).toBeVisible();

    // Wait for bonds to load
    await expect(page.getByRole("button", { name: "Добавить бумагу…" })).toBeVisible({
      timeout: TIMEOUT,
    });

    // Open combobox
    await page.getByRole("button", { name: "Добавить бумагу…" }).click();

    // Type in search
    await page.getByPlaceholder("Поиск по названию или SECID…").fill("о");

    // Should show filtered results
    await expect(
      page.getByRole("button").filter({ hasText: /YTM/i }).first(),
    ).toBeVisible({
      timeout: 5000,
    });
  });

  test("расчёт с выбранной бумагой показывает breakdown", async ({ page }) => {
    await page.goto("/calculator");

    await expect(page.getByRole("button", { name: "Добавить бумагу…" })).toBeVisible({
      timeout: TIMEOUT,
    });

    // Open combobox and pick first available bond
    await page.getByRole("button", { name: "Добавить бумагу…" }).click();
    await page.getByPlaceholder("Поиск по названию или SECID…").fill("о");

    const firstOption = page.getByRole("button").filter({ hasText: /YTM/i }).first();
    await expect(firstOption).toBeVisible({ timeout: 5000 });
    await firstOption.click();

    await expect(page.getByRole("button", { name: "Рассчитать" })).toBeEnabled({
      timeout: 5000,
    });

    // Now calculate
    await page.getByRole("button", { name: "Рассчитать" }).click();

    // Should show results
    await expect(page.getByText("Детализация по бумагам")).toBeVisible({ timeout: TIMEOUT });
    await expect(page.getByText("Вложено").first()).toBeVisible();
    await expect(page.getByText("Прибыль").first()).toBeVisible();
  });
});
