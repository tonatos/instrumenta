import type {
  AccountPreview,
  Bond,
  BondsListResponse,
  BrokerAccount,
  CalculatorResponse,
  ConfigResponse,
  DeleteSandboxAccountResult,
  OrderPreviewResponse,
  PlanResponse,
  Portfolio,
  TradingSyncResponse,
} from "./types";

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  getConfig: () => request<ConfigResponse>("/config/"),

  getBonds: (filterBy = "effective") =>
    request<BondsListResponse>(`/bonds/?filter_by=${filterBy}`),
  getBond: (secid: string) =>
    request<{ bond: Bond; coupons: unknown[] }>(`/bonds/${secid}`),
  refreshBonds: () => request<{ status: string }>("/bonds/refresh", { method: "POST" }),
  refreshRatings: () => request<{ count: number }>("/ratings/refresh", { method: "POST" }),

  getFavorites: () => request<BondsListResponse>("/favorites/"),
  addFavorite: (isin: string) =>
    request<{ isin: string }>(`/favorites/${isin}`, { method: "PUT" }),
  removeFavorite: (isin: string) =>
    request<void>(`/favorites/${isin}`, { method: "DELETE" }),

  getPortfolios: () => request<Portfolio[]>("/portfolios/"),
  getPortfolio: (id: string) => request<Portfolio>(`/portfolios/${id}`),
  createPortfolio: (body: {
    name: string;
    initial_amount_rub: number;
    horizon_date: string;
    risk_profile: string;
    api_trade_only?: boolean;
  }) =>
    request<Portfolio>("/portfolios/", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updatePortfolio: (
    id: string,
    body: {
      name?: string;
      initial_amount_rub?: number;
      horizon_date?: string;
      risk_profile?: string;
      api_trade_only?: boolean;
    },
  ) =>
    request<Portfolio>(`/portfolios/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deletePortfolio: (id: string) =>
    request<void>(`/portfolios/${id}`, { method: "DELETE" }),
  autoCompose: (id: string) =>
    request<Portfolio>(`/portfolios/${id}/auto-compose`, { method: "POST" }),
  clearPositions: (id: string) =>
    request<Portfolio>(`/portfolios/${id}/clear`, { method: "POST" }),
  addPosition: (id: string, body: { isin: string; lots: number }) =>
    request<Portfolio>(`/portfolios/${id}/positions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removePosition: (id: string, isin: string) =>
    request<void>(`/portfolios/${id}/positions/${isin}`, { method: "DELETE" }),
  setSlotOverride: (
    id: string,
    sourcePositionIsin: string,
    confirmedIsin: string | null,
  ) =>
    request<Portfolio>(`/portfolios/${id}/slots/override`, {
      method: "POST",
      body: JSON.stringify({
        source_position_isin: sourcePositionIsin,
        confirmed_isin: confirmedIsin,
      }),
    }),
  getPlan: (id: string) => request<PlanResponse>(`/portfolios/${id}/plan`),

  getAccounts: (kind: "sandbox" | "production" = "sandbox") =>
    request<BrokerAccount[]>(`/accounts?kind=${kind}`),
  createSandboxAccount: (body: { initial_amount_rub: number; name?: string }) =>
    request<BrokerAccount>("/accounts/sandbox", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteSandboxAccount: (accountId: string) =>
    request<DeleteSandboxAccountResult>(
      `/accounts/sandbox/${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
    ),
  getAccountPreview: (
    portfolioId: string,
    params: { account_id: string; kind: "sandbox" | "production" },
  ) =>
    request<AccountPreview>(
      `/portfolios/${portfolioId}/account-preview?account_id=${encodeURIComponent(params.account_id)}&kind=${params.kind}`,
    ),
  clearAccountForAttach: (
    portfolioId: string,
    body: {
      account_id: string;
      kind: "sandbox" | "production";
      pay_in_rub?: number;
    },
  ) =>
    request<AccountPreview>(`/portfolios/${portfolioId}/clear-account`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  attachAccount: (id: string, body: { account_id: string; kind: string }) =>
    request<Portfolio>(`/portfolios/${id}/attach`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  detachAccount: (id: string) =>
    request<Portfolio>(`/portfolios/${id}/detach`, { method: "POST" }),
  getPendingOperations: (id: string) =>
    request<TradingSyncResponse["pending_operations"]>(`/portfolios/${id}/pending-operations`),
  syncPortfolio: (id: string) =>
    request<TradingSyncResponse>(`/portfolios/${id}/sync`, { method: "POST" }),
  confirmPendingOperation: (
    id: string,
    opId: string,
    body: { lots?: number; price_pct?: number },
  ) =>
    request<TradingSyncResponse>(
      `/portfolios/${id}/pending-operations/${opId}/confirm`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  previewPendingOperation: (
    id: string,
    opId: string,
    body: { lots: number; price_pct: number },
  ) =>
    request<OrderPreviewResponse>(
      `/portfolios/${id}/pending-operations/${opId}/preview`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  cancelPendingOrder: (id: string, opId: string) =>
    request<TradingSyncResponse>(
      `/portfolios/${id}/pending-operations/${opId}/cancel-order`,
      { method: "POST" },
    ),
  cancelTopUpBatch: (id: string, batchId: string) =>
    request<TradingSyncResponse>(
      `/portfolios/${id}/top-up-batches/${batchId}/cancel`,
      { method: "POST" },
    ),
  setPutOfferDecision: (id: string, isin: string, decision: "exercise" | "hold") =>
    request<TradingSyncResponse>(
      `/portfolios/${id}/positions/${isin}/put-offer-decision`,
      { method: "POST", body: JSON.stringify({ decision }) },
    ),
  getPerformance: (id: string) =>
    request<{
      xirr_pct: number | null;
      coupons_received_rub: number;
      tax_paid_rub: number;
      money_rub: number;
    } | null>(`/portfolios/${id}/performance`),

  calculatePortfolio: (body: {
    secids: string[];
    budget_rub: number;
  }) =>
    request<CalculatorResponse>("/calculator/portfolio", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
