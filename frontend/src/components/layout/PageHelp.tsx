import { ChevronDown, CircleHelp } from "lucide-react";
import { Link, useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import { isNavigationActive, NAVIGATION_GROUPS, type NavigationItem } from "./navigation";

export function PageHelp() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const item = NAVIGATION_GROUPS.flatMap<NavigationItem>((group) => [...group.items]).find((entry) => isNavigationActive(entry.to, pathname));
  if (!item || item.id === "agent") return null;
  return (
    <details key={item.id} className="group border-b border-border/60 bg-card/50 px-4 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 [&::-webkit-details-marker]:hidden">
        <CircleHelp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        {t("navigation.howTo", { feature: t(`layout.${item.id}`) })}
        <ChevronDown className="ms-auto h-3 w-3 transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="max-w-3xl space-y-2 py-3 text-sm leading-relaxed">
        <p>{t(`navigation.descriptions.${item.id}`)}</p>
        <p className="text-muted-foreground">{t(`navigation.instructions.${item.id}`)}</p>
        {item.id === "reports" && <Link to="/" className="inline-flex text-primary underline underline-offset-2">{t("navigation.startResearch")}</Link>}
      </div>
    </details>
  );
}
