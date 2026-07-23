import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/api/client";
import type { BillingPeriod } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRub } from "@/lib/utils";

function kopecksToRub(k: number) {
  return k / 100;
}

type Props = {
  /** When true, hide complimentary / already-subscribed CTAs noise — compact for dialog. */
  compact?: boolean;
};

export function PlanCheckoutOptions({ compact = false }: Props) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ["billing-catalog"],
    queryFn: () => api.getBillingCatalog(),
  });
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["billing-status"],
    queryFn: () => api.getBillingStatus(),
  });

  const checkoutMutation = useMutation({
    mutationFn: (period: BillingPeriod) => api.createBillingCheckout(period),
    onSuccess: (res) => {
      setError(null);
      if (res.confirmation_url) {
        window.location.assign(res.confirmation_url);
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["billing-status"] });
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Не удалось начать оплату");
    },
  });

  if (catalogLoading || statusLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  const month = catalog?.plans.find((p) => p.period === "month");
  const year = catalog?.plans.find((p) => p.period === "year");
  const paymentEnabled = Boolean(catalog?.payment_enabled ?? status?.payment_enabled);
  const blocked = !paymentEnabled || checkoutMutation.isPending || status?.complimentary;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {month && (
          <div className="space-y-3 rounded-md border border-border p-4">
            <p className="text-sm font-medium">Месяц</p>
            <p className="text-2xl font-semibold tracking-tight">
              {formatRub(kopecksToRub(month.amount_kopecks))}
              <span className="text-sm font-normal text-muted-foreground"> / мес</span>
            </p>
            <Button
              className="min-h-10 w-full"
              disabled={blocked}
              onClick={() => checkoutMutation.mutate("month")}
            >
              Оплатить месяц
            </Button>
          </div>
        )}
        {year && (
          <div className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-4">
            <p className="text-sm font-medium">Год</p>
            <p className="text-2xl font-semibold tracking-tight">
              {formatRub(kopecksToRub(year.monthly_kopecks))}
              <span className="text-sm font-normal text-muted-foreground"> / мес</span>
            </p>
            {!compact && (
              <p className="text-xs text-muted-foreground">
                {formatRub(kopecksToRub(year.amount_kopecks))} сразу · экономия{" "}
                {formatRub(kopecksToRub(year.savings_kopecks))} (
                {year.savings_percent.toFixed(0)}%)
              </p>
            )}
            {compact && (
              <p className="text-xs text-muted-foreground">
                {formatRub(kopecksToRub(year.amount_kopecks))} / год · −
                {year.savings_percent.toFixed(0)}%
              </p>
            )}
            <Button
              className="min-h-10 w-full"
              disabled={blocked}
              onClick={() => checkoutMutation.mutate("year")}
            >
              Оплатить год
            </Button>
          </div>
        )}
      </div>

      {!paymentEnabled && (
        <p className="text-sm text-muted-foreground">
          {compact
            ? "Оплата временно недоступна (эквайринг не настроен). Каталог тарифов доступен."
            : "Оплата временно недоступна (эквайринг не настроен). Каталог и расчёт окупаемости работают."}
        </p>
      )}

      {status?.complimentary && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          У вас complimentary‑доступ ко всем платным функциям.
        </p>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
