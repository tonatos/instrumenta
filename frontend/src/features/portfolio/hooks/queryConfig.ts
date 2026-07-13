/** Shared React Query tuning for portfolio/trading screens. */

export const STALE = {
  /** Bonds universe changes slowly (MOEX refresh is manual or periodic). */
  bonds: 5 * 60_000,
  config: 5 * 60_000,
  portfolios: 30_000,
  plan: 60_000,
  tradingSync: 30_000,
  accountOperations: 60_000,
} as const;

export function tradingStateQueryKey(portfolioId: string, rateScenario: string) {
  return ["trading-state", portfolioId, rateScenario] as const;
}
