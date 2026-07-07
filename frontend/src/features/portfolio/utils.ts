import type { Portfolio } from "@/api/types";

export function portfolioPath(portfolioId: string, searchParams: URLSearchParams) {
  const qs = searchParams.toString();
  return `/portfolio/${encodeURIComponent(portfolioId)}${qs ? `?${qs}` : ""}`;
}

export function portfolioInvestedCapitalRub(portfolio: Portfolio): number {
  return portfolio.invested_capital_rub;
}
