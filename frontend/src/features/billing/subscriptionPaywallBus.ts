/** Bridge for API client → React paywall (same pattern as auth unauthorized). */

export type SubscriptionPaywallReason =
  | "portfolio.attach"
  | "broker_credentials.write"
  | "trading_portfolio.access"
  | "telegram_bot"
  | "default";

export type SubscriptionPaywallPayload = {
  reason?: SubscriptionPaywallReason;
};

type Handler = (payload?: SubscriptionPaywallPayload) => void;

let onPaywall: Handler | null = null;

export function setSubscriptionPaywallHandler(handler: Handler | null): void {
  onPaywall = handler;
}

export function notifySubscriptionRequired(payload?: SubscriptionPaywallPayload): void {
  onPaywall?.(payload);
}
