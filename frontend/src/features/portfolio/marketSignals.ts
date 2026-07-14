import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Notification, NotificationKind } from "@/api/types";

export const MARKET_SIGNAL_KINDS = new Set<NotificationKind>([
  "spread_anomaly",
  "spread_widening",
  "sector_stress",
  "turbo_entry",
]);

export function isMarketSignalKind(kind: string): boolean {
  return MARKET_SIGNAL_KINDS.has(kind as NotificationKind);
}

export function isMarketSignal(notification: Notification): boolean {
  return isMarketSignalKind(notification.kind);
}

export function usePortfolioNotifications(portfolioId: string, enabled = true) {
  const query = useQuery({
    queryKey: ["notifications", portfolioId],
    queryFn: () => api.getNotifications(portfolioId),
    refetchInterval: 60_000,
    enabled: enabled && portfolioId.length > 0,
  });

  const all = query.data?.notifications ?? [];

  const signals = useMemo(
    () => all.filter(isMarketSignal),
    [all],
  );

  const notifications = useMemo(
    () => all.filter((n) => !isMarketSignal(n)),
    [all],
  );

  const unreadSignalsCount = useMemo(
    () => signals.filter((n) => n.is_unread).length,
    [signals],
  );

  const unreadNotificationsCount = useMemo(
    () => notifications.filter((n) => n.is_unread).length,
    [notifications],
  );

  return {
    ...query,
    all,
    signals,
    notifications,
    unreadSignalsCount,
    unreadNotificationsCount,
  };
}
