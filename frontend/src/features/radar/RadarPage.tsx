import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Activity, X } from "lucide-react";
import { api } from "@/api/client";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import {
  getScreenerRiskProfile,
  setScreenerRiskProfile,
  subscribeScreenerRiskProfile,
  type ScreenerRiskProfile,
} from "@/features/screener/screenerRiskProfile";
import { AnomaliesTable } from "@/features/radar/AnomaliesTable";
import { DipIdeasPanel } from "@/features/radar/DipIdeasPanel";
import { SectorHeatmap } from "@/features/radar/SectorHeatmap";
import { useMarketRadar } from "@/features/radar/useMarketRadar";
import { sectorLabel } from "@/features/bonds/sectorLabels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  SelectContent,
  SelectItem,
  SelectRoot,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";

function formatScannedAt(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return formatDate(value);
  return date.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const RISK_PROFILES: { value: ScreenerRiskProfile; label: string }[] = [
  { value: "conservative", label: "Консервативный" },
  { value: "normal", label: "Нормальный" },
  { value: "aggressive", label: "Агрессивный" },
];

export function RadarPage() {
  const [detailSecid, setDetailSecid] = useState<string | null>(null);
  const [riskProfile, setRiskProfile] = useState<ScreenerRiskProfile>(getScreenerRiskProfile);

  const {
    data,
    isLoading,
    isError,
    sectors,
    anomalies,
    dipIdeas,
    mineFirst,
    setMineFirst,
    selectedSector,
    setSelectedSector,
  } = useMarketRadar();

  const { data: portfolios } = useQuery({
    queryKey: ["portfolios"],
    queryFn: api.getPortfolios,
  });

  const portfolioNames = useMemo(
    () => new Map((portfolios ?? []).map((p) => [p.id, p.name])),
    [portfolios],
  );

  const fallbackPortfolioId = useMemo(() => {
    const trading = (portfolios ?? []).find((p) => p.mode === "trading");
    return trading?.id ?? portfolios?.[0]?.id ?? null;
  }, [portfolios]);

  useEffect(() => subscribeScreenerRiskProfile(() => setRiskProfile(getScreenerRiskProfile())), []);

  if (isLoading) {
    return (
      <div className="space-y-6" data-testid="radar-page">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-32 w-full" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg border border-dashed border-border py-16 text-center" data-testid="radar-page">
        <Activity className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" />
        <p className="text-sm font-medium">Не удалось загрузить radar</p>
        <p className="mt-1 text-xs text-muted-foreground">Проверьте API и повторите позже.</p>
      </div>
    );
  }

  const emptySnapshot =
    !data.scanned_at ||
    (data.universe_scanned === 0 &&
      data.sectors.length === 0 &&
      data.anomalies.length === 0 &&
      data.dip_ideas.length === 0);

  if (emptySnapshot) {
    return (
      <div className="rounded-lg border border-dashed border-border py-16 text-center" data-testid="radar-page">
        <Activity className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" />
        <p className="text-sm font-medium">Radar ещё не сканировался</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Запустите notifier — после первого цикла здесь появятся аномалии и идеи на просадке.
        </p>
      </div>
    );
  }

  const scannedLabel = formatScannedAt(data.scanned_at);

  return (
    <div className="space-y-6" data-testid="radar-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Activity className="h-6 w-6 text-sky-600" />
            Radar рынка
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Аномалии спреда и просадки по секторам · {data.universe_scanned} бумаг
          </p>
          {scannedLabel && (
            <p className="mt-1 text-xs text-muted-foreground">Обновлено {scannedLabel}</p>
          )}
          <p className="mt-2 text-xs">
            <Link to="/portfolio" className="text-sky-700 underline-offset-2 hover:underline dark:text-sky-300">
              Сигналы по моим позициям → Портфель
            </Link>
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={mineFirst}
              onCheckedChange={(v) => setMineFirst(v === true)}
              data-testid="radar-mine-first-toggle"
            />
            Сначала мои позиции
          </label>
          <SelectRoot
            value={riskProfile}
            onValueChange={(value) => {
              const next = value as ScreenerRiskProfile;
              setScreenerRiskProfile(next);
              setRiskProfile(next);
            }}
          >
            <SelectTrigger className="h-9 w-full sm:w-[180px]" data-testid="radar-risk-profile">
              <SelectValue placeholder="Профиль риска">
                {RISK_PROFILES.find((p) => p.value === riskProfile)?.label}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {RISK_PROFILES.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </SelectRoot>
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Heatmap секторов</h2>
        <SectorHeatmap
          sectors={sectors}
          selectedSector={selectedSector}
          onSelectSector={setSelectedSector}
          portfolioNames={portfolioNames}
          hasAnomaliesWithoutHistory={data.anomalies.length > 0}
        />
        {selectedSector && (
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="gap-1">
              {sectorLabel(selectedSector)}
              <button
                type="button"
                aria-label="Сбросить фильтр сектора"
                onClick={() => setSelectedSector(null)}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
            <Button variant="ghost" size="sm" onClick={() => setSelectedSector(null)}>
              Показать все секторы
            </Button>
          </div>
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold">Топ аномалий спреда</h2>
          <AnomaliesTable anomalies={anomalies} onSelectBond={setDetailSecid} />
        </section>
        <section className="space-y-3">
          <h2 className="text-sm font-semibold">Идеи на просадке</h2>
          <DipIdeasPanel
            dipIdeas={dipIdeas}
            portfolios={portfolios ?? []}
            fallbackPortfolioId={fallbackPortfolioId}
          />
        </section>
      </div>

      <BondDetailSheet
        secid={detailSecid}
        onClose={() => setDetailSecid(null)}
        riskProfile={riskProfile}
      />
    </div>
  );
}
