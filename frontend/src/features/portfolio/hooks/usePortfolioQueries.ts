import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type { Bond, PortfolioPosition } from "@/api/types";
import type { BondRiskProfile } from "@/features/bonds/bondScore";
import { STALE, tradingStateQueryKey } from "@/features/portfolio/hooks/queryConfig";
import { useRateScenario } from "@/features/settings/RateScenarioProvider";
import { portfolioPath } from "@/features/portfolio/utils";

const TERMINAL_ORDER_STATUSES = new Set([
  "EXECUTION_REPORT_STATUS_FILL",
  "EXECUTION_REPORT_STATUS_CANCELLED",
  "EXECUTION_REPORT_STATUS_REJECTED",
]);

function hasActiveOrders(advice: { active_orders: Array<{ status: string }> } | undefined) {
  if (!advice) return false;
  return advice.active_orders.some((o) => !TERMINAL_ORDER_STATUSES.has(o.status));
}

export function usePortfolioQueries() {
  const navigate = useNavigate();
  const { portfolioId: urlPortfolioId } = useParams();
  const [searchParams] = useSearchParams();
  const { rateScenario } = useRateScenario();

  const { data: portfolios, isLoading } = useQuery({
    queryKey: ["portfolios"],
    queryFn: api.getPortfolios,
    staleTime: STALE.portfolios,
  });

  const activeId = useMemo(() => {
    if (urlPortfolioId) return urlPortfolioId;
    if (!portfolios?.length) return null;
    return portfolios[0].id;
  }, [urlPortfolioId, portfolios]);

  const activeFromList = portfolios?.find((p) => p.id === activeId);
  const needsDirectPortfolio = Boolean(activeId && portfolios && !activeFromList);

  const { data: directPortfolio, isError: directPortfolioMissing } = useQuery({
    queryKey: ["portfolio", activeId],
    queryFn: () => api.getPortfolio(activeId!),
    enabled: needsDirectPortfolio,
    staleTime: STALE.portfolios,
    retry: false,
  });

  const active = activeFromList ?? directPortfolio;
  const isTrading = active?.mode === "trading";
  const accessLocked = Boolean(active?.access_locked);
  const tradingEnabled = isTrading && Boolean(active?.account_id) && !accessLocked;

  const searchQuery = searchParams.toString();

  useEffect(() => {
    if (!portfolios?.length || !urlPortfolioId || urlPortfolioId === portfolios[0].id) return;
    if (portfolios.some((p) => p.id === urlPortfolioId)) return;
    if (needsDirectPortfolio && !directPortfolioMissing) return;
    navigate(portfolioPath(portfolios[0].id, searchParams), { replace: true });
  }, [
    portfolios,
    urlPortfolioId,
    needsDirectPortfolio,
    directPortfolioMissing,
    navigate,
    searchQuery,
  ]);

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    staleTime: STALE.config,
  });

  const { data: me, isSuccess: meLoaded } = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api.getMe(),
    staleTime: STALE.config,
  });

  const sandboxConfigured = Boolean(me?.credentials?.sandbox);
  const productionConfigured = Boolean(me?.credentials?.production);
  const tradingCredentialsLoaded = meLoaded;

  const portfolioRiskProfile = (active?.risk_profile ?? "normal") as BondRiskProfile;

  const portfolioReady = Boolean(active);

  const { data: bonds } = useQuery({
    queryKey: ["bonds", rateScenario, portfolioRiskProfile],
    queryFn: () => api.getBonds({ export: true }, portfolioRiskProfile),
    staleTime: STALE.bonds,
    refetchOnWindowFocus: false,
    enabled: portfolioReady,
  });

  const positions: PortfolioPosition[] =
    (active?.data?.positions as PortfolioPosition[]) ?? [];

  const {
    data: simulationPlan,
    isLoading: simulationPlanLoading,
    refetch: refetchSimulationPlan,
  } = useQuery({
    queryKey: ["plan", activeId, rateScenario],
    queryFn: () => api.getPlan(activeId!),
    enabled: !!activeId && portfolioReady && !isTrading,
    staleTime: STALE.plan,
    refetchOnWindowFocus: true,
  });

  const {
    data: tradingState,
    isLoading: tradingStateLoading,
    isFetching: tradingStateFetching,
    isError: tradingStateError,
    error: tradingStateErrorDetail,
    dataUpdatedAt: tradingStateUpdatedAt,
    refetch: refetchTradingState,
  } = useQuery({
    queryKey: tradingStateQueryKey(activeId ?? "", rateScenario),
    queryFn: () => api.getTradingState(activeId!),
    enabled: !!activeId && portfolioReady && tradingEnabled,
    staleTime: STALE.tradingSync,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!tradingEnabled) return false;
      if (hasActiveOrders(query.state.data?.advice)) return 30_000;
      return false;
    },
  });

  const plan = isTrading ? tradingState?.plan : simulationPlan;
  const planLoading = isTrading ? tradingStateLoading : simulationPlanLoading;
  const refetchPlan = isTrading ? refetchTradingState : refetchSimulationPlan;

  const positionIsins = useMemo(() => {
    const isins = new Set<string>();
    for (const position of positions) {
      if (position.isin) isins.add(position.isin);
    }
    for (const holding of tradingState?.advice?.holdings ?? []) {
      isins.add(holding.isin);
    }
    return [...isins].sort();
  }, [positions, tradingState?.advice?.holdings]);

  const missingPositionIsins = useMemo(() => {
    const screenerIsins = new Set((bonds?.bonds ?? []).map((bond) => bond.isin));
    return positionIsins.filter((isin) => !screenerIsins.has(isin));
  }, [bonds?.bonds, positionIsins]);

  const { data: positionBonds } = useQuery({
    queryKey: ["bonds-by-isins", activeId, missingPositionIsins, portfolioRiskProfile],
    queryFn: () => api.getBondsByIsins(missingPositionIsins, portfolioRiskProfile),
    enabled: missingPositionIsins.length > 0 && portfolioReady,
    staleTime: STALE.bonds,
    refetchOnWindowFocus: false,
  });

  const bondsList = useMemo(() => {
    const byIsin = new Map<string, Bond>();
    for (const bond of bonds?.bonds ?? []) {
      byIsin.set(bond.isin, bond);
    }
    if (missingPositionIsins.length > 0) {
      for (const bond of positionBonds?.bonds ?? []) {
        byIsin.set(bond.isin, bond);
      }
    }
    return [...byIsin.values()];
  }, [bonds?.bonds, missingPositionIsins.length, positionBonds?.bonds]);

  const slots = plan?.slots ?? [];

  return {
    searchParams,
    portfolios,
    isLoading,
    config,
    sandboxConfigured,
    productionConfigured,
    tradingCredentialsLoaded,
    bondsList,
    activeId,
    active,
    plan,
    planLoading,
    refetchPlan,
    positions,
    slots,
    isTrading,
    accessLocked,
    tradingEnabled,
    tradingAdvice: tradingState?.advice,
    tradingStateFetching,
    tradingStateError,
    tradingStateErrorDetail,
    tradingStateUpdatedAt,
    rateScenario,
  };
}
