import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  ShoppingCart,
  Sparkles,
  XCircle,
} from "lucide-react";
import type { Portfolio, Suggestion } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatRub } from "@/lib/utils";
import { ConfirmOrderDialog } from "@/features/portfolio/trading/ConfirmOrderDialog";
import {
  ActiveOrderCard,
  AdvisorySection,
  groupSuggestions,
  SuggestionCard,
} from "@/features/portfolio/trading/OperationGroups";
import { useTradingAdvice } from "@/features/portfolio/trading/hooks/useTradingAdvice";
import { SandboxPayInPanel } from "@/features/portfolio/trading/TopUpBatchCard";

interface Props {
  portfolio: Portfolio;
  suggestionConfirmId?: string | null;
}

export function TradingActionQueue({ portfolio, suggestionConfirmId }: Props) {
  const [confirmSuggestion, setConfirmSuggestion] = useState<Suggestion | null>(null);
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
    placeMutation,
    cancelMutation,
    isPending,
    parseApiError,
  } = useTradingAdvice(portfolio);

  const suggestions = data?.suggestions ?? [];
  const groups = useMemo(() => groupSuggestions(suggestions), [suggestions]);
  const activeOrders = data?.active_orders ?? [];

  const urgentCount = groups.urgent.length;

  useEffect(() => {
    if (!suggestionConfirmId || !suggestions.length) return;
    const target = suggestions.find((s) => s.id === suggestionConfirmId);
    if (!target) return;
    document.getElementById(`suggestion-${target.id}`)?.scrollIntoView({ behavior: "smooth" });
    if (target.kind !== "put_offer_reminder") {
      setConfirmSuggestion(target);
    }
  }, [suggestionConfirmId, suggestions]);

  const adviceTime = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : null;

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
        Загружаем данные счёта…
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
    suggestions.length > 0 ||
    activeOrders.length > 0 ||
    (data?.warnings.length ?? 0) > 0;

  if (!hasContent) {
    return (
      <div className="space-y-3 rounded-xl border border-green-400/30 bg-green-500/5 px-4 py-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-green-800 dark:text-green-300">
            Рекомендаций нет — портфель в порядке
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

  const freeCash = data?.available_money_rub ?? data?.money_rub ?? portfolio.cash_balance_rub;
  const buySuggestions = groups.buys;

  return (
    <>
      <div className="space-y-4 rounded-xl border border-amber-400/40 bg-amber-500/5 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="space-y-0.5">
            <p className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
              <Sparkles className="h-4 w-4" />
              Советы по торговле
              {urgentCount > 0 && (
                <Badge className="bg-amber-500/20 text-amber-900 dark:text-amber-200">
                  {urgentCount} срочных
                </Badge>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              Свободно {formatRub(freeCash)}
              {(data?.blocked_money_rub ?? 0) > 0 &&
                ` · заблокировано ${formatRub(data!.blocked_money_rub)}`}
              {adviceTime && ` · обновлено ${adviceTime}`}
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

        {freeCash > 0 && buySuggestions.length > 0 && (
          <div className="rounded-lg border border-blue-400/40 bg-blue-500/10 px-3 py-2 text-sm text-blue-900 dark:text-blue-200">
            Свободный кэш {formatRub(freeCash)} — рекомендуем:{" "}
            {buySuggestions.map((s) => s.name).join(", ")}
          </div>
        )}

        {(data?.warnings.length ?? 0) > 0 && (
          <div className="space-y-1 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100">
            <p className="font-medium">Предупреждения</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
              {data!.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}

        <AdvisorySection
          title="Срочно"
          icon={<AlertTriangle className="h-3.5 w-3.5" />}
          count={groups.urgent.length}
        >
          {groups.urgent.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              isProduction={isProduction}
              isPending={isPending}
              onConfirm={(item) => {
                setConfirmError(null);
                setConfirmSuggestion(item);
              }}
            />
          ))}
        </AdvisorySection>

        <AdvisorySection
          title="Покупки"
          icon={<ShoppingCart className="h-3.5 w-3.5" />}
          count={groups.buys.length}
        >
          {groups.buys.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              isProduction={isProduction}
              isPending={isPending}
              onConfirm={(item) => {
                setConfirmError(null);
                setConfirmSuggestion(item);
              }}
            />
          ))}
        </AdvisorySection>

        <AdvisorySection
          title="Активные заявки"
          icon={<Sparkles className="h-3.5 w-3.5" />}
          count={activeOrders.length}
        >
          {activeOrders.map((order) => (
            <ActiveOrderCard
              key={order.order_id}
              order={order}
              isPending={isPending}
              onCancel={(o) => cancelMutation.mutate(o.order_id)}
            />
          ))}
        </AdvisorySection>

        {sandboxPayInPanel}
      </div>

      <ConfirmOrderDialog
        suggestion={confirmSuggestion}
        portfolioId={portfolio.id}
        open={confirmSuggestion !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmSuggestion(null);
            setConfirmError(null);
          }
        }}
        isProduction={isProduction}
        isPending={placeMutation.isPending}
        error={confirmError}
        onSubmit={(lots, pricePct) => {
          if (!confirmSuggestion) return;
          const direction =
            confirmSuggestion.kind === "sell" ? "SELL" : "BUY";
          placeMutation.mutate(
            {
              isin: confirmSuggestion.isin,
              direction,
              lots,
              price_pct: pricePct,
              figi: confirmSuggestion.figi,
              suggestion_id: confirmSuggestion.id,
            },
            {
              onSuccess: () => {
                setConfirmSuggestion(null);
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
