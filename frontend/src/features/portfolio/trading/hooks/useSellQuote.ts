import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { SellQuoteResponse } from "@/api/types";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";

export function useSellQuote({
  open,
  portfolioId,
  isin,
}: {
  open: boolean;
  portfolioId: string;
  isin: string | null;
}) {
  const [quote, setQuote] = useState<SellQuoteResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !isin) {
      return;
    }

    let cancelled = false;
    setQuote(null);
    setLoading(true);
    setError(null);

    api
      .getSellQuote(portfolioId, isin)
      .then((data) => {
        if (!cancelled) {
          setQuote(data);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(parseApiError(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open, portfolioId, isin]);

  return { quote, loading, error };
}
