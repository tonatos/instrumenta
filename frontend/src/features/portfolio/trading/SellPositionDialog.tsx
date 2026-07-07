import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import type { PortfolioPosition } from "@/api/types";
import { invalidateAfterTradingMutation } from "@/features/portfolio/hooks/invalidatePortfolio";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";
import { useSellQuote } from "@/features/portfolio/trading/hooks/useSellQuote";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatPct } from "@/lib/utils";

export function SellPositionDialog({
  position,
  portfolioId,
  open,
  onOpenChange,
}: {
  position: PortfolioPosition | null;
  portfolioId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [lots, setLots] = useState(1);
  const [pricePct, setPricePct] = useState("");
  const parsedPricePct = parseFloat(pricePct);

  const { quote, loading: quoteLoading, error: quoteError } = useSellQuote({
    open,
    portfolioId,
    isin: position?.isin ?? null,
  });

  useEffect(() => {
    if (position) {
      setLots(position.actual_lots ?? 1);
      setPricePct("");
    }
  }, [position]);

  useEffect(() => {
    if (quote && open && pricePct === "") {
      setPricePct(quote.suggested_price_pct.toFixed(4));
    }
  }, [quote, open, pricePct]);

  const sellMutation = useMutation({
    mutationFn: ({ lots: sellLots, pricePct: sellPrice }: { lots: number; pricePct: number }) =>
      api.queueManualSell(portfolioId, position!.isin, {
        lots: sellLots,
        price_pct: sellPrice,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["trading-sync", portfolioId], data);
      invalidateAfterTradingMutation(queryClient, portfolioId);
      onOpenChange(false);
    },
  });

  if (!position) return null;

  const lotSize = position.lot_size ?? 1;
  const maxLots = position.actual_lots ?? 0;
  const suggestedPrice = quote?.suggested_price_pct;
  const insufficientLots = lots > maxLots;

  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Поставить продажу в очередь</DialogTitle>
          <DialogDescription>
            {position.name} · на счёте {maxLots} лот(а). Стоимость и комиссию
            покажем при подтверждении в очереди действий.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <p className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            Лимитная заявка по{" "}
            <span className="font-medium text-foreground">чистой</span> цене — % от
            номинала бумаги (не рубли). По умолчанию рынок
            {quote ? ` ${formatPct(quote.market_price_pct)}` : ""} −{" "}
            {quote?.sell_buffer_label ?? "0.5%"}.
          </p>

          {quoteLoading && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Загружаем рыночную цену…
            </p>
          )}
          {quoteError && (
            <p className="text-xs text-destructive">{quoteError}</p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                Лоты
              </label>
              <Input
                type="number"
                min={1}
                max={maxLots}
                value={lots}
                onChange={(e) =>
                  setLots(
                    Math.min(
                      maxLots,
                      Math.max(1, Number(e.target.value)),
                    ),
                  )
                }
                data-testid="sell-lots-input"
              />
              {lotSize > 1 && (
                <p className="mt-1 text-xs text-muted-foreground">
                  1 лот = {lotSize} бумаг · всего {lots * lotSize} шт
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                Лимит (чистая цена), %
              </label>
              <Input
                type="number"
                step="0.01"
                min={0}
                value={pricePct}
                onChange={(e) => setPricePct(e.target.value)}
                data-testid="sell-price-input"
              />
            </div>
          </div>

          {suggestedPrice != null && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => setPricePct(suggestedPrice.toFixed(4))}
            >
              Сбросить к рекомендуемой ({suggestedPrice.toFixed(4)}%)
            </Button>
          )}

          {insufficientLots && (
            <p className="flex items-start gap-1.5 text-sm text-amber-800 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              На счёте недостаточно лотов для продажи ({maxLots} доступно).
            </p>
          )}

          {sellMutation.isError && (
            <p className="text-sm text-destructive">
              {parseApiError(sellMutation.error as Error)}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={sellMutation.isPending}
          >
            Отмена
          </Button>
          <Button
            data-testid="sell-position-submit"
            onClick={() =>
              sellMutation.mutate({ lots, pricePct: parseFloat(pricePct) })
            }
            disabled={
              sellMutation.isPending ||
              quoteLoading ||
              !pricePct ||
              Number.isNaN(parsedPricePct) ||
              lots > maxLots ||
              lots <= 0
            }
          >
            {sellMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Поставить SELL
          </Button>
        </DialogFooter>
      </DialogContent>
    </DialogRoot>
  );
}
