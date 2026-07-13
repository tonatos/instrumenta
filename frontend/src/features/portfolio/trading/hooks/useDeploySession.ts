import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { tradingStateQueryKey } from "@/features/portfolio/hooks/queryConfig";

export function useDeploySession(portfolioId: string, rateScenario: string) {
  const queryClient = useQueryClient();
  const stateKey = tradingStateQueryKey(portfolioId, rateScenario);

  const invalidateTradingState = () => {
    void queryClient.invalidateQueries({ queryKey: stateKey });
  };

  const createMutation = useMutation({
    mutationFn: () => api.createDeploySession(portfolioId),
    onSuccess: invalidateTradingState,
  });

  const refreshMutation = useMutation({
    mutationFn: (sessionId: string) => api.refreshDeploySession(portfolioId, sessionId),
    onSuccess: invalidateTradingState,
  });

  const cancelMutation = useMutation({
    mutationFn: (sessionId: string) => api.cancelDeploySession(portfolioId, sessionId),
    onSuccess: invalidateTradingState,
  });

  const skipItemMutation = useMutation({
    mutationFn: ({ sessionId, itemId }: { sessionId: string; itemId: string }) =>
      api.skipDeploySessionItem(portfolioId, sessionId, itemId),
    onSuccess: invalidateTradingState,
  });

  const isPending =
    createMutation.isPending ||
    refreshMutation.isPending ||
    cancelMutation.isPending ||
    skipItemMutation.isPending;

  return {
    createMutation,
    refreshMutation,
    cancelMutation,
    skipItemMutation,
    isPending,
  };
}
