import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "@/components/theme-provider";
import { AppShell } from "@/components/layout/AppShell";
import { ScreenerPage } from "@/features/screener/ScreenerPage";
import { FavoritesPage } from "@/features/favorites/FavoritesPage";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";
import { RadarPage } from "@/features/radar/RadarPage";
import { CalculatorPage } from "@/features/calculator/CalculatorPage";
import { AccountLayout } from "@/features/account/AccountLayout";
import { AccountKeysPage } from "@/features/account/AccountPage";
import { NotificationsPage } from "@/features/account/NotificationsPage";
import { PlanPage } from "@/features/account/PlanPage";
import { FinancePage } from "@/features/account/FinancePage";
import { AuthProvider } from "@/features/auth/AuthContext";
import { LoginPage } from "@/features/auth/LoginPage";
import { LoginCallbackPage } from "@/features/auth/LoginCallbackPage";
import { ProtectedRoute } from "@/features/auth/ProtectedRoute";
import { SubscriptionPaywallProvider } from "@/features/billing/SubscriptionPaywallProvider";
import { RateScenarioProvider } from "@/features/settings/RateScenarioProvider";
import { LandingPage } from "@/features/landing/LandingPage";
import { OfferPage } from "@/features/landing/OfferPage";
import { SecurityPage } from "@/features/landing/SecurityPage";

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
            <SubscriptionPaywallProvider>
              <BrowserRouter>
                <Routes>
                  <Route path="/landing" element={<LandingPage />} />
                  <Route path="/offer" element={<OfferPage />} />
                  <Route path="/security" element={<SecurityPage />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/login/callback" element={<LoginCallbackPage />} />
                  <Route element={<ProtectedRoute />}>
                    <Route element={<AppShell />}>
                      <Route index element={<ScreenerPage />} />
                      <Route path="favorites" element={<FavoritesPage />} />
                      <Route path="portfolio/:portfolioId?" element={<PortfolioPage />} />
                      <Route path="radar" element={<RadarPage />} />
                      <Route path="calculator" element={<CalculatorPage />} />
                      <Route path="account" element={<AccountLayout />}>
                        <Route index element={<AccountKeysPage />} />
                        <Route path="notifications" element={<NotificationsPage />} />
                        <Route path="plan" element={<PlanPage />} />
                        <Route path="finance" element={<FinancePage />} />
                      </Route>
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Route>
                  </Route>
                </Routes>
              </BrowserRouter>
            </SubscriptionPaywallProvider>
          </AuthProvider>
        </RateScenarioProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
