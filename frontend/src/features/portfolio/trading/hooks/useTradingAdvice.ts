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

  const adviceQuery = useQuery({
    queryKey: ["trading-advice", portfolio.id],
    queryFn: () => api.getAdvice(portfolio.id),
    enabled,
    staleTime: STALE.tradingSync,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!enabled) return false;
      if (hasActiveOrders(query.state.data)) return 30_000;
      return false;
    },
  });

  const afterPlace = () => {
    void queryClient.invalidateQueries({ queryKey: ["trading-advice", portfolio.id] });
    invalidateAfterTradingMutation(queryClient, portfolio.id, {
      refreshPlan: true,
      refreshOperations: true,
    });
  };

  const afterCancel = () => {
    void queryClient.invalidateQueries({ queryKey: ["trading-advice", portfolio.id] });
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

  const isPending = placeMutation.isPending || cancelMutation.isPending;

  return {
    ...adviceQuery,
    placeMutation,
    cancelMutation,
    isPending,
    parseApiError,
  };
}

export type { Suggestion };
