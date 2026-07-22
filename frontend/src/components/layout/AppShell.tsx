import { Link, NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Calculator,
  Heart,
  KeyRound,
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
  { to: "/", label: "Скринер", mobileLabel: "Скринер", icon: TrendingUp },
  { to: "/favorites", label: "Избранное", mobileLabel: "Избран.", icon: Heart },
  { to: "/portfolio", label: "Портфель", mobileLabel: "Портф.", icon: BarChart3 },
  { to: "/radar", label: "Radar", mobileLabel: "Radar", icon: Activity },
  { to: "/calculator", label: "Калькулятор", mobileLabel: "Кальк.", icon: Calculator },
  { to: "/account", label: "Кабинет", mobileLabel: "Кабинет", icon: KeyRound },
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
    <div className="flex min-h-screen overflow-x-hidden bg-transparent">
      <aside className="hidden w-64 flex-col border-r border-border bg-card/90 backdrop-blur-md md:flex">
        <div className="flex h-16 items-center justify-center border-b border-border px-5">
          <Link to="/" className="min-w-0" aria-label="Instrumenta">
            <img
              src="/brand/instrumenta-logo.png"
              alt="Instrumenta"
              width={140}
              className=""
            />
          </Link>
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

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur-md md:hidden">
          <Link to="/" className="min-w-0" aria-label="Instrumenta">
            <img
              src="/brand/instrumenta-logo.png"
              alt="Instrumenta"
              width={141}
              height={24}
              className="h-6 w-auto max-w-[11rem]"
            />
          </Link>
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" size="icon" onClick={toggle} aria-label="Тема">
              {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </Button>
            <Button variant="outline" size="icon" onClick={() => setSettingsOpen(true)} aria-label="Настройки">
              <Settings className="h-4 w-4" />
            </Button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-4 pb-[calc(3.5rem+env(safe-area-inset-bottom,0px))] md:p-6 md:pb-6">
          <Outlet />
        </main>

        <nav
          className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-card/90 pb-safe backdrop-blur-md md:hidden"
          aria-label="Мобильная навигация"
        >
          {navItems.map(({ to, label, mobileLabel, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              aria-label={label}
              className={({ isActive }) =>
                cn(
                  "flex min-w-0 flex-1 flex-col items-center gap-1 py-2 text-xs",
                  isActive ? "text-primary" : "text-muted-foreground",
                )
              }
            >
              <span className="relative">
                <Icon className="h-5 w-5" aria-hidden />
                {to === "/favorites" && favorites && favorites.count > 0 && (
                  <span className="absolute -right-2 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
                    {favorites.count > 99 ? "99+" : favorites.count}
                  </span>
                )}
              </span>
              <span className="max-w-[4.5rem] truncate text-center">{mobileLabel}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      <SettingsSheet open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
