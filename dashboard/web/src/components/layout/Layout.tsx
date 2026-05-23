import { Outlet, NavLink } from "react-router-dom";
import { BarChart2, TrendingUp, FlaskConical, Moon, Sun } from "lucide-react";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Strategies", icon: BarChart2, end: true },
  { to: "/factors", label: "Factors", icon: TrendingUp, end: false },
  { to: "/testnet", label: "Testnet", icon: FlaskConical, end: false },
];

export function Layout() {
  const { dark, toggle } = useDarkMode();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-card px-4 py-2 flex items-center gap-4">
        <span className="font-semibold text-sm tracking-tight">Quant Strategy Dashboard</span>
        <nav className="flex gap-1 ml-4">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to} to={to} end={end}
              className={({ isActive }) =>
                cn("flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted")
              }
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </NavLink>
          ))}
        </nav>
        <button onClick={toggle} className="ml-auto p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
