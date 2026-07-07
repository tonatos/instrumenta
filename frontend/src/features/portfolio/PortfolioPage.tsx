import { forwardRef, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  BarChart3,
  ChevronDown,
  ChevronUp,
  Edit2,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { api } from "@/api/client";
import type { Bond, Portfolio, PortfolioPosition } from "@/api/types";
import { CashflowTable } from "@/features/portfolio/CashflowTable";
import { PortfolioValueChart } from "@/features/portfolio/PortfolioValueChart";
import { ReinvestmentSlots } from "@/features/portfolio/ReinvestmentSlots";
import { TradingActionQueue } from "@/features/portfolio/TradingActionQueue";
import { TradingModeBadge, TradingModeWizard } from "@/features/portfolio/TradingModeWizard";
import { BondDetailSheet } from "@/features/screener/BondDetailSheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatPct, formatRub } from "@/lib/utils";

// ─── constants ───────────────────────────────────────────────────────────────

const RISK_LABELS: Record<string, string> = {
  normal: "Нормальный",
  aggressive: "Агрессивный",
  conservative: "Консервативный",
};

const SOURCE_LABELS: Record<string, string> = {
  initial: "Старт",
  reinvest_maturity: "Реинв. погаш.",
  reinvest_put_offer: "Реинв. оферта",
  reinvest_coupon_cash: "Реинв. купоны",
};

// ─── Portfolio form (shared create / edit) ───────────────────────────────────

function PortfolioForm({
  initial,
  onSubmit,
  isPending,
  submitLabel,
}: {
  initial: {
    name: string;
    initial_amount_rub: number;
    horizon_date: string;
    risk_profile: string;
    api_trade_only: boolean;
  };
  onSubmit: (values: typeof initial) => void;
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
        <Input
          type="date"
          value={form.horizon_date}
          min={new Date().toISOString().slice(0, 10)}
          onChange={(e) => setForm({ ...form, horizon_date: e.target.value })}
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

// ─── Positions Table ─────────────────────────────────────────────────────────

function PositionsTab({
  positions,
  portfolioId,
  isTrading,
  bonds,
}: {
  positions: PortfolioPosition[];
  portfolioId: string;
  isTrading: boolean;
  bonds: Bond[];
}) {
  const queryClient = useQueryClient();
  const [addLots, setAddLots] = useState(1);
  const [selectedIsin, setSelectedIsin] = useState<string | null>(null);
  const [detailSecid, setDetailSecid] = useState<string | null>(null);

  const removeMutation = useMutation({
    mutationFn: (isin: string) => api.removePosition(portfolioId, isin),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
    },
  });

  const addMutation = useMutation({
    mutationFn: (isin: string) => api.addPosition(portfolioId, { isin, lots: addLots }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", portfolioId] });
      setSelectedIsin(null);
    },
  });

  const bondOptions: ComboboxOption[] = bonds.map((b) => ({
    value: b.isin,
    label: b.name,
    description: [
      b.ytm_net != null ? `YTM ${b.ytm_net.toFixed(2)}%` : null,
      b.credit_rating ?? null,
    ]
      .filter(Boolean)
      .join(" · "),
  }));

  return (
    <div className="space-y-4">
      {positions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
          Позиций нет — воспользуйтесь «Автосостав» или добавьте бумаги вручную
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs" data-testid="positions-table">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Бумага</th>
                <th className="px-3 py-2 text-right font-semibold">
                  {isTrading ? "Пл / Фк" : "Лотов"}
                </th>
                <th className="px-3 py-2 text-right font-semibold">Вложено</th>
                <th className="px-3 py-2 text-left font-semibold">Источник</th>
                <th className="px-3 py-2 text-left font-semibold">Погашение</th>
                {!isTrading && <th className="w-8 px-2 py-2" />}
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr
                  key={pos.isin}
                  className="cursor-pointer border-t border-border hover:bg-muted/20"
                  onClick={() => setDetailSecid(pos.secid)}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="max-w-[180px] truncate text-left font-medium hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailSecid(pos.secid);
                      }}
                    >
                      {pos.name}
                    </button>
                    <p className="text-muted-foreground">{pos.secid}</p>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    {isTrading && pos.actual_lots != null ? (
                      <Tooltip
                        content={`Плановых: ${pos.lots} л. · Фактических: ${pos.actual_lots} л.`}
                      >
                        <span
                          className={cn(
                            "cursor-help",
                            pos.actual_lots !== pos.lots && "text-amber-600",
                          )}
                        >
                          {pos.lots}&nbsp;/&nbsp;{pos.actual_lots}
                        </span>
                      </Tooltip>
                    ) : (
                      `${pos.lots} л.`
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {formatRub(pos.purchase_amount_rub)}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {SOURCE_LABELS[pos.source] ?? pos.source}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {pos.offer_date
                      ? <span className="text-orange-600 dark:text-orange-400">{pos.offer_date} ⚡</span>
                      : (pos.maturity_date ?? "—")}
                  </td>
                  {!isTrading && (
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        className="rounded p-1 text-muted-foreground/50 transition-colors hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeMutation.mutate(pos.isin);
                        }}
                        disabled={removeMutation.isPending}
                        title="Убрать позицию"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add position row */}
      {!isTrading && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border bg-muted/20 p-3">
          <div className="min-w-[200px] flex-1">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Добавить бумагу</p>
            <Combobox
              options={bondOptions}
              value={selectedIsin}
              onChange={setSelectedIsin}
              placeholder="Найти по названию или ISIN…"
              searchPlaceholder="Поиск…"
            />
          </div>
          <div className="w-24">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Лотов</p>
            <Input
              type="number"
              min={1}
              value={addLots}
              onChange={(e) => setAddLots(Math.max(1, Number(e.target.value)))}
              className="h-9 text-sm"
            />
          </div>
          <Button
            size="sm"
            className="h-9"
            onClick={() => { if (selectedIsin) addMutation.mutate(selectedIsin); }}
            disabled={!selectedIsin || addMutation.isPending}
          >
            {addMutation.isPending
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Plus className="h-4 w-4" />}
          </Button>
        </div>
      )}

      <BondDetailSheet secid={detailSecid} onClose={() => setDetailSecid(null)} />
    </div>
  );
}

// ─── Forecast metrics ────────────────────────────────────────────────────────

function ForecastMetrics({
  plan,
}: {
  plan: NonNullable<ReturnType<typeof useQuery>["data"]>;
}) {
  const [heldExpanded, setHeldExpanded] = useState(false);

  const p = plan as {
    total_net_profit_rub: number;
    total_net_profit_with_held_rub: number;
    expected_xirr_pct: number | null;
    final_cash_balance: number;
    final_portfolio_value: number;
    held_positions: Array<{
      isin: string;
      name: string;
      lots: number;
      estimated_value_rub: number;
      maturity_date: string | null;
    }>;
  };

  return (
    <div className="space-y-3">
      {/* Primary metrics — big three */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Чистая прибыль
            <Tooltip content="Купоны + возврат номинала − вложения − НДФЛ. Позиции за горизонтом не учитываются.">
              <InfoIconButton />
            </Tooltip>
          </p>
          <p
            className={cn(
              "mt-1.5 text-2xl font-bold tabular-nums",
              p.total_net_profit_rub > 0
                ? "text-green-600 dark:text-green-400"
                : "text-red-600 dark:text-red-400",
            )}
          >
            {p.total_net_profit_rub > 0 ? "+" : ""}
            {formatRub(p.total_net_profit_rub)}
          </p>
          {p.held_positions.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              с held: {p.total_net_profit_with_held_rub > 0 ? "+" : ""}
              {formatRub(p.total_net_profit_with_held_rub)}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Годовая доходность (XIRR)
            <Tooltip content="Internal Rate of Return по всему cashflow от сегодня до горизонта. Аннуализированная, с учётом НДФЛ.">
              <InfoIconButton />
            </Tooltip>
          </p>
          {p.expected_xirr_pct != null ? (
            <p
              className={cn(
                "mt-1.5 text-2xl font-bold tabular-nums",
                p.expected_xirr_pct > 0
                  ? "text-green-600 dark:text-green-400"
                  : "text-muted-foreground",
              )}
            >
              {formatPct(p.expected_xirr_pct)}
            </p>
          ) : (
            <p className="mt-1.5 text-2xl font-bold text-muted-foreground">—</p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            Итоговая стоимость
            <Tooltip content="Свободный кэш + рыночная стоимость всех held-позиций по номиналу к дате горизонта.">
              <InfoIconButton />
            </Tooltip>
          </p>
          <p className="mt-1.5 text-2xl font-bold tabular-nums">
            {formatRub(p.final_portfolio_value)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            кэш: {formatRub(p.final_cash_balance)}
          </p>
        </div>
      </div>

      {/* Held positions — collapsible */}
      {p.held_positions.length > 0 && (
        <div className="rounded-xl border border-border bg-card">
          <button
            type="button"
            onClick={() => setHeldExpanded((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm"
          >
            <span className="font-medium">
              Удерживаются за горизонтом
              <Badge variant="secondary" className="ml-2 text-xs">
                {p.held_positions.length}
              </Badge>
            </span>
            {heldExpanded
              ? <ChevronUp className="h-4 w-4 text-muted-foreground" />
              : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>
          {heldExpanded && (
            <div className="border-t border-border px-4 pb-4 pt-3">
              <div className="space-y-2">
                {p.held_positions.map((h) => (
                  <div key={h.isin} className="flex items-center justify-between gap-2 text-sm">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{h.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {h.lots} л. · погашение {h.maturity_date ?? "—"}
                      </p>
                    </div>
                    <span className="shrink-0 tabular-nums">
                      {formatRub(h.estimated_value_rub)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const InfoIconButton = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(function InfoIconButton({ className, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      className={cn(
        "inline-flex shrink-0 cursor-help rounded-sm text-muted-foreground/50 hover:text-muted-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
      aria-label="Подробнее"
      {...props}
    >
      <svg
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4M12 8h.01" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </button>
  );
});

function portfolioPath(portfolioId: string, searchParams: URLSearchParams) {
  const qs = searchParams.toString();
  return `/portfolio/${encodeURIComponent(portfolioId)}${qs ? `?${qs}` : ""}`;
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { portfolioId: urlPortfolioId } = useParams();
  const [searchParams] = useSearchParams();
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [notesExpanded, setNotesExpanded] = useState(false);
  const defaultCreateForm = {
    name: "",
    initial_amount_rub: 400_000,
    horizon_date: new Date(Date.now() + 365 * 24 * 3600 * 1000).toISOString().slice(0, 10),
    risk_profile: "normal",
    api_trade_only: true,
  };

  const { data: portfolios, isLoading } = useQuery({
    queryKey: ["portfolios"],
    queryFn: api.getPortfolios,
  });

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
  });

  const { data: bonds } = useQuery({
    queryKey: ["bonds"],
    queryFn: () => api.getBonds(),
  });

  const activeId = useMemo(() => {
    if (!portfolios?.length) return null;
    if (urlPortfolioId && portfolios.some((p) => p.id === urlPortfolioId)) {
      return urlPortfolioId;
    }
    return portfolios[0].id;
  }, [portfolios, urlPortfolioId]);

  const searchQuery = searchParams.toString();

  useEffect(() => {
    if (!portfolios?.length || !activeId || urlPortfolioId === activeId) return;
    navigate(portfolioPath(activeId, searchParams), { replace: true });
  }, [portfolios, urlPortfolioId, activeId, navigate, searchQuery]);

  const active = portfolios?.find((p) => p.id === activeId);

  const selectPortfolio = (id: string) => {
    navigate(portfolioPath(id, searchParams));
    setEditOpen(false);
    setClearOpen(false);
    setDeleteOpen(false);
  };

  const {
    data: plan,
    isLoading: planLoading,
    refetch: refetchPlan,
  } = useQuery({
    queryKey: ["plan", activeId],
    queryFn: () => api.getPlan(activeId!),
    enabled: !!activeId,
  });

  const createMutation = useMutation({
    mutationFn: (values: typeof defaultCreateForm) => api.createPortfolio(values),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      navigate(portfolioPath(p.id, new URLSearchParams()));
      setCreateOpen(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: Partial<Portfolio>) => api.updatePortfolio(active!.id, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      setEditOpen(false);
    },
  });

  const composeMutation = useMutation({
    mutationFn: (id: string) => api.autoCompose(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", activeId] });
    },
  });

  const clearMutation = useMutation({
    mutationFn: (id: string) => api.clearPositions(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", activeId] });
      setClearOpen(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deletePortfolio(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      setDeleteOpen(false);
    },
  });

  const positions: PortfolioPosition[] = (active?.data?.positions as PortfolioPosition[]) ?? [];
  const slots = plan?.slots ?? [];
  const isTrading = active?.mode === "trading";
  const bondsList = bonds?.bonds ?? [];

  return (
    <div className="space-y-5">
      {/* ── Page header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Портфель</h1>
          <p className="text-sm text-muted-foreground">Планирование и прогноз доходности</p>
        </div>

        {/* Create dialog */}
        <DialogRoot open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Создать
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Новый портфель</DialogTitle>
              <DialogDescription>
                Задайте параметры. Состав можно добавить позже вручную или через «Автосостав».
              </DialogDescription>
            </DialogHeader>
            <PortfolioForm
              initial={defaultCreateForm}
              onSubmit={createMutation.mutate}
              isPending={createMutation.isPending}
              submitLabel="Создать"
            />
          </DialogContent>
        </DialogRoot>
      </div>

      {isLoading && <Skeleton className="h-12 w-full" />}

      {/* ── Portfolio selector ── */}
      {portfolios && portfolios.length > 0 && (
        <div className="flex flex-wrap gap-1.5 overflow-x-auto pb-1">
          {portfolios.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => selectPortfolio(p.id)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors",
                p.id === activeId
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted/50",
              )}
            >
              <span className="max-w-[140px] truncate">{p.name}</span>
              <TradingModeBadge portfolio={p} />
            </button>
          ))}
        </div>
      )}

      {/* ── Empty state ── */}
      {portfolios?.length === 0 && !isLoading && (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
            <BarChart3 className="h-12 w-12 text-muted-foreground" />
            <p className="text-muted-foreground">Создайте первый портфель для планирования</p>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Создать портфель
            </Button>
          </CardContent>
        </Card>
      )}

      {active && (
        <div className="space-y-5">
          {/* ─────────────────────────────────────────────────────────────────
              PORTFOLIO HEADER — визуально выделенная "шапка"
          ───────────────────────────────────────────────────────────────── */}
          <div className="overflow-hidden rounded-2xl border-2 border-primary/20 bg-card shadow-sm">
            {/* Name + mode + params */}
            <div className="bg-gradient-to-r from-primary/5 to-transparent px-6 py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <h2 className="text-xl font-bold tracking-tight">{active.name}</h2>
                    <TradingModeBadge portfolio={active} />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {formatRub(active.initial_amount_rub)}
                    </span>
                    <span>·</span>
                    <span>до {active.horizon_date}</span>
                    <span>·</span>
                    <span>{RISK_LABELS[active.risk_profile] ?? active.risk_profile}</span>
                    {active.cash_balance_rub > 0 && (
                      <>
                        <span>·</span>
                        <Tooltip
                          content={
                            isTrading
                              ? "Свободный кэш на брокерском счёте; пополнения распределяются автоматически"
                              : "Остаток бюджета, ещё не вложенный в бумаги"
                          }
                        >
                          <span className="cursor-help text-amber-600 dark:text-amber-400">
                            свободно {formatRub(active.cash_balance_rub)}
                          </span>
                        </Tooltip>
                      </>
                    )}
                  </div>
                  {isTrading && active.account_id && (
                    <p className="text-xs text-muted-foreground">
                      Счёт T-Invest: {active.account_id} ({active.account_kind})
                    </p>
                  )}
                </div>

                {/* Action buttons */}
                <div className="flex shrink-0 flex-wrap gap-2">
                  {/* Edit dialog */}
                  <DialogRoot open={editOpen} onOpenChange={setEditOpen}>
                    <DialogTrigger asChild>
                      <Button variant="outline" size="sm" className="gap-1.5">
                        <Edit2 className="h-3.5 w-3.5" />
                        Изменить
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-lg">
                      <DialogHeader>
                        <DialogTitle>Редактировать портфель</DialogTitle>
                        <DialogDescription>
                          Изменение бюджета не влияет на существующие позиции.
                        </DialogDescription>
                      </DialogHeader>
                      <PortfolioForm
                        initial={{
                          name: active.name,
                          initial_amount_rub: active.initial_amount_rub,
                          horizon_date: active.horizon_date,
                          risk_profile: active.risk_profile,
                          api_trade_only:
                            active.api_trade_only ??
                            active.data?.api_trade_only ??
                            true,
                        }}
                        onSubmit={updateMutation.mutate}
                        isPending={updateMutation.isPending}
                        submitLabel="Сохранить"
                      />
                    </DialogContent>
                  </DialogRoot>

                  {/* Auto-compose */}
                  {!isTrading && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => composeMutation.mutate(active.id)}
                      disabled={composeMutation.isPending}
                      className="gap-1.5"
                    >
                      {composeMutation.isPending
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <Wand2 className="h-3.5 w-3.5" />}
                      Автосостав
                    </Button>
                  )}

                  {/* Clear dialog */}
                  {!isTrading && positions.length > 0 && (
                    <DialogRoot open={clearOpen} onOpenChange={setClearOpen}>
                      <DialogTrigger asChild>
                        <Button variant="outline" size="sm" className="gap-1.5">
                          <X className="h-3.5 w-3.5" />
                          Очистить
                        </Button>
                      </DialogTrigger>
                      <DialogContent>
                        <DialogHeader>
                          <DialogTitle>Очистить состав портфеля</DialogTitle>
                          <DialogDescription>
                            Все позиции будут удалены. Бюджет вернётся к{" "}
                            {formatRub(active.initial_amount_rub)}.
                          </DialogDescription>
                        </DialogHeader>
                        <DialogFooter>
                          <Button
                            variant="destructive"
                            onClick={() => clearMutation.mutate(active.id)}
                            disabled={clearMutation.isPending}
                          >
                            {clearMutation.isPending && (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            )}
                            Очистить
                          </Button>
                        </DialogFooter>
                      </DialogContent>
                    </DialogRoot>
                  )}

                  {/* Trading mode */}
                  <TradingModeWizard
                    key={`${active.id}-${active.mode}`}
                    portfolio={active}
                    sandboxConfigured={config?.sandbox_configured ?? false}
                    productionConfigured={config?.production_configured ?? false}
                    tradingConfigLoaded={config !== undefined}
                    onPortfolioDeleted={(deletedId) => {
                      if (deletedId === active.id) {
                        const fallback = portfolios?.find((p) => p.id !== deletedId);
                        if (fallback) {
                          selectPortfolio(fallback.id);
                        } else {
                          navigate("/portfolio", { replace: true });
                        }
                      }
                    }}
                  />

                  {/* Delete dialog */}
                  <DialogRoot open={deleteOpen} onOpenChange={setDeleteOpen}>
                    <DialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground/60 hover:text-destructive"
                        title="Удалить портфель"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Удалить портфель</DialogTitle>
                        <DialogDescription>
                          «{active.name}» будет удалён без возможности восстановления.
                        </DialogDescription>
                      </DialogHeader>
                      <DialogFooter>
                        <Button
                          variant="destructive"
                          onClick={() => deleteMutation.mutate(active.id)}
                          disabled={deleteMutation.isPending}
                        >
                          {deleteMutation.isPending && (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          )}
                          Удалить
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </DialogRoot>
                </div>
              </div>
            </div>
          </div>

          {/* ── Pending operations (trading mode) ── */}
          {isTrading && active && (
            <TradingActionQueue
              portfolio={active}
              pendingConfirmId={searchParams.get("pending_confirm")}
            />
          )}

          {/* ─────────────────────────────────────────────────────────────────
              FORECAST — ключевые метрики
          ───────────────────────────────────────────────────────────────── */}
          {planLoading && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </div>
          )}
          {plan && <ForecastMetrics plan={plan} />}

          {plan && plan.value_timeline.length > 0 && (
            <PortfolioValueChart
              timeline={plan.value_timeline}
              initialAmount={active.initial_amount_rub}
              horizonDate={active.horizon_date}
            />
          )}

          {/* ─────────────────────────────────────────────────────────────────
              TABS: Позиции / Реинвестиции / Cashflow
          ───────────────────────────────────────────────────────────────── */}
          <TabsRoot defaultValue="positions">
            <TabsList className="w-full sm:w-auto">
              <TabsTrigger value="positions">
                Позиции
                {positions.length > 0 && (
                  <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs font-mono">
                    {positions.length}
                  </span>
                )}
              </TabsTrigger>
              <TabsTrigger value="reinvest">
                Реинвестиции
                {slots.length > 0 && (
                  <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs font-mono">
                    {slots.length}
                  </span>
                )}
              </TabsTrigger>
              <TabsTrigger value="cashflow" disabled={!plan}>
                Cashflow
                {plan && (
                  <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs font-mono">
                    {plan.cashflow.length}
                  </span>
                )}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="positions" className="mt-4">
              <PositionsTab
                positions={positions}
                portfolioId={active.id}
                isTrading={isTrading}
                bonds={bondsList}
              />
            </TabsContent>

            <TabsContent value="reinvest" className="mt-4">
              {plan ? (
                <ReinvestmentSlots
                  portfolioId={active.id}
                  slots={slots}
                  positions={positions}
                  bonds={bondsList}
                />
              ) : (
                <div className="flex items-center justify-center py-10">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetchPlan()}
                    className="gap-2"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Рассчитать прогноз
                  </Button>
                </div>
              )}
            </TabsContent>

            <TabsContent value="cashflow" className="mt-4">
              {plan && plan.cashflow.length > 0 ? (
                <CashflowTable
                  cashflow={plan.cashflow}
                  initialCash={
                    active.mode === "trading"
                      ? active.cash_balance_rub
                      : active.initial_amount_rub
                  }
                />
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  Нет данных. Добавьте позиции и пересчитайте прогноз.
                </p>
              )}
            </TabsContent>
          </TabsRoot>

          {/* Refresh plan */}
          {plan && (
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => refetchPlan()}
                className="gap-1.5 text-xs text-muted-foreground"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Пересчитать прогноз
              </Button>
            </div>
          )}

          {/* ─────────────────────────────────────────────────────────────────
              NOTES — в самом низу, свёрнуто по умолчанию
          ───────────────────────────────────────────────────────────────── */}
          {plan && plan.notes.length > 0 && (
            <div className="rounded-xl border border-border bg-muted/20">
              <button
                type="button"
                onClick={() => setNotesExpanded((v) => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-sm text-muted-foreground"
              >
                <span className="flex items-center gap-2">
                  <span>Замечания по составу</span>
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-xs font-mono">
                    {plan.notes.length}
                  </span>
                </span>
                {notesExpanded
                  ? <ChevronUp className="h-4 w-4" />
                  : <ChevronDown className="h-4 w-4" />}
              </button>
              {notesExpanded && (
                <div className="border-t border-border px-4 pb-4 pt-3">
                  <ul className="space-y-2 text-xs text-muted-foreground">
                    {plan.notes.map((n, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
                        <span>{n}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
