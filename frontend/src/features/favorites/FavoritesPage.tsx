import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star, X } from "lucide-react";
import { api } from "@/api/client";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDate, formatPct } from "@/lib/utils";

const RISK_LABELS: Record<number, { label: string; className: string }> = {
  0: { label: "Неизвестен", className: "bg-muted text-muted-foreground" },
  1: { label: "Низкий", className: "bg-green-500/15 text-green-700 dark:text-green-400" },
  2: { label: "Умеренный", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  3: { label: "Высокий", className: "bg-red-500/15 text-red-700 dark:text-red-400" },
};

const COUPON_TYPE_LABELS: Record<string, string> = {
  fixed: "Фикс.",
  floating: "Плав.",
  variable: "Перем.",
  unknown: "—",
};

export function FavoritesPage() {
  const queryClient = useQueryClient();
  const [selectedSecid, setSelectedSecid] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["favorites"],
    queryFn: api.getFavorites,
  });

  const removeFavorite = useMutation({
    mutationFn: (isin: string) => api.removeFavorite(isin),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
      queryClient.invalidateQueries({ queryKey: ["bonds"] });
    },
  });

  return (
    <div className="min-w-0 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Избранное</h1>
        <p className="text-sm text-muted-foreground">
          Отслеживаемые бумаги. Нажмите на карточку, чтобы открыть детали.
        </p>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full rounded-lg" />
          ))}
        </div>
      )}

      {data?.bonds.length === 0 && !isLoading && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border py-16 text-center">
          <Star className="h-10 w-10 text-muted-foreground" />
          <p className="text-muted-foreground">
            Добавьте бумаги из скринера, нажав на звёздочку
          </p>
        </div>
      )}

      {data && data.bonds.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.bonds.map((bond) => {
            const riskInfo = RISK_LABELS[bond.risk_level ?? 0];
            return (
              <div
                key={bond.isin}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedSecid(bond.secid)}
                onKeyDown={(e) => e.key === "Enter" && setSelectedSecid(bond.secid)}
                className="group relative flex cursor-pointer flex-col gap-3 rounded-lg border border-border bg-card p-4 shadow-sm transition-colors hover:border-primary/40 hover:bg-muted/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {/* Remove button */}
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute right-2 top-2 h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100"
                  aria-label="Убрать из избранного"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFavorite.mutate(bond.isin);
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>

                {/* Name */}
                <p className="pr-6 text-sm font-semibold leading-snug">{bond.name}</p>

                {/* Tags */}
                <div className="flex flex-wrap gap-1.5">
                  <Badge className={cn("text-xs font-normal", riskInfo.className)}>
                    {riskInfo.label}
                  </Badge>
                  <Badge variant="outline" className="text-xs font-normal">
                    {COUPON_TYPE_LABELS[bond.coupon_type] ?? bond.coupon_type}
                  </Badge>
                  {bond.has_warnings && (
                    <Badge variant="destructive" className="text-xs font-normal">
                      Есть риски
                    </Badge>
                  )}
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <p className="text-xs text-muted-foreground">YTM нетто</p>
                    <p className="text-sm font-semibold">{formatPct(bond.ytm_net)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Скор</p>
                    <p className="text-sm font-semibold">{bond.score?.toFixed(0) ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Погашение</p>
                    <p className="text-xs font-medium">{formatDate(bond.maturity_date)}</p>
                  </div>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{bond.secid}</span>
                  {bond.credit_rating && <span>{bond.credit_rating}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <BondDetailSheet secid={selectedSecid} onClose={() => setSelectedSecid(null)} />
    </div>
  );
}
