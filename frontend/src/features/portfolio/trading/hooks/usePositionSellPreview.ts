import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { SellPositionPreviewResponse } from "@/api/types";
import { previewMatchesForm } from "@/features/portfolio/trading/hooks/useOrderPreview";

export function usePositionSellPreview({
  open,
  portfolioId,
  isin,
  lots,
  parsedPricePct,
}: {
  open: boolean;
  portfolioId: string;
  isin: string | null;
  lots: number;
  parsedPricePct: number;
}) {
  const [preview, setPreview] = useState<SellPositionPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !isin) {
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
        .sellPositionPreview(portfolioId, isin, {
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
          setPreviewError(err.message || "Не удалось получить превью");
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
  }, [open, portfolioId, isin, lots, parsedPricePct]);

  return { preview, previewLoading, previewError };
}
