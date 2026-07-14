import { Badge } from "@/components/ui/badge";
import { sectorLabel } from "@/features/bonds/sectorLabels";
import type { MarketRadarAnomalyRow } from "@/features/radar/useMarketRadar";
import { cn, formatPct } from "@/lib/utils";

function AnomalyCard({
  row,
  onSelectBond,
}: {
  row: MarketRadarAnomalyRow;
  onSelectBond: (secid: string) => void;
}) {
  const inPortfolio = (row.in_portfolios?.length ?? 0) > 0;

  return (
    <button
      type="button"
      data-testid={`radar-anomaly-${row.secid}`}
      className={cn(
        "w-full rounded-lg border border-border/60 p-3 text-left transition-colors hover:bg-muted/40",
        inPortfolio && "border-sky-400/40 bg-sky-500/5",
      )}
      onClick={() => onSelectBond(row.secid)}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{row.name}</span>
            {inPortfolio && (
              <Badge variant="outline" className="border-sky-400/50 text-sky-800 dark:text-sky-200">
                В портфеле
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {row.secid} · {sectorLabel(row.sector)}
          </p>
        </div>
        <div className="text-right text-xs">
          <p className="font-mono tabular-nums">{formatPct(row.spread_pp, 1)}</p>
          <p className="font-mono tabular-nums text-red-600 dark:text-red-400">
            +{formatPct(row.delta_pp, 1)}
          </p>
        </div>
      </div>
      {row.z_score != null && (
        <p className="mt-2 text-xs text-muted-foreground">
          Z-score: <span className="font-mono tabular-nums">{row.z_score.toFixed(1)}</span>
        </p>
      )}
    </button>
  );
}

export function AnomaliesTable({
  anomalies,
  onSelectBond,
}: {
  anomalies: MarketRadarAnomalyRow[];
  onSelectBond: (secid: string) => void;
}) {
  if (anomalies.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground" data-testid="radar-anomalies-empty">
        Аномалий спреда нет
      </p>
    );
  }

  return (
    <div data-testid="radar-anomalies">
      <div className="space-y-2 md:hidden">
        {anomalies.map((row) => (
          <AnomalyCard key={row.isin} row={row} onSelectBond={onSelectBond} />
        ))}
      </div>

      <div className="hidden overflow-x-auto rounded-lg border border-border/60 md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Бумага</th>
              <th className="px-3 py-2 font-medium">Сектор</th>
              <th className="px-3 py-2 text-right font-medium">Спред</th>
              <th className="px-3 py-2 text-right font-medium">vs peers</th>
              <th className="px-3 py-2 text-right font-medium">Z</th>
            </tr>
          </thead>
          <tbody>
            {anomalies.map((row) => {
              const inPortfolio = (row.in_portfolios?.length ?? 0) > 0;
              return (
                <tr
                  key={row.isin}
                  data-testid={`radar-anomaly-${row.secid}`}
                  className={cn(
                    "cursor-pointer border-b border-border/40 hover:bg-muted/40",
                    inPortfolio && "bg-sky-500/5",
                  )}
                  onClick={() => onSelectBond(row.secid)}
                >
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{row.name}</span>
                      {inPortfolio && (
                        <Badge variant="outline" className="border-sky-400/50 text-sky-800 dark:text-sky-200">
                          В портфеле
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{row.secid}</p>
                  </td>
                  <td className="px-3 py-2">{sectorLabel(row.sector)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {formatPct(row.spread_pp, 1)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-red-600 dark:text-red-400">
                    +{formatPct(row.delta_pp, 1)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {row.z_score != null ? row.z_score.toFixed(1) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
