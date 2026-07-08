import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { getAuthToken, setAuthToken, setUnauthorizedHandler } from "./authStorage";

interface AuthContextValue {
  authEnabled: boolean;
  isAuthenticated: boolean;
  loading: boolean;
  displayName: string | null;
  loginWithTelegram: (payload: TelegramAuthPayload) => Promise<void>;
  logout: () => void;
}

export interface TelegramAuthPayload {
  id: number;
  first_name: string;
  auth_date: number;
  hash: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(() => getAuthToken());

  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: ["config"],
    queryFn: api.getConfig,
    retry: 1,
  });

  const authEnabled = config?.auth_enabled ?? false;

  const refreshMe = useCallback(async (accessToken: string) => {
    const me = await api.getMe(accessToken);
    setDisplayName(me.display_name);
  }, []);

  useEffect(() => {
    if (!authEnabled || !token) {
      setDisplayName(null);
      return;
    }
    void refreshMe(token).catch(() => {
      setAuthToken(null);
      setToken(null);
      setDisplayName(null);
    });
  }, [authEnabled, refreshMe, token]);

  const logout = useCallback(() => {
    setAuthToken(null);
    setToken(null);
    setDisplayName(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const loginWithTelegram = useCallback(async (payload: TelegramAuthPayload) => {
    const response = await api.loginWithTelegram(payload);
    setAuthToken(response.access_token);
    setToken(response.access_token);
    setDisplayName(payload.first_name);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      authEnabled,
      isAuthenticated: !authEnabled || Boolean(token),
      loading: configLoading,
      displayName,
      loginWithTelegram,
      logout,
    }),
    [authEnabled, configLoading, displayName, loginWithTelegram, logout, token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
