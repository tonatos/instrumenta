/**
 * E2E: in-app notifications panel and signals tab.
 */

import { test, expect } from "@playwright/test";
import {
  gotoPortfolio,
  makeTradingPortfolio,
  mockTradingPortfolioRoutes,
} from "./fixtures";

const PORTFOLIO_ID = "trading-portfolio-notify";

const notificationsPayload = {
  notifications: [
    {
      id: "notif-1",
      fingerprint: "fp-1",
      portfolio_id: PORTFOLIO_ID,
      kind: "put_offer_action",
      payload: {
        isin: "RU000PO",
        name: "Put Offer Bond",
        reason: "Окно подачи по пут-оферте открыто — подайте заявку на досрочное погашение.",
      },
      urgency: "soon",
      created_at: "2026-07-28T10:00:00+00:00",
      read_at: null,
      dismissed_at: null,
      is_unread: true,
    },
    {
      id: "notif-2",
      fingerprint: "fp-2",
      portfolio_id: PORTFOLIO_ID,
      kind: "sector_concentration",
      payload: {
        isin: "sector:financial",
        name: "Концентрация в секторе: financial",
        reason: "Сектор «financial» занимает 42.0% портфеля (лимит 35%). Рекомендуем диверсифицировать.",
      },
      urgency: "normal",
      created_at: "2026-07-28T10:01:00+00:00",
      read_at: null,
      dismissed_at: null,
      is_unread: true,
    },
    {
      id: "notif-3",
      fingerprint: "fp-3",
      portfolio_id: PORTFOLIO_ID,
      kind: "spread_anomaly",
      payload: {
        isin: "RU000SPREAD1",
        name: "Spread Bond",
        reason:
          "Кредитный спред расширился относительно похожих бумаг: 15.0 п.п. vs медиана 5.0 п.п. (Δ 10.0 п.п., peers 6).",
      },
      urgency: "normal",
      created_at: "2026-07-28T10:02:00+00:00",
      read_at: null,
      dismissed_at: null,
      is_unread: true,
    },
    {
      id: "notif-4",
      fingerprint: "fp-4",
      portfolio_id: PORTFOLIO_ID,
      kind: "sector_stress",
      payload: {
        isin: "RU000SECTOR1",
        name: "Sector Stress Bond",
        reason: "Похоже на секторное давление: бумага падает вместе с похожими бумагами из сектора.",
      },
      urgency: "normal",
      created_at: "2026-07-28T10:03:00+00:00",
      read_at: null,
      dismissed_at: null,
      is_unread: true,
    },
    {
      id: "notif-5",
      fingerprint: "fp-5",
      portfolio_id: PORTFOLIO_ID,
      kind: "turbo_entry",
      payload: {
        isin: "RU000TURBO1",
        name: "Turbo Bond",
        reason: "Turbo-entry: сектор в панике, а бумага просела сильнее сектора без ухудшения рейтинга.",
        suggested_price_pct: 99.1,
        lots: 1,
      },
      urgency: "normal",
      created_at: "2026-07-28T10:04:00+00:00",
      read_at: null,
      dismissed_at: null,
      is_unread: true,
    },
  ],
};

test.describe("Уведомления портфеля", () => {
  test("разделяет операционные уведомления и вкладку сигналов", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Notifications E2E",
    });
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio);
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/notifications**`, async (route) => {
      await route.fulfill({ json: notificationsPayload });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);
    const panel = page.getByTestId("notifications-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("notifications-unread-badge")).toHaveText("2");
    await expect(panel.getByText("Put Offer Bond")).toBeVisible();
    await expect(panel.getByText("Окно подачи по пут-оферте открыто")).toBeVisible();
    await expect(panel.getByText("Концентрация в секторе")).toBeVisible();
    await expect(panel.getByText("Spread Bond")).not.toBeVisible();
    await expect(panel.getByText("Turbo Bond")).not.toBeVisible();

    await page.getByRole("tab", { name: /Сигналы/ }).click();
    const signalsPanel = page.getByTestId("signals-panel");
    await expect(signalsPanel).toBeVisible();
    await expect(signalsPanel.getByText("Сигналы рынка")).toBeVisible();
    await expect(signalsPanel.getByText("Spread Bond")).toBeVisible();
    await expect(signalsPanel.getByText("Sector Stress Bond")).toBeVisible();
    await expect(signalsPanel.getByText("Turbo Bond")).toBeVisible();
    await expect(signalsPanel.getByText("Put Offer Bond")).not.toBeVisible();
  });
});
