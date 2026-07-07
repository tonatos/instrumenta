import { useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { OrderPreviewResponse, PendingOperation } from "@/api/types";
import { KIND_LABELS } from "@/features/portfolio/labels";
import {
  previewMatchesForm,
  useOrderPreview,
} from "@/features/portfolio/trading/hooks/useOrderPreview";
import {
  formatLotPriceHint,
} from "@/features/portfolio/trading/pricing";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatPct, formatRub } from "@/lib/utils";

function PricingRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div className="text-right">
        <span className="font-medium tabular-nums">{value}</span>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  );
}

export function ConfirmOrderDialog({
  op,
  portfolioId,
  open,
  onOpenChange,
  isProduction,
  onSubmit,
  isPending,
  error,
}: {
  op: PendingOperation | null;
  portfolioId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isProduction: boolean;
  onSubmit: (lots: number, pricePct: number) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [lots, setLots] = useState(1);
  const [pricePct, setPricePct] = useState("");
  const parsedPricePct = parseFloat(pricePct);

  useEffect(() => {
    if (op) {
      setLots(op.lots);
      const initialPrice =
        op.active_order_price_pct ?? op.suggested_price_pct ?? null;
      setPricePct(initialPrice != null ? initialPrice.toFixed(4) : "");
    }
  }, [op]);

  const { preview, previewLoading, previewError, isBuy, isSell } = useOrderPreview({
    open,
    op,
    portfolioId,
    lots,
    parsedPricePct,
  });

  if (!op) return null;

  const isSellOp = op.kind === "manual_sell";
  const lotSize = op.lot_size ?? 1;
  const faceValueRub = op.face_value_rub ?? 1000;
  const previewApplies =
    preview != null &&
    Number.isFinite(parsedPricePct) &&
    previewMatchesForm(preview, lots, parsedPricePct);
  const aciRubPerBond =
    (previewApplies ? preview?.aci_rub_per_bond : null) ??
    op.aci_rub_per_bond ??
    0;
  const pricePerLotHint =
    Number.isFinite(parsedPricePct) && parsedPricePct > 0
      ? formatLotPriceHint({
          pricePct: parsedPricePct,
          faceValueRub,
          lotSize,
          aciRubPerBond,
        })
      : null;
  const suggestedLotPriceHint =
    op.suggested_price_pct != null
      ? formatLotPriceHint({
          pricePct: op.suggested_price_pct,
          faceValueRub,
          lotSize,
          aciRubPerBond: op.aci_rub_per_bond ?? 0,
        })
      : null;
  const brokerPreview =
    previewApplies && preview?.preview_source === "broker" ? preview : null;
  const insufficientCash = isBuy && previewApplies && !preview!.sufficient_cash;
  const totalToPay =
    brokerPreview?.broker_total_amount_rub ??
    (previewApplies ? preview?.local_total_amount_rub : null);

  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isSellOp ? "Подтвердить продажу" : "Подтвердить покупку"}
          </DialogTitle>
          <DialogDescription>
            {op.name} · {KIND_LABELS[op.kind]}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {isProduction && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              Реальные деньги. Заявка будет отправлена на биржу.
            </div>
          )}

          {isBuy && (
            <p className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
              На биржу уходит лимитная заявка по{" "}
              <span className="font-medium text-foreground">чистой</span> цене (% от
              номинала). НКД и комиссия спишутся дополнительно при исполнении.
            </p>
          )}

          {isSellOp && (
            <p className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
              Лимитная заявка на продажу по{" "}
              <span className="font-medium text-foreground">чистой</span> цене. НКД и
              комиссия учтутся при исполнении.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                Лоты
              </label>
              <Input
                type="number"
                min={1}
                value={lots}
                onChange={(e) => setLots(Math.max(1, Number(e.target.value)))}
              />
              {lotSize > 1 && (
                <p className="mt-1 text-xs text-muted-foreground">
                  1 лот = {lotSize} бумаг · всего {lots * lotSize} шт
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                Лимит (чистая цена), %
              </label>
              <Input
                type="number"
                step="0.01"
                min={0}
                value={pricePct}
                onChange={(e) => setPricePct(e.target.value)}
              />
              {pricePerLotHint && (
                <p className="mt-1 text-xs text-muted-foreground">
                  ≈ {pricePerLotHint} за лот
                </p>
              )}
            </div>
          </div>

          {(isBuy || isSellOp) && op.suggested_price_pct != null && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => setPricePct(op.suggested_price_pct!.toFixed(4))}
            >
              Сбросить к рекомендуемой ({op.suggested_price_pct.toFixed(4)}%
              {suggestedLotPriceHint ? ` · ≈ ${suggestedLotPriceHint}/лот` : ""})
            </Button>
          )}

          {(isBuy || isSellOp) && (previewLoading || previewApplies || previewError) && (
            <div className="space-y-2 rounded-lg border border-blue-400/30 bg-blue-500/5 p-3">
              <p className="text-xs font-medium text-blue-900 dark:text-blue-200">
                {brokerPreview ? "Расчёт брокера" : "Оценка по MOEX"}
              </p>
              {previewLoading && (
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Запрашиваем стоимость у брокера…
                </p>
              )}
              {previewError && (
                <p className="text-xs text-destructive">{previewError}</p>
              )}
              {previewApplies && preview && (
                <PreviewDetails
                  preview={preview}
                  brokerPreview={brokerPreview}
                  isSell={isSellOp}
                />
              )}
            </div>
          )}

          {insufficientCash && (
            <p className="flex items-start gap-1.5 text-sm text-amber-800 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              По оценке брокера на счёте может не хватить средств
              {totalToPay != null ? ` (~${formatRub(totalToPay)} при ${formatRub(preview!.money_rub)} на счёте)` : ""}.
              Заявку всё равно можно отправить — биржа примет или отклонит.
            </p>
          )}

          <p className="text-xs text-muted-foreground">{op.reason}</p>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Отмена
          </Button>
          <Button
            onClick={() => onSubmit(lots, parseFloat(pricePct))}
            disabled={
              isPending ||
              !pricePct ||
              Number.isNaN(parseFloat(pricePct))
            }
          >
            {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Отправить заявку
          </Button>
        </DialogFooter>
      </DialogContent>
    </DialogRoot>
  );
}

function PreviewDetails({
  preview,
  brokerPreview,
  isSell = false,
}: {
  preview: OrderPreviewResponse;
  brokerPreview: OrderPreviewResponse | null;
  isSell?: boolean;
}) {
  const cleanTotal =
    brokerPreview?.broker_clean_amount_rub ?? preview.clean_amount_rub;
  const cleanPerLot = cleanTotal / preview.order_lots;
  const dirtyPerLot = cleanPerLot + preview.aci_rub_per_bond * preview.lot_size;

  return (
    <div className="space-y-2">
      <PricingRow
        label="Цена за лот"
        value={formatRub(cleanPerLot)}
        hint={
          preview.aci_rub_per_bond > 0
            ? `${formatRub(dirtyPerLot)} с НКД · лимит ${formatPct(preview.order_price_pct)}`
            : `лимит ${formatPct(preview.order_price_pct)} от номинала`
        }
      />
      <PricingRow
        label="Бумаг"
        value={`${preview.order_bonds} шт`}
        hint={`${preview.order_lots} лот × ${preview.lot_size} шт`}
      />
      {brokerPreview?.broker_clean_amount_rub != null && (
        <PricingRow
          label="Чистая стоимость"
          value={formatRub(brokerPreview.broker_clean_amount_rub)}
          hint={`${preview.order_lots} лот × ${formatRub(cleanPerLot)}`}
        />
      )}
      {brokerPreview?.broker_aci_amount_rub != null &&
        brokerPreview.broker_aci_amount_rub > 0 && (
          <PricingRow
            label="НКД"
            value={formatRub(brokerPreview.broker_aci_amount_rub)}
          />
        )}
      {brokerPreview?.broker_commission_rub != null &&
        brokerPreview.broker_commission_rub > 0 && (
          <PricingRow
            label="Комиссия"
            value={formatRub(brokerPreview.broker_commission_rub)}
          />
        )}
      {!brokerPreview && (
        <PricingRow
          label="Оценка"
          value={formatRub(preview.local_total_amount_rub)}
          hint="брокер недоступен, расчёт по MOEX"
        />
      )}
      <PricingRow
        label={isSell ? "Итого к зачислению" : "Итого к списанию"}
        value={formatRub(
          brokerPreview?.broker_total_amount_rub ??
            preview.local_total_amount_rub,
        )}
      />
      {!isSell && (
        <PricingRow
          label="На счёте"
          value={formatRub(preview.money_rub)}
        />
      )}
    </div>
  );
}
