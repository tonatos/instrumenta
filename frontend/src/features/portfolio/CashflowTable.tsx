import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Filter } from "lucide-react";
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
import {
  CASHFLOW_KIND_OPTIONS,
  cashflowKindLabel,
  defaultActiveCashflowKinds,
  normalizeCashflowKind,
  uniqueCashflowKindKeys,
  type CashflowKindKey,
} from "@/features/portfolio/cashflowKinds";
import { cn, formatDate, formatRub } from "@/lib/utils";

const KIND_ROW_CLASS: Record<string, string> = {
  purchase: "bg-blue-500/5",
  sale: "bg-rose-500/5",
  coupon: "bg-green-500/5",
  maturity: "bg-purple-500/5",
  put_offer: "bg-orange-500/5",
  deposit: "bg-emerald-500/5",
  withdrawal: "bg-amber-500/5",
  fee: "bg-slate-500/5",
  tax: "bg-red-500/5",
  reconciliation: "bg-cyan-500/5",
};

const KIND_BADGE_CLASS: Record<string, string> = {
  purchase: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  sale: "bg-rose-500/15 text-rose-700 dark:text-rose-400",
  coupon: "bg-green-500/15 text-green-700 dark:text-green-400",
  maturity: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  put_offer: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  deposit: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  withdrawal: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  fee: "bg-slate-500/15 text-slate-700 dark:text-slate-400",
  tax: "bg-red-500/15 text-red-700 dark:text-red-400",
  reconciliation: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-400",
};

function getKindStyle(kind: string) {
  const key = normalizeCashflowKind(kind);
  return {
    label: cashflowKindLabel(kind),
    rowClass: KIND_ROW_CLASS[key] ?? "",
    badgeClass: KIND_BADGE_CLASS[key] ?? "bg-muted text-muted-foreground",
  };
}

export function CashflowTable({
  cashflow,
  initialCash,
  cashflowFromDate,
}: {
  cashflow: PlanResponse["cashflow"];
  initialCash: number;
  cashflowFromDate?: string | null;
}) {
  const [view, setView] = useState<"table" | "chart">("table");
  const [filtersOpen, setFiltersOpen] = useState(false);

  const availableKinds = useMemo(
    () => uniqueCashflowKindKeys(cashflow.map((e) => e.kind)),
    [cashflow],
  );

  const [activeKinds, setActiveKinds] = useState<Set<CashflowKindKey>>(() =>
    defaultActiveCashflowKinds(availableKinds),
  );

  useEffect(() => {
    setActiveKinds(defaultActiveCashflowKinds(availableKinds));
  }, [availableKinds]);

  const allKindsSelected = activeKinds.size === availableKinds.length;

  const filteredCashflow = useMemo(() => {
    if (allKindsSelected) return cashflow;
    return cashflow.filter((e) =>
      activeKinds.has(normalizeCashflowKind(e.kind) as CashflowKindKey),
    );
  }, [cashflow, activeKinds, allKindsSelected]);

  const rows = useMemo(() => {
    let balance = initialCash;
    return filteredCashflow.map((e) => {
      balance += e.amount_rub;
      return {
        ...e,
        running_balance:
          e.balance_after_rub != null ? e.balance_after_rub : balance,
      };
    });
  }, [filteredCashflow, initialCash]);

  const toggleKind = (key: CashflowKindKey) => {
    setActiveKinds((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size === 1) return next;
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const selectAllKinds = () => setActiveKinds(new Set(availableKinds));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Cashflow</h3>
          {cashflowFromDate && (
            <p className="text-xs text-muted-foreground">
              С {formatDate(cashflowFromDate)} (открытие / привязка счёта)
            </p>
          )}
        </div>
        <div className="flex flex-wrap overflow-hidden rounded-md border border-border">
          <button
            type="button"
            onClick={() => setView("table")}
            className={cn(
              "min-h-10 px-3 py-1.5 text-xs transition-colors",
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
              "min-h-10 px-3 py-1.5 text-xs transition-colors",
              view === "chart"
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted/50",
            )}
          >
            График
          </button>
        </div>
      </div>

      {availableKinds.length > 0 && (
        <div className="rounded-lg border border-border">
          <button
            type="button"
            className="flex min-h-10 w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium"
            onClick={() => setFiltersOpen((v) => !v)}
            aria-expanded={filtersOpen}
          >
            <span className="inline-flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              Типы операций
              {!allKindsSelected && (
                <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs font-normal text-primary">
                  {activeKinds.size} из {availableKinds.length}
                </span>
              )}
            </span>
            <ChevronDown
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                filtersOpen && "rotate-180",
              )}
            />
          </button>
          {filtersOpen && (
            <div className="flex flex-wrap gap-2 border-t border-border px-3 py-3">
              {CASHFLOW_KIND_OPTIONS.filter((o) => availableKinds.includes(o.key)).map(
                (option) => {
                  const active = activeKinds.has(option.key);
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => toggleKind(option.key)}
                      className={cn(
                        "min-h-10 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                        active
                          ? KIND_BADGE_CLASS[option.key]
                          : "bg-muted/40 text-muted-foreground line-through opacity-60",
                      )}
                    >
                      {option.label}
                    </button>
                  );
                },
              )}
              {!allKindsSelected && (
                <button
                  type="button"
                  onClick={selectAllKinds}
                  className="min-h-10 rounded-full border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/30"
                >
                  Все типы
                </button>
              )}
            </div>
          )}
        </div>
      )}

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
                {allKindsSelected && (
                  <th className="hidden px-3 py-2 text-right font-semibold sm:table-cell">Баланс</th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const cfg = getKindStyle(row.kind);
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
                    {allKindsSelected && (
                      <td className="hidden whitespace-nowrap px-3 py-2 text-right sm:table-cell">
                        {formatRub(row.running_balance)}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {cashflow.length === 0
                ? "Нет данных cashflow"
                : "Нет операций выбранных типов"}
            </p>
          )}
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={filteredCashflow}>
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
