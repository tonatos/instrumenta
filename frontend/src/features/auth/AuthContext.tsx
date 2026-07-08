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
  loginWithAccessToken: (accessToken: string) => Promise<void>;
  logout: () => void;
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

  const loginWithAccessToken = useCallback(async (accessToken: string) => {
    setAuthToken(accessToken);
    setToken(accessToken);
    await refreshMe(accessToken);
  }, [refreshMe]);

  const value = useMemo<AuthContextValue>(
    () => ({
      authEnabled,
      isAuthenticated: !authEnabled || Boolean(token),
      loading: configLoading,
      displayName,
      loginWithAccessToken,
      logout,
    }),
    [authEnabled, configLoading, displayName, loginWithAccessToken, logout, token],
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
