import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { api } from "@/api/client";
import type { Notification } from "@/api/types";
import { NOTIFICATION_KIND_LABELS } from "@/features/portfolio/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function notificationTitle(notification: Notification): string {
  const payload = notification.payload;
  const name = typeof payload.name === "string" ? payload.name : "Уведомление";
  const kindLabel = NOTIFICATION_KIND_LABELS[notification.kind] ?? notification.kind;
  return `${kindLabel}: ${name}`;
}

function notificationBody(notification: Notification): string {
  const reason = notification.payload.reason;
  return typeof reason === "string" ? reason : "";
}

interface NotificationsPanelProps {
  portfolioId: string;
}

export function NotificationsPanel({ portfolioId }: NotificationsPanelProps) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["notifications", portfolioId],
    queryFn: () => api.getNotifications(portfolioId),
    refetchInterval: 60_000,
  });

  const markRead = useMutation({
    mutationFn: (notificationId: string) => api.markNotificationRead(notificationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications", portfolioId] });
    },
  });

  const notifications = data?.notifications ?? [];
  const unreadCount = notifications.filter((item) => item.is_unread).length;

  if (isLoading) {
    return null;
  }

  if (notifications.length === 0) {
    return null;
  }

  return (
    <Card data-testid="notifications-panel">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <Bell className="h-4 w-4" />
          Уведомления
          {unreadCount > 0 && (
            <Badge variant="destructive" data-testid="notifications-unread-badge">
              {unreadCount}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {notifications.map((notification) => (
          <div
            key={notification.id}
            data-testid={`notification-${notification.id}`}
            className={cn(
              "rounded-md border p-3 text-sm",
              notification.is_unread ? "border-amber-300 bg-amber-50/60" : "border-border",
            )}
          >
            <div className="font-medium">{notificationTitle(notification)}</div>
            <p className="mt-1 text-muted-foreground">{notificationBody(notification)}</p>
            {notification.is_unread && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => markRead.mutate(notification.id)}
              >
                Прочитано
              </Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
