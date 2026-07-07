import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PlanResponse } from "@/api/types";
import { formatDate, formatRub } from "@/lib/utils";

type TimelinePoint = PlanResponse["value_timeline"][number];

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ payload: TimelinePoint }>;
  label?: string;
}) {
  if (!active || !payload?.length || !label) return null;
  const point = payload[0].payload;

  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-2 font-medium">{formatDate(label)}</p>
      <div className="space-y-1">
        <p className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Итого</span>
          <span className="font-semibold tabular-nums">{formatRub(point.total_value_rub)}</span>
        </p>
        <p className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500/80" />
            Бумаги
          </span>
          <span className="tabular-nums">{formatRub(point.positions_value_rub)}</span>
        </p>
        <p className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-block h-2 w-2 rounded-full bg-sky-500/80" />
            Кэш
          </span>
          <span className="tabular-nums">{formatRub(point.cash_rub)}</span>
        </p>
      </div>
    </div>
  );
}

export function PortfolioValueChart({
  timeline,
  initialAmount,
  horizonDate,
}: {
  timeline: PlanResponse["value_timeline"];
  initialAmount: number;
  horizonDate: string;
}) {
  const data = useMemo(() => timeline, [timeline]);

  const growthPct = useMemo(() => {
    if (data.length < 2) return null;
    const start = data[0].total_value_rub;
    const end = data[data.length - 1].total_value_rub;
    if (start <= 0) return null;
    return ((end - start) / start) * 100;
  }, [data]);

  if (data.length < 2) {
    return (
      <div
        data-testid="portfolio-value-chart"
        className="flex h-56 items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground"
      >
        Недостаточно данных для графика
      </div>
    );
  }

  const startLabel = formatDate(data[0].date);
  const endLabel = formatDate(horizonDate);

  return (
    <div
      data-testid="portfolio-value-chart"
      className="rounded-xl border border-border bg-card p-4"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Рост стоимости портфеля</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {startLabel} → {endLabel}
          </p>
        </div>
        <div className="text-right">
          {growthPct != null && (
            <p
              className={
                growthPct >= 0
                  ? "text-lg font-bold tabular-nums text-emerald-600 dark:text-emerald-400"
                  : "text-lg font-bold tabular-nums text-red-600 dark:text-red-400"
              }
            >
              {growthPct >= 0 ? "+" : ""}
              {growthPct.toFixed(1)}%
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            от {formatRub(initialAmount)}
          </p>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500/70" />
          Бумаги
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-sky-500/50" />
          Кэш
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded bg-primary" />
          Итого
        </span>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="positionsGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="rgb(16 185 129)" stopOpacity={0.45} />
                <stop offset="100%" stopColor="rgb(16 185 129)" stopOpacity={0.08} />
              </linearGradient>
              <linearGradient id="cashGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="rgb(14 165 233)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="rgb(14 165 233)" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border/60" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={(v) => formatDate(String(v))}
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              minTickGap={32}
            />
            <YAxis
              tickFormatter={(v) =>
                v >= 1_000_000
                  ? `${(v / 1_000_000).toFixed(1)}M`
                  : v >= 1_000
                    ? `${(v / 1_000).toFixed(0)}k`
                    : String(v)
              }
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <RechartsTooltip content={<ChartTooltip />} />
            <Area
              type="monotone"
              dataKey="cash_rub"
              stackId="portfolio"
              stroke="rgb(14 165 233)"
              strokeWidth={1}
              fill="url(#cashGradient)"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="positions_value_rub"
              stackId="portfolio"
              stroke="rgb(16 185 129)"
              strokeWidth={1}
              fill="url(#positionsGradient)"
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="total_value_rub"
              stroke="var(--color-primary)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
