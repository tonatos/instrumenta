import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ClipboardCopy,
  Loader2,
  RefreshCw,
  ShoppingCart,
  Tag,
  XCircle,
} from "lucide-react";
import { api } from "@/api/client";
import type {
  OrderPreviewResponse,
  PendingOperation,
  Portfolio,
  TradingSyncResponse,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
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
import { cn, formatPct, formatRub } from "@/lib/utils";

const BUY_KINDS = new Set(["initial_buy", "reinvest_buy", "top_up_buy"]);

function previewMatchesForm(
  preview: OrderPreviewResponse,
  lots: number,
  pricePct: number,
): boolean {
  return (
    preview.order_lots === lots &&
    Math.abs(preview.order_price_pct - pricePct) < 1e-4
  );
}

function computeBuyOrderPricing({
  lots,
  pricePct,
  faceValueRub,
  lotSize,
  aciRubPerBond,
}: {
  lots: number;
  pricePct: number;
  faceValueRub: number;
  lotSize: number;
  aciRubPerBond: number;
}) {
  const cleanPerBond = (faceValueRub * pricePct) / 100;
  const cleanPerLot = cleanPerBond * lotSize;
  const aciPerLot = aciRubPerBond * lotSize;
  const dirtyPerLot = cleanPerLot + aciPerLot;
  const totalDirty = dirtyPerLot * lots;
  const aciPct = faceValueRub > 0 ? (aciRubPerBond / faceValueRub) * 100 : 0;

  return {
    cleanPerLot,
    aciPerLot,
    dirtyPerLot,
    totalDirty,
    pricePct,
    aciPct,
  };
}

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

const KIND_LABELS: Record<string, string> = {
  initial_buy: "Стартовая покупка",
  reinvest_buy: "Реинвестиция",
  top_up_buy: "Покупка (пополнение)",
  put_offer_submit: "Пут-оферта",
  manual_sell: "Продажа",
};

const STATUS_LABELS: Record<string, string> = {
  action_required: "Требует действия",
  in_progress: "На бирже",
  overdue: "Просрочено",
  blocked: "Заблокировано",
};

const ORDER_STATUS_LABELS: Record<string, string> = {
  EXECUTION_REPORT_STATUS_NEW: "Новая",
  EXECUTION_REPORT_STATUS_PARTIALLYFILL: "Частично исполнена",
  EXECUTION_REPORT_STATUS_FILL: "Исполнена",
  EXECUTION_REPORT_STATUS_CANCELLED: "Отменена",
  EXECUTION_REPORT_STATUS_REJECTED: "Отклонена",
  EXECUTION_REPORT_STATUS_PENDING_CANCEL: "Отмена в обработке",
};

function formatOrderStatus(status: string | null | undefined): string {
  if (!status) return "—";
  return ORDER_STATUS_LABELS[status] ?? status.replace("EXECUTION_REPORT_STATUS_", "");
}

interface Props {
  portfolio: Portfolio;
  pendingConfirmId?: string | null;
}

function needsPolling(ops: PendingOperation[]) {
  return ops.some(
    (op) => op.status === "in_progress" || op.status === "action_required" || op.status === "overdue",
  );
}

function groupOperations(ops: PendingOperation[]) {
  const urgent = ops.filter(
    (op) =>
      op.kind === "put_offer_submit" ||
      op.status === "overdue" ||
      op.urgency === "critical" ||
      op.urgency === "soon",
  );
  const buys = ops.filter(
    (op) =>
      (op.kind === "initial_buy" || op.kind === "reinvest_buy" || op.kind === "top_up_buy") &&
      !urgent.includes(op),
  );
  const sells = ops.filter((op) => op.kind === "manual_sell" && !urgent.includes(op));
  const urgentIds = new Set(urgent.map((o) => o.id));
  const otherUrgent = ops.filter(
    (op) =>
      !urgentIds.has(op.id) &&
      !buys.includes(op) &&
      !sells.includes(op) &&
      (op.status === "overdue" || op.urgency === "critical"),
  );
  return {
    urgent: [...urgent, ...otherUrgent],
    buys,
    sells,
  };
}

function StatusBadge({ status }: { status: PendingOperation["status"] }) {
  const cfg: Record<string, string> = {
    action_required: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
    in_progress: "bg-blue-500/15 text-blue-800 dark:text-blue-300",
    overdue: "bg-red-500/15 text-red-800 dark:text-red-300",
    blocked: "bg-muted text-muted-foreground",
  };
  return (
    <Badge className={cn("text-xs font-medium", cfg[status])}>
      {STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

function OrderDetailPanel({ op }: { op: PendingOperation }) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const copyOrderId = async () => {
    if (!op.active_order_id) return;
    await navigator.clipboard.writeText(op.active_order_id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const lotsLabel =
    op.active_order_lots_executed != null && op.active_order_lots_executed > 0
      ? `исполнено ${op.active_order_lots_executed} из ${op.active_order_lots ?? "—"}`
      : `${op.active_order_lots ?? "—"} лот.`;

  return (
    <div className="space-y-2">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="h-7 gap-1.5 px-2 text-xs"
        onClick={() => setExpanded((v) => !v)}
      >
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")}
        />
        Детали заявки
      </Button>
      {expanded && (
        <div className="space-y-2 rounded-lg border border-border/70 bg-muted/20 p-3 text-sm">
          {op.active_order_id && (
            <div className="flex items-start justify-between gap-3">
              <span className="text-muted-foreground">ID заявки</span>
              <div className="text-right">
                <span className="font-mono text-xs break-all">{op.active_order_id}</span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="mt-1 h-6 px-2 text-xs"
                  onClick={copyOrderId}
                >
                  {copied ? <Check className="h-3 w-3" /> : <ClipboardCopy className="h-3 w-3" />}
                  {copied ? "Скопировано" : "Копировать"}
                </Button>
              </div>
            </div>
          )}
          <PricingRow label="Лоты" value={lotsLabel} />
          {op.active_order_bonds_count != null && (
            <PricingRow label="Облигаций" value={`${op.active_order_bonds_count} шт`} />
          )}
          {op.active_order_price_pct != null && (
            <PricingRow
              label="Лимит (чистая)"
              value={`${op.active_order_price_pct.toFixed(2)}%`}
            />
          )}
          {op.active_order_total_rub != null && (
            <PricingRow label="Сумма заявки" value={formatRub(op.active_order_total_rub)} />
          )}
          {op.active_order_commission_rub != null && op.active_order_commission_rub > 0 && (
            <PricingRow
              label="Комиссия"
              value={formatRub(op.active_order_commission_rub)}
            />
          )}
          <PricingRow
            label="Статус"
            value={formatOrderStatus(op.active_order_status)}
          />
        </div>
      )}
    </div>
  );
}

function OperationCard({
  op,
  isProduction,
  onConfirm,
  onCancel,
  onPutOffer,
  isPending,
}: {
  op: PendingOperation;
  isProduction: boolean;
  onConfirm: (op: PendingOperation) => void;
  onCancel: (op: PendingOperation) => void;
  onPutOffer: (op: PendingOperation, decision: "exercise" | "hold") => void;
  isPending: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const isOnExchange = op.status === "in_progress";

  const borderClass =
    op.status === "overdue" || op.urgency === "critical"
      ? "border-red-400/50"
      : op.status === "in_progress"
        ? "border-blue-400/40"
        : op.status === "blocked"
          ? "border-border opacity-75"
          : "border-amber-400/30";

  const copyTemplate = async () => {
    if (!op.chat_template) return;
    await navigator.clipboard.writeText(op.chat_template);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const displayAmount = isOnExchange
    ? (op.active_order_total_rub ?? op.estimated_amount_rub)
    : op.estimated_amount_rub;
  const displayLots = isOnExchange ? (op.active_order_lots ?? op.lots) : op.lots;
  const displayPricePct = isOnExchange
    ? (op.active_order_price_pct ?? op.suggested_price_pct)
    : op.suggested_price_pct;
  const bondsCount = isOnExchange
    ? op.active_order_bonds_count
    : op.lots > 0 && op.lot_size
      ? op.lots * op.lot_size
      : null;

  return (
    <div
      id={`pending-op-${op.id}`}
      className={cn("rounded-lg border bg-card p-3 space-y-2", borderClass)}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{op.name}</span>
            <StatusBadge status={op.status} />
            <Badge variant="outline" className="text-xs">
              {KIND_LABELS[op.kind] ?? op.kind}
            </Badge>
          </div>
          {!isOnExchange && (
            <p className="text-xs text-muted-foreground">{op.reason}</p>
          )}
          {isOnExchange && op.active_order_status && (
            <p className="text-xs text-muted-foreground">
              {formatOrderStatus(op.active_order_status)}
            </p>
          )}
        </div>
        {displayAmount != null && (
          <p className="text-sm font-semibold tabular-nums shrink-0">
            {isOnExchange ? formatRub(displayAmount) : `~${formatRub(displayAmount)}`}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {displayLots > 0 && (
          <span>
            {displayLots} лот.
            {bondsCount != null && bondsCount !== displayLots ? ` · ${bondsCount} шт` : ""}
          </span>
        )}
        {displayPricePct != null && (
          <span>лимит {displayPricePct.toFixed(2)}%</span>
        )}
        {!isOnExchange && op.due_date && <span>до {op.due_date}</span>}
      </div>

      {isOnExchange && <OrderDetailPanel op={op} />}

      {op.block_reason && (
        <p className="flex items-start gap-1.5 text-xs text-destructive">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {op.block_reason}
        </p>
      )}

      {op.kind === "put_offer_submit" &&
        op.urgency === "critical" &&
        op.status === "action_required" && (
          <p className="flex items-start gap-1.5 rounded-md bg-red-500/10 px-2.5 py-2 text-xs text-red-800 dark:text-red-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Осталось мало времени: подайте заявку на пут-оферту через чат брокера
            {op.due_date ? ` до ${op.due_date}` : ""}, иначе право на досрочный выкуп будет упущено.
          </p>
        )}

      <div className="flex flex-wrap gap-2 pt-1">
        {op.kind === "put_offer_submit" ? (
          <>
            {op.chat_template && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="gap-1.5"
                onClick={copyTemplate}
                disabled={isPending}
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <ClipboardCopy className="h-3.5 w-3.5" />}
                {copied ? "Скопировано" : "Текст для чата"}
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              onClick={() => onPutOffer(op, "exercise")}
              disabled={isPending}
            >
              Я подал оферту
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onPutOffer(op, "hold")}
              disabled={isPending}
            >
              Оставить до погашения
            </Button>
          </>
        ) : op.status === "in_progress" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1.5 text-destructive"
            onClick={() => onCancel(op)}
            disabled={isPending}
          >
            <XCircle className="h-3.5 w-3.5" />
            Отменить заявку
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            className="gap-1.5"
            onClick={() => onConfirm(op)}
            disabled={isPending || op.status === "blocked"}
          >
            <ShoppingCart className="h-3.5 w-3.5" />
            {op.kind === "manual_sell" ? "Подтвердить продажу" : "Подтвердить покупку"}
          </Button>
        )}
      </div>

      {isProduction && op.kind !== "put_offer_submit" && op.status === "action_required" && (
        <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Боевой счёт: заявка уйдёт на биржу с реальными деньгами.
        </p>
      )}
    </div>
  );
}

function ConfirmDialog({
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
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (op) {
      setLots(op.lots);
      setPricePct(op.suggested_price_pct?.toFixed(4) ?? "");
      setPreview(null);
      setPreviewError(null);
    }
  }, [op]);

  const isSell = op?.kind === "manual_sell";
  const isBuy = op != null && BUY_KINDS.has(op.kind);
  const parsedPricePct = parseFloat(pricePct);

  useEffect(() => {
    if (!open || !op || !isBuy) {
      return;
    }
    if (!Number.isFinite(parsedPricePct) || parsedPricePct <= 0 || lots <= 0) {
      setPreview(null);
      setPreviewLoading(false);
      setPreviewError(null);
      return;
    }

    let cancelled = false;
    setPreview(null);
    setPreviewLoading(true);
    setPreviewError(null);

    const timer = window.setTimeout(() => {
      api
        .previewPendingOperation(portfolioId, op.id, {
          lots,
          price_pct: parsedPricePct,
        })
        .then((data) => {
          if (cancelled) {
            return;
          }
          if (!previewMatchesForm(data, lots, parsedPricePct)) {
            return;
          }
          setPreview(data);
        })
        .catch((err: Error) => {
          if (cancelled) {
            return;
          }
          setPreview(null);
          setPreviewError(parseApiError(err));
        })
        .finally(() => {
          if (!cancelled) {
            setPreviewLoading(false);
          }
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, isBuy, op, portfolioId, lots, parsedPricePct]);

  if (!op) return null;

  const faceValueRub = op.face_value_rub ?? 1000;
  const lotSize = op.lot_size ?? 1;
  const aciRubPerBond = op.aci_rub_per_bond ?? 0;
  const pricing =
    isBuy &&
    Number.isFinite(parsedPricePct) &&
    parsedPricePct > 0 &&
    lots > 0
      ? computeBuyOrderPricing({
          lots,
          pricePct: parsedPricePct,
          faceValueRub,
          lotSize,
          aciRubPerBond,
        })
      : null;

  const previewApplies =
    preview != null &&
    Number.isFinite(parsedPricePct) &&
    previewMatchesForm(preview, lots, parsedPricePct);
  const brokerPreview =
    previewApplies && preview?.preview_source === "broker" ? preview : null;
  const insufficientCash = isBuy && previewApplies && !preview!.sufficient_cash;
  const totalToPay =
    brokerPreview?.broker_total_amount_rub ??
    (previewApplies ? preview?.local_total_amount_rub : null) ??
    pricing?.totalDirty ??
    null;

  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isSell ? "Подтвердить продажу" : "Подтвердить покупку"}
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
            </div>
          </div>

          {isBuy && op.suggested_price_pct != null && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => setPricePct(op.suggested_price_pct!.toFixed(4))}
            >
              Сбросить к рекомендуемой ({op.suggested_price_pct.toFixed(4)}%)
            </Button>
          )}

          {pricing && (
            <div className="space-y-2 rounded-lg border border-border/70 bg-muted/30 p-3">
              <p className="text-xs font-medium text-muted-foreground">
                Оценка по MOEX
              </p>
              <PricingRow label="Номинал" value={`${formatRub(faceValueRub)} / шт`} />
              <PricingRow
                label="Чистая стоимость лота"
                value={formatRub(pricing.cleanPerLot)}
                hint={`чистая ${formatPct(pricing.pricePct)}`}
              />
              <PricingRow
                label="НКД за лот"
                value={formatRub(pricing.aciPerLot)}
                hint={
                  pricing.aciPct > 0
                    ? `${formatPct(pricing.aciPct)} × ${lotSize} шт`
                    : `${lotSize} шт без НКД`
                }
              />
              <div className="border-t border-border/60 pt-2">
                <PricingRow
                  label={`Итого (${lots} лот.)`}
                  value={formatRub(pricing.totalDirty)}
                  hint={`грязная ${formatPct(pricing.pricePct + pricing.aciPct)}`}
                />
              </div>
            </div>
          )}

          {isBuy && (previewLoading || previewApplies || previewError) && (
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
                <div className="space-y-2">
                  <PricingRow
                    label="Бумаг"
                    value={`${preview.order_bonds} шт`}
                    hint={`${preview.order_lots} лот × ${preview.lot_size} шт`}
                  />
                  {brokerPreview?.broker_clean_amount_rub != null && (
                    <PricingRow
                      label="Чистая стоимость"
                      value={formatRub(brokerPreview.broker_clean_amount_rub)}
                      hint={`лимит ${formatPct(preview.order_price_pct)} от номинала`}
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
                    label="Итого к списанию"
                    value={formatRub(
                      brokerPreview?.broker_total_amount_rub ??
                        preview.local_total_amount_rub,
                    )}
                  />
                  <PricingRow
                    label="На счёте"
                    value={formatRub(preview.money_rub)}
                  />
                </div>
              )}
            </div>
          )}

          {insufficientCash && (
            <p className="flex items-start gap-1.5 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              Недостаточно средств на счёте для покупки
              {totalToPay != null ? ` (~${formatRub(totalToPay)})` : ""}.
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
              Number.isNaN(parseFloat(pricePct)) ||
              insufficientCash
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

function Section({
  title,
  icon,
  ops,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  ops: PendingOperation[];
  children: React.ReactNode;
}) {
  if (!ops.length) return null;
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {icon}
        {title}
        <Badge variant="outline" className="font-mono text-xs">
          {ops.length}
        </Badge>
      </p>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

export function TradingActionQueue({ portfolio, pendingConfirmId }: Props) {
  const queryClient = useQueryClient();
  const [confirmOp, setConfirmOp] = useState<PendingOperation | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const isProduction = portfolio.account_kind === "production";

  const { data, isLoading, isError, error, isFetching, refetch, dataUpdatedAt } = useQuery({
    queryKey: ["trading-sync", portfolio.id],
    queryFn: () => api.syncPortfolio(portfolio.id),
    refetchInterval: (query) => {
      const ops = query.state.data?.pending_operations ?? [];
      if (needsPolling(ops)) return 30_000;
      return 60_000;
    },
  });

  const invalidateAll = (data?: TradingSyncResponse) => {
    if (data) {
      queryClient.setQueryData(["trading-sync", portfolio.id], data);
    } else {
      queryClient.invalidateQueries({ queryKey: ["trading-sync", portfolio.id] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolio.id] });
    }
    queryClient.invalidateQueries({ queryKey: ["portfolios"] });
  };

  const confirmMutation = useMutation({
    mutationFn: ({ opId, lots, pricePct }: { opId: string; lots: number; pricePct: number }) =>
      api.confirmPendingOperation(portfolio.id, opId, { lots, price_pct: pricePct }),
    onSuccess: (data) => {
      setConfirmOp(null);
      setConfirmError(null);
      invalidateAll(data);
    },
    onError: (err: Error) => {
      setConfirmError(parseApiError(err));
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (opId: string) => api.cancelPendingOrder(portfolio.id, opId),
    onSuccess: (data) => invalidateAll(data),
  });

  const cancelBatchMutation = useMutation({
    mutationFn: (batchId: string) => api.cancelTopUpBatch(portfolio.id, batchId),
    onSuccess: (data) => invalidateAll(data),
  });

  const putOfferMutation = useMutation({
    mutationFn: ({ isin, decision }: { isin: string; decision: "exercise" | "hold" }) =>
      api.setPutOfferDecision(portfolio.id, isin, decision),
    onSuccess: (data) => invalidateAll(data),
  });

  const ops = data?.pending_operations ?? [];
  const groups = useMemo(() => groupOperations(ops), [ops]);
  const topUpBatchIds = useMemo(
    () =>
      [
        ...new Set(
          ops
            .filter((op) => op.kind === "top_up_buy" && op.top_up_batch_id)
            .map((op) => op.top_up_batch_id as string),
        ),
      ],
    [ops],
  );

  const attentionCount = ops.filter(
    (op) => op.status === "action_required" || op.status === "overdue",
  ).length;

  const apiTradeWarnings = useMemo(
    () =>
      (data?.notes ?? []).filter((note) => note.includes("не торгуется через T-Invest API")),
    [data?.notes],
  );

  useEffect(() => {
    if (!pendingConfirmId || !ops.length) return;
    const target = ops.find((op) => op.id === pendingConfirmId);
    if (!target) return;
    document.getElementById(`pending-op-${target.id}`)?.scrollIntoView({ behavior: "smooth" });
    if (
      target.kind !== "put_offer_submit" &&
      target.status !== "blocked" &&
      target.status !== "in_progress"
    ) {
      setConfirmOp(target);
    }
  }, [pendingConfirmId, ops]);

  const syncTime = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : null;

  const renderCard = (op: PendingOperation) => (
    <OperationCard
      key={op.id}
      op={op}
      isProduction={isProduction}
      isPending={
        confirmMutation.isPending ||
        cancelMutation.isPending ||
        cancelBatchMutation.isPending ||
        putOfferMutation.isPending
      }
      onConfirm={(o) => {
        setConfirmError(null);
        setConfirmOp(o);
      }}
      onCancel={(o) => cancelMutation.mutate(o.id)}
      onPutOffer={(o, decision) => putOfferMutation.mutate({ isin: o.isin, decision })}
    />
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-border p-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Синхронизация со счётом…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
        <span className="flex items-center gap-2 text-destructive">
          <XCircle className="h-4 w-4 shrink-0" />
          {parseApiError(error)}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          Повторить
        </Button>
      </div>
    );
  }

  const hasContent =
    ops.length > 0 || (data?.drifts?.length ?? 0) > 0 || apiTradeWarnings.length > 0;

  if (!hasContent) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-green-400/30 bg-green-500/5 px-4 py-3 text-sm">
        <span className="text-green-800 dark:text-green-300">
          Очередь действий пуста — все операции выполнены
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 text-muted-foreground"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          Обновить
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4 rounded-xl border border-amber-400/40 bg-amber-500/5 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="space-y-0.5">
            <p className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
              <Tag className="h-4 w-4" />
              Очередь действий
              {attentionCount > 0 && (
                <Badge className="bg-amber-500/20 text-amber-900 dark:text-amber-200">
                  {attentionCount} требуют внимания
                </Badge>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              На счёте {formatRub(data?.money_rub ?? portfolio.cash_balance_rub)}
              {syncTime && ` · обновлено ${syncTime}`}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            Обновить счёт
          </Button>
        </div>

        {data?.top_up_auto_applied && data.top_up_distributed_rub > 0 && (
          <div className="rounded-lg border border-blue-400/40 bg-blue-500/10 px-3 py-2 text-sm text-blue-900 dark:text-blue-200">
            Обнаружено пополнение {formatRub(data.top_up_distributed_rub)} — заявки на покупку
            добавлены в очередь
          </div>
        )}

        {apiTradeWarnings.length > 0 && (
          <div className="space-y-1 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100">
            <p className="font-medium">Позиции недоступны для покупки через API</p>
            <p className="text-xs text-amber-900/80 dark:text-amber-200/80">
              Они остались в плане до автосбора с фильтром «только API». Удалите вручную или
              пересоберите портфель.
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
              {apiTradeWarnings.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        )}

        {topUpBatchIds.map((batchId) => (
          <div
            key={batchId}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-xs"
          >
            <span className="text-muted-foreground">
              Партия пополнения · {batchId.slice(0, 8)}…
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 text-destructive"
              onClick={() => cancelBatchMutation.mutate(batchId)}
              disabled={cancelBatchMutation.isPending}
            >
              Отменить партию
            </Button>
          </div>
        ))}

        <Section title="Срочно" icon={<AlertTriangle className="h-3.5 w-3.5" />} ops={groups.urgent}>
          {groups.urgent.map(renderCard)}
        </Section>

        <Section title="Покупки" icon={<ShoppingCart className="h-3.5 w-3.5" />} ops={groups.buys}>
          {groups.buys.map(renderCard)}
        </Section>

        <Section title="Продажи" icon={<Tag className="h-3.5 w-3.5" />} ops={groups.sells}>
          {groups.sells.map(renderCard)}
        </Section>

        {data?.drifts && data.drifts.length > 0 && (
          <div className="space-y-2 border-t border-border/60 pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Расхождения со счётом
            </p>
            {data.drifts.map((d) => (
              <div
                key={`${d.isin}-${d.name}`}
                className={cn(
                  "rounded-lg px-3 py-2 text-xs",
                  d.severity === "critical"
                    ? "bg-red-500/10 text-red-800 dark:text-red-300"
                    : "bg-muted/50 text-muted-foreground",
                )}
              >
                {d.message}
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        op={confirmOp}
        portfolioId={portfolio.id}
        open={confirmOp !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmOp(null);
            setConfirmError(null);
          }
        }}
        isProduction={isProduction}
        isPending={confirmMutation.isPending}
        error={confirmError}
        onSubmit={(lots, pricePct) => {
          if (!confirmOp) return;
          confirmMutation.mutate({ opId: confirmOp.id, lots, pricePct });
        }}
      />
    </>
  );
}

function parseApiError(err: Error): string {
  try {
    const parsed = JSON.parse(err.message) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // not JSON
  }
  return err.message || "Не удалось выполнить операцию";
}
