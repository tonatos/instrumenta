import type {
  AuthMeResponse,
  AccountOperationsResponse,
  AccountPreview,
  Bond,
  BondsListResponse,
  BrokerAccount,
  CalculatorResponse,
  ConfigResponse,
  DeleteSandboxAccountResult,
  OrderPreviewResponse,
  PlaceOrderRequest,
  PlaceOrderResponse,
  PlanResponse,
  Portfolio,
  SandboxPayInResponse,
  SellPositionPreviewResponse,
  SellQuoteResponse,
  TradingAdviceResponse,
  TradingStateResponse,
} from "./types";
import { getAuthToken, notifyUnauthorized } from "@/features/auth/authStorage";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  extra?: Record<string, unknown>;

  constructor(message: string, status: number, extra?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.extra = extra;
  }
}

function parseErrorMessage(text: string, status: number): ApiError {
  try {
    const body = JSON.parse(text) as {
      detail?: string;
      extra?: Record<string, unknown>;
    };
    const message =
      typeof body.detail === "string" && body.detail
        ? body.detail
        : text || `HTTP ${status}`;
    return new ApiError(message, status, body.extra);
  } catch {
    return new ApiError(text || `HTTP ${status}`, status);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    headers,
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401 && !path.startsWith("/auth/")) {
      notifyUnauthorized();
    }
    throw parseErrorMessage(text, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  getConfig: () => request<ConfigResponse>("/config/"),

  getMe: (token?: string) =>
    request<AuthMeResponse>("/auth/me", {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }),
  logout: () => request<{ status: string }>("/auth/logout", { method: "POST" }),

  getBonds: (filterBy = "effective") =>
    request<BondsListResponse>(`/bonds/?filter_by=${filterBy}`),
  getBondsByIsins: (isins: string[]) =>
    request<BondsListResponse>(
      `/bonds/by-isins?isins=${encodeURIComponent(isins.join(","))}`,
    ),
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
  resetAllSlotOverrides: (id: string) =>
    request<Portfolio>(`/portfolios/${id}/slots/reset-all`, { method: "POST" }),
  getPlan: (id: string) => request<PlanResponse>(`/portfolios/${id}/plan`),
  getTradingState: (id: string) =>
    request<TradingStateResponse>(`/portfolios/${id}/trading-state`),

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
  getAdvice: (id: string) =>
    request<TradingAdviceResponse>(`/portfolios/${id}/advice`),
  sandboxPayIn: (id: string, body: { amount_rub: number }) =>
    request<SandboxPayInResponse>(`/portfolios/${id}/sandbox-pay-in`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  previewOrder: (id: string, body: PlaceOrderRequest) =>
    request<OrderPreviewResponse>(`/portfolios/${id}/orders/preview`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  placeOrder: (id: string, body: PlaceOrderRequest) =>
    request<PlaceOrderResponse>(`/portfolios/${id}/orders/place`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancelOrder: (id: string, orderId: string) =>
    request<{ order_id: string; status: string }>(
      `/portfolios/${id}/orders/${encodeURIComponent(orderId)}/cancel`,
      { method: "POST" },
    ),
  sellPositionPreview: (
    id: string,
    isin: string,
    body: { lots: number; price_pct: number },
  ) =>
    request<SellPositionPreviewResponse>(
      `/portfolios/${id}/positions/${encodeURIComponent(isin)}/sell-preview`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  getSellQuote: (id: string, isin: string) =>
    request<SellQuoteResponse>(
      `/portfolios/${id}/positions/${encodeURIComponent(isin)}/sell-quote`,
    ),
  getPerformance: (id: string) =>
    request<{
      xirr_pct: number | null;
      coupons_received_rub: number;
      tax_paid_rub: number;
      money_rub: number;
    } | null>(`/portfolios/${id}/performance`),
  getAccountOperations: (id: string) =>
    request<AccountOperationsResponse>(`/portfolios/${id}/account-operations`),

  calculatePortfolio: (body: {
    secids: string[];
    budget_rub: number;
  }) =>
    request<CalculatorResponse>("/calculator/portfolio", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
