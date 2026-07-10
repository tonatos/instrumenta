/**
 * E2E: in-app notifications panel.
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
  ],
};

test.describe("Уведомления портфеля", () => {
  test("показывает панель уведомлений из API", async ({ page }) => {
    const portfolio = makeTradingPortfolio(PORTFOLIO_ID, {
      name: "Notifications E2E",
    });
    await mockTradingPortfolioRoutes(page, PORTFOLIO_ID, portfolio);
    await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/notifications**`, async (route) => {
      await route.fulfill({ json: notificationsPayload });
    });

    await gotoPortfolio(page, PORTFOLIO_ID);
    await expect(page.getByTestId("notifications-panel")).toBeVisible();
    await expect(page.getByTestId("notifications-unread-badge")).toHaveText("1");
    await expect(page.getByText("Put Offer Bond")).toBeVisible();
    await expect(page.getByText("Окно подачи по пут-оферте открыто")).toBeVisible();
  });
});
