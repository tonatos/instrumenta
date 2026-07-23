const AUTH_TOKEN_KEY = "instrumenta_auth_token";

let authToken: string | null =
  typeof localStorage !== "undefined" ? localStorage.getItem(AUTH_TOKEN_KEY) : null;

let onUnauthorized: (() => void) | null = null;

export function getAuthToken(): string | null {
  return authToken;
}

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (typeof localStorage === "undefined") return;
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export function notifyUnauthorized(): void {
  onUnauthorized?.();
}
