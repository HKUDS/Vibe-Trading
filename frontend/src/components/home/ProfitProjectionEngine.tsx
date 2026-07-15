import { useMemo, useState } from "react";
import { calculateProfitProjection, classifyRiskHealth } from "@/lib/calculators";
import { DisclosureNote } from "./DisclosureNote";
import { SectionHeading } from "./SectionHeading";

const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function ProfitProjectionEngine() {
  const [input, setInput] = useState({ accountBalance: 10000, riskPercentage: 1, rewardRatio: 2, winRate: 50, numberOfTrades: 20 });
  const errors = validate(input);
  const result = useMemo(() => errors.length ? null : calculateProfitProjection(input), [input, errors.length]);
  const riskHealth = errors.length ? null : classifyRiskHealth(input.riskPercentage);
  const warning = input.riskPercentage > 10 ? "Critical exposure" : input.riskPercentage > 5 ? "High risk" : input.riskPercentage > 2 ? "Elevated caution" : null;
  const bar = result ? Math.max(4, Math.min(100, 50 + result.percentageChange)) : 50;

  return (
    <section id="profit-projection" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading title="Profit Projection Engine" intro="Model trade-series outcomes from your own assumptions before risking capital." />
        <div className="mt-10 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-2xl border bg-card p-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <NumberField label="Account balance" value={input.accountBalance} onChange={(v) => setInput({ ...input, accountBalance: v })} />
              <NumberField label="Risk percentage" value={input.riskPercentage} onChange={(v) => setInput({ ...input, riskPercentage: v })} />
              <NumberField label="Risk-to-reward ratio" value={input.rewardRatio} onChange={(v) => setInput({ ...input, rewardRatio: v })} />
              <NumberField label="Estimated win rate" value={input.winRate} onChange={(v) => setInput({ ...input, winRate: v })} />
              <NumberField label="Number of trades" value={input.numberOfTrades} onChange={(v) => setInput({ ...input, numberOfTrades: v })} />
            </div>
            <div aria-live="polite" className="mt-4 space-y-2">
              {errors.map((error) => <p key={error} className="text-sm text-danger">{error}</p>)}
              {warning && <p className="text-sm font-medium text-warning">{warning}: review whether this exposure is appropriate for your rules.</p>}
              {riskHealth && <p className="text-sm text-muted-foreground">Risk health classification: <strong className="text-foreground">{riskHealth}</strong></p>}
            </div>
          </div>
          <div className="rounded-2xl border bg-card p-5">
            {result && <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Metric label="Risk amount per trade" value={currency.format(result.riskAmount)} />
                <Metric label="Estimated profit on a winning trade" value={currency.format(result.profitPerWin)} />
                <Metric label="Estimated loss on a losing trade" value={currency.format(result.lossPerLoss)} />
                <Metric label="Estimated wins" value={percent.format(result.estimatedWins)} />
                <Metric label="Estimated losses" value={percent.format(result.estimatedLosses)} />
                <Metric label="Estimated gross profit" value={currency.format(result.grossProfit)} />
                <Metric label="Estimated gross loss" value={currency.format(result.grossLoss)} />
                <Metric label="Estimated net outcome" value={currency.format(result.netOutcome)} />
                <Metric label="Estimated ending balance" value={currency.format(result.endingBalance)} />
                <Metric label="Estimated percentage change" value={`${percent.format(result.percentageChange)}%`} />
              </div>
              <div className="mt-6" role="img" aria-label={`Lightweight balance projection bar showing ${percent.format(result.percentageChange)} percent estimated change`}>
                <div className="h-3 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${bar}%` }} /></div>
              </div>
            </>}
          </div>
        </div>
        <div className="mt-6"><DisclosureNote>These projections are mathematical illustrations based on the assumptions entered. They do not predict actual trading performance and do not include spreads, slippage, commissions or changing market conditions.</DisclosureNote></div>
      </div>
    </section>
  );
}

function validate(input: { accountBalance: number; riskPercentage: number; rewardRatio: number; winRate: number; numberOfTrades: number }) {
  const errors: string[] = [];
  if (!Number.isFinite(input.accountBalance) || input.accountBalance < 0) errors.push("Account balance cannot be negative.");
  if (input.accountBalance === 0) errors.push("Account balance must be greater than 0 for projections.");
  if (!Number.isFinite(input.riskPercentage) || input.riskPercentage < 0) errors.push("Risk cannot be below 0.");
  if (!Number.isFinite(input.rewardRatio) || input.rewardRatio <= 0) errors.push("Reward ratio must be greater than 0.");
  if (!Number.isFinite(input.winRate) || input.winRate < 0 || input.winRate > 100) errors.push("Win rate must remain between 0 and 100.");
  if (!Number.isInteger(input.numberOfTrades) || input.numberOfTrades <= 0) errors.push("Number of trades must be a positive whole number.");
  return errors;
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  const id = label.toLowerCase().replace(/\W+/g, "-");
  return <label htmlFor={id} className="text-sm font-medium">{label}<input id={id} type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 w-full rounded-lg border bg-background px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" /></label>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border bg-background/60 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-semibold">{value}</p></div>; }
