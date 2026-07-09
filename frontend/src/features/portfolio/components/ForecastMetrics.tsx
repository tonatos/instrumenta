import { forwardRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { PlanResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";

const InfoIconButton = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(function InfoIconButton({ className, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      className={cn(
        "inline-flex shrink-0 cursor-help rounded-sm text-muted-foreground/50 hover:text-muted-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
      aria-label="Подробнее"
      {...props}
    >
      <svg
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </button>
  );
});

export function ForecastMetrics({
  plan,
  isTrading,
  weightedDurationYears,
}: {
  plan: PlanResponse;
  isTrading: boolean;
  weightedDurationYears?: number | null;
}) {
  const [heldExpanded, setHeldExpanded] = useState(false);
  const durationYears = weightedDurationYears ?? plan.weighted_duration_years;
  const durationTooltip = isTrading
    ? "Средневзвешенная дюрация позиций на счёте (по рыночной стоимости). Мера процентного риска."
    : "Средневзвешенная дюрация текущих позиций (по сумме покупки). Мера процентного риска: чем выше, тем сильнее переоценка тела при изменении ключевой ставки.";

  const primaryProfit = isTrading ? plan.total_net_profit_with_held_rub : plan.total_net_profit_rub;
  const secondaryProfit = isTrading ? plan.total_net_profit_rub : plan.total_net_profit_with_held_rub;
  const secondaryLabel = isTrading ? "реализовано в кэш" : "с held";

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Чистая прибыль
            <Tooltip
              content={
                isTrading
                  ? "Итоговая стоимость на горизонте − вложенный капитал (старт + пополнения) − НДФЛ. Включает удерживаемые бумаги."
                  : "Купоны + возврат номинала − вложения − НДФЛ. Позиции за горизонтом не учитываются."
              }
            >
              <InfoIconButton />
            </Tooltip>
          </p>
          <p
            className={cn(
              "mt-1.5 text-2xl font-bold tabular-nums",
              primaryProfit > 0
                ? "text-green-600 dark:text-green-400"
                : "text-red-600 dark:text-red-400",
            )}
          >
            {primaryProfit > 0 ? "+" : ""}
            {formatRub(primaryProfit)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            вложено: {formatRub(plan.invested_capital_rub)}
          </p>
          {(isTrading || plan.held_positions.length > 0) && (
            <p className="mt-1 text-xs text-muted-foreground">
              {secondaryLabel}: {secondaryProfit > 0 ? "+" : ""}
              {formatRub(secondaryProfit)}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Годовая доходность (XIRR)
            <Tooltip content="Годовая доходность на вложенный капитал: XIRR по датам покупок и итоговой стоимости на горизонте, с учётом НДФЛ.">
              <InfoIconButton />
            </Tooltip>
          </p>
          {plan.expected_xirr_pct != null ? (
            <p
              className={cn(
                "mt-1.5 text-2xl font-bold tabular-nums",
                plan.expected_xirr_pct > 0
                  ? "text-green-600 dark:text-green-400"
                  : "text-muted-foreground",
              )}
            >
              {formatPct(plan.expected_xirr_pct)}
            </p>
          ) : (
            <p className="mt-1.5 text-2xl font-bold text-muted-foreground">—</p>
          )}
          {durationYears != null && (
            <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
              дюрация: {durationYears.toFixed(1)} г
              <Tooltip content={durationTooltip}>
                <InfoIconButton />
              </Tooltip>
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Итоговая стоимость
            <Tooltip content="Свободный кэш + рыночная стоимость всех held-позиций по номиналу к дате горизонта.">
              <InfoIconButton />
            </Tooltip>
          </p>
          <p className="mt-1.5 text-2xl font-bold tabular-nums">
            {formatRub(plan.final_portfolio_value)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            кэш: {formatRub(plan.final_cash_balance)}
          </p>
        </div>
      </div>

      {plan.held_positions.length > 0 && (
        <div className="rounded-xl border border-border bg-card">
          <button
            type="button"
            onClick={() => setHeldExpanded((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm"
          >
            <span className="font-medium">
              Удерживаются за горизонтом
              <Badge variant="secondary" className="ml-2 text-xs">
                {plan.held_positions.length}
              </Badge>
            </span>
            {heldExpanded
              ? <ChevronUp className="h-4 w-4 text-muted-foreground" />
              : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>
          {heldExpanded && (
            <div className="border-t border-border px-4 pb-4 pt-3">
              <div className="space-y-2">
                {plan.held_positions.map((h) => (
                  <div key={h.isin} className="flex items-center justify-between gap-2 text-sm">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{h.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {h.lots} л. · погашение {formatDate(h.maturity_date)}
                      </p>
                    </div>
                    <span className="shrink-0 tabular-nums">
                      {formatRub(h.estimated_value_rub)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
