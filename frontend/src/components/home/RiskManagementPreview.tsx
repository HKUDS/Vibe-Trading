import { useMemo, useState } from "react";
import { calculateDrawdown, calculatePositionSize, classifyRiskHealth } from "@/lib/calculators";
import { SectionHeading } from "./SectionHeading";

const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

export function RiskManagementPreview() {
  const [position, setPosition] = useState({ accountBalance: 10000, riskPercentage: 1, stopLossPips: 25, pipValuePerStandardLot: 10 });
  const [drawdown, setDrawdown] = useState({ startingBalance: 10000, riskPercentage: 2, consecutiveLosses: 5 });
  const positionResult = useMemo(() => safe(() => calculatePositionSize(position)), [position]);
  const drawdownResult = useMemo(() => safe(() => calculateDrawdown(drawdown.startingBalance, drawdown.riskPercentage, drawdown.consecutiveLosses)), [drawdown]);
  const health = safe(() => classifyRiskHealth(drawdown.riskPercentage));

  return (
    <section id="risk-tools" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading title="Risk Management" intro="Preview exposure before the trade, model losing sequences and evaluate risk posture with educational classifications." />
        <div className="mt-10 grid gap-6 lg:grid-cols-3">
          <article className="rounded-2xl border bg-card p-5">
            <h3 className="font-semibold">Position Size Calculator</h3>
            <div className="mt-4 grid gap-3">
              <Field label="Account balance" value={position.accountBalance} set={(v) => setPosition({ ...position, accountBalance: v })} />
              <Field label="Risk percentage" value={position.riskPercentage} set={(v) => setPosition({ ...position, riskPercentage: v })} />
              <Field label="Stop-loss distance in pips" value={position.stopLossPips} set={(v) => setPosition({ ...position, stopLossPips: v })} />
              <Field label="Pip value per standard lot" value={position.pipValuePerStandardLot} set={(v) => setPosition({ ...position, pipValuePerStandardLot: v })} />
            </div>
            {positionResult.ok ? <dl className="mt-4 grid gap-2 text-sm"><Row k="Risk amount" v={currency.format(positionResult.value.riskAmount)} /><Row k="Estimated standard lots" v={number.format(positionResult.value.standardLots)} /><Row k="Estimated mini lots" v={number.format(positionResult.value.miniLots)} /><Row k="Estimated micro lots" v={number.format(positionResult.value.microLots)} /></dl> : <p className="mt-4 text-sm text-danger">Enter positive stop-loss and pip values, and non-negative balance/risk values.</p>}
          </article>

          <article className="rounded-2xl border bg-card p-5">
            <h3 className="font-semibold">Drawdown Simulator</h3>
            <div className="mt-4 grid gap-3">
              <Field label="Starting balance" value={drawdown.startingBalance} set={(v) => setDrawdown({ ...drawdown, startingBalance: v })} />
              <Field label="Risk per trade" value={drawdown.riskPercentage} set={(v) => setDrawdown({ ...drawdown, riskPercentage: v })} />
              <Field label="Consecutive losses" value={drawdown.consecutiveLosses} set={(v) => setDrawdown({ ...drawdown, consecutiveLosses: Math.trunc(v) })} />
            </div>
            {drawdownResult.ok ? <dl className="mt-4 grid gap-2 text-sm"><Row k="Ending balance" v={currency.format(drawdownResult.value.endingBalance)} /><Row k="Drawdown percentage" v={`${number.format(drawdownResult.value.drawdownPercentage)}%`} /><Row k="Recovery required" v={`${number.format(drawdownResult.value.recoveryRequired)}%`} /></dl> : <p className="mt-4 text-sm text-danger">Enter a positive balance, non-negative risk and whole-number losses.</p>}
          </article>

          <article className="rounded-2xl border bg-card p-5">
            <h3 className="font-semibold">Risk Health Check</h3>
            <p className="mt-4 text-sm leading-6 text-muted-foreground">This educational classification describes the selected risk percentage. It is not financial advice and should be checked against your own written risk rules.</p>
            <div className="mt-6 rounded-2xl border bg-background/60 p-5 text-center">
              <p className="text-sm text-muted-foreground">Current classification</p>
              <p className="mt-2 text-2xl font-bold">{health.ok ? health.value : "Unavailable"}</p>
            </div>
            <ul className="mt-5 space-y-2 text-sm text-muted-foreground">
              {['Conservative', 'Controlled', 'Elevated', 'High Risk', 'Critical Exposure'].map((item) => <li key={item} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 rounded-full bg-primary" />{item}</li>)}
            </ul>
          </article>
        </div>
      </div>
    </section>
  );
}

function safe<T>(fn: () => T): { ok: true; value: T } | { ok: false } { try { return { ok: true, value: fn() }; } catch { return { ok: false }; } }
function Field({ label, value, set }: { label: string; value: number; set: (value: number) => void }) { const id = `risk-${label.toLowerCase().replace(/\W+/g, '-')}`; return <label htmlFor={id} className="text-sm font-medium">{label}<input id={id} type="number" value={value} onChange={(e) => set(Number(e.target.value))} className="mt-2 w-full rounded-lg border bg-background px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" /></label>; }
function Row({ k, v }: { k: string; v: string }) { return <div className="flex justify-between gap-4 rounded-lg border bg-background/60 p-2"><dt className="text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>; }
