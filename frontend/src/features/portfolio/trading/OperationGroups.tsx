import { useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ClipboardCopy,
  ShoppingCart,
  XCircle,
} from "lucide-react";
import type { PendingOperation } from "@/api/types";
import {
  formatOrderStatus,
  KIND_LABELS,
  STATUS_LABELS,
} from "@/features/portfolio/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatDate, formatRub } from "@/lib/utils";

export function groupOperations(ops: PendingOperation[]) {
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

export function OperationCard({
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
        {!isOnExchange && op.due_date && <span>до {formatDate(op.due_date)}</span>}
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
            {op.due_date ? ` до ${formatDate(op.due_date)}` : ""}, иначе право на досрочный выкуп будет упущено.
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

export function OperationSection({
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
