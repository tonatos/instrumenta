import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "@/components/theme-provider";
import { AppShell } from "@/components/layout/AppShell";
import { ScreenerPage } from "@/features/screener/ScreenerPage";
import { FavoritesPage } from "@/features/favorites/FavoritesPage";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";
import { RadarPage } from "@/features/radar/RadarPage";
import { CalculatorPage } from "@/features/calculator/CalculatorPage";
import { AuthProvider } from "@/features/auth/AuthContext";
import { LoginPage } from "@/features/auth/LoginPage";
import { LoginCallbackPage } from "@/features/auth/LoginCallbackPage";
import { ProtectedRoute } from "@/features/auth/ProtectedRoute";
import { RateScenarioProvider } from "@/features/settings/RateScenarioProvider";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, retry: 1 },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RateScenarioProvider>
          <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/login/callback" element={<LoginCallbackPage />} />
              <Route element={<ProtectedRoute />}>
                <Route element={<AppShell />}>
                  <Route index element={<ScreenerPage />} />
                  <Route path="favorites" element={<FavoritesPage />} />
                  <Route path="portfolio/:portfolioId?" element={<PortfolioPage />} />
                  <Route path="radar" element={<RadarPage />} />
                  <Route path="calculator" element={<CalculatorPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
        </RateScenarioProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
