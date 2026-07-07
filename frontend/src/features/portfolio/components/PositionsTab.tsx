import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";
import { api } from "@/api/client";
import type { Bond, PendingOperation, PortfolioPosition } from "@/api/types";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import { POSITION_STATUS_LABELS, SOURCE_LABELS } from "@/features/portfolio/labels";
import { SellPositionDialog } from "@/features/portfolio/trading/SellPositionDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";

const ACTIVE_SELL_STATUSES = new Set(["action_required", "in_progress"]);

function manualSellLabel(op: PendingOperation): string {
  if (op.status === "in_progress") {
    return `На бирже · ${op.lots} л.`;
  }
  return `В очереди · ${op.lots} л.`;
}

function manualSellHint(op: PendingOperation): string {
  if (op.status === "in_progress") {
    return "Заявка на продажу уже выставлена на бирже — отмените её в очереди действий";
  }
  return "Продажа в очереди — подтвердите или уберите в блоке «Очередь действий»";
}

export function PositionsTab({
  positions,
  portfolioId,
  isTrading,
  accountKind,
  bonds,
  closedPositionsCount,
}: {
  positions: PortfolioPosition[];
  portfolioId: string;
  isTrading: boolean;
  accountKind: string | null;
  bonds: Bond[];
  closedPositionsCount: number;
}) {
  const queryClient = useQueryClient();
  const [addLots, setAddLots] = useState(1);
  const [selectedIsin, setSelectedIsin] = useState<string | null>(null);
  const [detailSecid, setDetailSecid] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const [sellPosition, setSellPosition] = useState<PortfolioPosition | null>(null);

  const canSellInSandbox =
    isTrading && accountKind === "sandbox";

  const { data: tradingSync } = useQuery({
    queryKey: ["trading-sync", portfolioId],
    queryFn: () => api.syncPortfolio(portfolioId),
    enabled: canSellInSandbox,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const manualSellByIsin = useMemo(() => {
    const map = new Map<string, PendingOperation>();
    for (const op of tradingSync?.pending_operations ?? []) {
      if (op.kind !== "manual_sell" || !ACTIVE_SELL_STATUSES.has(op.status)) {
        continue;
      }
      map.set(op.isin, op);
    }
    return map;
  }, [tradingSync?.pending_operations]);

  const visiblePositions = useMemo(
    () => (showClosed ? positions : positions.filter((p) => p.status !== "closed")),
    [positions, showClosed],
  );
  const closedCount = closedPositionsCount;

  const removeMutation = useMutation({
    mutationFn: (isin: string) => api.removePosition(portfolioId, isin),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
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

  const bondsByIsin = useMemo(
    () => new Map(bonds.map((b) => [b.isin, b])),
    [bonds],
  );

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
      {isTrading && closedCount > 0 && (
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={showClosed}
            onChange={(e) => setShowClosed(e.target.checked)}
            data-testid="show-closed-positions"
          />
          Показать закрытые ({closedCount})
        </label>
      )}

      {visiblePositions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
          {positions.length > 0 && !showClosed
            ? "Нет активных позиций — включите «Показать закрытые»"
            : "Позиций нет — воспользуйтесь «Автосостав» или добавьте бумаги вручную"}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs" data-testid="positions-table">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Бумага</th>
                {isTrading && (
                  <th className="px-3 py-2 text-left font-semibold">Статус</th>
                )}
                <th className="px-3 py-2 text-right font-semibold">YTM</th>
                <th className="px-3 py-2 text-right font-semibold">Скор</th>
                <th className="px-3 py-2 text-right font-semibold">
                  {isTrading ? "Пл / Фк" : "Лотов"}
                </th>
                <th className="px-3 py-2 text-right font-semibold">Вложено</th>
                <th className="px-3 py-2 text-left font-semibold">Источник</th>
                <th className="px-3 py-2 text-left font-semibold">Погашение</th>
                {(canSellInSandbox || !isTrading) && <th className="w-20 px-2 py-2" />}
              </tr>
            </thead>
            <tbody>
              {visiblePositions.map((pos) => {
                const status = pos.status ?? "active";
                const bond = bondsByIsin.get(pos.isin);
                const manualSell = manualSellByIsin.get(pos.isin);
                const sellBlocked = manualSell != null;
                return (
                <tr
                  key={pos.isin}
                  data-testid={`position-row-${pos.isin}`}
                  data-status={status}
                  className={cn(
                    "cursor-pointer border-t border-border hover:bg-muted/20",
                    status === "closed" && "text-muted-foreground opacity-70",
                  )}
                  onClick={() => setDetailSecid(pos.secid)}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className={cn(
                        "max-w-[180px] truncate text-left font-medium hover:underline",
                        status === "closed" && "line-through",
                      )}
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailSecid(pos.secid);
                      }}
                    >
                      {pos.name}
                    </button>
                    <p className="text-muted-foreground">{pos.secid}</p>
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
                            {manualSell.status === "in_progress" ? "SELL на бирже" : "SELL в очереди"}
                          </Badge>
                        )}
                      </div>
                    </td>
                  )}
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
                        bond?.score != null && bond.score >= 60 ? "default" : "secondary"
                      }
                      className="font-mono text-[10px] font-normal"
                    >
                      {bond?.score != null ? Math.round(bond.score) : "—"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    {isTrading && pos.actual_lots != null ? (
                      <Tooltip
                        content={`Плановых: ${pos.lots} л. · Фактических: ${pos.actual_lots} л.`}
                      >
                        <span
                          className={cn(
                            "cursor-help",
                            pos.actual_lots !== pos.lots && "text-amber-600",
                          )}
                        >
                          {pos.lots}&nbsp;/&nbsp;{pos.actual_lots}
                        </span>
                      </Tooltip>
                    ) : (
                      `${pos.lots} л.`
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {formatRub(pos.purchase_amount_rub)}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {SOURCE_LABELS[pos.source] ?? pos.source}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {pos.offer_date
                      ? <span className="text-orange-600 dark:text-orange-400">{formatDate(pos.offer_date)} ⚡</span>
                      : formatDate(pos.maturity_date)}
                  </td>
                  {canSellInSandbox && (
                    <td className="px-2 py-2">
                      {(pos.actual_lots ?? 0) > 0 && pos.status !== "closed" && (
                        sellBlocked && manualSell ? (
                          <Tooltip content={manualSellHint(manualSell)}>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-7 max-w-[120px] truncate px-2 text-xs"
                              data-testid={`sell-position-${pos.isin}`}
                              disabled
                            >
                              {manualSellLabel(manualSell)}
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

      <BondDetailSheet secid={detailSecid} onClose={() => setDetailSecid(null)} />

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
