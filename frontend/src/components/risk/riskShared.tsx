import type { RiskHealth } from "@/lib/calculators";

export interface RiskInputs {
  accountBalance: number;
  riskPercentage: number;
  stopLossPips: number;
  pipValuePerStandardLot: number;
  rewardRatio: number;
  winRate: number;
  numberOfTrades: number;
  consecutiveLosses: number;
  recoveryTarget: number;
  monthlyContribution: number;
  currency: string;
  compounding: boolean;
}

export function Currency({ value, currency }: { value: number; currency: string }) {
  return <>{new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value)}</>;
}

export function NumberField({ label, value, onChange, min = 0, step = "any", error }: { label: string; value: number; onChange: (value: number) => void; min?: number; step?: string; error?: string }) {
  const id = label.toLowerCase().replace(/\W+/g, "-");
  return (
    <label htmlFor={id} className="text-sm font-medium">
      {label}
      <input id={id} type="number" min={min} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined} className="mt-2 w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40" />
      {error && <span id={`${id}-error`} className="mt-1 block text-xs text-danger">{error}</span>}
    </label>
  );
}

export function RiskBadge({ value }: { value: RiskHealth }) {
  return <span className="rounded-full border px-2 py-1 text-xs font-medium text-muted-foreground">{value}</span>;
}

export function riskExplanation(value: RiskHealth): string {
  switch (value) {
    case "Conservative": return "The entered assumptions keep exposure low, though execution and market conditions can still differ.";
    case "Controlled": return "The entered assumptions keep risk exposure within a moderate range, but actual market conditions and execution may differ.";
    case "Elevated": return "The entered assumptions increase sensitivity to losing sequences and should be reviewed against written risk rules.";
    case "High Risk": return "The entered assumptions could create large drawdowns during normal losing sequences.";
    case "Critical Exposure": return "The entered risk level could cause severe capital loss during a losing sequence. This classification is educational and not financial advice.";
  }
}
