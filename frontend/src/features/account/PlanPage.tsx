import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { api, ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PlanCheckoutOptions } from "@/features/billing/PlanCheckoutOptions";
import { formatRub } from "@/lib/utils";

/** Marketing teaser: expected net yield of auto-compose (not from API). */
const AUTO_PORTFOLIO_YIELD_PP = 28.46;

const CAPITAL_MIN = 50_000;
const CAPITAL_MAX = 1_000_000;
const CAPITAL_STEP = 10_000;
const CAPITAL_DEFAULT = 100_000;

function kopecksToRub(k: number) {
  return k / 100;
}

function excessYieldPP(autoYieldPP: number, keyRatePP: number) {
  return Math.max(0, autoYieldPP - keyRatePP);
}

function annualExcessRub(capitalRub: number, excessPP: number) {
  return capitalRub * (excessPP / 100);
}

function breakevenRub(yearlyCostRub: number, excessPP: number) {
  if (excessPP <= 0) return 0;
  return yearlyCostRub / (excessPP / 100);
}

export function PlanPage() {
  const [params] = useSearchParams();
  const paymentReturn = params.get("payment") === "return";
  const queryClient = useQueryClient();
  const [capitalRub, setCapitalRub] = useState(CAPITAL_DEFAULT);
  const [error, setError] = useState<string | null>(null);

  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
  });
  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: ["billing-catalog"],
    queryFn: () => api.getBillingCatalog(),
  });
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["billing-status"],
    queryFn: () => api.getBillingStatus(),
  });

  const changeMutation = useMutation({
    mutationFn: () => api.changeBillingPeriod("year"),
    onSuccess: (res) => {
      setError(null);
      if (res.confirmation_url) {
        window.location.assign(res.confirmation_url);
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["billing-status"] });
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Не удалось сменить период");
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelBillingSubscription(),
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["billing-status"] });
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Не удалось отменить");
    },
  });

  const year = catalog?.plans.find((p) => p.period === "year");
  const keyRatePP = config?.key_rate;
  const excessPP = excessYieldPP(AUTO_PORTFOLIO_YIELD_PP, keyRatePP ?? 0);
  const yearlyCost = year ? kopecksToRub(year.amount_kopecks) : 5940;
  const annualExcess = useMemo(
    () => annualExcessRub(capitalRub, excessPP),
    [capitalRub, excessPP],
  );
  const breakeven = useMemo(
    () => breakevenRub(yearlyCost, excessPP),
    [yearlyCost, excessPP],
  );
  const coversSubscription = annualExcess >= yearlyCost;

  if (catalogLoading || statusLoading || configLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const hasAccess = Boolean(status?.has_active_access || status?.complimentary);
  const paymentEnabled = Boolean(catalog?.payment_enabled ?? status?.payment_enabled);

  return (
    <div className="space-y-8">
      {paymentReturn && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          Если оплата прошла успешно, статус обновится в течение минуты.{" "}
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => void queryClient.invalidateQueries({ queryKey: ["billing-status"] })}
          >
            Обновить
          </button>
        </p>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Instrumenta Pro</h2>
        <p className="text-sm text-muted-foreground">
          Подписка открывает привязку брокерского счёта и сохранение ключей T‑Invest. Скринер,
          симуляция, radar и избранное остаются бесплатными после входа через Telegram.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Уведомления в Telegram о пут‑офертах и эскалации риска</li>
          <li>Очередь действий: покупки, реинвест, срочные продажи</li>
          <li>Market radar и сигналы по удерживаемым бумагам</li>
        </ul>
      </section>

      <PlanCheckoutOptions />

      {status?.subscription && (
        <section className="space-y-3 rounded-md border border-border p-4">
          <h3 className="text-sm font-medium">Текущая подписка</h3>
          <p className="text-sm text-muted-foreground">
            Статус: {status.subscription.status} · период: {status.subscription.period} · до{" "}
            {new Date(status.subscription.current_period_end).toLocaleDateString("ru-RU")}
            {status.subscription.cancel_at_period_end ? " · автопродление отключено" : ""}
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            {status.subscription.period === "month" && hasAccess && (
              <Button
                variant="outline"
                className="min-h-10"
                disabled={!paymentEnabled || changeMutation.isPending}
                onClick={() => changeMutation.mutate()}
              >
                Перейти на год
              </Button>
            )}
            {!status.subscription.cancel_at_period_end && hasAccess && !status.complimentary && (
              <Button
                variant="outline"
                className="min-h-10"
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate()}
              >
                Отменить автопродление
              </Button>
            )}
          </div>
        </section>
      )}

      <section className="space-y-4">
        <h2 className="text-lg font-medium">Когда подписка окупается</h2>
        <p className="text-sm text-muted-foreground">
          Избыточная доходность автопортфеля ({AUTO_PORTFOLIO_YIELD_PP.toFixed(2)}%) над ключевой
          ставкой ({keyRatePP != null ? `${keyRatePP}%` : "—"}) ={" "}
          {keyRatePP != null ? `${excessPP.toFixed(2)} п.п.` : "—"}. Ползунок — размер капитала.
        </p>
        <label className="block space-y-2 text-sm">
          <span className="text-muted-foreground">
            Капитал: {formatRub(capitalRub)}
          </span>
          <input
            type="range"
            min={CAPITAL_MIN}
            max={CAPITAL_MAX}
            step={CAPITAL_STEP}
            value={capitalRub}
            onChange={(e) => setCapitalRub(Number(e.target.value))}
            className="w-full accent-foreground"
            aria-label="Размер капитала для инвестиций"
          />
        </label>
        <p className="text-sm">
          При таком капитале избыточный доход ≈{" "}
          <strong>{formatRub(Math.round(annualExcess))}</strong>/год при годовой подписке{" "}
          {formatRub(yearlyCost)}
          {coversSubscription ? " — подписка окупается." : "."}
        </p>
        {breakeven > 0 && (
          <p className="text-xs text-muted-foreground">
            Точка окупаемости ≈ {formatRub(Math.round(breakeven))} портфеля.
          </p>
        )}
      </section>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <p className="text-sm text-muted-foreground">
        Нужны ключи брокера?{" "}
        <Link to="/account" className="underline underline-offset-2">
          Перейти к ключам
        </Link>
        . Telegram-уведомления:{" "}
        <Link to="/account/notifications" className="underline underline-offset-2">
          подключить бота
        </Link>
        .
      </p>
    </div>
  );
}
