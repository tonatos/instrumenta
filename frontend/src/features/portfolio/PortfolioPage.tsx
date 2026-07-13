import { useState } from "react";
import { useNavigate } from "react-router-dom";
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
import { ForecastMetrics } from "@/features/portfolio/components/ForecastMetrics";
import { PortfolioForm } from "@/features/portfolio/components/PortfolioForm";
import { PortfolioTabs } from "@/features/portfolio/components/PortfolioTabs";
import {
  defaultCreateForm,
  usePortfolioMutations,
} from "@/features/portfolio/hooks/usePortfolioMutations";
import { usePortfolioQueries } from "@/features/portfolio/hooks/usePortfolioQueries";
import { RISK_LABELS } from "@/features/portfolio/labels";
import { PortfolioValueChart } from "@/features/portfolio/PortfolioValueChart";
import { TradingActionQueue } from "@/features/portfolio/trading/TradingActionQueue";
import { NotificationsPanel } from "@/features/portfolio/NotificationsPanel";
import { TradingModeBadge, TradingModeWizard } from "@/features/portfolio/TradingModeWizard";
import { portfolioInvestedCapitalRub, portfolioPath } from "@/features/portfolio/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogRoot,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, formatDate, formatRub } from "@/lib/utils";

export function PortfolioPage() {
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [notesExpanded, setNotesExpanded] = useState(false);

  const {
    searchParams,
    portfolios,
    isLoading,
    config,
    bondsList,
    activeId,
    active,
    plan,
    planLoading,
    refetchPlan,
    positions,
    slots,
    isTrading,
    tradingAdvice,
    tradingStateFetching,
    tradingStateError,
    tradingStateErrorDetail,
    tradingStateUpdatedAt,
    rateScenario,
  } = usePortfolioQueries();

  const {
    createMutation,
    updateMutation,
    composeMutation,
    clearMutation,
    deleteMutation,
  } = usePortfolioMutations({
    activeId,
    onCreateSuccess: () => setCreateOpen(false),
    onEditSuccess: () => setEditOpen(false),
    onClearSuccess: () => setClearOpen(false),
    onDeleteSuccess: () => setDeleteOpen(false),
  });

  const selectPortfolio = (id: string) => {
    navigate(portfolioPath(id, searchParams));
    setEditOpen(false);
    setClearOpen(false);
    setDeleteOpen(false);
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Портфель</h1>
          <p className="text-sm text-muted-foreground">Планирование и прогноз доходности</p>
        </div>

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
          <div className="overflow-hidden rounded-2xl border-2 border-primary/20 bg-card shadow-sm">
            <div className="bg-gradient-to-r from-primary/5 to-transparent px-6 py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <h2 className="text-xl font-bold tracking-tight">{active.name}</h2>
                    <TradingModeBadge portfolio={active} />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                    {portfolioInvestedCapitalRub(active) > active.initial_amount_rub ? (
                      <>
                        <Tooltip content="Начальный бюджет при создании портфеля">
                          <span className="cursor-help font-medium text-foreground">
                            старт {formatRub(active.initial_amount_rub)}
                          </span>
                        </Tooltip>
                        <span>·</span>
                        <Tooltip content="Вложенный капитал: начальный бюджет плюс учтённые пополнения счёта">
                          <span className="cursor-help font-semibold text-foreground">
                            капитал {formatRub(portfolioInvestedCapitalRub(active))}
                          </span>
                        </Tooltip>
                      </>
                    ) : (
                      <span className="font-medium text-foreground">
                        {formatRub(active.initial_amount_rub)}
                      </span>
                    )}
                    <span>·</span>
                    <span>до {formatDate(active.horizon_date)}</span>
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

                <div className="flex shrink-0 flex-wrap gap-2">
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
                          Изменение бюджета не влияет на существующие позиции. Смена
                          горизонта пересчитывает прогноз реинвестиций, не меняя уже
                          купленные бумаги на счёте.
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
                          max_weighted_duration_years:
                            active.data?.max_weighted_duration_years != null
                              ? String(active.data.max_weighted_duration_years)
                              : "",
                        }}
                        onSubmit={updateMutation.mutate}
                        isPending={updateMutation.isPending}
                        submitLabel="Сохранить"
                      />
                    </DialogContent>
                  </DialogRoot>

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

          {isTrading && activeId && (
            <NotificationsPanel portfolioId={activeId} />
          )}

          {isTrading && active && (
            <TradingActionQueue
              portfolio={active}
              suggestionConfirmId={searchParams.get("suggestion_confirm")}
              advice={tradingAdvice}
              adviceLoading={planLoading}
              adviceFetching={tradingStateFetching}
              adviceError={tradingStateError}
              adviceErrorDetail={tradingStateErrorDetail}
              refetchAdvice={refetchPlan}
              adviceUpdatedAt={tradingStateUpdatedAt}
              rateScenario={rateScenario}
            />
          )}

          {planLoading && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </div>
          )}
          {plan && (
            <ForecastMetrics
              plan={plan}
              isTrading={isTrading}
              weightedDurationYears={
                isTrading
                  ? tradingAdvice?.weighted_duration_years ?? plan.weighted_duration_years
                  : plan.weighted_duration_years
              }
            />
          )}

          {plan && plan.value_timeline.length > 0 && (
            <PortfolioValueChart
              timeline={plan.value_timeline}
              initialAmount={active.initial_amount_rub}
              horizonDate={active.horizon_date}
            />
          )}

          <PortfolioTabs
            active={active}
            plan={plan}
            positions={positions}
            slots={slots}
            bondsList={bondsList}
            isTrading={isTrading}
            tradingAdvice={tradingAdvice}
            refetchPlan={refetchPlan}
          />

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
