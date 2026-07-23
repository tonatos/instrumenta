import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

const TABS = [
  { to: "/account", end: true, label: "Ключи" },
  { to: "/account/notifications", end: false, label: "Уведомления" },
  { to: "/account/plan", end: false, label: "Тариф" },
  { to: "/account/finance", end: false, label: "Финансы" },
] as const;

export function AccountLayout() {
  return (
    <div className="mx-auto max-w-xl space-y-6 p-4 pb-24 md:pb-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Личный кабинет</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ключи брокера, Telegram-уведомления, подписка и история списаний
        </p>
      </div>

      <nav
        className="flex gap-1 overflow-x-auto rounded-lg border border-border bg-muted/40 p-1"
        aria-label="Разделы кабинета"
      >
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                "min-h-10 flex-1 whitespace-nowrap rounded-md px-3 py-2 text-center text-sm font-medium transition-colors",
                isActive
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  );
}
