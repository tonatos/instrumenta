import { cn, formatPct } from "@/lib/utils";
import { sectorLabel } from "@/features/bonds/sectorLabels";
import type { MarketRadarSectorRow } from "@/features/radar/useMarketRadar";

function heatmapClass(change: number): string {
  if (change <= -10) return "bg-red-500/15 border-red-500/30";
  if (change <= -3) return "bg-red-500/8 border-red-500/20";
  if (change >= 10) return "bg-emerald-500/15 border-emerald-500/30";
  if (change >= 3) return "bg-emerald-500/10 border-emerald-500/20";
  return "bg-muted/30 border-border/60";
}

export function SectorHeatmap({
  sectors,
  selectedSector,
  onSelectSector,
  portfolioNames,
  hasAnomaliesWithoutHistory = false,
}: {
  sectors: MarketRadarSectorRow[];
  selectedSector: string | null;
  onSelectSector: (sector: string | null) => void;
  portfolioNames: Map<string, string>;
  hasAnomaliesWithoutHistory?: boolean;
}) {
  if (sectors.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground" data-testid="radar-heatmap-empty">
        {hasAnomaliesWithoutHistory ? (
          <>
            <p>Heatmap Δ7д по секторам появится после ~7 дней накопления ценовых снимков notifier.</p>
            <p className="mt-1 text-xs">
              Сегодня уже есть аномалии спреда — они в таблице ниже; dip-идеи тоже требуют историю цен.
            </p>
          </>
        ) : (
          <p>Нет данных по секторам</p>
        )}
      </div>
    );
  }

  return (
    <div
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      data-testid="radar-heatmap"
    >
      {sectors.map((row) => {
        const selected = selectedSector === row.sector;
        const inPortfolio = (row.in_portfolios?.length ?? 0) > 0;
        const portfolioHint = row.in_portfolios
          ?.map((id) => portfolioNames.get(id) ?? id)
          .join(", ");

        return (
          <button
            key={row.sector}
            type="button"
            data-testid={`radar-sector-${row.sector}`}
            onClick={() => onSelectSector(selected ? null : row.sector)}
            className={cn(
              "relative rounded-lg border p-3 text-left transition-colors hover:ring-2 hover:ring-primary/30",
              heatmapClass(row.change_7d_pct),
              selected && "ring-2 ring-primary",
            )}
          >
            {inPortfolio && (
              <span
                className="absolute right-2 top-2 h-2.5 w-2.5 rounded-full ring-2 ring-sky-400"
                title={portfolioHint ? `В портфеле: ${portfolioHint}` : "В портфеле"}
                aria-label="В портфеле"
              />
            )}
            <p className="text-sm font-semibold">{sectorLabel(row.sector)}</p>
            <p className="mt-1 font-mono text-lg tabular-nums">
              <span className="text-xs font-sans font-normal text-muted-foreground">Δ7д </span>
              {formatPct(row.change_7d_pct, 1)}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {row.anomaly_count} anom · {row.dip_idea_count} идей · {row.bond_count} бумаг
            </p>
          </button>
        );
      })}
    </div>
  );
}
