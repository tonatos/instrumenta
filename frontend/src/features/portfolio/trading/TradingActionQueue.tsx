import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  ShoppingCart,
  Tag,
  XCircle,
} from "lucide-react";
import type { PendingOperation, Portfolio } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatRub } from "@/lib/utils";
import { ConfirmOrderDialog } from "@/features/portfolio/trading/ConfirmOrderDialog";
import {
  groupOperations,
  OperationCard,
  OperationSection,
} from "@/features/portfolio/trading/OperationGroups";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";
import { useTradingSync } from "@/features/portfolio/trading/hooks/useTradingSync";
import { SandboxPayInPanel, TopUpBatchCard } from "@/features/portfolio/trading/TopUpBatchCard";

interface Props {
  portfolio: Portfolio;
  pendingConfirmId?: string | null;
}

export function TradingActionQueue({ portfolio, pendingConfirmId }: Props) {
  const [confirmOp, setConfirmOp] = useState<PendingOperation | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const isProduction = portfolio.account_kind === "production";

  const {
    data,
    isLoading,
    isError,
    error,
    isFetching,
    refetch,
    dataUpdatedAt,
    confirmMutation,
    cancelMutation,
    cancelBatchMutation,
    putOfferMutation,
    isPending,
  } = useTradingSync(portfolio);

  const ops = data?.pending_operations ?? [];
  const groups = useMemo(() => groupOperations(ops), [ops]);
  const topUpBatchIds = useMemo(
    () =>
      [
        ...new Set(
          ops
            .filter((op) => op.kind === "top_up_buy" && op.top_up_batch_id)
            .map((op) => op.top_up_batch_id as string),
        ),
      ],
    [ops],
  );

  const attentionCount = ops.filter(
    (op) => op.status === "action_required" || op.status === "overdue",
  ).length;

  const apiTradeWarnings = useMemo(
    () =>
      (data?.notes ?? []).filter((note) => note.includes("не торгуется через T-Invest API")),
    [data?.notes],
  );

  useEffect(() => {
    if (!pendingConfirmId || !ops.length) return;
    const target = ops.find((op) => op.id === pendingConfirmId);
    if (!target) return;
    document.getElementById(`pending-op-${target.id}`)?.scrollIntoView({ behavior: "smooth" });
    if (
      target.kind !== "put_offer_submit" &&
      target.status !== "blocked" &&
      target.status !== "in_progress"
    ) {
      setConfirmOp(target);
    }
  }, [pendingConfirmId, ops]);

  const syncTime = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : null;

  const renderCard = (op: PendingOperation) => (
    <OperationCard
      key={op.id}
      op={op}
      isProduction={isProduction}
      isPending={isPending}
      onConfirm={(o) => {
        setConfirmError(null);
        setConfirmOp(o);
      }}
      onCancel={(o) => cancelMutation.mutate(o.id)}
      onPutOffer={(o, decision) => putOfferMutation.mutate({ isin: o.isin, decision })}
    />
  );

  const sandboxPayInPanel = !isProduction ? (
    <SandboxPayInPanel
      portfolioId={portfolio.id}
      onSuccess={() => void refetch()}
      disabled={isFetching}
    />
  ) : null;

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-border p-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Синхронизация со счётом…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
        <span className="flex items-center gap-2 text-destructive">
          <XCircle className="h-4 w-4 shrink-0" />
          {parseApiError(error)}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          Повторить
        </Button>
      </div>
    );
  }

  const hasContent =
    ops.length > 0 || (data?.drifts?.length ?? 0) > 0 || apiTradeWarnings.length > 0;

  if (!hasContent) {
    return (
      <div className="space-y-3 rounded-xl border border-green-400/30 bg-green-500/5 px-4 py-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-green-800 dark:text-green-300">
            Очередь действий пуста — все операции выполнены
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-muted-foreground"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            Обновить
          </Button>
        </div>
        {sandboxPayInPanel}
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4 rounded-xl border border-amber-400/40 bg-amber-500/5 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="space-y-0.5">
            <p className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
              <Tag className="h-4 w-4" />
              Очередь действий
              {attentionCount > 0 && (
                <Badge className="bg-amber-500/20 text-amber-900 dark:text-amber-200">
                  {attentionCount} требуют внимания
                </Badge>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              На счёте {formatRub(data?.money_rub ?? portfolio.cash_balance_rub)}
              {syncTime && ` · обновлено ${syncTime}`}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            Обновить счёт
          </Button>
        </div>

        {data?.top_up_auto_applied && data.top_up_distributed_rub > 0 && (
          <div className="rounded-lg border border-blue-400/40 bg-blue-500/10 px-3 py-2 text-sm text-blue-900 dark:text-blue-200">
            Обнаружено пополнение {formatRub(data.top_up_distributed_rub)} — заявки на покупку
            добавлены в очередь
          </div>
        )}

        {apiTradeWarnings.length > 0 && (
          <div className="space-y-1 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100">
            <p className="font-medium">Позиции недоступны для покупки через API</p>
            <p className="text-xs text-amber-900/80 dark:text-amber-200/80">
              Они остались в плане до автосбора с фильтром «только API». Удалите вручную или
              пересоберите портфель.
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
              {apiTradeWarnings.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        )}

        {topUpBatchIds.map((batchId) => (
          <TopUpBatchCard
            key={batchId}
            batchId={batchId}
            onCancel={(id) => cancelBatchMutation.mutate(id)}
            isPending={cancelBatchMutation.isPending}
          />
        ))}

        <OperationSection title="Срочно" icon={<AlertTriangle className="h-3.5 w-3.5" />} ops={groups.urgent}>
          {groups.urgent.map(renderCard)}
        </OperationSection>

        <OperationSection title="Покупки" icon={<ShoppingCart className="h-3.5 w-3.5" />} ops={groups.buys}>
          {groups.buys.map(renderCard)}
        </OperationSection>

        <OperationSection title="Продажи" icon={<Tag className="h-3.5 w-3.5" />} ops={groups.sells}>
          {groups.sells.map(renderCard)}
        </OperationSection>

        {data?.drifts && data.drifts.length > 0 && (
          <div className="space-y-2 border-t border-border/60 pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Расхождения со счётом
            </p>
            {data.drifts.map((d) => (
              <div
                key={`${d.isin}-${d.name}`}
                className={cn(
                  "rounded-lg px-3 py-2 text-xs",
                  d.severity === "critical"
                    ? "bg-red-500/10 text-red-800 dark:text-red-300"
                    : "bg-muted/50 text-muted-foreground",
                )}
              >
                {d.message}
              </div>
            ))}
          </div>
        )}

        {sandboxPayInPanel}
      </div>

      <ConfirmOrderDialog
        op={confirmOp}
        portfolioId={portfolio.id}
        open={confirmOp !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmOp(null);
            setConfirmError(null);
          }
        }}
        isProduction={isProduction}
        isPending={confirmMutation.isPending}
        error={confirmError}
        onSubmit={(lots, pricePct) => {
          if (!confirmOp) return;
          confirmMutation.mutate(
            { opId: confirmOp.id, lots, pricePct },
            {
              onSuccess: () => {
                setConfirmOp(null);
                setConfirmError(null);
              },
              onError: (err: Error) => {
                setConfirmError(parseApiError(err));
              },
            },
          );
        }}
      />
    </>
  );
}
