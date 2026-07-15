import { calculateDrawdown, classifyRiskHealth } from "@/lib/calculators";
import { Currency, type RiskInputs } from "./riskShared";

export function RiskOverview({ inputs }: { inputs: RiskInputs }) {
  let drawdown = 0;
  try {
    drawdown = calculateDrawdown(inputs.accountBalance || 1, Math.max(0, inputs.riskPercentage), Math.max(0, Math.trunc(inputs.consecutiveLosses))).drawdownPercentage;
  } catch {
    drawdown = 100;
  }
  const cards = [
    ["Account Balance", <Currency value={inputs.accountBalance} currency={inputs.currency} />],
    ["Risk Per Trade", `${inputs.riskPercentage}%`],
    ["Current Risk Classification", classifyRiskHealth(inputs.riskPercentage)],
    ["Maximum Planned Drawdown", `${drawdown.toFixed(2)}%`],
  ];
  return <section className="rounded-2xl border bg-card p-5"><p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">Editable assumptions</p><h1 id="risk-manager-title" className="mt-2 text-2xl font-bold tracking-tight">Know Your Exposure Before You Enter</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">TradeCoreFX helps traders calculate position size, model drawdown and explore possible outcomes before capital is placed at risk.</p><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label, value]) => <div key={String(label)} className="rounded-xl border bg-background/70 p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 font-mono text-lg font-semibold tabular-nums">{value}</p></div>)}</div></section>;
}
