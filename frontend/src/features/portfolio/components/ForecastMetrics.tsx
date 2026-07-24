import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { PlanResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { FieldHelp } from "@/components/ui/field-help";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";

export function ForecastMetrics({
  plan,
  isTrading,
  weightedDurationYears,
  horizonDate,
}: {
  plan: PlanResponse;
  isTrading: boolean;
  weightedDurationYears?: number | null;
  horizonDate: string;
}) {
  const [heldExpanded, setHeldExpanded] = useState(false);
  const durationYears = weightedDurationYears ?? plan.weighted_duration_years;
  const durationTooltip = isTrading
    ? "Средневзвешенная дюрация позиций на счёте (по рыночной стоимости). Мера процентного риска."
    : "Средневзвешенная дюрация текущих позиций (по сумме покупки). Мера процентного риска: чем выше, тем сильнее переоценка тела при изменении ключевой ставки.";

  const primaryProfit = isTrading ? plan.total_net_profit_with_held_rub : plan.total_net_profit_rub;
  const secondaryProfit = isTrading ? plan.total_net_profit_rub : plan.total_net_profit_with_held_rub;
  const secondaryLabel = isTrading ? "реализовано в кэш" : "с held";

  const profitHelp = isTrading
    ? "Прогноз до горизонта плана: итоговая стоимость − вложенный капитал (старт + пополнения) − НДФЛ. Включает удерживаемые бумаги. Это модель реинвестиций и денежных потоков продукта, не гарантия и не отчёт брокера."
    : "Прогноз до горизонта плана: купоны + возврат номинала − вложения − НДФЛ. Позиции за горизонтом не входят в эту цифру. Модель, не гарантия результата.";

  const xirrHelp =
    "Прогнозная годовая доходность на вложенный капитал (XIRR) по датам покупок и итоговой стоимости на горизонте, с учётом НДФЛ и правил реинвестиций в плане. Не факт и не обещание доходности.";

  const valueHelp =
    "Прогноз стоимости на дату горизонта: свободный кэш + оценка удерживаемых позиций по правилам плана (номинал/модель). Зависит от допущений по погашениям, офертам и реинвестициям — не снимок брокерского счёта «как есть».";

  return (
    <div className="space-y-3" data-testid="forecast-metrics">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Прогнозная чистая прибыль
            <FieldHelp content={profitHelp} label="Что значит прогнозная чистая прибыль" />
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
            Прогнозный XIRR
            <FieldHelp content={xirrHelp} label="Что значит прогнозный XIRR" />
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
              <FieldHelp content={durationTooltip} label="Что значит дюрация" />
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Прогнозная стоимость
            <FieldHelp content={valueHelp} label="Что значит прогнозная стоимость" />
          </p>
          <p className="mt-1.5 text-2xl font-bold tabular-nums">
            {formatRub(plan.final_portfolio_value)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            кэш: {formatRub(plan.final_cash_balance)}
          </p>
        </div>
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground" data-testid="forecast-disclaimer">
        Показатели — прогноз по плану до горизонта{" "}
        <span className="font-medium text-foreground/80">{formatDate(horizonDate)}</span>
        : модель денежных потоков и реинвестиций, а не гарантия и не факт брокерского отчёта.
      </p>

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
