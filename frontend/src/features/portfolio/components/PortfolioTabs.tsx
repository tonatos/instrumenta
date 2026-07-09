import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { Bond, PlanResponse, Portfolio, PortfolioPosition, TradingAdviceResponse } from "@/api/types";
import { buildTradingDisplayPositions } from "@/features/portfolio/trading/buildTradingDisplayPositions";
import { AccountOperationsTable } from "@/features/portfolio/AccountOperationsTable";
import { CashflowTable } from "@/features/portfolio/CashflowTable";
import { PositionsTab } from "@/features/portfolio/components/PositionsTab";
import { useAccountOperations } from "@/features/portfolio/hooks/useAccountOperations";
import { ReinvestmentSlots } from "@/features/portfolio/ReinvestmentSlots";
import { Button } from "@/components/ui/button";
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from "@/components/ui/tabs";

export function PortfolioTabs({
  active,
  plan,
  positions,
  slots,
  bondsList,
  isTrading,
  tradingAdvice,
  refetchPlan,
}: {
  active: Portfolio;
  plan: PlanResponse | undefined;
  positions: PortfolioPosition[];
  slots: PlanResponse["slots"];
  bondsList: Bond[];
  isTrading: boolean;
  tradingAdvice?: TradingAdviceResponse;
  refetchPlan: () => void;
}) {
  const [activeTab, setActiveTab] = useState("positions");
  const operationsEnabled =
    isTrading && Boolean(active.account_id) && activeTab === "operations";

  const {
    data: accountOperationsData,
    isLoading: accountOperationsLoading,
    isError: accountOperationsError,
    refetch: refetchAccountOperations,
    isFetching: accountOperationsFetching,
  } = useAccountOperations(active.id, operationsEnabled);

  const bondsByIsin = useMemo(
    () => new Map(bondsList.map((b) => [b.isin, b])),
    [bondsList],
  );

  const positionsBadgeCount = useMemo(() => {
    if (!isTrading) {
      return active.positions_count;
    }
    return buildTradingDisplayPositions(
      tradingAdvice?.holdings ?? [],
      positions,
      bondsByIsin,
    ).length;
  }, [
    isTrading,
    active.positions_count,
    tradingAdvice?.holdings,
    positions,
    bondsByIsin,
  ]);

  return (
    <TabsRoot value={activeTab} onValueChange={setActiveTab}>
      <TabsList className="w-full sm:w-auto">
        <TabsTrigger value="positions">
          Позиции
          {positionsBadgeCount > 0 && (
            <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs font-mono">
              {positionsBadgeCount}
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
        {isTrading && active.account_id && (
          <TabsTrigger value="operations">
            История операций
            {accountOperationsData && (
              <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs font-mono">
                {accountOperationsData.operations.length}
              </span>
            )}
          </TabsTrigger>
        )}
      </TabsList>

      <TabsContent value="positions" className="mt-4">
        <PositionsTab
          positions={positions}
          portfolioId={active.id}
          isTrading={isTrading}
          accountKind={active.account_kind}
          bonds={bondsList}
          closedPositionsCount={active.closed_positions_count ?? 0}
          tradingAdvice={tradingAdvice}
        />
      </TabsContent>

      <TabsContent value="reinvest" className="mt-4">
        {plan ? (
          <ReinvestmentSlots
            portfolioId={active.id}
            slots={slots}
            positions={positions}
            planNotes={plan.notes}
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

      {isTrading && active.account_id && (
        <TabsContent value="operations" className="mt-4">
          <AccountOperationsTable
            operations={accountOperationsData?.operations ?? []}
            isLoading={accountOperationsLoading}
            isError={accountOperationsError}
            onRefresh={() => refetchAccountOperations()}
            isRefreshing={accountOperationsFetching}
          />
        </TabsContent>
      )}
    </TabsRoot>
  );
}
