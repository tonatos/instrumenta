import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { OrderPreviewResponse, PendingOperation } from "@/api/types";

export const BUY_KINDS = new Set(["initial_buy", "reinvest_buy", "top_up_buy"]);
export const SELL_KINDS = new Set(["manual_sell"]);

export function previewMatchesForm(
  preview: OrderPreviewResponse,
  lots: number,
  pricePct: number,
): boolean {
  return (
    preview.order_lots === lots &&
    Math.abs(preview.order_price_pct - pricePct) < 1e-4
  );
}

export function parseApiError(err: Error): string {
  try {
    const parsed = JSON.parse(err.message) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // not JSON
  }
  return err.message || "Не удалось выполнить операцию";
}

export function useOrderPreview({
  open,
  op,
  portfolioId,
  lots,
  parsedPricePct,
}: {
  open: boolean;
  op: PendingOperation | null;
  portfolioId: string;
  lots: number;
  parsedPricePct: number;
}) {
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const isBuy = op != null && BUY_KINDS.has(op.kind);
  const isSell = op != null && SELL_KINDS.has(op.kind);
  const previewEnabled = isBuy || isSell;

  useEffect(() => {
    if (!open || !op || !previewEnabled) {
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
  }, [open, previewEnabled, op, portfolioId, lots, parsedPricePct]);

  return { preview, previewLoading, previewError, isBuy, isSell };
}
