import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, HelpCircle, Star, AlertTriangle } from "lucide-react";
import { api } from "@/api/client";
import type { Bond } from "@/api/types";
import {
  PROFILE_SCORE_WEIGHTS,
  type BondRiskProfile,
} from "@/features/bonds/bondScore";
import { sectorLabel } from "@/features/bonds/sectorLabels";
import { isMarketSignal } from "@/features/portfolio/marketSignals";
import { OFFER_WINDOW_STATUS_LABELS, RISK_LABELS } from "@/features/portfolio/labels";
import { useRateScenario } from "@/features/settings/RateScenarioProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatDate, formatPct, formatRub } from "@/lib/utils";

interface Props {
  secid: string | null;
  onClose: () => void;
  riskProfile?: BondRiskProfile;
  portfolioId?: string;
  isin?: string | null;
}

const RISK_LEVEL_LABELS: Record<number, { label: string; className: string }> = {
  0: { label: "Неизвестен", className: "bg-muted text-muted-foreground" },
  1: { label: "Низкий", className: "bg-green-500/15 text-green-700 dark:text-green-400" },
  2: { label: "Умеренный", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  3: { label: "Высокий", className: "bg-red-500/15 text-red-700 dark:text-red-400" },
};

const COUPON_TYPE_LABELS: Record<string, string> = {
  fixed: "Фиксированный",
  floating: "Плавающий",
  variable: "Переменный",
  unknown: "Неизвестен",
};

function InfoRow({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: React.ReactNode;
  tooltip?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 py-1.5 text-sm sm:flex-row sm:items-start sm:justify-between sm:gap-2">
      <dt className="flex shrink-0 items-center gap-1 text-muted-foreground">
        {label}
        {tooltip && (
          <Tooltip content={<span className="leading-relaxed">{tooltip}</span>} side="top">
            <HelpCircle className="h-3.5 w-3.5 cursor-help opacity-60" />
          </Tooltip>
        )}
      </dt>
      <dd className="min-w-0 break-words font-medium sm:text-right">{value ?? "—"}</dd>
    </div>
  );
}

const PROFILE_KEYS: BondRiskProfile[] = ["conservative", "normal", "aggressive"];

function formatWeight(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, "");
}

function ScoreBar({ value, max = 100 }: { value: number | null; max?: number }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const pct = Math.min(100, (value / max) * 100);
  const color =
    pct >= 60 ? "bg-green-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span>{value.toFixed(1)}</span>
    </div>
  );
}

function ComponentCard({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: number | null;
  tooltip?: string;
}) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="mb-2 flex items-center gap-1 text-xs text-muted-foreground">
        <span>{label}</span>
        {tooltip && (
          <Tooltip content={<span className="leading-relaxed">{tooltip}</span>} side="top">
            <HelpCircle className="h-3 w-3 cursor-help opacity-60" />
          </Tooltip>
        )}
      </div>
      <ScoreBar value={value} />
    </div>
  );
}

function ProfileScoreCard({
  profile,
  score,
  isActive,
}: {
  profile: BondRiskProfile;
  score: number | null;
  isActive: boolean;
}) {
  const weights = PROFILE_SCORE_WEIGHTS[profile];
  return (
    <div
      className={cn(
        "flex flex-col rounded-lg border p-3 transition-colors",
        isActive
          ? "border-primary bg-primary/5 shadow-sm"
          : "border-border/60 bg-background",
      )}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {RISK_LABELS[profile]}
        </span>
        {isActive && (
          <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-normal">
            в скринере
          </Badge>
        )}
      </div>
      <div className="mb-2 text-2xl font-semibold tabular-nums">
        {score != null ? score.toFixed(0) : "—"}
      </div>
      <ScoreBar value={score} />
      <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
        {formatWeight(weights.ytm)}×YTM + {formatWeight(weights.risk)}×Риск +{" "}
        {formatWeight(weights.liquidity)}×Ликв.
      </p>
    </div>
  );
}

export function BondDetailSheet({
  secid,
  onClose,
  riskProfile = "normal",
  portfolioId,
  isin,
}: Props) {
  const queryClient = useQueryClient();
  const rateScenario = useRateScenario();

  const { data, isLoading } = useQuery({
    queryKey: ["bond", secid, riskProfile, rateScenario],
    queryFn: () => api.getBond(secid!, riskProfile),
    enabled: !!secid,
  });

  const { data: notificationsData } = useQuery({
    queryKey: ["notifications", portfolioId],
    queryFn: () => api.getNotifications(portfolioId!),
    enabled: Boolean(portfolioId),
    refetchInterval: 60_000,
  });

  const toggleFavorite = useMutation({
    mutationFn: async (bond: Bond) => {
      if (bond.is_favorite) await api.removeFavorite(bond.isin);
      else await api.addFavorite(bond.isin);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bonds"] });
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
      queryClient.invalidateQueries({ queryKey: ["bond", secid] });
    },
  });

  const bond = data?.bond;
  const lotPriceRub =
    bond?.last_price != null
      ? (bond.last_price / 100) * bond.face_value * bond.lot_size
      : null;
  const riskInfo = RISK_LEVEL_LABELS[bond?.risk_level ?? 0];
  const issuerTitle = bond?.issuer_name || bond?.name || "";
  const instrumentSubtitle =
    bond?.instrument_full_name && bond.instrument_full_name !== issuerTitle
      ? bond.instrument_full_name
      : null;
  const showIssuerSection = Boolean(
    bond && (bond.issuer_name || bond.sector || bond.description),
  );

  const signal = (() => {
    if (!isin) return null;
    const items = (notificationsData?.notifications ?? []).filter((n) => {
      if (!isMarketSignal(n)) {
        return false;
      }
      return typeof n.payload?.isin === "string" && n.payload.isin === isin;
    });
    if (items.length === 0) return null;
    items.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    return items[0];
  })();

  return (
    <Sheet open={!!secid} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {isLoading && (
          <div className="space-y-3 pt-6">
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-48 w-full" />
          </div>
        )}
        {bond && (
          <div className="space-y-5 pb-8">
            <SheetHeader>
              <SheetTitle className="pr-8 text-base leading-snug">{issuerTitle}</SheetTitle>
              {instrumentSubtitle && (
                <p className="pr-8 text-sm text-muted-foreground">{instrumentSubtitle}</p>
              )}
            </SheetHeader>

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => toggleFavorite.mutate(bond)}
                disabled={toggleFavorite.isPending}
              >
                <Star
                  className={cn(
                    "mr-2 h-4 w-4",
                    bond.is_favorite && "fill-amber-400 text-amber-400",
                  )}
                />
                {bond.is_favorite ? "В избранном" : "В избранное"}
              </Button>
              {bond.isin && (
                <Button variant="outline" size="sm" asChild>
                  <a
                    href={`https://www.tbank.ru/invest/bonds/${bond.isin}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Т-Инвестиции
                  </a>
                </Button>
              )}
              {bond.has_warnings && (
                <Badge variant="destructive" className="gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Есть риски
                </Badge>
              )}
            </div>

            <Separator />

            {showIssuerSection && (
              <>
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Эмитент
                  </h3>
                  <dl className="divide-y divide-border/50">
                    {bond.sector && <InfoRow label="Сектор" value={sectorLabel(bond.sector)} />}
                  </dl>
                  {bond.description && (
                    <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                      {bond.description}
                    </p>
                  )}
                </section>
                <Separator />
              </>
            )}

            {signal && (
              <>
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Рыночный контекст
                  </h3>
                  <div className="space-y-2 rounded-lg border border-sky-400/40 bg-sky-500/5 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="text-sm font-medium">{signal.payload?.name as string}</p>
                      <Badge variant="outline" className="text-xs">
                        {signal.kind}
                      </Badge>
                    </div>
                    {typeof signal.payload?.reason === "string" && (
                      <p className="text-sm text-muted-foreground">{signal.payload.reason}</p>
                    )}
                    <dl className="divide-y divide-border/50">
                      {typeof signal.payload?.bond_change_7d_pct === "number" && (
                        <InfoRow
                          label="Бумага (7д)"
                          value={`${signal.payload.bond_change_7d_pct.toFixed(1)}%`}
                        />
                      )}
                      {typeof signal.payload?.sector_change_7d_pct === "number" && (
                        <InfoRow
                          label="Сектор (7д)"
                          value={`${signal.payload.sector_change_7d_pct.toFixed(1)}%`}
                        />
                      )}
                      {typeof signal.payload?.spread_change_7d_pp === "number" && (
                        <InfoRow
                          label="Спред (7д)"
                          value={`${signal.payload.spread_change_7d_pp.toFixed(1)} п.п.`}
                        />
                      )}
                    </dl>
                  </div>
                </section>
                <Separator />
              </>
            )}

            {/* Идентификаторы */}
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Идентификаторы
              </h3>
              <dl className="divide-y divide-border/50">
                <InfoRow label="SECID" value={bond.secid} />
                <InfoRow label="ISIN" value={bond.isin} />
                <InfoRow label="FIGI" value={bond.figi || "—"} />
              </dl>
            </section>

            <Separator />

            {/* Основные параметры */}
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Параметры
              </h3>
              <dl className="divide-y divide-border/50">
                <InfoRow
                  label="Дата погашения"
                  value={formatDate(bond.maturity_date)}
                />
                <InfoRow
                  label="Дата пут-оферты"
                  value={formatDate(bond.offer_date)}
                  tooltip="Дата исполнения пут-оферты — когда поступят деньги, если вы подали заявку в окне приёма."
                />
                <InfoRow
                    label="Окно подачи"
                    value={
                      bond.offer_submission_start && bond.offer_submission_end
                        ? `${formatDate(bond.offer_submission_start)} — ${formatDate(bond.offer_submission_end)}`
                        : bond.offer_date
                          ? "ещё не объявлено"
                          : "—"
                    }
                  tooltip="Период, когда можно подать заявку эмитенту на досрочный выкуп."
                />
                <InfoRow
                  label="Цена выкупа"
                  value={
                    bond.offer_price_pct != null ? `${bond.offer_price_pct.toFixed(2)}%` : "—"
                  }
                />
                <InfoRow
                  label="Статус оферты"
                  value={
                    bond.offer_window_status
                      ? (OFFER_WINDOW_STATUS_LABELS[bond.offer_window_status] ??
                        bond.offer_window_status)
                      : "—"
                  }
                />
                <InfoRow
                  label="Дата колл-оферты"
                  value={formatDate(bond.call_date)}
                  tooltip="Колл-оферта — дата, когда эмитент может досрочно выкупить облигацию. После колла выплаты по купонам прекращаются."
                />
                <InfoRow
                  label="Эффективная дата"
                  value={formatDate(bond.effective_date)}
                  tooltip="Ближайшая из дат погашения и оферты — именно по ней рассчитывается YTM."
                />
                <InfoRow
                  label="Дней до погашения"
                  value={bond.days_to_maturity != null ? `${bond.days_to_maturity} д.` : "—"}
                />
                <InfoRow
                  label="YTM брутто"
                  value={formatPct(bond.ytm)}
                  tooltip="Yield to Maturity — доходность к погашению до уплаты НДФЛ. Годовых, при покупке по текущей цене."
                />
                <InfoRow
                  label="YTM нетто"
                  value={formatPct(bond.ytm_net)}
                  tooltip="YTM после уплаты НДФЛ по вашей ставке из настроек. Именно это деньги, которые получает инвестор."
                />
                <InfoRow
                  label="Купон, % год."
                  value={formatPct(bond.coupon_rate)}
                />
                <InfoRow
                  label="Тип купона"
                  value={COUPON_TYPE_LABELS[bond.coupon_type] ?? bond.coupon_type}
                  tooltip="Фиксированный — ставка не меняется. Плавающий — привязан к ключевой ставке или RUONIA. Переменный — следующий купон объявляется эмитентом."
                />
                <InfoRow
                  label="Номинал"
                  value={formatRub(bond.face_value)}
                />
                <InfoRow
                  label="Размер лота"
                  value={`${bond.lot_size} облиг.`}
                  tooltip="Минимальная единица покупки в лотах."
                />
                <InfoRow
                  label="Цена, % от номинала"
                  value={bond.last_price != null ? `${bond.last_price.toFixed(2)}%` : "—"}
                />
                <InfoRow
                  label="Стоимость лота, ₽"
                  value={formatRub(lotPriceRub)}
                  tooltip="Приблизительная стоимость покупки одного лота по текущей цене: цена% × номинал × лотность. Без учёта НКД."
                />
                <InfoRow
                  label="Объём торгов, ₽/день"
                  value={formatRub(bond.volume_rub)}
                  tooltip="Средний дневной оборот на MOEX. Низкий объём означает риск ликвидности — сложно продать без потерь в цене."
                />
                <InfoRow
                  label="Уровень риска"
                  value={
                    <Badge className={cn("font-normal", riskInfo.className)}>
                      {riskInfo.label}
                    </Badge>
                  }
                  tooltip="1 — Низкий: ОФЗ, крупные госкорпорации. 2 — Умеренный: крупные частные компании с хорошим рейтингом. 3 — Высокий: компании с рейтингом BB и ниже или без рейтинга."
                />
                <InfoRow
                  label="Кредитный рейтинг"
                  value={bond.credit_rating ?? "—"}
                />
                <InfoRow
                  label="Обогащён T-Invest"
                  value={
                    <span className={bond.tinvest_enriched ? "text-green-600" : "text-muted-foreground"}>
                      {bond.tinvest_enriched ? "Да" : "Нет"}
                    </span>
                  }
                  tooltip="Дополнительные данные получены из T-Invest API: FIGI, НКД, флаги риска. Без обогащения часть данных может отсутствовать."
                />
              </dl>
            </section>

            <Separator />

            {/* Скоринг */}
            <section className="space-y-4">
              <div className="flex items-center gap-1.5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Скоринг
                </h3>
                <Tooltip
                  content="Комплексная оценка 0–100: взвешенная сумма компонентов плюс корректировка дюрации под сценарий по ставке. Скор в таблице совпадает с выбранным профилем."
                  side="right"
                >
                  <HelpCircle className="h-3.5 w-3.5 cursor-help opacity-60" />
                </Tooltip>
              </div>

              <div>
                <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Составляющие
                </h4>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <ComponentCard
                    label="YTM"
                    value={bond.ytm_score}
                    tooltip="Насколько YTM нетто превышает безрисковую ставку (КС ЦБ). Нормируется по 95-му перцентилю выборки."
                  />
                  <ComponentCard
                    label="Риск"
                    value={bond.risk_score}
                    tooltip="Оценка риска: уровень риска, рейтинг, штрафы за амортизацию / плавающий купон / субординацию / колл."
                  />
                  <ComponentCard
                    label="Ликвидность"
                    value={bond.liquidity_score}
                    tooltip="Логарифмическая шкала по объёму торгов в рублях за день."
                  />
                </div>
                {bond.duration_adjustment != null && bond.duration_adjustment !== 0 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Корректировка дюрации:{" "}
                    <span className="font-medium text-foreground">
                      {bond.duration_adjustment > 0 ? "+" : ""}
                      {bond.duration_adjustment.toFixed(1)} п.п.
                    </span>
                  </p>
                )}
              </div>

              <div>
                <h4 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Итог по стратегиям
                </h4>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {PROFILE_KEYS.map((profile) => (
                    <ProfileScoreCard
                      key={profile}
                      profile={profile}
                      score={bond.profile_scores?.[profile] ?? null}
                      isActive={profile === riskProfile}
                    />
                  ))}
                </div>
              </div>
            </section>

            {/* Предупреждения */}
            {bond.warnings.length > 0 && (
              <>
                <Separator />
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-destructive">
                    Предупреждения
                  </h3>
                  <ul className="space-y-2">
                    {bond.warnings.map((w, i) => (
                      <li key={i} className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>{w}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              </>
            )}

            {/* Купонный график */}
            {data.coupons && (data.coupons as unknown[]).length > 0 && (
              <>
                <Separator />
                <section>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Купонный график
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {(data.coupons as unknown[]).length} выплат (T-Invest)
                  </p>
                </section>
              </>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
