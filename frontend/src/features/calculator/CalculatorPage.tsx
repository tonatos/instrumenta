import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calculator, X } from "lucide-react";
import { api } from "@/api/client";
import type { Bond, CalculatorResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatPct, formatRub } from "@/lib/utils";

const MAX_BONDS = 6;

export function CalculatorPage() {
  const [budget, setBudget] = useState(100_000);
  const [selected, setSelected] = useState<Bond[]>([]);
  const [result, setResult] = useState<CalculatorResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: bonds, isLoading: bondsLoading } = useQuery({
    queryKey: ["bonds"],
    queryFn: () => api.getBonds({ export: true }),
  });

  const bondOptions: ComboboxOption[] = (bonds?.bonds ?? []).map((b) => ({
    value: b.secid,
    label: b.name,
    description: [
      b.ytm_net != null ? `YTM ${b.ytm_net.toFixed(2)}%` : null,
      b.score != null ? `Скор ${Math.round(b.score)}` : null,
      b.credit_rating ?? null,
    ]
      .filter(Boolean)
      .join(" · "),
  }));

  const addBond = (secid: string | null) => {
    if (!secid || selected.length >= MAX_BONDS) return;
    if (selected.some((b) => b.secid === secid)) return;
    const bond = bonds?.bonds.find((b) => b.secid === secid);
    if (bond) setSelected((prev) => [...prev, bond]);
  };

  const removeBond = (secid: string) => {
    setSelected((prev) => prev.filter((b) => b.secid !== secid));
  };

  const calculate = async () => {
    if (!selected.length) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.calculatePortfolio({
        secids: selected.map((b) => b.secid),
        budget_rub: budget,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка расчёта");
    } finally {
      setLoading(false);
    }
  };

  const alreadySelected = new Set(selected.map((b) => b.secid));
  const availableOptions = bondOptions.filter((o) => !alreadySelected.has(o.value));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Калькулятор</h1>
        <p className="text-sm text-muted-foreground">
          Оценка прибыли при удержании до оферты/погашения с учётом купонов (до {MAX_BONDS}{" "}
          бумаг, без налога)
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Parameters */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Параметры</CardTitle>
            <CardDescription>Выберите бумаги и укажите бюджет</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-1.5 text-sm">
              <span className="font-medium">Бюджет, ₽</span>
              <Input
                type="number"
                min={1000}
                step={1000}
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
              />
            </label>

            {/* Bond selector */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">Бумаги</span>
                <span
                  className={cn(
                    "text-xs",
                    selected.length >= MAX_BONDS ? "text-amber-600" : "text-muted-foreground",
                  )}
                >
                  {selected.length}/{MAX_BONDS}
                </span>
              </div>
              {bondsLoading ? (
                <Skeleton className="h-9 w-full" />
              ) : (
                <Combobox
                  options={availableOptions}
                  value={null}
                  onChange={addBond}
                  placeholder={
                    selected.length >= MAX_BONDS
                      ? `Максимум ${MAX_BONDS} бумаг`
                      : "Добавить бумагу…"
                  }
                  searchPlaceholder="Поиск по названию или SECID…"
                  disabled={selected.length >= MAX_BONDS}
                  emptyText="Бумага не найдена"
                />
              )}
            </div>

            {/* Selected bonds list */}
            {selected.length > 0 && (
              <div className="space-y-2">
                {selected.map((bond) => (
                  <div
                    key={bond.secid}
                    className="flex items-center justify-between rounded-md border border-border bg-muted/20 px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{bond.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {bond.secid}
                        {bond.ytm_net != null && ` · YTM ${bond.ytm_net.toFixed(2)}%`}
                        {bond.credit_rating && ` · ${bond.credit_rating}`}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="ml-2 h-7 w-7 shrink-0"
                      onClick={() => removeBond(bond.secid)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {error && (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}

            <Button
              className="w-full"
              onClick={calculate}
              disabled={!selected.length || loading}
            >
              <Calculator className="mr-2 h-4 w-4" />
              {loading ? "Расчёт…" : "Рассчитать"}
            </Button>
          </CardContent>
        </Card>

        {/* Results */}
        <div className="space-y-4">
          {result && (
            <>
              {/* Summary */}
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricCard label="Вложено" value={formatRub(result.total_invested_rub)} />
                <MetricCard
                  label="Прибыль"
                  value={formatRub(result.total_profit_rub)}
                  positive={result.total_profit_rub > 0}
                />
                <MetricCard
                  label="Доходность"
                  value={formatPct(result.portfolio_yield_pct)}
                  positive={(result.portfolio_yield_pct ?? 0) > 0}
                />
              </div>

              {/* Per-bond breakdown */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Детализация по бумагам</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-xs text-muted-foreground">
                          <th className="pb-2 text-left font-medium">Бумага</th>
                          <th className="pb-2 text-right font-medium">Лотов</th>
                          <th className="pb-2 text-right font-medium">Вложено</th>
                          <th className="pb-2 text-right font-medium">Купоны</th>
                          <th className="pb-2 text-right font-medium">Прибыль</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {result.results.map((r) => (
                          <tr key={r.secid}>
                            <td className="py-2">
                              <p className="font-medium">{r.name}</p>
                              <p className="text-xs text-muted-foreground">{r.secid}</p>
                            </td>
                            <td className="py-2 text-right">{r.lots}</td>
                            <td className="py-2 text-right">{formatRub(r.invested_rub)}</td>
                            <td className="py-2 text-right">{formatRub(r.coupon_income_rub)}</td>
                            <td
                              className={cn(
                                "py-2 text-right font-medium",
                                r.profit_rub > 0
                                  ? "text-green-600 dark:text-green-400"
                                  : "text-muted-foreground",
                              )}
                            >
                              {formatRub(r.profit_rub)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </>
          )}

          {!result && !loading && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
              <Calculator className="mb-3 h-10 w-10 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Выберите бумаги и нажмите «Рассчитать»
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p
          className={cn(
            "mt-1 text-xl font-bold",
            positive === true && "text-green-600 dark:text-green-400",
          )}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
