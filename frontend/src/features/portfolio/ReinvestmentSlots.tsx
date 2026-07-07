import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import type { Bond, PortfolioPosition, ReinvestmentSlot } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { cn, formatRub } from "@/lib/utils";

interface Props {
  portfolioId: string;
  slots: ReinvestmentSlot[];
  positions: PortfolioPosition[];
  bonds: Bond[];
}

const TRIGGER_LABELS: Record<string, string> = {
  maturity: "Погашение",
  put_offer: "Пут-оферта",
  coupon_cash: "Купонный кэш",
};

function SlotCard({
  slot,
  idx,
  sourceName,
  bondOptions,
  onOverride,
  onReset,
  isPending,
}: {
  slot: ReinvestmentSlot;
  idx: number;
  sourceName: string | null;
  bondOptions: ComboboxOption[];
  onOverride: (isin: string | null) => void;
  onReset: () => void;
  isPending: boolean;
}) {
  const isPutOffer = slot.trigger_reason === "put_offer";
  const effectiveIsin = slot.confirmed_isin ?? slot.suggested_isin;
  const targetName = effectiveIsin
    ? (bondOptions.find((o) => o.value === effectiveIsin)?.label ??
      slot.suggested_name ??
      effectiveIsin)
    : null;
  const isUserOverride = !!slot.confirmed_isin;
  const hasNoTarget = !effectiveIsin;

  return (
    <div
      className={cn(
        "rounded-xl border p-4 space-y-3",
        isPutOffer
          ? "border-orange-400/50 bg-orange-500/5"
          : "border-border bg-card",
      )}
    >
      {/* Event header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                isPutOffer
                  ? "bg-orange-500/20 text-orange-700 dark:text-orange-400"
                  : "bg-purple-500/15 text-purple-700 dark:text-purple-400",
              )}
            >
              {TRIGGER_LABELS[slot.trigger_reason] ?? slot.trigger_reason}
            </span>
            <span className="font-mono text-sm font-medium">{slot.trigger_date}</span>
            {isUserOverride && (
              <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400">
                переназначено
              </span>
            )}
          </div>
          {sourceName && (
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{sourceName}</span>
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold">{formatRub(slot.expected_cash_rub)}</p>
          <p className="text-xs text-muted-foreground">освобождается</p>
        </div>
      </div>

      {/* Put-offer warning */}
      {isPutOffer && (
        <div className="flex items-start gap-2 rounded-lg bg-orange-500/10 px-3 py-2 text-sm text-orange-800 dark:text-orange-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Необходимо подать заявку на досрочный выкуп в T-Инвестициях до даты оферты. Средства
            поступят на счёт {slot.gap_days > 0 ? `через ${slot.gap_days} дн.` : "в тот же день"}.
          </span>
        </div>
      )}

      {/* Arrow + reinvest target */}
      <div className="flex items-center gap-2 text-muted-foreground">
        <ArrowDown className="h-4 w-4 shrink-0" />
        <span className="text-xs">реинвестировать через {slot.gap_days} дн. (T+{slot.gap_days})</span>
      </div>

      <div className="space-y-1.5">
        <p className="text-xs text-muted-foreground">
          {isUserOverride ? "Выбранная замена" : "Предлагаемая бумага"}
          {hasNoTarget && (
            <span className="ml-1 text-amber-600 dark:text-amber-400">⚠ не найдено подходящей</span>
          )}
          {targetName && !isUserOverride && (
            <span className="ml-1 font-medium text-foreground">{targetName}</span>
          )}
        </p>
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <Combobox
              options={bondOptions}
              value={slot.confirmed_isin ?? slot.suggested_isin}
              onChange={onOverride}
              placeholder={hasNoTarget ? "Выбрать бумагу вручную…" : "Изменить выбор…"}
              searchPlaceholder="Поиск по названию или ISIN…"
              disabled={isPending}
            />
          </div>
          {isUserOverride && (
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={onReset}
              disabled={isPending}
              title="Сбросить к рекомендации"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Slot index for debugging */}
      <p className="text-right text-xs text-muted-foreground/50">слот #{idx + 1}</p>
    </div>
  );
}

export function ReinvestmentSlots({ portfolioId, slots, positions, bonds }: Props) {
  const queryClient = useQueryClient();

  const setOverride = useMutation({
    mutationFn: ({
      sourcePositionIsin,
      confirmedIsin,
    }: {
      sourcePositionIsin: string;
      confirmedIsin: string | null;
    }) => api.setSlotOverride(portfolioId, sourcePositionIsin, confirmedIsin),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
    },
  });

  const bondOptions: ComboboxOption[] = bonds.map((b) => ({
    value: b.isin,
    label: b.name,
    description: [
      b.ytm_net != null ? `YTM ${b.ytm_net.toFixed(2)}%` : null,
      b.score != null ? `Скор ${Math.round(b.score)}` : null,
      b.credit_rating ?? null,
    ]
      .filter(Boolean)
      .join(" · "),
  }));

  if (!slots.length) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Реинвестиционных событий нет — все позиции погашаются за пределами горизонта
      </p>
    );
  }

  return (
    <div className="space-y-1">
      {slots.map((slot, idx) => {
        const sourceName = slot.source_position_isin
          ? (positions.find((p) => p.isin === slot.source_position_isin)?.name ??
             slot.source_position_isin)
          : null;

        return (
          <div key={idx} className="space-y-1">
            <SlotCard
              slot={slot}
              idx={idx}
              sourceName={sourceName}
              bondOptions={bondOptions}
              onOverride={(v) => {
                if (slot.source_position_isin) {
                  setOverride.mutate({
                    sourcePositionIsin: slot.source_position_isin,
                    confirmedIsin: v,
                  });
                }
              }}
              onReset={() => {
                if (slot.source_position_isin) {
                  setOverride.mutate({
                    sourcePositionIsin: slot.source_position_isin,
                    confirmedIsin: null,
                  });
                }
              }}
              isPending={setOverride.isPending}
            />
            {idx < slots.length - 1 && (
              <div className="flex justify-center py-0.5">
                <div className="h-4 w-px bg-border" />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
