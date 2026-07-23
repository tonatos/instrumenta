import { Navigate, useLocation } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "./AuthContext";
import { TelegramLoginButton } from "./TelegramLoginButton";

export function LoginPage() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (isAuthenticated) {
    const redirectTo =
      (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-transparent p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center py-12 text-center">
          <img
            src="/brand/instrumenta-logo.png"
            alt="Instrumenta"
            width={220}
            height={37}
            className="my-2 h-9 w-auto"
          />
          <CardTitle className="sr-only">Instrumenta</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4  text-center">
          <CardDescription className="text-base">Войдите через Telegram, чтобы открыть приложение.</CardDescription>
          <TelegramLoginButton />
        </CardContent>
      </Card>
    </div>
  );
}
