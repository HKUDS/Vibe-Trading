import { calculateDrawdown, calculatePositionSize, calculateRecoveryTarget, classifyRiskHealth } from "@/lib/calculators";
import { RiskBadge, type RiskInputs, riskExplanation } from "./riskShared";

function safeDrawdown(inputs: RiskInputs) {
  try {
    return calculateDrawdown(inputs.accountBalance, Math.max(0, inputs.riskPercentage), Math.max(0, Math.trunc(inputs.consecutiveLosses)));
  } catch {
    return null;
  }
}

function safePositionExposure(inputs: RiskInputs) {
  try {
    return calculatePositionSize(inputs).standardLots;
  } catch {
    return null;
  }
}

export function RiskHealthPanel({ inputs }: { inputs: RiskInputs }) {
  const classification = classifyRiskHealth(Math.max(0, inputs.riskPercentage));
  const drawdown = safeDrawdown(inputs);
  const recovery = drawdown ? calculateRecoveryTarget(inputs.accountBalance, drawdown.endingBalance) : Infinity;
  const standardLots = safePositionExposure(inputs);
  const scenarioNote = inputs.rewardRatio >= 1 && inputs.winRate >= 40 ? "Scenario assumptions remain within a testable educational range." : "Scenario assumptions require careful review before relying on projected outcomes.";

  return (
    <section className="rounded-2xl border bg-card p-5" aria-labelledby="risk-health-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="risk-health-title" className="text-xl font-semibold">Risk Health Summary</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">This educational summary reviews the entered assumptions without recommending whether to trade.</p>
        </div>
        <RiskBadge value={classification} />
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Summary label="Risk percentage" value={`${inputs.riskPercentage}%`} detail={riskExplanation(classification)} />
        <Summary label="Consecutive-loss drawdown" value={drawdown ? `${drawdown.drawdownPercentage.toFixed(2)}%` : "Unavailable"} detail="Models how a losing sequence may reduce capital under the entered risk percentage." />
        <Summary label="Recovery burden" value={Number.isFinite(recovery) ? `${recovery.toFixed(2)}%` : "Severe"} detail="Recovery becomes harder as balance declines because gains are calculated from a smaller base." />
        <Summary label="Position-size exposure" value={standardLots == null ? "Unavailable" : `${standardLots.toFixed(3)} standard lots`} detail="Estimated exposure depends on the stop-loss distance and pip-value assumption." />
        <Summary label="Scenario assumptions" value={scenarioNote} detail={`Current balance assumption: ${new Intl.NumberFormat("en-US", { style: "currency", currency: inputs.currency }).format(inputs.accountBalance)}.`} />
      </div>
      <p className="mt-4 rounded-xl border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">{classification === "Critical Exposure" ? "Critical Exposure: The entered risk level could cause severe capital loss during a losing sequence. This classification is educational and not financial advice." : "The entered assumptions should be verified against market conditions, execution quality and written risk rules before capital is placed at risk."}</p>
    </section>
  );
}

function Summary({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="rounded-xl border bg-background/70 p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p><p className="mt-2 font-mono text-sm font-semibold tabular-nums">{value}</p><p className="mt-2 text-xs text-muted-foreground">{detail}</p></article>;
}
