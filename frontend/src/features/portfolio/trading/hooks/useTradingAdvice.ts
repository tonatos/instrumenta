import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { PlaceOrderRequest, Suggestion } from "@/api/types";
import { tradingStateQueryKey } from "@/features/portfolio/hooks/queryConfig";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";

export function useTradingMutations(portfolioId: string, rateScenario: string) {
  const queryClient = useQueryClient();
  const stateKey = tradingStateQueryKey(portfolioId, rateScenario);

  const invalidateTradingState = () => {
    void queryClient.invalidateQueries({ queryKey: stateKey });
  };

  const placeMutation = useMutation({
    mutationFn: (body: PlaceOrderRequest) => api.placeOrder(portfolioId, body),
    onSuccess: invalidateTradingState,
  });

  const cancelMutation = useMutation({
    mutationFn: (orderId: string) => api.cancelOrder(portfolioId, orderId),
    onSuccess: invalidateTradingState,
  });

  const acknowledgeRiskMutation = useMutation({
    mutationFn: (isin: string) => api.acknowledgeRiskAlert(portfolioId, isin),
    onSuccess: invalidateTradingState,
  });

  const isPending =
    placeMutation.isPending || cancelMutation.isPending || acknowledgeRiskMutation.isPending;

  return {
    placeMutation,
    cancelMutation,
    acknowledgeRiskMutation,
    isPending,
    parseApiError,
  };
}

/** @deprecated Use useTradingMutations — trading-state query lives in usePortfolioQueries. */
export const useTradingAdvice = useTradingMutations;

export type { Suggestion };
