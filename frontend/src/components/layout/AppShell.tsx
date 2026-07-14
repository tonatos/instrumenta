import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Calculator,
  Heart,
  LogOut,
  Moon,
  Settings,
  Sun,
  TrendingUp,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/theme-provider";
import { SettingsSheet } from "@/features/settings/SettingsSheet";
import { useAuth } from "@/features/auth/AuthContext";
import { api } from "@/api/client";
import { cn } from "@/lib/utils";
import { useState } from "react";

const navItems = [
  { to: "/", label: "Скринер", icon: TrendingUp },
  { to: "/favorites", label: "Избранное", icon: Heart },
  { to: "/portfolio", label: "Портфель", icon: BarChart3 },
  { to: "/radar", label: "Radar", icon: Activity },
  { to: "/calculator", label: "Калькулятор", icon: Calculator },
];

export function AppShell() {
  const { theme, toggle } = useTheme();
  const { authEnabled, displayName, logout } = useAuth();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { data: favorites } = useQuery({
    queryKey: ["favorites"],
    queryFn: api.getFavorites,
  });

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-64 flex-col border-r border-border bg-card md:flex">
        <div className="flex h-16 items-center gap-3 border-b border-border px-6">
          <img src="/favicon.svg" alt="" width={32} height={32} className="shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold tracking-tight">Bond Monitor</p>
            <p className="truncate text-xs text-muted-foreground">Краткосрочные ОФЗ и корп.</p>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-4" aria-label="Основная навигация">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
              {to === "/favorites" && favorites && favorites.count > 0 && (
                <span className="ml-auto rounded-full bg-primary/20 px-2 py-0.5 text-xs">
                  {favorites.count}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="flex gap-2 border-t border-border p-4">
          {authEnabled && displayName && (
            <div className="flex min-w-0 flex-1 items-center text-xs text-muted-foreground">
              <span className="truncate">{displayName}</span>
            </div>
          )}
          {authEnabled && (
            <Button variant="outline" size="icon" onClick={logout} aria-label="Выйти">
              <LogOut className="h-4 w-4" />
            </Button>
          )}
          <Button variant="outline" size="icon" onClick={toggle} aria-label="Переключить тему">
            {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
          </Button>
          <Button variant="outline" size="icon" onClick={() => setSettingsOpen(true)} aria-label="Настройки">
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-border px-4 md:hidden">
          <div className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" width={28} height={28} className="shrink-0" />
            <p className="font-semibold tracking-tight">Bond Monitor</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="icon" onClick={toggle} aria-label="Тема">
              {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </Button>
            <Button variant="outline" size="icon" onClick={() => setSettingsOpen(true)} aria-label="Настройки">
              <Settings className="h-4 w-4" />
            </Button>
          </div>
        </header>

        <main className="flex-1 overflow-auto p-4 md:p-6">
          <Outlet />
        </main>

        <nav
          className="flex border-t border-border bg-card md:hidden"
          aria-label="Мобильная навигация"
        >
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex flex-1 flex-col items-center gap-1 py-2 text-xs",
                  isActive ? "text-primary" : "text-muted-foreground",
                )
              }
            >
              <Icon className="h-5 w-5" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>

      <SettingsSheet open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
