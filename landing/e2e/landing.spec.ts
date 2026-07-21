import { expect, test } from "@playwright/test";

test.describe("Bond Monitor landing", () => {
  test("visitor sees product pitch, product mock, and pricing", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.getByRole("banner")).toContainText("Bond Monitor");
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /Облигации без сюрпризов/i,
      }),
    ).toBeVisible();

    await expect(
      page.getByRole("link", { name: /Открыть скринер/i }).first(),
    ).toBeVisible();
    await expect(page.getByTestId("product-mock")).toBeVisible();
    await expect(page.getByTestId("product-mock")).toContainText("ОФЗ");

    await page.getByRole("heading", { name: /Простой прайс/i }).scrollIntoViewIfNeeded();
    await expect(page.getByTestId("pricing-free")).toContainText("0 ₽");
    await expect(page.getByTestId("pricing-free")).toContainText("Скринер");
    await expect(page.getByTestId("pricing-pro")).toContainText("Pro");
    await expect(page.getByTestId("pricing-pro")).toContainText("T-Invest");
    await expect(page.getByTestId("pricing-pro")).toContainText("Telegram");
  });

  test("mobile viewport has no page-level horizontal overflow", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile", "mobile project only");

    await page.goto("/");
    const overflow = await page.evaluate(() => {
      const doc = document.documentElement;
      return {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
      };
    });
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
  });
});
