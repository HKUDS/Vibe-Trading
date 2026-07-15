import { useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { BarChart3, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";

const MARKETING_NAV = [
  "Platform",
  "Intelligence",
  "Risk Tools",
  "Performance",
  "Pricing",
  "Company",
];

export function MarketingLayout() {
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <Link to="/" className="flex min-w-0 items-center gap-3" onClick={() => setOpen(false)}>
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <BarChart3 className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="min-w-0">
              <span className="block text-base font-bold leading-tight tracking-tight">TradeCoreFX</span>
              <span className="block truncate text-xs font-medium text-muted-foreground">
                Filter Better. Trade Smarter. Risk Less.
              </span>
            </span>
          </Link>

          <nav className="hidden items-center gap-1 lg:flex" aria-label="Marketing navigation">
            {MARKETING_NAV.map((item) => (
              <Link
                key={item}
                to={`/#${item.toLowerCase().replace(/\s+/g, "-")}`}
                className="rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {item}
              </Link>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <Link
              to="/agent"
              className="hidden rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition hover:opacity-90 sm:inline-flex"
            >
              Begin Analysis
            </Link>
            <button
              type="button"
              className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:hidden"
              aria-label={open ? "Close navigation" : "Open navigation"}
              aria-expanded={open}
              onClick={() => setOpen((value) => !value)}
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        <div className={cn("border-t lg:hidden", open ? "block" : "hidden")}>
          <nav className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-3 sm:px-6" aria-label="Mobile marketing navigation">
            {MARKETING_NAV.map((item) => (
              <Link
                key={item}
                to={`/#${item.toLowerCase().replace(/\s+/g, "-")}`}
                onClick={() => setOpen(false)}
                className="rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {item}
              </Link>
            ))}
            <Link
              to="/agent"
              onClick={() => setOpen(false)}
              className="mt-2 rounded-lg bg-primary px-4 py-2 text-center text-sm font-semibold text-primary-foreground shadow-sm transition hover:opacity-90 sm:hidden"
            >
              Begin Analysis
            </Link>
          </nav>
        </div>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  );
}
