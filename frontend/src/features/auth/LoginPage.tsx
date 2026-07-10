import { Navigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  const { data: config, isLoading, isError } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
  });

  if (isAuthenticated) {
    const redirectTo =
      (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <img src="/favicon.svg" alt="" width={56} height={56} className="mb-1" />
          <CardTitle>Bond Monitor</CardTitle>
          <CardDescription>Войдите через Telegram, чтобы открыть приложение.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : config?.telegram_oidc_configured ? (
            <Button onClick={() => window.location.assign("/api/v1/auth/telegram/login")}>
              Войти через Telegram
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              Telegram OIDC не настроен. Укажите TELEGRAM_OIDC_CLIENT_ID, TELEGRAM_OIDC_CLIENT_SECRET
              и TELEGRAM_OIDC_REDIRECT_URI в .env.
            </p>
          )}
          {isError && (
            <p className="text-sm text-destructive">Не удалось загрузить конфигурацию приложения.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
