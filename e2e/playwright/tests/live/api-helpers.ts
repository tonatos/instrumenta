import { expect, type APIRequestContext } from "@playwright/test";

/** Имена портфелей, которые создают live/mocked E2E-тесты. */
export const E2E_PORTFOLIO_NAME_RE = /^(E2E |Тестовый портфель E2E)/;

export type PortfolioSummary = { id: string; name: string };

export async function listPortfolios(request: APIRequestContext): Promise<PortfolioSummary[]> {
  const response = await request.get("/api/v1/portfolios/");
  expect(response.ok(), `GET /portfolios failed: ${response.status()}`).toBeTruthy();
  return response.json();
}

export async function deletePortfolio(request: APIRequestContext, id: string): Promise<void> {
  const response = await request.delete(`/api/v1/portfolios/${id}`);
  expect(
    response.ok() || response.status() === 404,
    `DELETE /portfolios/${id} failed: ${response.status()}`,
  ).toBeTruthy();
}

export async function cleanupE2ePortfolios(request: APIRequestContext): Promise<void> {
  const portfolios = await listPortfolios(request);
  await Promise.all(
    portfolios
      .filter((portfolio) => E2E_PORTFOLIO_NAME_RE.test(portfolio.name))
      .map((portfolio) => deletePortfolio(request, portfolio.id)),
  );
}

export async function createPortfolioViaApi(
  request: APIRequestContext,
  name: string,
): Promise<PortfolioSummary> {
  const horizonDate = new Date(Date.now() + 365 * 24 * 3600 * 1000).toISOString().slice(0, 10);
  const response = await request.post("/api/v1/portfolios/", {
    data: {
      name,
      initial_amount_rub: 400_000,
      horizon_date: horizonDate,
      risk_profile: "normal",
      api_trade_only: true,
    },
  });
  expect(response.ok(), `POST /portfolios failed: ${response.status()} ${await response.text()}`).toBeTruthy();
  return response.json();
}
