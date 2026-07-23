import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSubscriptionPaywall } from "@/features/billing/SubscriptionPaywallProvider";

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const { openPaywall } = useSubscriptionPaywall();
  const { data: me, isLoading: meLoading } = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api.getMe(),
  });
  const { data: billing, isLoading: billingLoading } = useQuery({
    queryKey: ["billing-status"],
    queryFn: () => api.getBillingStatus(),
  });

  const disconnectMutation = useMutation({
    mutationFn: () => api.disconnectTelegramBot(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth-me"] });
    },
  });

  if (meLoading || billingLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const hasAccess = Boolean(billing?.complimentary || billing?.has_active_access);
  const bot = me?.telegram_bot;
  const deepLink = bot?.deep_link;
  const connected = Boolean(bot?.connected);
  const configured = Boolean(bot?.configured);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-lg font-medium">Telegram-уведомления</h2>
        <p className="text-sm text-muted-foreground">
          Бот пишет о пут‑офертах и критических эскалациях риска по вашим trading-портфелям.
          Сообщения уходят на Telegram ID владельца портфеля — тот же аккаунт, через который вы
          вошли в приложение.
        </p>
      </section>

      {!hasAccess && (
        <div className="space-y-3 rounded-md border border-border bg-muted/30 p-4">
          <p className="text-sm font-medium">Доступно по подписке Pro</p>
          <p className="text-sm text-muted-foreground">
            Подключите тариф, затем откройте бота в Telegram и нажмите Start.
          </p>
          <Button className="min-h-10" onClick={() => openPaywall({ reason: "telegram_bot" })}>
            Подключить тариф
          </Button>
        </div>
      )}

      {hasAccess && !configured && (
        <p className="text-sm text-muted-foreground">
          Бот ещё не настроен на сервере (нет TELEGRAM_BOT_TOKEN). Обратитесь к администратору.
        </p>
      )}

      {hasAccess && configured && (
        <section className="space-y-4 rounded-md border border-border p-4">
          <div className="space-y-1">
            <p className="text-sm font-medium">
              Статус:{" "}
              {connected ? (
                <span className="text-foreground">подключён</span>
              ) : (
                <span className="text-muted-foreground">не подключён</span>
              )}
            </p>
            {bot?.bot_username && (
              <p className="text-sm text-muted-foreground">@{bot.bot_username}</p>
            )}
          </div>

          {!connected && (
            <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
              <li>
                Откройте бота в Telegram
                {deepLink ? (
                  <>
                    {" "}
                    (
                    <a
                      href={deepLink}
                      target="_blank"
                      rel="noreferrer"
                      className="underline underline-offset-2"
                    >
                      {deepLink}
                    </a>
                    )
                  </>
                ) : null}
                .
              </li>
              <li>
                Нажмите <strong>Start</strong> или отправьте команду{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">/start</code>.
              </li>
              <li>
                Без этого шага Telegram не разрешает боту писать вам первым — простого входа в
                приложение недостаточно.
              </li>
              <li>Вернитесь сюда и обновите статус (или перезагрузите страницу).</li>
            </ol>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            {!connected && deepLink && (
              <Button asChild className="min-h-10">
                <a href={deepLink} target="_blank" rel="noreferrer">
                  Открыть бота в Telegram
                </a>
              </Button>
            )}
            <Button
              variant="outline"
              className="min-h-10"
              onClick={() => void queryClient.invalidateQueries({ queryKey: ["auth-me"] })}
            >
              Обновить статус
            </Button>
            {connected && (
              <Button
                variant="outline"
                className="min-h-10"
                disabled={disconnectMutation.isPending}
                onClick={() => disconnectMutation.mutate()}
              >
                Отключить в приложении
              </Button>
            )}
          </div>

          {disconnectMutation.isError && (
            <p className="text-sm text-destructive">
              {disconnectMutation.error instanceof ApiError
                ? disconnectMutation.error.message
                : "Не удалось отключить"}
            </p>
          )}

          {connected && (
            <p className="text-xs text-muted-foreground">
              В чате с ботом также можно отправить{" "}
              <code className="rounded bg-muted px-1 py-0.5">/stop</code>.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
