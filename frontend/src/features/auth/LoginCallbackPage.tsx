import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "./AuthContext";

function readAccessToken(): string | null {
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const hashToken = new URLSearchParams(hash).get("access_token");
  if (hashToken) return hashToken;
  return new URLSearchParams(window.location.search).get("access_token");
}

function readOAuthError(): { error: string; description: string } | null {
  const params = new URLSearchParams(window.location.search);
  const error = params.get("error");
  if (!error) return null;
  return {
    error,
    description: params.get("error_description") ?? error,
  };
}

export function LoginCallbackPage() {
  const navigate = useNavigate();
  const { loginWithAccessToken } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const handledRef = useRef(false);

  useEffect(() => {
    if (handledRef.current) return;
    handledRef.current = true;

    const accessToken = readAccessToken();
    if (accessToken) {
      window.history.replaceState({}, document.title, window.location.pathname);
      void loginWithAccessToken(accessToken)
        .then(() => navigate("/", { replace: true }))
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Не удалось завершить вход через Telegram.");
        });
      return;
    }

    const oauthError = readOAuthError();
    if (oauthError) {
      setError(oauthError.description);
      window.history.replaceState({}, document.title, window.location.pathname);
    } else {
      setError("Telegram не вернул результат авторизации.");
    }
  }, [loginWithAccessToken, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-transparent p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Telegram</CardTitle>
          <CardDescription>
            {error ? "Вход не выполнен." : "Завершаем вход через Telegram..."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error ? (
            <>
              <p className="text-sm text-destructive">{error}</p>
              {error.includes("invalid_client") && (
                <p className="text-sm text-muted-foreground">
                  Проверьте в BotFather → Bot Settings → Web Login: Client ID и Client Secret
                  должны совпадать с TELEGRAM_OIDC_CLIENT_ID и TELEGRAM_OIDC_CLIENT_SECRET в .env.
                  Это не bot token.
                </p>
              )}
              <Button asChild>
                <Link to="/login">Попробовать снова</Link>
              </Button>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Пожалуйста, подождите.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
