import { Activity } from "lucide-react";
import type { Notification } from "@/api/types";
import { NOTIFICATION_KIND_LABELS } from "@/features/portfolio/labels";
import { usePortfolioNotifications } from "@/features/portfolio/marketSignals";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatPct } from "@/lib/utils";

function title(n: Notification): string {
  const name = n.payload?.name;
  return typeof name === "string" && name.length > 0 ? name : "Сигнал";
}

function reason(n: Notification): string {
  const r = n.payload?.reason;
  return typeof r === "string" ? r : "";
}

function maybePct(payload: Record<string, unknown>, key: string): string | null {
  const v = payload[key];
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return formatPct(v / 100);
}

export function SignalsPanel({ portfolioId }: { portfolioId: string }) {
  const { signals, isLoading } = usePortfolioNotifications(portfolioId);

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="signals-panel">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (signals.length === 0) {
    return (
      <div
        className="rounded-lg border border-dashed border-border py-12 text-center"
        data-testid="signals-panel"
      >
        <Activity className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" />
        <p className="text-sm font-medium">Сигналов пока нет</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Аномалии спреда, секторное давление и turbo-entry появятся после скана notifier.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="signals-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-sky-900 dark:text-sky-200">
          <Activity className="h-4 w-4" />
          Сигналы рынка
          <Badge className="bg-sky-500/15 text-sky-900 dark:text-sky-200">
            {signals.length}
          </Badge>
        </p>
      </div>

      <div className="space-y-2">
        {signals.map((n) => {
          const kindLabel = NOTIFICATION_KIND_LABELS[n.kind] ?? n.kind;
          const payload = n.payload ?? {};
          const bond7d = maybePct(payload, "bond_change_7d_pct");
          const sector7d = maybePct(payload, "sector_change_7d_pct");

          return (
            <div
              key={n.id}
              data-testid={`signal-${n.id}`}
              className={cn(
                "space-y-2 rounded-lg border border-border/60 bg-card/50 p-3",
                n.is_unread && "border-sky-400/40 bg-sky-500/5",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="text-sm font-medium">{title(n)}</p>
                <Badge variant="outline" className="text-xs">
                  {kindLabel}
                </Badge>
              </div>
              {reason(n) && <p className="text-sm text-muted-foreground">{reason(n)}</p>}
              {(bond7d || sector7d) && (
                <p className="text-xs text-muted-foreground">
                  {bond7d && <span>Бумага 7д: {bond7d}</span>}
                  {bond7d && sector7d && <span> · </span>}
                  {sector7d && <span>Сектор 7д: {sector7d}</span>}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
