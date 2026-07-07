import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "@/components/theme-provider";
import { AppShell } from "@/components/layout/AppShell";
import { ScreenerPage } from "@/features/screener/ScreenerPage";
import { FavoritesPage } from "@/features/favorites/FavoritesPage";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";
import { CalculatorPage } from "@/features/calculator/CalculatorPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, retry: 1 },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<ScreenerPage />} />
              <Route path="favorites" element={<FavoritesPage />} />
              <Route path="portfolio/:portfolioId?" element={<PortfolioPage />} />
              <Route path="calculator" element={<CalculatorPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
