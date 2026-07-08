import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { OrderPreviewResponse, Suggestion } from "@/api/types";

export function suggestionDirection(
  kind: Suggestion["kind"],
): "BUY" | "SELL" | null {
  if (kind === "buy" || kind === "reinvest") return "BUY";
  if (kind === "sell") return "SELL";
  return null;
}

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
  suggestion,
  portfolioId,
  lots,
  parsedPricePct,
}: {
  open: boolean;
  suggestion: Suggestion | null;
  portfolioId: string;
  lots: number;
  parsedPricePct: number;
}) {
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const direction = suggestion ? suggestionDirection(suggestion.kind) : null;
  const isBuy = direction === "BUY";
  const isSell = direction === "SELL";
  const previewEnabled = Boolean(direction);

  useEffect(() => {
    if (!open || !suggestion || !direction || !previewEnabled) {
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
        .previewOrder(portfolioId, {
          isin: suggestion.isin,
          direction,
          lots,
          price_pct: parsedPricePct,
          figi: suggestion.figi,
          suggestion_id: suggestion.id,
        })
        .then((data) => {
          if (cancelled) return;
          if (!previewMatchesForm(data, lots, parsedPricePct)) return;
          setPreview(data);
        })
        .catch((err: Error) => {
          if (cancelled) return;
          setPreview(null);
          setPreviewError(parseApiError(err));
        })
        .finally(() => {
          if (!cancelled) setPreviewLoading(false);
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, previewEnabled, suggestion, direction, portfolioId, lots, parsedPricePct]);

  return { preview, previewLoading, previewError, isBuy, isSell };
}
