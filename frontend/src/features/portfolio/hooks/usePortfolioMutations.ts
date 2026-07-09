import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import type { Portfolio } from "@/api/types";
import { portfolioPath } from "@/features/portfolio/utils";

export type PortfolioFormValues = {
  name: string;
  initial_amount_rub: number;
  horizon_date: string;
  risk_profile: string;
  api_trade_only: boolean;
};

export const defaultCreateForm: PortfolioFormValues = {
  name: "",
  initial_amount_rub: 400_000,
  horizon_date: new Date(Date.now() + 365 * 24 * 3600 * 1000).toISOString().slice(0, 10),
  risk_profile: "normal",
  api_trade_only: true,
};

export function usePortfolioMutations({
  activeId,
  onCreateSuccess,
  onEditSuccess,
  onClearSuccess,
  onDeleteSuccess,
}: {
  activeId: string | null;
  onCreateSuccess?: () => void;
  onEditSuccess?: () => void;
  onClearSuccess?: () => void;
  onDeleteSuccess?: () => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const createMutation = useMutation({
    mutationFn: (values: PortfolioFormValues) => api.createPortfolio(values),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      navigate(portfolioPath(p.id, new URLSearchParams()));
      onCreateSuccess?.();
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: Partial<Portfolio>) => api.updatePortfolio(activeId!, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      queryClient.invalidateQueries({ queryKey: ["plan", activeId] });
      queryClient.invalidateQueries({ queryKey: ["trading-state", activeId] });
      onEditSuccess?.();
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
      onClearSuccess?.();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deletePortfolio(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      onDeleteSuccess?.();
    },
  });

  return {
    createMutation,
    updateMutation,
    composeMutation,
    clearMutation,
    deleteMutation,
  };
}
