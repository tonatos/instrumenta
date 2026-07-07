import type { QueryClient } from "@tanstack/react-query";

/** Invalidate portfolio list and derived plan after structural portfolio changes. */
export function invalidatePortfolioStructure(
  queryClient: QueryClient,
  portfolioId: string,
) {
  void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
  void queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
}

/** After trading sync mutations: pending queue is in the response; avoid plan refetch. */
export function invalidateAfterTradingMutation(
  queryClient: QueryClient,
  portfolioId: string,
  options?: { refreshPlan?: boolean; refreshOperations?: boolean },
) {
  void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
  if (options?.refreshPlan) {
    void queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
  }
  if (options?.refreshOperations) {
    void queryClient.invalidateQueries({ queryKey: ["account-operations", portfolioId] });
  }
}
