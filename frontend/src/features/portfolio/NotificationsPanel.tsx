import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { api } from "@/api/client";
import type { Notification } from "@/api/types";
import { NOTIFICATION_KIND_LABELS } from "@/features/portfolio/labels";
import { usePortfolioNotifications } from "@/features/portfolio/marketSignals";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function notificationTitle(notification: Notification): string {
  const payload = notification.payload;
  const name = typeof payload.name === "string" ? payload.name : "Уведомление";
  return name;
}

function notificationBody(notification: Notification): string {
  const reason = notification.payload.reason;
  return typeof reason === "string" ? reason : "";
}

function notificationBorderClass(notification: Notification): string {
  if (!notification.is_unread) {
    return "border-border/60";
  }
  if (notification.urgency === "critical" || notification.kind === "risk_escalation") {
    return "border-red-400/50";
  }
  if (notification.urgency === "soon" || notification.kind === "put_offer_action") {
    return "border-amber-400/40";
  }
  return "border-border/60";
}

function notificationBackgroundClass(notification: Notification): string {
  if (!notification.is_unread) {
    return "bg-card/50";
  }
  if (notification.urgency === "critical" || notification.kind === "risk_escalation") {
    return "bg-red-500/5";
  }
  if (notification.urgency === "soon" || notification.kind === "put_offer_action") {
    return "bg-amber-500/10";
  }
  return "bg-card/50";
}

interface NotificationsPanelProps {
  portfolioId: string;
}

export function NotificationsPanel({ portfolioId }: NotificationsPanelProps) {
  const queryClient = useQueryClient();
  const { notifications, unreadNotificationsCount, isLoading } =
    usePortfolioNotifications(portfolioId);

  const markRead = useMutation({
    mutationFn: (notificationId: string) => api.markNotificationRead(notificationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications", portfolioId] });
    },
  });

  if (isLoading) {
    return null;
  }

  if (notifications.length === 0) {
    return null;
  }

  return (
    <div
      className="space-y-4 rounded-xl border border-amber-400/40 bg-amber-500/5 p-4"
      data-testid="notifications-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
          <Bell className="h-4 w-4" />
          Уведомления
          {unreadNotificationsCount > 0 && (
            <Badge
              className="bg-amber-500/20 text-amber-900 dark:text-amber-200"
              data-testid="notifications-unread-badge"
            >
              {unreadNotificationsCount}
            </Badge>
          )}
        </p>
      </div>

      <div className="space-y-2">
        {notifications.map((notification) => {
          const kindLabel =
            NOTIFICATION_KIND_LABELS[notification.kind] ?? notification.kind;

          return (
            <div
              key={notification.id}
              data-testid={`notification-${notification.id}`}
              className={cn(
                "space-y-2 rounded-lg border p-3",
                notificationBorderClass(notification),
                notificationBackgroundClass(notification),
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="text-sm font-medium">{notificationTitle(notification)}</p>
                <Badge variant="outline" className="text-xs">
                  {kindLabel}
                </Badge>
              </div>
              {notificationBody(notification) && (
                <p className="text-sm text-muted-foreground">{notificationBody(notification)}</p>
              )}
              {notification.is_unread && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => markRead.mutate(notification.id)}
                  disabled={markRead.isPending}
                >
                  Прочитано
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
