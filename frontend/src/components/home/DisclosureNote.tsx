import type { ReactNode } from "react";
import { Info } from "lucide-react";

export function DisclosureNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-muted/35 p-4 text-sm leading-6 text-muted-foreground">
      <div className="flex gap-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <p>{children}</p>
      </div>
    </div>
  );
}
