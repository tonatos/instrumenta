import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { RATE_SCENARIO_HINTS, RATE_SCENARIO_LABELS } from "@/features/portfolio/labels";
import { useRateScenario } from "@/features/settings/RateScenarioProvider";
import { TAX_RATE_OPTIONS, taxRateLabel } from "@/features/settings/taxRate";
import type { RateScenario } from "@/features/settings/durationPreferences";
import { formatRub } from "@/lib/utils";

interface SettingsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SCENARIOS: RateScenario[] = ["hold", "cut", "hike"];

export function SettingsSheet({ open, onOpenChange }: SettingsSheetProps) {
  const queryClient = useQueryClient();
  const { rateScenario, setRateScenario } = useRateScenario();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    enabled: open,
  });

  const taxMutation = useMutation({
    mutationFn: (taxRate: number) => api.putPreferences(taxRate),
    onSuccess: async (resp) => {
      queryClient.setQueryData(["config"], (prev: typeof data) =>
        prev ? { ...prev, tax_rate: resp.tax_rate } : prev,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["config"] }),
        queryClient.invalidateQueries({ queryKey: ["bonds"] }),
        queryClient.invalidateQueries({ queryKey: ["plan"] }),
        queryClient.invalidateQueries({ queryKey: ["trading-state"] }),
      ]);
    },
  });

  const handleScenarioChange = (value: RateScenario) => {
    setRateScenario(value);
    void queryClient.invalidateQueries({ queryKey: ["bonds"] });
    void queryClient.invalidateQueries({ queryKey: ["plan"] });
    void queryClient.invalidateQueries({ queryKey: ["trading-state"] });
  };

  const handleTaxChange = (raw: string) => {
    const pct = Number(raw);
    if (Number.isNaN(pct)) return;
    taxMutation.mutate(pct);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>Настройки</SheetTitle>
        </SheetHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="text-sm font-medium">Сценарий по ключевой ставке</p>
            <p className="text-xs text-muted-foreground">
              Влияет на ранжирование в скринере и подбор бумаг в портфеле. Сохраняется локально в браузере.
            </p>
            <select
              aria-label="Сценарий по ключевой ставке"
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              value={rateScenario}
              onChange={(e) => handleScenarioChange(e.target.value as RateScenario)}
            >
              {SCENARIOS.map((scenario) => (
                <option key={scenario} value={scenario}>
                  {RATE_SCENARIO_LABELS[scenario]}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              <Tooltip content={RATE_SCENARIO_HINTS[rateScenario]}>
                <span className="cursor-help underline decoration-dotted underline-offset-2">
                  {RATE_SCENARIO_HINTS[rateScenario]}
                </span>
              </Tooltip>
            </p>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">НДФЛ</p>
            <p className="text-xs text-muted-foreground">
              Учитывается в YTM net, скоринге и плане портфеля. Сохраняется в профиле.
            </p>
            <select
              aria-label="НДФЛ"
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              value={data?.tax_rate ?? 13}
              disabled={isLoading || taxMutation.isPending || data == null}
              onChange={(e) => handleTaxChange(e.target.value)}
            >
              {TAX_RATE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {taxMutation.isError && (
              <p className="text-xs text-destructive">Не удалось сохранить ставку НДФЛ</p>
            )}
          </div>

          {isLoading && <Skeleton className="h-32 w-full" />}
          {data && (
            <dl className="space-y-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted-foreground">
                  <Tooltip content="Актуальная ключевая ставка Банка России. Обновляется раз в сутки.">
                    <span className="cursor-help underline decoration-dotted underline-offset-2">
                      Ключевая ставка
                    </span>
                  </Tooltip>
                </dt>
                <dd>{data.key_rate}%</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">НДФЛ (текущий)</dt>
                <dd>{taxRateLabel(data.tax_rate)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">
                  <Tooltip content="Начальное значение фильтра «Макс. срок» в скринере. Фильтрация выполняется на сервере при каждом запросе.">
                    <span className="cursor-help underline decoration-dotted underline-offset-2">Макс. срок</span>
                  </Tooltip>
                </dt>
                <dd>{data.max_days} дн.</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">
                  <Tooltip content="Начальное значение фильтра «Мин. объём» в скринере. Фильтрация выполняется на сервере при каждом запросе.">
                    <span className="cursor-help underline decoration-dotted underline-offset-2">Мин. объём</span>
                  </Tooltip>
                </dt>
                <dd>{formatRub(data.min_volume_rub)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">T-Invest (read)</dt>
                <dd>{data.tinkoff_configured ? "✓" : "—"}</dd>
              </div>
            </dl>
          )}
          <div className="flex flex-col gap-2">
            <Button variant="outline" asChild>
              <Link to="/account" onClick={() => onOpenChange(false)}>
                Брокерские ключи
              </Link>
            </Button>
            <Button variant="outline" onClick={() => api.refreshBonds().then(() => refetch())}>
              Обновить данные MOEX
            </Button>
            <Button variant="outline" onClick={() => api.refreshRatings()}>
              Обновить рейтинги
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
