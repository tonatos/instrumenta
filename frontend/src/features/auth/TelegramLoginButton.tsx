import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";

type Props = {
  /** Visual variant: landing CSS button or app Button styles via className. */
  className?: string;
  children?: ReactNode;
  /** When true, renders landing-styled consent + gradient button. */
  landingStyle?: boolean;
};

export function TelegramLoginButton({
  className,
  children = "Войти через Telegram",
  landingStyle = false,
}: Props) {
  const [accepted, setAccepted] = useState(false);
  const { data: config, isLoading, isError } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
  });

  const oidcReady = Boolean(config?.telegram_oidc_configured);
  const disabled = !accepted || !oidcReady || isLoading;

  const onLogin = () => {
    if (disabled) return;
    window.location.assign("/api/v1/auth/telegram/login");
  };

  if (landingStyle) {
    return (
      <div className="cta-login" data-testid="telegram-login">
        <Link
          to="/login"
          className={className ?? "btn btn--primary btn--block"}
          data-testid="telegram-login-button"
        >
          {children}
        </Link>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col items-stretch gap-3" data-testid="telegram-login">
      <button
        type="button"
        className={
          className ??
          "inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:pointer-events-none disabled:opacity-50"
        }
        disabled={disabled}
        onClick={onLogin}
        data-testid="telegram-login-button"
      >
        {children}
      </button>
      <label className="flex items-center justify-center gap-2 text-center text-sm text-muted-foreground">
        <input
          type="checkbox"
          className="h-4 w-4 accent-foreground"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
          data-testid="offer-consent"
        />
        <span>
          Согласен с{" "}
          <Link to="/offer" className="underline underline-offset-2" data-testid="offer-link">
            публичной офертой
          </Link>
        </span>
      </label>
      {!isLoading && !oidcReady && (
        <p className="text-sm text-muted-foreground">
          Telegram OIDC не настроен. Укажите TELEGRAM_OIDC_CLIENT_ID,
          TELEGRAM_OIDC_CLIENT_SECRET и TELEGRAM_OIDC_REDIRECT_URI в .env.
        </p>
      )}
      {isError && (
        <p className="text-sm text-destructive">Не удалось загрузить конфигурацию приложения.</p>
      )}
    </div>
  );
}
