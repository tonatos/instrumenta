import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useState } from "react";
import { api, ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useSubscriptionPaywall } from "@/features/billing/SubscriptionPaywallProvider";

const TOKEN_DOCS = "https://developer.tbank.ru/invest/intro/intro/token";

export function AccountKeysPage() {
  const [params] = useSearchParams();
  const highlightKind = params.get("kind");
  const queryClient = useQueryClient();
  const { openPaywall } = useSubscriptionPaywall();
  const { data: me, isLoading } = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api.getMe(),
  });
  const { data: billing } = useQuery({
    queryKey: ["billing-status"],
    queryFn: () => api.getBillingStatus(),
  });

  const [productionToken, setProductionToken] = useState("");
  const [sandboxToken, setSandboxToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  const canWriteKeys = Boolean(
    billing?.complimentary ||
      billing?.entitlements?.includes("broker_credentials.write") ||
      billing?.has_active_access,
  );

  const saveMutation = useMutation({
    mutationFn: ({ kind, token }: { kind: "sandbox" | "production"; token: string }) =>
      api.putBrokerCredential(kind, token),
    onSuccess: async (_data, vars) => {
      setError(null);
      if (vars.kind === "production") setProductionToken("");
      else setSandboxToken("");
      await queryClient.invalidateQueries({ queryKey: ["auth-me"] });
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.extra?.code === "subscription_required") {
        openPaywall({ reason: "broker_credentials.write" });
        setError(null);
        return;
      }
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить ключ");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (kind: "sandbox" | "production") => api.deleteBrokerCredential(kind),
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["auth-me"] });
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Не удалось удалить ключ");
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const production = me?.credentials?.production;
  const sandbox = me?.credentials?.sandbox;

  return (
    <div className="space-y-8">
      <div>
        <p className="text-sm text-muted-foreground">
          {me?.display_name ? `${me.display_name} · ` : ""}
          Telegram ID {me?.telegram_id ?? "—"}
        </p>
      </div>

      {!canWriteKeys && billing && (
        <div className="space-y-3 rounded-md border border-border bg-muted/30 p-4">
          <p className="text-sm font-medium">Сохранение ключей доступно по подписке</p>
          <p className="text-sm text-muted-foreground">
            Удалить уже сохранённые ключи можно без оплаты. Чтобы добавить или обновить токен —
            подключите тариф Pro.
          </p>
          <Button
            className="min-h-10"
            onClick={() => openPaywall({ reason: "broker_credentials.write" })}
          >
            Подключить тариф
          </Button>
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Брокерские ключи T‑Invest</h2>
        <p className="text-sm text-muted-foreground">
          Ключи нужны, чтобы читать портфель и выставлять заявки от вашего имени. Выпустите токен в{" "}
          <a
            href={TOKEN_DOCS}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2"
          >
            кабинете T‑Invest API
          </a>
          . Рекомендуем минимальные права и привязку к одному счёту.
        </p>

        <div
          className={`space-y-3 rounded-md border border-border p-4 ${
            highlightKind === "production" ? "ring-1 ring-ring" : ""
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium">Production</p>
            {production ? (
              <span className="text-xs text-muted-foreground">
                сохранён · {production.fingerprint}
              </span>
            ) : (
              <span className="text-xs text-amber-700 dark:text-amber-400">не задан</span>
            )}
          </div>
          {canWriteKeys && (
            <>
              <Input
                type="password"
                autoComplete="off"
                placeholder="Вставьте production-токен"
                value={productionToken}
                onChange={(e) => setProductionToken(e.target.value)}
                className="min-h-10"
              />
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  className="min-h-10"
                  disabled={!productionToken.trim() || saveMutation.isPending}
                  onClick={() =>
                    saveMutation.mutate({ kind: "production", token: productionToken.trim() })
                  }
                >
                  Сохранить production
                </Button>
                {production && (
                  <Button
                    variant="outline"
                    className="min-h-10"
                    disabled={deleteMutation.isPending}
                    onClick={() => deleteMutation.mutate("production")}
                  >
                    Удалить
                  </Button>
                )}
              </div>
            </>
          )}
          {!canWriteKeys && production && (
            <Button
              variant="outline"
              className="min-h-10"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate("production")}
            >
              Удалить
            </Button>
          )}
        </div>

        <details
          className={`rounded-md border border-border p-4 ${
            highlightKind === "sandbox" ? "ring-1 ring-ring" : ""
          }`}
          open={highlightKind === "sandbox" || Boolean(sandbox)}
        >
          <summary className="cursor-pointer text-sm font-medium">
            Песочница (опционально)
          </summary>
          <p className="mt-2 text-sm text-muted-foreground">
            Если хотите попробовать алгоритм в режиме песочницы — добавьте sandbox-токен.
          </p>
          <div className="mt-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm">Sandbox</p>
              {sandbox ? (
                <span className="text-xs text-muted-foreground">
                  сохранён · {sandbox.fingerprint}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">не задан</span>
              )}
            </div>
            {canWriteKeys && (
              <>
                <Input
                  type="password"
                  autoComplete="off"
                  placeholder="Вставьте sandbox-токен"
                  value={sandboxToken}
                  onChange={(e) => setSandboxToken(e.target.value)}
                  className="min-h-10"
                />
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    className="min-h-10"
                    disabled={!sandboxToken.trim() || saveMutation.isPending}
                    onClick={() =>
                      saveMutation.mutate({ kind: "sandbox", token: sandboxToken.trim() })
                    }
                  >
                    Сохранить sandbox
                  </Button>
                  {sandbox && (
                    <Button
                      variant="outline"
                      className="min-h-10"
                      disabled={deleteMutation.isPending}
                      onClick={() => deleteMutation.mutate("sandbox")}
                    >
                      Удалить
                    </Button>
                  )}
                </div>
              </>
            )}
            {!canWriteKeys && sandbox && (
              <Button
                variant="outline"
                className="min-h-10"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate("sandbox")}
              >
                Удалить
              </Button>
            )}
          </div>
        </details>

        {error && <p className="text-sm text-destructive">{error}</p>}
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">Как мы защищаем ключи</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            Токены хранятся только в зашифрованном виде (envelope AES‑GCM), ключ шифрования находится
            отдельно от базы.
          </li>
          <li>Plaintext токена не возвращается API и не пишется в логи.</li>
          <li>Вы можете удалить ключ здесь в любой момент и отозвать его в T‑Банке.</li>
        </ul>
        <p className="text-sm text-muted-foreground">
          Подробнее простым языком — на странице{" "}
          <Link to="/security" className="underline underline-offset-2">
            Безопасность
          </Link>
          .
        </p>
      </section>
    </div>
  );
}

/** @deprecated use AccountKeysPage via AccountLayout */
export const AccountPage = AccountKeysPage;
