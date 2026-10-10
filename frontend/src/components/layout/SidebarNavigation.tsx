import { useEffect, useRef, useState } from "react";
import { Menu, X } from "lucide-react";
import { Link, useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { isNavigationActive, NAVIGATION_GROUPS } from "./navigation";

export function SidebarNavigation({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => { setMenuOpen(false); }, [pathname, collapsed]);
  useEffect(() => {
    if (!menuOpen) return;
    panelRef.current?.querySelector<HTMLElement>("a")?.focus();
    const close = () => setMenuOpen(false);
    const dismiss = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)
        && !triggerRef.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close();
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
    };
  }, [menuOpen]);

  const groups = (compact: boolean, drawer = false) => NAVIGATION_GROUPS.map(({ id, items }) => (
    <section key={id} aria-label={t(`navigation.groups.${id}`)} className={cn(id !== "research" && "border-t border-border/60 pt-2")}>
      {!compact && <p className={cn("mb-1 px-3 text-[10px] font-medium text-muted-foreground/70", !drawer && "max-md:hidden")}>{t(`navigation.groups.${id}`)}</p>}
      <div className="space-y-0.5">
        {items.map(({ id: itemId, to, icon: Icon }) => {
          const label = t(`layout.${itemId}`);
          const active = isNavigationActive(to, pathname);
          return (
            <Link key={to} to={to} aria-label={label} aria-current={active ? "page" : undefined}
              title={`${label} — ${t(`navigation.descriptions.${itemId}`)}`}
              onClick={() => setMenuOpen(false)}
              className={cn("flex items-center rounded-md text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
                compact ? "justify-center px-2 py-1.5" : "gap-3 px-3 py-1.5",
                !compact && !drawer && "max-md:justify-center max-md:px-2",
                active ? "bg-primary/10 text-primary font-medium" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground")}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {!compact && <span className={cn(!drawer && "max-md:hidden")}>{label}</span>}
            </Link>
          );
        })}
      </div>
    </section>
  ));

  return (
    <>
      <nav aria-label={t("layout.mainNavigation")}
        className={cn("max-h-[60vh] shrink-0 overflow-y-auto space-y-3", collapsed ? "p-1" : "p-2 max-md:p-1")}
      >
        <button ref={triggerRef} type="button" aria-label={t("navigation.menu")} title={t("navigation.menu")}
          aria-expanded={menuOpen} aria-controls="sidebar-feature-menu" onClick={() => setMenuOpen((open) => !open)}
          className={cn("flex w-full justify-center rounded-md border border-border/60 p-2 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40", !collapsed && "md:hidden")}
        ><Menu className="h-4 w-4" aria-hidden="true" /></button>
        {groups(collapsed)}
      </nav>
      {menuOpen && (
        <nav ref={panelRef} id="sidebar-feature-menu" aria-label={t("navigation.menu")}
          className="fixed inset-y-0 start-12 z-40 w-[min(18rem,calc(100vw-3rem))] space-y-3 overflow-y-auto border-e bg-card p-3 shadow-xl"
        >
          <div className="flex items-center justify-between px-3 py-1 text-sm font-medium">
            {t("navigation.menu")}
            <button type="button" aria-label={t("navigation.close")} onClick={() => { setMenuOpen(false); triggerRef.current?.focus(); }} className="rounded p-1.5 hover:bg-muted"><X className="h-4 w-4" aria-hidden="true" /></button>
          </div>
          {groups(false, true)}
        </nav>
      )}
    </>
  );
}
