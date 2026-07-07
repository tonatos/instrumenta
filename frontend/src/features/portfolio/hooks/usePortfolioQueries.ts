import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type { PortfolioPosition } from "@/api/types";
import { STALE } from "@/features/portfolio/hooks/queryConfig";
import { portfolioPath } from "@/features/portfolio/utils";

export function usePortfolioQueries() {
  const navigate = useNavigate();
  const { portfolioId: urlPortfolioId } = useParams();
  const [searchParams] = useSearchParams();

  const { data: portfolios, isLoading } = useQuery({
    queryKey: ["portfolios"],
    queryFn: api.getPortfolios,
    staleTime: STALE.portfolios,
  });

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    staleTime: STALE.config,
  });

  const { data: bonds } = useQuery({
    queryKey: ["bonds"],
    queryFn: () => api.getBonds(),
    staleTime: STALE.bonds,
    refetchOnWindowFocus: false,
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
  const isTrading = active?.mode === "trading";

  const {
    data: plan,
    isLoading: planLoading,
    refetch: refetchPlan,
  } = useQuery({
    queryKey: ["plan", activeId],
    queryFn: () => api.getPlan(activeId!),
    enabled: !!activeId,
    staleTime: STALE.plan,
    refetchOnWindowFocus: !isTrading,
  });

  const positions: PortfolioPosition[] =
    (active?.data?.positions as PortfolioPosition[]) ?? [];
  const slots = plan?.slots ?? [];
  const bondsList = bonds?.bonds ?? [];

  return {
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
  };
}
