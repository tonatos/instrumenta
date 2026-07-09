import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { portfolioPath } from "@/features/portfolio/utils";

function parseDurationLimit(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function portfolioFormToUpdateBody(values: Partial<PortfolioFormValues>) {
  const body: Record<string, unknown> = {};
  if (values.name !== undefined) body.name = values.name;
  if (values.initial_amount_rub !== undefined) body.initial_amount_rub = values.initial_amount_rub;
  if (values.horizon_date !== undefined) body.horizon_date = values.horizon_date;
  if (values.risk_profile !== undefined) body.risk_profile = values.risk_profile;
  if (values.api_trade_only !== undefined) body.api_trade_only = values.api_trade_only;
  if (values.max_weighted_duration_years !== undefined) {
    body.max_weighted_duration_years = parseDurationLimit(values.max_weighted_duration_years);
  }
  return body;
}

export type PortfolioFormValues = {
  name: string;
  initial_amount_rub: number;
  horizon_date: string;
  risk_profile: string;
  api_trade_only: boolean;
  max_weighted_duration_years: string;
};

export const defaultCreateForm: PortfolioFormValues = {
  name: "",
  initial_amount_rub: 400_000,
  horizon_date: new Date(Date.now() + 365 * 24 * 3600 * 1000).toISOString().slice(0, 10),
  risk_profile: "normal",
  api_trade_only: true,
  max_weighted_duration_years: "",
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
    mutationFn: (values: PortfolioFormValues) =>
      api.createPortfolio({
        name: values.name,
        initial_amount_rub: values.initial_amount_rub,
        horizon_date: values.horizon_date,
        risk_profile: values.risk_profile,
        api_trade_only: values.api_trade_only,
        max_weighted_duration_years: parseDurationLimit(values.max_weighted_duration_years),
      }),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      navigate(portfolioPath(p.id, new URLSearchParams()));
      onCreateSuccess?.();
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: PortfolioFormValues) =>
      api.updatePortfolio(activeId!, portfolioFormToUpdateBody(values)),
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
