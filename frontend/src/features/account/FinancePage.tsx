import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRub } from "@/lib/utils";

const REASON_LABELS: Record<string, string> = {
  subscription_month: "Подписка · месяц",
  subscription_year: "Подписка · год",
  renewal_month: "Продление · месяц",
  renewal_year: "Продление · год",
  change_period_year: "Переход на год",
};

export function FinancePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["billing-ledger"],
    queryFn: () => api.getBillingLedger(50),
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  const entries = data?.entries ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-medium">Списания и начисления</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          История платежей по подписке. Complimentary‑доступ в ledger не пишется.
        </p>
      </div>

      {entries.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
          Пока нет операций
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {entries.map((e) => (
            <li key={e.id} className="flex items-start justify-between gap-3 px-4 py-3 text-sm">
              <div className="min-w-0 space-y-0.5">
                <p className="font-medium">
                  {REASON_LABELS[e.reason] ?? e.reason}
                </p>
                <p className="text-xs text-muted-foreground">
                  {new Date(e.created_at).toLocaleString("ru-RU")}
                </p>
              </div>
              <p
                className={
                  e.kind === "credit"
                    ? "shrink-0 font-medium text-emerald-700 dark:text-emerald-400"
                    : "shrink-0 font-medium"
                }
              >
                {e.kind === "credit" ? "+" : "−"}
                {formatRub(e.amount_kopecks / 100)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
