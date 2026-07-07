import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { PendingOperation, Portfolio, TradingSyncResponse } from "@/api/types";
import { invalidateAfterTradingMutation } from "@/features/portfolio/hooks/invalidatePortfolio";
import { STALE } from "@/features/portfolio/hooks/queryConfig";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";

function needsPolling(ops: PendingOperation[]) {
  return ops.some(
    (op) =>
      op.status === "in_progress" ||
      op.status === "action_required" ||
      op.status === "overdue",
  );
}

export function useTradingSync(portfolio: Portfolio) {
  const queryClient = useQueryClient();
  const enabled = portfolio.mode === "trading" && Boolean(portfolio.account_id);

  const syncQuery = useQuery({
    queryKey: ["trading-sync", portfolio.id],
    queryFn: () => api.syncPortfolio(portfolio.id),
    enabled,
    staleTime: STALE.tradingSync,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!enabled) return false;
      const ops = query.state.data?.pending_operations ?? [];
      if (needsPolling(ops)) return 30_000;
      return false;
    },
  });

  const afterMutation = (
    data: TradingSyncResponse,
    options?: { refreshPlan?: boolean; refreshOperations?: boolean },
  ) => {
    queryClient.setQueryData(["trading-sync", portfolio.id], data);
    invalidateAfterTradingMutation(queryClient, portfolio.id, options);
  };

  const confirmMutation = useMutation({
    mutationFn: ({ opId, lots, pricePct }: { opId: string; lots: number; pricePct: number }) =>
      api.confirmPendingOperation(portfolio.id, opId, { lots, price_pct: pricePct }),
    onSuccess: (data) =>
      afterMutation(data, { refreshPlan: true, refreshOperations: true }),
  });

  const cancelMutation = useMutation({
    mutationFn: (opId: string) => api.cancelPendingOrder(portfolio.id, opId),
    onSuccess: (data) => afterMutation(data),
  });

  const cancelBatchMutation = useMutation({
    mutationFn: (batchId: string) => api.cancelTopUpBatch(portfolio.id, batchId),
    onSuccess: (data) => afterMutation(data),
  });

  const putOfferMutation = useMutation({
    mutationFn: ({ isin, decision }: { isin: string; decision: "exercise" | "hold" }) =>
      api.setPutOfferDecision(portfolio.id, isin, decision),
    onSuccess: (data) => afterMutation(data, { refreshPlan: true }),
  });

  const dismissMutation = useMutation({
    mutationFn: (opId: string) => api.dismissManualSell(portfolio.id, opId),
    onSuccess: (data) => afterMutation(data),
  });

  const isPending =
    confirmMutation.isPending ||
    cancelMutation.isPending ||
    cancelBatchMutation.isPending ||
    putOfferMutation.isPending ||
    dismissMutation.isPending;

  return {
    ...syncQuery,
    confirmMutation,
    cancelMutation,
    cancelBatchMutation,
    putOfferMutation,
    dismissMutation,
    isPending,
    parseApiError,
  };
}
