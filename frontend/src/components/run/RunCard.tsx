import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Shared Run-Card building blocks. Extracted from pages/RunDetail.tsx so that
 * FactorResearchPanel can reuse them without importing the page module (which
 * imports FactorResearchPanel back, creating a circular import).
 */
export function RunCardStat({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "warning" | "positive" | "negative" }) {
  return (
    <div className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn(
        "mt-1 truncate text-sm font-medium",
        tone === "warning" && "text-warning",
        tone === "positive" && "text-success",
        tone === "negative" && "text-danger",
      )}>{value}</div>
    </div>
  );
}

export function RunCardPanel({ title, icon: Icon, children }: { title: string; icon: LucideIcon; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Icon className="h-4 w-4 text-muted-foreground" />
        {title}
      </div>
      {children}
    </section>
  );
}

export function formatRunCardValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value ?? "");
}
