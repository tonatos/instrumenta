import { useMutation } from "@tanstack/react-query";
import { Loader2, PlusCircle } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseApiError } from "@/features/portfolio/trading/hooks/useOrderPreview";
import { useState } from "react";

export function SandboxPayInPanel({
  portfolioId,
  onSuccess,
  disabled,
}: {
  portfolioId: string;
  onSuccess: () => void;
  disabled?: boolean;
}) {
  const [amountRub, setAmountRub] = useState("50 000");
  const [error, setError] = useState<string | null>(null);

  const payInMutation = useMutation({
    mutationFn: async () => {
      const amount = Number(amountRub.replace(/\s/g, "").replace(",", "."));
      if (!Number.isFinite(amount) || amount <= 0) {
        throw new Error("Укажите корректную сумму пополнения");
      }
      return api.sandboxPayIn(portfolioId, { amount_rub: amount });
    },
    onSuccess: () => {
      setError(null);
      onSuccess();
    },
    onError: (err: Error) => {
      setError(parseApiError(err));
    },
  });

  return (
    <div className="space-y-2 border-t border-border/60 pt-3">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <PlusCircle className="h-3.5 w-3.5" />
        Песочница · добавить средства
      </p>
      <p className="text-xs text-muted-foreground">
        Имитирует пополнение брокерского счёта. После добавления нажмите «Обновить счёт» или
        дождитесь авто-синхронизации — пополнение распределится по портфелю.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[140px] flex-1 space-y-1">
          <label htmlFor={`sandbox-pay-in-${portfolioId}`} className="text-xs text-muted-foreground">
            Сумма, ₽
          </label>
          <Input
            id={`sandbox-pay-in-${portfolioId}`}
            inputMode="decimal"
            value={amountRub}
            onChange={(e) => setAmountRub(e.target.value)}
            disabled={disabled || payInMutation.isPending}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => payInMutation.mutate()}
          disabled={disabled || payInMutation.isPending}
        >
          {payInMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlusCircle className="h-3.5 w-3.5" />
          )}
          Добавить средства
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
