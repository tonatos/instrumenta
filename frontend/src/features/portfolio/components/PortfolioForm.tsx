import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { todayIsoDate } from "@/lib/utils";
import type { PortfolioFormValues } from "@/features/portfolio/hooks/usePortfolioMutations";

export function PortfolioForm({
  initial,
  onSubmit,
  isPending,
  submitLabel,
}: {
  initial: PortfolioFormValues;
  onSubmit: (values: PortfolioFormValues) => void;
  isPending: boolean;
  submitLabel: string;
}) {
  const [form, setForm] = useState(initial);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="space-y-1.5 text-sm sm:col-span-2">
        <span className="font-medium text-muted-foreground">Название</span>
        <Input
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Мой портфель"
          autoFocus
        />
      </label>
      <label className="space-y-1.5 text-sm">
        <span className="font-medium text-muted-foreground">Начальный бюджет, ₽</span>
        <Input
          type="number"
          min={1000}
          step={10000}
          value={form.initial_amount_rub}
          onChange={(e) => setForm({ ...form, initial_amount_rub: Number(e.target.value) })}
        />
      </label>
      <label className="space-y-1.5 text-sm">
        <span className="font-medium text-muted-foreground">Горизонт инвестирования</span>
        <DatePicker
          value={form.horizon_date}
          min={todayIsoDate()}
          onChange={(horizon_date) => setForm({ ...form, horizon_date })}
        />
      </label>
      <label className="space-y-1.5 text-sm sm:col-span-2">
        <span className="font-medium text-muted-foreground">Профиль риска</span>
        <select
          className="flex h-9 w-full rounded-md border border-border bg-card px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          value={form.risk_profile}
          onChange={(e) => setForm({ ...form, risk_profile: e.target.value })}
        >
          <option value="conservative">Консервативный</option>
          <option value="normal">Нормальный</option>
          <option value="aggressive">Агрессивный</option>
        </select>
      </label>
      <label className="space-y-1.5 text-sm sm:col-span-2">
        <span className="font-medium text-muted-foreground">Макс. дюрация, лет</span>
        <Input
          type="number"
          min={0}
          step={0.5}
          placeholder="Без лимита"
          value={form.max_weighted_duration_years}
          onChange={(e) =>
            setForm({ ...form, max_weighted_duration_years: e.target.value })
          }
        />
        <span className="block text-xs text-muted-foreground">
          Гардрейл процентного риска в автосборе и реинвесте. Пусто — без ограничения.
        </span>
      </label>
      <label className="flex cursor-pointer items-start gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          className="mt-1"
          checked={form.api_trade_only}
          onChange={(e) => setForm({ ...form, api_trade_only: e.target.checked })}
        />
        <span>
          <span className="font-medium text-foreground">Только API-торгуемые</span>
          <span className="mt-0.5 block text-muted-foreground">
            В автосборе и реинвесте — только бумаги, которые можно купить через T-Invest API
            (рекомендуется для режима торговли)
          </span>
        </span>
      </label>
      <DialogFooter className="sm:col-span-2">
        <Button
          onClick={() => onSubmit(form)}
          disabled={!form.name.trim() || isPending}
        >
          {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {submitLabel}
        </Button>
      </DialogFooter>
    </div>
  );
}
