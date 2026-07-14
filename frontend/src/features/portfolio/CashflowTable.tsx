import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PlanResponse } from "@/api/types";
import { cn, formatDate, formatRub } from "@/lib/utils";

const KIND_CONFIG: Record<
  string,
  { label: string; rowClass: string; badgeClass: string }
> = {
  buy: {
    label: "Покупка",
    rowClass: "bg-blue-500/5",
    badgeClass: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  },
  purchase: {
    label: "Покупка",
    rowClass: "bg-blue-500/5",
    badgeClass: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  },
  coupon: {
    label: "Купон",
    rowClass: "bg-green-500/5",
    badgeClass: "bg-green-500/15 text-green-700 dark:text-green-400",
  },
  maturity: {
    label: "Погашение",
    rowClass: "bg-purple-500/5",
    badgeClass: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  },
  put_offer: {
    label: "Пут-оферта",
    rowClass: "bg-orange-500/5",
    badgeClass: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  },
  reinvest: {
    label: "Реинвестиция",
    rowClass: "bg-teal-500/5",
    badgeClass: "bg-teal-500/15 text-teal-700 dark:text-teal-400",
  },
};

function getKindConfig(kind: string) {
  const key = Object.keys(KIND_CONFIG).find((k) => kind.toLowerCase().includes(k));
  return (
    key
      ? KIND_CONFIG[key]
      : { label: kind, rowClass: "", badgeClass: "bg-muted text-muted-foreground" }
  );
}

export function CashflowTable({
  cashflow,
  initialCash,
}: {
  cashflow: PlanResponse["cashflow"];
  initialCash: number;
}) {
  const [view, setView] = useState<"table" | "chart">("table");

  const rows = useMemo(() => {
    let balance = initialCash;
    return cashflow.map((e) => {
      balance += e.amount_rub;
      return {
        ...e,
        running_balance:
          e.balance_after_rub != null ? e.balance_after_rub : balance,
      };
    });
  }, [cashflow, initialCash]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Cashflow</h3>
        <div className="flex flex-wrap overflow-hidden rounded-md border border-border">
          <button
            type="button"
            onClick={() => setView("table")}
            className={cn(
              "px-3 py-1.5 text-xs transition-colors",
              view === "table"
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted/50",
            )}
          >
            Таблица
          </button>
          <button
            type="button"
            onClick={() => setView("chart")}
            className={cn(
              "px-3 py-1.5 text-xs transition-colors",
              view === "chart"
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted/50",
            )}
          >
            График
          </button>
        </div>
      </div>

      {view === "table" ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Дата</th>
                <th className="px-3 py-2 text-left font-semibold">Тип</th>
                <th className="px-3 py-2 text-left font-semibold">Описание</th>
                <th className="hidden px-3 py-2 text-right font-semibold sm:table-cell">Кол-во</th>
                <th className="px-3 py-2 text-right font-semibold">Сумма</th>
                <th className="hidden px-3 py-2 text-right font-semibold sm:table-cell">Баланс</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const cfg = getKindConfig(row.kind);
                return (
                  <tr key={i} className={cn("border-t border-border", cfg.rowClass)}>
                    <td className="whitespace-nowrap px-3 py-2 font-medium">{formatDate(row.date)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          cfg.badgeClass,
                        )}
                      >
                        {cfg.label}
                      </span>
                    </td>
                    <td className="max-w-[200px] truncate px-3 py-2 text-muted-foreground">
                      {row.label}
                    </td>
                    <td className="hidden whitespace-nowrap px-3 py-2 text-right text-muted-foreground sm:table-cell">
                      {row.bonds_count != null && row.bonds_count > 0
                        ? `${row.bonds_count} шт.`
                        : row.lots != null && row.lots > 0
                          ? `${row.lots} л.`
                          : "—"}
                    </td>
                    <td
                      className={cn(
                        "whitespace-nowrap px-3 py-2 text-right font-medium",
                        row.amount_rub < 0
                          ? "text-red-600 dark:text-red-400"
                          : "text-green-600 dark:text-green-400",
                      )}
                    >
                      {row.amount_rub < 0
                        ? `−${formatRub(Math.abs(row.amount_rub))}`
                        : `+${formatRub(row.amount_rub)}`}
                    </td>
                    <td className="hidden whitespace-nowrap px-3 py-2 text-right sm:table-cell">
                      {formatRub(row.running_balance)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">
              Нет данных cashflow
            </p>
          )}
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={cashflow}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => formatDate(String(v))} />
              <YAxis tick={{ fontSize: 10 }} />
              <RechartsTooltip
                formatter={(v) => [formatRub(Number(v)), "Сумма"]}
                labelFormatter={(l) => `Дата: ${formatDate(String(l))}`}
              />
              <Bar dataKey="amount_rub" fill="var(--color-primary)" radius={3} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
