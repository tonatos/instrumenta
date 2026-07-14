import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";
import { api } from "@/api/client";
import type { Bond, PortfolioPosition, PutOfferDecision, TradingAdviceResponse } from "@/api/types";
import { bondScoreForProfile, type BondRiskProfile } from "@/features/bonds/bondScore";
import { sectorLabel } from "@/features/bonds/sectorLabels";
import { isMarketSignal } from "@/features/portfolio/marketSignals";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import {
  OFFER_WINDOW_STATUS_LABELS,
  POSITION_STATUS_LABELS,
  PUT_OFFER_DECISION_LABELS,
  SOURCE_LABELS,
} from "@/features/portfolio/labels";
import { SellPositionDialog } from "@/features/portfolio/trading/SellPositionDialog";
import { resolveVisiblePositions } from "@/features/portfolio/trading/buildTradingDisplayPositions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";
const ACTIVE_ORDER_STATUSES = new Set([
  "EXECUTION_REPORT_STATUS_NEW",
  "EXECUTION_REPORT_STATUS_PARTIALLYFILL",
  "EXECUTION_REPORT_STATUS_PENDING_CANCEL",
]);

export function PositionsTab({
  positions,
  portfolioId,
  isTrading,
  accountKind: _accountKind,
  bonds,
  riskProfile = "normal",
  closedPositionsCount: _closedPositionsCount,
  tradingAdvice,
  adviceLoading = false,
}: {
  positions: PortfolioPosition[];
  portfolioId: string;
  isTrading: boolean;
  accountKind: string | null;
  bonds: Bond[];
  riskProfile?: BondRiskProfile;
  closedPositionsCount: number;
  tradingAdvice?: TradingAdviceResponse;
  adviceLoading?: boolean;
}) {
  const queryClient = useQueryClient();
  const [addLots, setAddLots] = useState(1);
  const [selectedIsin, setSelectedIsin] = useState<string | null>(null);
  const [detailSecid, setDetailSecid] = useState<string | null>(null);
  const [detailIsin, setDetailIsin] = useState<string | null>(null);
  const [sellPosition, setSellPosition] = useState<PortfolioPosition | null>(null);

  const canSellInTrading = isTrading;

  const activeSellByFigi = useMemo(() => {
    const map = new Map<string, { lots: number; onExchange: boolean }>();
    for (const order of tradingAdvice?.active_orders ?? []) {
      if (order.direction !== "SELL" || !ACTIVE_ORDER_STATUSES.has(order.status)) {
        continue;
      }
      map.set(order.figi, {
        lots: order.lots_requested,
        onExchange: true,
      });
    }
    return map;
  }, [tradingAdvice?.active_orders]);

  const holdingsByIsin = useMemo(() => {
    const map = new Map<string, number>();
    for (const holding of tradingAdvice?.holdings ?? []) {
      map.set(holding.isin, holding.lots);
    }
    return map;
  }, [tradingAdvice?.holdings]);

  const bondsByIsin = useMemo(
    () => new Map(bonds.map((b) => [b.isin, b])),
    [bonds],
  );

  const { data: notificationsData } = useQuery({
    queryKey: ["notifications", portfolioId],
    queryFn: () => api.getNotifications(portfolioId),
    enabled: Boolean(portfolioId),
    refetchInterval: 60_000,
  });

  const signalsByIsin = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const n of notificationsData?.notifications ?? []) {
      if (!isMarketSignal(n)) continue;
      const isin = typeof n.payload?.isin === "string" ? n.payload.isin : "";
      if (!isin) continue;
      const list = map.get(isin) ?? [];
      list.push(n.kind);
      map.set(isin, list);
    }
    return map;
  }, [notificationsData?.notifications]);

  const visiblePositions = useMemo(() => {
    if (isTrading && (adviceLoading || !tradingAdvice)) {
      return positions;
    }
    return resolveVisiblePositions(positions, isTrading, bondsByIsin, tradingAdvice);
  }, [isTrading, positions, tradingAdvice, adviceLoading, bondsByIsin]);

  const removeMutation = useMutation({
    mutationFn: (isin: string) => api.removePosition(portfolioId, isin),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
    },
  });

  const putOfferDecisionMutation = useMutation({
    mutationFn: ({ isin, decision }: { isin: string; decision: PutOfferDecision }) =>
      api.setPutOfferDecision(portfolioId, isin, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
      queryClient.invalidateQueries({ queryKey: ["trading-advice", portfolioId] });
      queryClient.invalidateQueries({ queryKey: ["trading-state", portfolioId] });
    },
  });

  const addMutation = useMutation({
    mutationFn: (isin: string) => api.addPosition(portfolioId, { isin, lots: addLots }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
      setSelectedIsin(null);
    },
  });

  const bondOptions: ComboboxOption[] = bonds.map((b) => ({
    value: b.isin,
    label: b.name,
    description: [
      b.ytm_net != null ? `YTM ${b.ytm_net.toFixed(2)}%` : null,
      b.credit_rating ?? null,
    ]
      .filter(Boolean)
      .join(" · "),
  }));

  return (
    <div className="space-y-4">
      {visiblePositions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
          Позиций нет — воспользуйтесь «Автосостав» или добавьте бумаги вручную
        </p>
      ) : (
        <div className="space-y-3">
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-xs" data-testid="positions-table">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">Бумага</th>
                  {isTrading && (
                    <th className="px-3 py-2 text-left font-semibold">Статус</th>
                  )}
                  <th className="px-3 py-2 text-left font-semibold">Сектор</th>
                  <th className="px-3 py-2 text-left font-semibold">Сигнал</th>
                  <th className="px-3 py-2 text-right font-semibold">YTM</th>
                  <th className="px-3 py-2 text-right font-semibold">Скор</th>
                  <th className="px-3 py-2 text-right font-semibold">Лотов</th>
                  <th className="px-3 py-2 text-right font-semibold">Вложено</th>
                  <th className="px-3 py-2 text-left font-semibold">Источник</th>
                  <th className="px-3 py-2 text-left font-semibold">Погашение</th>
                  {(canSellInTrading || !isTrading) && <th className="w-20 px-2 py-2" />}
                </tr>
              </thead>
              <tbody>
                {visiblePositions.map((pos) => {
                const status = pos.status ?? "active";
                const bond = bondsByIsin.get(pos.isin);
                const profileScore = bond ? bondScoreForProfile(bond, riskProfile) : null;
                const detailId = bond?.secid ?? pos.isin;
                const manualSell = pos.figi ? activeSellByFigi.get(pos.figi) : undefined;
                const sellBlocked = manualSell != null;
                const sector = bond?.sector?.trim();
                const signals = signalsByIsin.get(pos.isin) ?? [];
                return (
                <tr
                  key={pos.isin}
                  data-testid={`position-row-${pos.isin}`}
                  data-status={status}
                  className={cn(
                    "cursor-pointer border-t border-border hover:bg-muted/20",
                  )}
                  onClick={() => {
                    setDetailSecid(detailId);
                    setDetailIsin(pos.isin);
                  }}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="max-w-[180px] truncate text-left font-medium hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailSecid(detailId);
                        setDetailIsin(pos.isin);
                      }}
                    >
                      {pos.name}
                    </button>
                    <p className="text-muted-foreground">{detailId}</p>
                  </td>
                  {isTrading && (
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap items-center gap-1">
                        <Badge
                          variant={
                            status === "active"
                              ? "default"
                              : status === "pending"
                                ? "secondary"
                                : status === "drift"
                                  ? "destructive"
                                  : "outline"
                          }
                          className="text-[10px] font-normal"
                        >
                          {POSITION_STATUS_LABELS[status] ?? status}
                        </Badge>
                        {manualSell && (
                          <Badge
                            variant="secondary"
                            className="text-[10px] font-normal"
                            data-testid={`sell-pending-badge-${pos.isin}`}
                          >
                            SELL на бирже
                          </Badge>
                        )}
                      </div>
                    </td>
                  )}
                  <td className="max-w-[160px] px-3 py-2">
                    <span className={cn("block truncate", !sector && "text-muted-foreground")}>
                      {sectorLabel(sector)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {signals.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {signals.slice(0, 2).map((k) => (
                          <Badge key={k} variant="secondary" className="text-[10px] font-normal">
                            {k === "turbo_entry" ? "Turbo" : k === "sector_stress" ? "Сектор" : "Спред"}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td
                    className="whitespace-nowrap px-3 py-2 text-right font-mono"
                    data-testid={`position-ytm-${pos.isin}`}
                  >
                    {formatPct(bond?.ytm_net)}
                  </td>
                  <td
                    className="px-3 py-2 text-right"
                    data-testid={`position-score-${pos.isin}`}
                  >
                    <Badge
                      variant={
                        profileScore != null && profileScore >= 60 ? "default" : "secondary"
                      }
                      className="font-mono text-[10px] font-normal"
                    >
                      {profileScore != null ? Math.round(profileScore) : "—"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    {`${pos.lots} л.`}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {formatRub(pos.purchase_amount_rub)}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {SOURCE_LABELS[pos.source] ?? pos.source}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    <div className="space-y-1">
                      {pos.offer_date ? (
                        <>
                          <span className="text-orange-600 dark:text-orange-400">
                            {formatDate(pos.offer_date)} ⚡
                          </span>
                          {pos.offer_window_status && (
                            <Badge variant="outline" className="block w-fit text-[10px] font-normal">
                              {OFFER_WINDOW_STATUS_LABELS[pos.offer_window_status] ??
                                pos.offer_window_status}
                            </Badge>
                          )}
                          {(pos.offer_window_status === "open" ||
                            pos.put_offer_decision === "exercise" ||
                            pos.put_offer_decision === "hold") && (
                            <div className="flex flex-wrap gap-1 pt-1">
                              {(["exercise", "hold"] as const).map((decision) => (
                                <Button
                                  key={decision}
                                  type="button"
                                  size="sm"
                                  variant={
                                    pos.put_offer_decision === decision ? "default" : "outline"
                                  }
                                  className="h-6 px-2 text-[10px]"
                                  disabled={putOfferDecisionMutation.isPending}
                                  data-testid={`put-offer-${decision}-${pos.isin}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    putOfferDecisionMutation.mutate({ isin: pos.isin, decision });
                                  }}
                                >
                                  {PUT_OFFER_DECISION_LABELS[decision]}
                                </Button>
                              ))}
                            </div>
                          )}
                        </>
                      ) : (
                        formatDate(pos.maturity_date)
                      )}
                    </div>
                  </td>
                  {canSellInTrading && (
                    <td className="px-2 py-2">
                      {(holdingsByIsin.get(pos.isin) ?? 0) > 0 && (
                        sellBlocked && manualSell ? (
                          <Tooltip content="Заявка на продажу уже на бирже — отмените в блоке «Советы по торговле»">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-7 max-w-[120px] truncate px-2 text-xs"
                              data-testid={`sell-position-${pos.isin}`}
                              disabled
                            >
                              На бирже · {manualSell.lots} л.
                            </Button>
                          </Tooltip>
                        ) : (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 px-2 text-xs"
                            data-testid={`sell-position-${pos.isin}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSellPosition(pos);
                            }}
                          >
                            Продать
                          </Button>
                        )
                      )}
                    </td>
                  )}
                  {!isTrading && (
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        className="rounded p-1 text-muted-foreground/50 transition-colors hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeMutation.mutate(pos.isin);
                        }}
                        disabled={removeMutation.isPending}
                        title="Убрать позицию"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  )}
                </tr>
                );
              })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!isTrading && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border bg-muted/20 p-3">
          <div className="min-w-[200px] flex-1">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Добавить бумагу</p>
            <Combobox
              options={bondOptions}
              value={selectedIsin}
              onChange={setSelectedIsin}
              placeholder="Найти по названию или ISIN…"
              searchPlaceholder="Поиск…"
            />
          </div>
          <div className="w-24">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Лотов</p>
            <Input
              type="number"
              min={1}
              value={addLots}
              onChange={(e) => setAddLots(Math.max(1, Number(e.target.value)))}
              className="h-9 text-sm"
            />
          </div>
          <Button
            size="sm"
            className="h-9"
            onClick={() => { if (selectedIsin) addMutation.mutate(selectedIsin); }}
            disabled={!selectedIsin || addMutation.isPending}
          >
            {addMutation.isPending
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Plus className="h-4 w-4" />}
          </Button>
        </div>
      )}

      <BondDetailSheet
        secid={detailSecid}
        riskProfile={riskProfile}
        portfolioId={portfolioId}
        isin={detailIsin}
        onClose={() => {
          setDetailSecid(null);
          setDetailIsin(null);
        }}
      />

      <SellPositionDialog
        position={sellPosition}
        portfolioId={portfolioId}
        open={sellPosition != null}
        onOpenChange={(open) => {
          if (!open) setSellPosition(null);
        }}
      />
    </div>
  );
}
