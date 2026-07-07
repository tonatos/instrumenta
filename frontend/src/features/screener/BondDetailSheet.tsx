import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, HelpCircle, Star, AlertTriangle } from "lucide-react";
import { api } from "@/api/client";
import type { Bond } from "@/api/types";
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
}

const RISK_LABELS: Record<number, { label: string; className: string }> = {
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
    <div className="flex items-start justify-between gap-2 py-1.5 text-sm">
      <dt className="flex shrink-0 items-center gap-1 text-muted-foreground">
        {label}
        {tooltip && (
          <Tooltip content={<span className="leading-relaxed">{tooltip}</span>} side="left">
            <HelpCircle className="h-3.5 w-3.5 cursor-help opacity-60" />
          </Tooltip>
        )}
      </dt>
      <dd className="text-right font-medium">{value ?? "—"}</dd>
    </div>
  );
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

export function BondDetailSheet({ secid, onClose }: Props) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["bond", secid],
    queryFn: () => api.getBond(secid!),
    enabled: !!secid,
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
  const riskInfo = RISK_LABELS[bond?.risk_level ?? 0];
  const issuerTitle = bond?.issuer_name || bond?.name || "";
  const instrumentSubtitle =
    bond?.instrument_full_name && bond.instrument_full_name !== issuerTitle
      ? bond.instrument_full_name
      : null;
  const showIssuerSection = Boolean(
    bond && (bond.issuer_name || bond.sector || bond.description),
  );

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
                    {bond.sector && <InfoRow label="Сектор" value={bond.sector} />}
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
                  tooltip="Пут-оферта — дата, когда инвестор может потребовать выкупа облигации по заранее оговорённой цене. Удобно, если ставки выросли."
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
                  tooltip="YTM после уплаты НДФЛ (13%). Именно это деньги, которые получает инвестор."
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
            <section>
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Скоринг
                <Tooltip
                  content="Комплексная оценка привлекательности облигации от 0 до 100. Формула: YTM-скор × 0.45 + Риск-скор × 0.35 + Ликвидность-скор × 0.20"
                  side="right"
                >
                  <HelpCircle className="h-3.5 w-3.5 cursor-help opacity-60" />
                </Tooltip>
              </h3>
              <dl className="divide-y divide-border/50">
                <InfoRow
                  label="Итого"
                  value={<ScoreBar value={bond.score} />}
                />
                <InfoRow
                  label="YTM-скор × 0.45"
                  value={<ScoreBar value={bond.ytm_score} />}
                  tooltip="Насколько YTM нетто превышает безрисковую ставку (КС ЦБ). Нормируется по 95-му перцентилю выборки."
                />
                <InfoRow
                  label="Риск-скор × 0.35"
                  value={<ScoreBar value={bond.risk_score} />}
                  tooltip="Оценка риска: уровень риска, рейтинг, штрафы за амортизацию / плавающий купон / субординацию / колл."
                />
                <InfoRow
                  label="Ликвидность × 0.20"
                  value={<ScoreBar value={bond.liquidity_score} />}
                  tooltip="Логарифмическая шкала по объёму торгов в рублях за день."
                />
              </dl>
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
