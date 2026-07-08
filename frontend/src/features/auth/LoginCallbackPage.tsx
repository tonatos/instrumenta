import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "./AuthContext";

export function LoginCallbackPage() {
  const [searchParams] = useSearchParams();
  const { completeTelegramLogin, isAuthenticated } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const oauthError = searchParams.get("error");

    if (oauthError) {
      setError(searchParams.get("error_description") ?? oauthError);
      return;
    }
    if (!code || !state) {
      setError("Telegram не вернул код авторизации.");
      return;
    }

    void completeTelegramLogin({ code, state }).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Не удалось завершить вход через Telegram.");
    });
  }, [completeTelegramLogin, searchParams]);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Telegram</CardTitle>
          <CardDescription>
            {error ? "Вход не выполнен." : "Завершаем вход через Telegram..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : (
            <p className="text-sm text-muted-foreground">Пожалуйста, подождите.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
