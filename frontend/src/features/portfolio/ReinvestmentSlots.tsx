import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  CheckCircle2,
  RefreshCw,
  Sparkles,
  Wand2,
} from "lucide-react";
import { ApiError, api } from "@/api/client";
import type {
  Bond,
  PortfolioPosition,
  ReinvestmentSlot,
  ReinvestmentSlotCandidate,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn, formatDate, formatRub } from "@/lib/utils";

interface Props {
  portfolioId: string;
  slots: ReinvestmentSlot[];
  positions: PortfolioPosition[];
  bonds?: Bond[];
  planNotes?: string[];
}

const TRIGGER_LABELS: Record<string, string> = {
  maturity: "Погашение",
  put_offer: "Пут-оферта",
  coupon_cash: "Купонный кэш",
};

function candidateToOption(candidate: ReinvestmentSlotCandidate): ComboboxOption {
  return {
    value: candidate.isin,
    label: candidate.name,
    description: [
      candidate.ytm_net != null ? `YTM ${candidate.ytm_net.toFixed(2)}%` : null,
      candidate.score != null ? `Скор ${Math.round(candidate.score)}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
  };
}

function formatBondMetrics(
  isin: string,
  name: string | null,
  candidates: ReinvestmentSlotCandidate[],
): string {
  const match = candidates.find((c) => c.isin === isin);
  const parts = [
    name ?? match?.name ?? isin,
    match?.ytm_net != null ? `YTM ${match.ytm_net.toFixed(2)}%` : null,
    match?.score != null ? `Скор ${Math.round(match.score)}` : null,
  ].filter(Boolean);
  return parts.join(" · ");
}

function slotNotes(
  slot: ReinvestmentSlot,
  notes: string[],
): string[] {
  const keys = [
    slot.source_position_isin,
    slot.suggested_isin,
    slot.confirmed_isin,
    slot.trigger_date,
  ].filter(Boolean) as string[];
  return notes.filter((note) => keys.some((key) => note.includes(key)));
}

function SlotCard({
  slot,
  index,
  sourceName,
  bondOptions,
  uiMode,
  onUiModeChange,
  onOverride,
  onResetToStrategy,
  isPending,
  errorMessage,
  onClearError,
  relatedNotes,
}: {
  slot: ReinvestmentSlot;
  index: number;
  sourceName: string | null;
  bondOptions: ComboboxOption[];
  uiMode: "strategy" | "manual";
  onUiModeChange: (mode: "strategy" | "manual") => void;
  onOverride: (isin: string) => void;
  onResetToStrategy: () => void;
  isPending: boolean;
  errorMessage: string | null;
  onClearError: () => void;
  relatedNotes: string[];
}) {
  const isPutOffer = slot.trigger_reason === "put_offer";
  const isCouponCash = slot.trigger_reason === "coupon_cash";
  const isEditable = !!slot.source_position_isin && !isCouponCash;
  const selectionMode = slot.selection_mode ?? (slot.confirmed_isin ? "manual" : "strategy");
  const status = slot.status ?? (slot.suggested_isin || slot.confirmed_isin ? "ok" : "no_candidate");
  const effectiveIsin = slot.confirmed_isin ?? slot.suggested_isin;
  const strategyLabel = slot.suggested_isin
    ? formatBondMetrics(slot.suggested_isin, slot.suggested_name, slot.eligible_candidates ?? [])
    : null;

  return (
    <div
      className={cn(
        "rounded-xl border p-4 space-y-3",
        isPutOffer
          ? "border-orange-400/50 bg-orange-500/5"
          : "border-border bg-card",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-mono text-muted-foreground">
              {index + 1}
            </span>
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
            <span className="text-sm font-medium">{formatDate(slot.trigger_date)}</span>
            {selectionMode === "manual" && (
              <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400">
                вручную
              </span>
            )}
          </div>
          {sourceName && (
            <p className="text-sm text-muted-foreground">
              из позиции{" "}
              <span className="font-medium text-foreground">{sourceName}</span>
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold">{formatRub(slot.expected_cash_rub)}</p>
          <p className="text-xs text-muted-foreground">освобождается</p>
        </div>
      </div>

      {isPutOffer && (
        <div className="flex items-start gap-2 rounded-lg bg-orange-500/10 px-3 py-2 text-sm text-orange-800 dark:text-orange-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Необходимо подать заявку на досрочный выкуп в T-Инвестициях до даты оферты. Средства
            поступят на счёт {slot.gap_days > 0 ? `через ${slot.gap_days} дн.` : "в тот же день"}.
          </span>
        </div>
      )}

      <div className="flex items-center gap-2 text-muted-foreground">
        <ArrowDown className="h-4 w-4 shrink-0" />
        <span className="text-xs">реинвестировать через {slot.gap_days} дн. (T+{slot.gap_days})</span>
      </div>

      {isCouponCash ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/30 px-3 py-3 text-sm text-muted-foreground">
          <div className="flex items-center gap-2 font-medium text-foreground">
            <Sparkles className="h-4 w-4 text-purple-500" />
            Автоматический реинвест купонного кэша
          </div>
          <p className="mt-1 text-xs">
            {strategyLabel
              ? `Стратегия предлагает: ${strategyLabel}`
              : "Подходящая бумага будет подобрана при пересчёте прогноза."}
          </p>
        </div>
      ) : (
        <div className="space-y-3 rounded-lg border border-border/70 bg-muted/10 p-3">
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant={uiMode === "strategy" ? "default" : "outline"}
              className="h-8 gap-1.5 text-xs"
              disabled={!isEditable || isPending}
              onClick={() => {
                onClearError();
                onUiModeChange("strategy");
                if (selectionMode === "manual") {
                  onResetToStrategy();
                }
              }}
            >
              <Sparkles className="h-3.5 w-3.5" />
              Предложенная стратегией
            </Button>
            <Button
              type="button"
              size="sm"
              variant={uiMode === "manual" ? "default" : "outline"}
              className="h-8 gap-1.5 text-xs"
              disabled={!isEditable || isPending || (slot.eligible_candidates?.length ?? 0) === 0}
              onClick={() => {
                onClearError();
                onUiModeChange("manual");
              }}
            >
              <Wand2 className="h-3.5 w-3.5" />
              Выбрать вручную
            </Button>
          </div>

          {uiMode === "strategy" ? (
            <div className="space-y-2">
              {strategyLabel ? (
                <div className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  <span>{strategyLabel}</span>
                </div>
              ) : (
                <div className="flex items-start gap-2 rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <p className="font-medium">Стратегия не нашла подходящую замену</p>
                    {slot.failure_reason && (
                      <p className="mt-1 text-xs opacity-90">{slot.failure_reason}</p>
                    )}
                  </div>
                </div>
              )}
              {status !== "ok" && status !== "no_candidate" && slot.failure_reason && (
                <p className="text-xs text-amber-700 dark:text-amber-300">{slot.failure_reason}</p>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Доступны только бумаги, подходящие по профилю, горизонту и сумме реинвеста.
              </p>
              <Combobox
                options={bondOptions}
                value={slot.confirmed_isin ?? slot.suggested_isin}
                onChange={(value) => {
                  if (value) onOverride(value);
                }}
                placeholder="Выберите бумагу из списка…"
                searchPlaceholder="Поиск по названию или ISIN…"
                disabled={isPending}
                allowDeselect={false}
                emptyText="Нет подходящих бумаг для этого слота"
              />
              {selectionMode === "manual" && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 gap-1.5 text-xs text-muted-foreground"
                  onClick={onResetToStrategy}
                  disabled={isPending}
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Вернуть к стратегии
                </Button>
              )}
            </div>
          )}

          {errorMessage && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          {relatedNotes.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {relatedNotes.map((note) => (
                <li key={note} className="flex gap-2">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {effectiveIsin && isEditable && uiMode === "strategy" && selectionMode === "manual" && (
        <p className="text-xs text-muted-foreground">
          Текущая покупка: {formatBondMetrics(effectiveIsin, null, slot.eligible_candidates ?? [])}
        </p>
      )}
    </div>
  );
}

export function ReinvestmentSlots({
  portfolioId,
  slots,
  positions,
  planNotes = [],
}: Props) {
  const queryClient = useQueryClient();
  const [pendingSourceIsin, setPendingSourceIsin] = useState<string | null>(null);
  const [slotErrors, setSlotErrors] = useState<Record<string, string>>({});
  const [uiModes, setUiModes] = useState<Record<string, "strategy" | "manual">>({});
  const [resetDialogOpen, setResetDialogOpen] = useState(false);

  const manualCount = slots.filter((s) => s.selection_mode === "manual").length;

  const setOverride = useMutation({
    mutationFn: ({
      sourcePositionIsin,
      confirmedIsin,
    }: {
      sourcePositionIsin: string;
      confirmedIsin: string | null;
    }) => {
      setPendingSourceIsin(sourcePositionIsin);
      return api.setSlotOverride(portfolioId, sourcePositionIsin, confirmedIsin);
    },
    onSuccess: (_data, variables) => {
      setSlotErrors((prev) => {
        const next = { ...prev };
        delete next[variables.sourcePositionIsin];
        return next;
      });
      if (variables.confirmedIsin === null) {
        setUiModes((prev) => ({ ...prev, [variables.sourcePositionIsin]: "strategy" }));
      }
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
    },
    onError: (error, variables) => {
      const message =
        error instanceof ApiError ? error.message : "Не удалось сохранить выбор";
      setSlotErrors((prev) => ({
        ...prev,
        [variables.sourcePositionIsin]: message,
      }));
    },
    onSettled: () => {
      setPendingSourceIsin(null);
    },
  });

  const resetAll = useMutation({
    mutationFn: () => api.resetAllSlotOverrides(portfolioId),
    onSuccess: () => {
      setUiModes({});
      setSlotErrors({});
      setResetDialogOpen(false);
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
    },
  });

  if (!slots.length) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Реинвестиционных событий нет — все позиции погашаются за пределами горизонта
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3">
        <div className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{slots.length}</span>{" "}
          {slots.length === 1 ? "слот" : slots.length < 5 ? "слота" : "слотов"}
          {manualCount > 0 && (
            <span>
              {" "}
              · <span className="text-amber-700 dark:text-amber-400">{manualCount}</span> вручную
            </span>
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={manualCount === 0 || resetAll.isPending}
          onClick={() => setResetDialogOpen(true)}
        >
          <RefreshCw className="h-4 w-4" />
          Реинвестировать автоматически
        </Button>
      </div>

      <div className="space-y-1">
        {slots.map((slot, idx) => {
          const slotKey = slot.source_position_isin ?? `${slot.trigger_date}-${slot.trigger_reason}`;
          const sourceName = slot.source_position_isin
            ? (positions.find((p) => p.isin === slot.source_position_isin)?.name ??
               slot.source_position_isin)
            : null;
          const candidates = slot.eligible_candidates ?? [];
          const bondOptions = candidates.map(candidateToOption);
          const effectiveIsin = slot.confirmed_isin ?? slot.suggested_isin;
          if (
            effectiveIsin &&
            !bondOptions.some((option) => option.value === effectiveIsin)
          ) {
            bondOptions.unshift({
              value: effectiveIsin,
              label: slot.confirmed_isin ? (slot.suggested_name ?? effectiveIsin) : (slot.suggested_name ?? effectiveIsin),
              description: "текущий выбор",
            });
          }
          const selectionMode = slot.selection_mode ?? (slot.confirmed_isin ? "manual" : "strategy");
          const uiMode =
            uiModes[slotKey] ?? (selectionMode === "manual" ? "manual" : "strategy");

          return (
            <div key={slotKey} className="space-y-1">
              <SlotCard
                slot={slot}
                index={idx}
                sourceName={sourceName}
                bondOptions={bondOptions}
                uiMode={uiMode}
                onUiModeChange={(mode) =>
                  setUiModes((prev) => ({ ...prev, [slotKey]: mode }))
                }
                onOverride={(isin) => {
                  if (!slot.source_position_isin) return;
                  if (isin === slot.suggested_isin && selectionMode !== "manual") {
                    return;
                  }
                  setOverride.mutate({
                    sourcePositionIsin: slot.source_position_isin,
                    confirmedIsin: isin,
                  });
                }}
                onResetToStrategy={() => {
                  if (!slot.source_position_isin) return;
                  setOverride.mutate({
                    sourcePositionIsin: slot.source_position_isin,
                    confirmedIsin: null,
                  });
                }}
                isPending={pendingSourceIsin === slot.source_position_isin && setOverride.isPending}
                errorMessage={slot.source_position_isin ? slotErrors[slot.source_position_isin] ?? null : null}
                onClearError={() => {
                  if (!slot.source_position_isin) return;
                  setSlotErrors((prev) => {
                    const next = { ...prev };
                    delete next[slot.source_position_isin!];
                    return next;
                  });
                }}
                relatedNotes={slotNotes(slot, planNotes)}
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

      <DialogRoot open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Реинвестировать автоматически?</DialogTitle>
            <DialogDescription>
              Будет сброшено {manualCount}{" "}
              {manualCount === 1 ? "ручное назначение" : "ручных назначений"}. Вся цепочка
              реинвестиций пересчитается по стратегии портфеля.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Отмена
              </Button>
            </DialogClose>
            <Button
              type="button"
              onClick={() => resetAll.mutate()}
              disabled={resetAll.isPending}
            >
              Сбросить и пересчитать
            </Button>
          </DialogFooter>
        </DialogContent>
      </DialogRoot>
    </div>
  );
}
