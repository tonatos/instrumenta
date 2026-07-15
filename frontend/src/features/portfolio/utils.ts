import type { PlanResponse, Portfolio } from "@/api/types";

export function portfolioPath(portfolioId: string, searchParams: URLSearchParams) {
  const qs = searchParams.toString();
  return `/portfolio/${encodeURIComponent(portfolioId)}${qs ? `?${qs}` : ""}`;
}

/**
 * Invested capital for the portfolio header.
 * Trading: prefer plan baseline (effective broker positions + MoneyRub);
 * persisted portfolio.invested_capital_rub can be 0 when holdings are only on the account.
 */
export function portfolioInvestedCapitalRub(
  portfolio: Portfolio,
  plan?: Pick<PlanResponse, "invested_capital_rub"> | null,
): number {
  if (portfolio.mode === "trading" && plan?.invested_capital_rub != null) {
    return plan.invested_capital_rub;
  }
  return portfolio.invested_capital_rub;
}

/** Free cash in the header: live broker money for trading, else persisted cash_balance. */
export function portfolioFreeCashRub(
  portfolio: Portfolio,
  advice?: { money_rub?: number } | null,
): number {
  if (portfolio.mode === "trading" && advice?.money_rub != null) {
    return advice.money_rub;
  }
  return portfolio.cash_balance_rub;
}
