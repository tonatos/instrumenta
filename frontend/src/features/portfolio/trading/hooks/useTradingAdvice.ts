import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { PlaceOrderRequest, Portfolio, Suggestion } from "@/api/types";
import { invalidateAfterTradingMutation } from "@/features/portfolio/hooks/invalidatePortfolio";
import { STALE } from "@/features/portfolio/hooks/queryConfig";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";

function hasActiveOrders(data: { active_orders: Array<{ status: string }> } | undefined) {
  if (!data) return false;
  const terminal = new Set([
    "EXECUTION_REPORT_STATUS_FILL",
    "EXECUTION_REPORT_STATUS_CANCELLED",
    "EXECUTION_REPORT_STATUS_REJECTED",
  ]);
  return data.active_orders.some((o) => !terminal.has(o.status));
}

export function useTradingAdvice(portfolio: Portfolio) {
  const queryClient = useQueryClient();
  const enabled = portfolio.mode === "trading" && Boolean(portfolio.account_id);

  const stateQuery = useQuery({
    queryKey: ["trading-state", portfolio.id],
    queryFn: () => api.getTradingState(portfolio.id),
    enabled,
    staleTime: STALE.tradingSync,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!enabled) return false;
      if (hasActiveOrders(query.state.data?.advice)) return 30_000;
      return false;
    },
    select: (data) => data.advice,
  });

  const afterPlace = () => {
    void queryClient.invalidateQueries({ queryKey: ["trading-state", portfolio.id] });
    invalidateAfterTradingMutation(queryClient, portfolio.id, {
      refreshOperations: true,
    });
  };

  const afterCancel = () => {
    void queryClient.invalidateQueries({ queryKey: ["trading-state", portfolio.id] });
    invalidateAfterTradingMutation(queryClient, portfolio.id, {
      refreshOperations: true,
    });
  };

  const placeMutation = useMutation({
    mutationFn: (body: PlaceOrderRequest) => api.placeOrder(portfolio.id, body),
    onSuccess: afterPlace,
  });

  const cancelMutation = useMutation({
    mutationFn: (orderId: string) => api.cancelOrder(portfolio.id, orderId),
    onSuccess: afterCancel,
  });

  const acknowledgeRiskMutation = useMutation({
    mutationFn: (isin: string) => api.acknowledgeRiskAlert(portfolio.id, isin),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["trading-state", portfolio.id] });
    },
  });

  const isPending =
    placeMutation.isPending || cancelMutation.isPending || acknowledgeRiskMutation.isPending;

  return {
    ...stateQuery,
    placeMutation,
    cancelMutation,
    acknowledgeRiskMutation,
    isPending,
    parseApiError,
  };
}

export type { Suggestion };
