import { useEffect, useRef } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth, type TelegramAuthPayload } from "./AuthContext";

declare global {
  interface Window {
    TelegramLoginCallback?: (user: TelegramAuthPayload) => void;
  }
}

export function LoginPage() {
  const { loginWithTelegram, isAuthenticated } = useAuth();
  const location = useLocation();
  const widgetRef = useRef<HTMLDivElement>(null);
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
  });

  useEffect(() => {
    const botUsername = config?.telegram_bot_username;
    const container = widgetRef.current;
    if (!botUsername || !container) return;

    container.replaceChildren();
    window.TelegramLoginCallback = (user) => {
      void loginWithTelegram(user).catch((error: unknown) => {
        console.error("Telegram login failed", error);
      });
    };

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-radius", "8");
    script.setAttribute("data-onauth", "TelegramLoginCallback(user)");
    container.appendChild(script);

    return () => {
      delete window.TelegramLoginCallback;
      container.replaceChildren();
    };
  }, [config?.telegram_bot_username, loginWithTelegram]);

  if (isAuthenticated) {
    const redirectTo =
      (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Bond Monitor</CardTitle>
          <CardDescription>Войдите через Telegram, чтобы открыть приложение.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          {config?.telegram_bot_username ? (
            <div ref={widgetRef} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Telegram-бот не настроен. Укажите TELEGRAM_BOT_USERNAME и TELEGRAM_BOT_TOKEN в .env.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
