import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Eye,
  Loader2,
  RefreshCw,
  ShoppingCart,
  Sparkles,
  XCircle,
} from "lucide-react";
import { api } from "@/api/client";
import type { DeploySessionItemStatus, Portfolio, Suggestion, TradingAdviceResponse } from "@/api/types";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import { STALE } from "@/features/portfolio/hooks/queryConfig";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useDeploySession } from "@/features/portfolio/trading/hooks/useDeploySession";
import { cn, formatDate, formatRub } from "@/lib/utils";
import { ANALYTICAL_INFO_SHORT } from "@/features/portfolio/labels";
import { ConfirmOrderDialog } from "@/features/portfolio/trading/ConfirmOrderDialog";
import {
  ActiveOrderCard,
  AdvisorySection,
  groupSuggestions,
  SuggestionCard,
} from "@/features/portfolio/trading/OperationGroups";
import { useTradingMutations } from "@/features/portfolio/trading/hooks/useTradingAdvice";
import { ApiError } from "@/api/client";
import { SandboxPayInPanel } from "@/features/portfolio/trading/TopUpBatchCard";

interface Props {
  portfolio: Portfolio;
  suggestionConfirmId?: string | null;
  advice: TradingAdviceResponse | undefined;
  adviceLoading: boolean;
  adviceFetching: boolean;
  adviceError: boolean;
  adviceErrorDetail: Error | null;
  refetchAdvice: () => void;
  adviceUpdatedAt: number;
  rateScenario: string;
}

function ReadOnlyTokenBanner() {
  return (
    <div
      className="rounded-lg border border-amber-400/50 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100"
      data-testid="readonly-token-banner"
    >
      Ключ только для чтения — заявки недоступны. Мониторинг и аналитические сигналы
      работают. Чтобы выставлять заявки, сохраните full-access токен в{" "}
      <Link to="/account" className="underline underline-offset-2">
        кабинете
      </Link>
      .
    </div>
  );
}

export function TradingActionQueue({
  portfolio,
  suggestionConfirmId,
  advice: data,
  adviceLoading: isLoading,
  adviceFetching: isFetching,
  adviceError: isError,
  adviceErrorDetail: error,
  refetchAdvice: refetch,
  adviceUpdatedAt: dataUpdatedAt,
  rateScenario,
}: Props) {
  const [confirmSuggestion, setConfirmSuggestion] = useState<Suggestion | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [createPlanError, setCreatePlanError] = useState<string | null>(null);
  const [detailSecid, setDetailSecid] = useState<string | null>(null);
  const isProduction = portfolio.account_kind === "production";

  const { data: bondsData } = useQuery({
    queryKey: ["bonds"],
    queryFn: () => api.getBonds({ export: true }),
    staleTime: STALE.bonds,
    refetchOnWindowFocus: false,
  });

  const secidByIsin = useMemo(() => {
    const map = new Map<string, string>();
    for (const bond of bondsData?.bonds ?? []) {
      map.set(bond.isin, bond.secid);
    }
    for (const position of portfolio.data?.positions ?? []) {
      if (position.secid && !map.has(position.isin)) {
        map.set(position.isin, position.secid);
      }
    }
    return map;
  }, [bondsData?.bonds, portfolio.data?.positions]);

  const {
    placeMutation,
    cancelMutation,
    isPending,
    parseApiError,
    acknowledgeRiskMutation,
  } = useTradingMutations(portfolio.id, rateScenario);

  const {
    createMutation,
    refreshMutation,
    cancelMutation: cancelDeployMutation,
    skipItemMutation,
    isPending: isDeployPending,
  } = useDeploySession(portfolio.id, rateScenario);

  const isPlanSyncing = isFetching || placeMutation.isPending || isDeployPending;

  const suggestions = data?.suggestions ?? [];
  const deploySession = data?.deploy_session ?? null;
  const canPlaceOrders = data?.can_place_orders !== false;
  const ordersDisabled = !canPlaceOrders;
  const sessionItemStatusById = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of deploySession?.items ?? []) {
      map.set(item.id, item.status);
    }
    return map;
  }, [deploySession?.items]);
  const groups = useMemo(() => groupSuggestions(suggestions), [suggestions]);
  const activeOrders = data?.active_orders ?? [];

  const urgentCount = groups.urgent.length;

  useEffect(() => {
    if (!suggestionConfirmId || !suggestions.length || ordersDisabled) return;
    const target = suggestions.find((s) => s.id === suggestionConfirmId);
    if (!target) return;
    document.getElementById(`suggestion-${target.id}`)?.scrollIntoView({ behavior: "smooth" });
    if (target.kind !== "put_offer_reminder") {
      setConfirmSuggestion(target);
    }
  }, [suggestionConfirmId, suggestions, ordersDisabled]);

  const adviceTime = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : null;

  const sandboxPayInPanel = !isProduction ? (
    <SandboxPayInPanel
      portfolioId={portfolio.id}
      rateScenario={rateScenario}
      onSuccess={() => void refetch()}
      disabled={isPlanSyncing}
      deploySessionActive={Boolean(deploySession)}
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
          {parseApiError(error ?? new Error("Не удалось загрузить очередь действий"))}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => refetch()}
          disabled={isPlanSyncing}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isPlanSyncing && "animate-spin")} />
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
        {ordersDisabled && <ReadOnlyTokenBanner />}
        <div className="flex items-center justify-between gap-3">
          <span className="text-green-800 dark:text-green-300">
            Расчётных вариантов нет — по текущим параметрам стратегии действий нет
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-muted-foreground"
            onClick={() => refetch()}
            disabled={isPlanSyncing}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isPlanSyncing && "animate-spin")} />
            Обновить
          </Button>
        </div>
        {sandboxPayInPanel}
      </div>
    );
  }

  const freeCash = data?.available_money_rub ?? data?.money_rub ?? portfolio.cash_balance_rub;
  const buySuggestions = groups.buys;
  const canFreezePlan =
    !ordersDisabled &&
    !deploySession &&
    buySuggestions.length > 0 &&
    (groups.buys.some((s) => s.kind === "buy") || groups.buys.some((s) => s.kind === "reinvest"));
  const planDoneCount =
    (deploySession?.progress.filled ?? 0) +
    (deploySession?.progress.skipped ?? 0) +
    (deploySession?.progress.stale ?? 0);

  return (
    <>
      <div className="space-y-4 rounded-xl border border-amber-400/40 bg-amber-500/5 p-4">
        {ordersDisabled && <ReadOnlyTokenBanner />}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="space-y-0.5">
            <p className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
              <Sparkles className="h-4 w-4" />
              Очередь действий
              {urgentCount > 0 && (
                <Badge className="bg-amber-500/20 text-amber-900 dark:text-amber-200">
                  {urgentCount} срочных
                </Badge>
              )}
            </p>
            <p className="text-xs text-muted-foreground">{ANALYTICAL_INFO_SHORT}</p>
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
            disabled={isPlanSyncing}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isPlanSyncing && "animate-spin")} />
            Обновить счёт
          </Button>
        </div>

        {freeCash > 0 && buySuggestions.length > 0 && !deploySession && (
          <div className="rounded-lg border border-blue-400/40 bg-blue-500/10 px-3 py-2 text-sm text-blue-900 dark:text-blue-200">
            Свободный кэш {formatRub(freeCash)} — алгоритмический отбор кандидатов:{" "}
            {buySuggestions.map((s) => s.name).join(", ")}
          </div>
        )}

        {canFreezePlan && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                data-testid="freeze-deploy-plan"
                disabled={isPlanSyncing || createMutation.isPending}
                onClick={() => {
                  setCreatePlanError(null);
                  createMutation.mutate(undefined, {
                    onError: (err: Error) => {
                      if (err instanceof ApiError && err.status === 409) {
                        setCreatePlanError(
                          "Есть незавершённый план — завершите покупки, обновите или отмените текущий план.",
                        );
                        return;
                      }
                      setCreatePlanError(parseApiError(err));
                    },
                  });
                }}
              >
                Зафиксировать план
              </Button>
              <p className="text-xs text-muted-foreground">
                Закрепить текущие расчётные варианты докупки и реинвестиций на время исполнения
              </p>
            </div>
            {createPlanError && (
              <p className="text-xs text-amber-900 dark:text-amber-100" data-testid="deploy-session-conflict">
                {createPlanError}
              </p>
            )}
          </div>
        )}

        {deploySession && (
          <div
            className={cn(
              "relative space-y-2 rounded-lg border border-violet-400/40 bg-violet-500/10 px-3 py-2 text-sm",
              isPlanSyncing && "pointer-events-none opacity-60",
            )}
            data-testid="deploy-session-banner"
          >
            {isPlanSyncing && (
              <div className="absolute right-3 top-3">
                <Loader2 className="h-4 w-4 animate-spin text-violet-800 dark:text-violet-200" />
              </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-medium text-violet-950 dark:text-violet-100">
                План закупки зафиксирован · {planDoneCount}/{deploySession.progress.total}{" "}
                выполнено
              </p>
              <p className="text-xs text-muted-foreground">
                истекает {formatDate(deploySession.expires_at.slice(0, 10))}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="refresh-deploy-plan"
                disabled={isPlanSyncing || refreshMutation.isPending || ordersDisabled}
                onClick={() => refreshMutation.mutate(deploySession.id)}
              >
                Обновить план
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="cancel-deploy-plan"
                disabled={isPlanSyncing || cancelDeployMutation.isPending}
                onClick={() => cancelDeployMutation.mutate(deploySession.id)}
              >
                Отменить план
              </Button>
            </div>
            {deploySession.warnings.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-amber-900 dark:text-amber-100">
                {deploySession.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
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
              ordersDisabled={ordersDisabled}
              onAcknowledgeRisk={
                s.risk_acknowledgeable
                  ? (item) => acknowledgeRiskMutation.mutate(item.isin)
                  : undefined
              }
              onConfirm={(item) => {
                setConfirmError(null);
                setConfirmSuggestion(item);
              }}
            />
          ))}
        </AdvisorySection>

        <AdvisorySection
          title="На контроле"
          icon={<Eye className="h-3.5 w-3.5" />}
          count={groups.watch.length}
        >
          {groups.watch.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              isProduction={isProduction}
              isPending={isPending}
              ordersDisabled={ordersDisabled}
              onConfirm={() => undefined}
            />
          ))}
        </AdvisorySection>

        {!deploySession && buySuggestions.length > 0 && !ordersDisabled && (
          <p className="text-xs text-muted-foreground" data-testid="freeze-plan-required-hint">
            Докупка и реинвестиции доступны только после фиксации плана закупки.
          </p>
        )}

        <div
          className={cn(
            deploySession && isPlanSyncing && "pointer-events-none opacity-60",
          )}
        >
        <AdvisorySection
          title={deploySession ? "План закупки" : "Покупки"}
          icon={<ShoppingCart className="h-3.5 w-3.5" />}
          count={groups.buys.length}
        >
          {deploySession && isPlanSyncing && (
            <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Обновляем план закупки…
            </p>
          )}
          {groups.buys.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              isProduction={isProduction}
              isPending={isPending || isPlanSyncing}
              ordersDisabled={ordersDisabled}
              buyRequiresFrozenPlan={!deploySession}
              sessionStatus={sessionItemStatusById.get(s.id) as DeploySessionItemStatus | undefined}
              onSkip={
                deploySession
                  ? (item) =>
                      skipItemMutation.mutate({
                        sessionId: deploySession.id,
                        itemId: item.id,
                      })
                  : undefined
              }
              onOpenDetail={() => {
                const secid = secidByIsin.get(s.isin);
                if (secid) setDetailSecid(secid);
              }}
              onConfirm={(item) => {
                setConfirmError(null);
                setConfirmSuggestion(item);
              }}
            />
          ))}
        </AdvisorySection>
        </div>

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
              cancelDisabled={ordersDisabled}
              onCancel={(o) => cancelMutation.mutate(o.order_id)}
            />
          ))}
        </AdvisorySection>

        {sandboxPayInPanel}
      </div>

      <BondDetailSheet secid={detailSecid} onClose={() => setDetailSecid(null)} />

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
