import { useMemo } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import type { AccountOperation } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";
import { OPERATION_TYPE_LABELS } from "@/features/portfolio/labels";

const TYPE_ROW_CLASSES: Record<string, { rowClass: string; badgeClass: string }> = {
  buy: {
    rowClass: "bg-blue-500/5",
    badgeClass: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  },
  sell: {
    rowClass: "bg-orange-500/5",
    badgeClass: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  },
  coupon: {
    rowClass: "bg-green-500/5",
    badgeClass: "bg-green-500/15 text-green-700 dark:text-green-400",
  },
  repayment: {
    rowClass: "bg-purple-500/5",
    badgeClass: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  },
  input: {
    rowClass: "bg-teal-500/5",
    badgeClass: "bg-teal-500/15 text-teal-700 dark:text-teal-400",
  },
  output: {
    rowClass: "bg-red-500/5",
    badgeClass: "bg-red-500/15 text-red-700 dark:text-red-400",
  },
  tax: {
    rowClass: "bg-amber-500/5",
    badgeClass: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  fee: {
    rowClass: "bg-slate-500/5",
    badgeClass: "bg-slate-500/15 text-slate-700 dark:text-slate-400",
  },
};

function getTypeConfig(type: string, typeLabel: string) {
  const key = Object.keys(TYPE_ROW_CLASSES).find((k) => type.toLowerCase().includes(k));
  if (key) {
    return {
      label: OPERATION_TYPE_LABELS[key],
      ...TYPE_ROW_CLASSES[key],
    };
  }
  return {
    label: typeLabel,
    rowClass: "",
    badgeClass: "bg-muted text-muted-foreground",
  };
}

function formatPayment(value: number | null | undefined) {
  if (value == null || Number.isNaN(value) || value === 0) return "—";
  if (value < 0) return `−${formatRub(Math.abs(value))}`;
  return `+${formatRub(value)}`;
}

function instrumentLabel(op: AccountOperation) {
  if (op.name) return op.name;
  if (op.isin) return op.isin;
  if (op.figi) return op.figi;
  if (op.instrument_type === "currency") return "Рубли";
  return "—";
}

export function AccountOperationsTable({
  operations,
  isLoading,
  isError,
  onRefresh,
  isRefreshing,
}: {
  operations: AccountOperation[];
  isLoading: boolean;
  isError: boolean;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const summary = useMemo(() => {
    let inflow = 0;
    let outflow = 0;
    for (const op of operations) {
      if (op.payment_rub == null) continue;
      if (op.payment_rub > 0) inflow += op.payment_rub;
      else outflow += Math.abs(op.payment_rub);
    }
    return { inflow, outflow, count: operations.length };
  }, [operations]);

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">История операций</h3>
          {!isLoading && operations.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {summary.count} операций · поступления {formatRub(summary.inflow)} · списания{" "}
              {formatRub(summary.outflow)}
            </p>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="gap-1.5"
        >
          {isRefreshing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Обновить
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Загрузка операций…
        </div>
      ) : isError ? (
        <p className="py-8 text-center text-sm text-destructive">
          Не удалось загрузить историю операций. Попробуйте обновить.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Дата</th>
                <th className="px-3 py-2 text-left font-semibold">Тип</th>
                <th className="px-3 py-2 text-left font-semibold">Инструмент</th>
                <th className="px-3 py-2 text-right font-semibold">Кол-во</th>
                <th className="px-3 py-2 text-right font-semibold">Цена</th>
                <th className="px-3 py-2 text-right font-semibold">Сумма</th>
                <th className="hidden px-3 py-2 text-right font-semibold md:table-cell">Комиссия</th>
                <th className="hidden px-3 py-2 text-left font-semibold md:table-cell">Статус</th>
              </tr>
            </thead>
            <tbody>
              {operations.map((op) => {
                const cfg = getTypeConfig(op.type, op.type_label);
                return (
                  <tr key={op.id} className={cn("border-t border-border", cfg.rowClass)}>
                    <td className="whitespace-nowrap px-3 py-2 font-medium">
                      {formatDate(op.date)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          cfg.badgeClass,
                        )}
                      >
                        {op.type_label || cfg.label}
                      </span>
                    </td>
                    <td className="max-w-[220px] truncate px-3 py-2 text-muted-foreground">
                      {instrumentLabel(op)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-muted-foreground">
                      {op.quantity > 0 ? `${op.quantity} шт.` : "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-muted-foreground">
                      {op.price_pct != null ? formatPct(op.price_pct) : "—"}
                    </td>
                    <td
                      className={cn(
                        "whitespace-nowrap px-3 py-2 text-right font-medium",
                        op.payment_rub != null && op.payment_rub < 0
                          ? "text-red-600 dark:text-red-400"
                          : op.payment_rub != null && op.payment_rub > 0
                            ? "text-green-600 dark:text-green-400"
                            : "",
                      )}
                    >
                      {formatPayment(op.payment_rub)}
                    </td>
                    <td className="hidden whitespace-nowrap px-3 py-2 text-right text-muted-foreground md:table-cell">
                      {op.commission_rub != null && op.commission_rub !== 0
                        ? formatRub(op.commission_rub)
                        : "—"}
                    </td>
                    <td className="hidden whitespace-nowrap px-3 py-2 text-muted-foreground md:table-cell">
                      {op.state_label}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {operations.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">
              Операций по счёту пока нет
            </p>
          )}
        </div>
      )}
    </div>
  );
}
