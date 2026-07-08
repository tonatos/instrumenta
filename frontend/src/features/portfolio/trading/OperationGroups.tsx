import { useState } from "react";
import {
  Check,
  ClipboardCopy,
  XCircle,
} from "lucide-react";
import type { ActiveOrder, Suggestion } from "@/api/types";
import { formatOrderStatus } from "@/features/portfolio/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatDate, formatRub } from "@/lib/utils";
import { suggestionDirection } from "@/features/portfolio/trading/hooks/useOrderPreview";

const KIND_LABELS: Record<string, string> = {
  buy: "Покупка",
  reinvest: "Реинвест",
  put_offer_reminder: "Пут-оферта",
  sell: "Продажа",
};

export function groupSuggestions(suggestions: Suggestion[]) {
  const urgent = suggestions.filter(
    (s) =>
      s.kind === "put_offer_reminder" ||
      s.urgency === "critical" ||
      s.urgency === "soon",
  );
  const buys = suggestions.filter(
    (s) => (s.kind === "buy" || s.kind === "reinvest") && !urgent.includes(s),
  );
  const sells = suggestions.filter((s) => s.kind === "sell" && !urgent.includes(s));
  return { urgent, buys, sells };
}

export function SuggestionCard({
  suggestion,
  isProduction,
  onConfirm,
  isPending,
}: {
  suggestion: Suggestion;
  isProduction: boolean;
  onConfirm: (s: Suggestion) => void;
  isPending: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const direction = suggestionDirection(suggestion.kind);
  const borderClass =
    suggestion.urgency === "critical"
      ? "border-red-400/50"
      : suggestion.urgency === "soon"
        ? "border-amber-400/40"
        : "border-border/60";

  const copyTemplate = async () => {
    if (!suggestion.chat_template) return;
    await navigator.clipboard.writeText(suggestion.chat_template);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      id={`suggestion-${suggestion.id}`}
      className={cn("rounded-lg border bg-card/50 p-3 space-y-2", borderClass)}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-sm">{suggestion.name}</p>
          <p className="text-xs text-muted-foreground">{suggestion.isin}</p>
        </div>
        <Badge variant="outline" className="text-xs">
          {KIND_LABELS[suggestion.kind] ?? suggestion.kind}
        </Badge>
      </div>
      <p className="text-sm text-muted-foreground">{suggestion.reason}</p>
      {suggestion.due_date && (
        <p className="text-xs text-muted-foreground">Срок: {formatDate(suggestion.due_date)}</p>
      )}
      {direction && (
        <p className="text-sm">
          {suggestion.lots} лот. · лимит {suggestion.suggested_price_pct?.toFixed(2) ?? "—"}%
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {suggestion.chat_template && (
          <>
            <Button type="button" size="sm" variant="outline" onClick={copyTemplate}>
              {copied ? <Check className="h-3.5 w-3.5" /> : <ClipboardCopy className="h-3.5 w-3.5" />}
              Копировать текст
            </Button>
          </>
        )}
        {direction && (
          <Button
            type="button"
            size="sm"
            onClick={() => onConfirm(suggestion)}
            disabled={isPending}
          >
            {direction === "BUY" ? "Подтвердить покупку" : "Подтвердить продажу"}
            {isProduction && " (боевой)"}
          </Button>
        )}
      </div>
    </div>
  );
}

export function ActiveOrderCard({
  order,
  onCancel,
  isPending,
}: {
  order: ActiveOrder;
  onCancel: (order: ActiveOrder) => void;
  isPending: boolean;
}) {
  return (
    <div className="rounded-lg border border-blue-400/40 bg-blue-500/5 p-3 space-y-2 text-sm">
      <div className="flex justify-between gap-2">
        <span className="font-medium">{order.direction === "BUY" ? "Покупка" : "Продажа"}</span>
        <Badge className="bg-blue-500/15 text-blue-800 dark:text-blue-300">На бирже</Badge>
      </div>
      <p className="text-xs text-muted-foreground font-mono break-all">{order.order_id}</p>
      <p>
        {order.lots_executed} / {order.lots_requested} лот.
        {order.price_pct != null && ` · ${order.price_pct.toFixed(2)}%`}
      </p>
      {order.total_order_amount_rub != null && (
        <p>Сумма: {formatRub(order.total_order_amount_rub)}</p>
      )}
      <p className="text-xs text-muted-foreground">{formatOrderStatus(order.status)}</p>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => onCancel(order)}
        disabled={isPending}
      >
        <XCircle className="h-3.5 w-3.5" />
        Отменить заявку
      </Button>
    </div>
  );
}

export function AdvisorySection({
  title,
  icon,
  children,
  count,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  count: number;
}) {
  if (count === 0) return null;
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {icon}
        {title}
        <Badge variant="secondary" className="text-xs">
          {count}
        </Badge>
      </p>
      <div className="space-y-2">{children}</div>
    </div>
  );
}
