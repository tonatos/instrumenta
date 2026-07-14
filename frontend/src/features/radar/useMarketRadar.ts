import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  MarketRadarAnomalyRow,
  MarketRadarDipIdeaRow,
  MarketRadarSectorRow,
} from "@/api/types";

export const MARKET_RADAR_QUERY_KEY = ["market-radar"] as const;

function sortMineFirst<T extends { in_portfolios?: string[] }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const aMine = (a.in_portfolios?.length ?? 0) > 0 ? 1 : 0;
    const bMine = (b.in_portfolios?.length ?? 0) > 0 ? 1 : 0;
    return bMine - aMine;
  });
}

export function useMarketRadar() {
  const [mineFirst, setMineFirst] = useState(true);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  const query = useQuery({
    queryKey: MARKET_RADAR_QUERY_KEY,
    queryFn: () => api.getMarketRadar(true),
    staleTime: 5 * 60_000,
  });

  const sectors = useMemo(() => {
    const rows = query.data?.sectors ?? [];
    return mineFirst ? sortMineFirst(rows) : rows;
  }, [query.data?.sectors, mineFirst]);

  const anomalies = useMemo(() => {
    let rows = query.data?.anomalies ?? [];
    if (selectedSector) {
      rows = rows.filter((a) => a.sector === selectedSector);
    }
    return mineFirst ? sortMineFirst(rows) : rows;
  }, [query.data?.anomalies, mineFirst, selectedSector]);

  const dipIdeas = useMemo(() => {
    let rows = query.data?.dip_ideas ?? [];
    if (selectedSector) {
      rows = rows.filter((d) => d.sector === selectedSector);
    }
    return mineFirst ? sortMineFirst(rows) : rows;
  }, [query.data?.dip_ideas, mineFirst, selectedSector]);

  return {
    ...query,
    sectors,
    anomalies,
    dipIdeas,
    mineFirst,
    setMineFirst,
    selectedSector,
    setSelectedSector,
  };
}

export type { MarketRadarAnomalyRow, MarketRadarDipIdeaRow, MarketRadarSectorRow };
