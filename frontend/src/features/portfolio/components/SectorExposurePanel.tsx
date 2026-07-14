import { useMemo } from "react";
import type { Bond, PortfolioPosition } from "@/api/types";
import { normalizeSectorKey, sectorLabel } from "@/features/bonds/sectorLabels";
import { cn, formatPct, formatRub } from "@/lib/utils";

const MAX_SECTOR_SHARE_DEFAULT = 0.35;

export type SectorExposure = {
  sector: string;
  value_rub: number;
  share: number;
  positions: number;
};

export function buildSectorExposures(
  positions: PortfolioPosition[],
  bonds: Bond[],
): SectorExposure[] {
  const bondsByIsin = new Map(bonds.map((b) => [b.isin, b]));
  const bySector = new Map<string, { value: number; positions: number }>();
  let total = 0;

  for (const pos of positions) {
    const value = pos.purchase_amount_rub ?? 0;
    if (value <= 0) continue;
    total += value;

    const sector = normalizeSectorKey(bondsByIsin.get(pos.isin)?.sector);
    const current = bySector.get(sector) ?? { value: 0, positions: 0 };
    current.value += value;
    current.positions += 1;
    bySector.set(sector, current);
  }

  const result: SectorExposure[] = Array.from(bySector.entries()).map(([sector, v]) => ({
    sector,
    value_rub: v.value,
    share: total > 0 ? v.value / total : 0,
    positions: v.positions,
  }));

  result.sort((a, b) => b.value_rub - a.value_rub);
  return result;
}

export function SectorExposurePanel({
  positions,
  bonds,
  maxSectorShare = MAX_SECTOR_SHARE_DEFAULT,
}: {
  positions: PortfolioPosition[];
  bonds: Bond[];
  maxSectorShare?: number;
}) {
  const exposures = useMemo(
    () => buildSectorExposures(positions, bonds),
    [positions, bonds],
  );

  if (exposures.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-border p-3">
      <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <div>
          <div className="text-sm font-semibold">Структура по секторам</div>
          <div className="text-xs text-muted-foreground">
            Доли рассчитаны по сумме «Вложено» (не по текущей рыночной цене).
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          Лимит: {formatPct(maxSectorShare * 100, 0)}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 text-left font-medium">Сектор</th>
              <th className="py-1 text-right font-medium">Доля</th>
              <th className="py-1 text-right font-medium">Вложено</th>
              <th className="py-1 text-right font-medium">Позиций</th>
            </tr>
          </thead>
          <tbody>
            {exposures.map((e) => {
              const isOver = maxSectorShare > 0 && e.share > maxSectorShare;
              return (
                <tr key={e.sector} className="border-t border-border">
                  <td className="py-1 pr-2">
                    <span className={cn(isOver && "font-semibold text-destructive")}>
                      {sectorLabel(e.sector)}
                    </span>
                  </td>
                  <td className={cn("py-1 text-right", isOver && "font-semibold text-destructive")}>
                    {formatPct(e.share * 100)}
                  </td>
                  <td className="py-1 text-right">{formatRub(e.value_rub)}</td>
                  <td className="py-1 text-right">{e.positions}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
