import { useState } from "react";
import { DrawdownSimulator } from "@/components/risk/DrawdownSimulator";
import { PositionSizeCalculator } from "@/components/risk/PositionSizeCalculator";
import { ProfitProjectionWorkspace } from "@/components/risk/ProfitProjectionWorkspace";
import { RiskDisclosure } from "@/components/risk/RiskDisclosure";
import { RiskHealthPanel } from "@/components/risk/RiskHealthPanel";
import { RiskOverview } from "@/components/risk/RiskOverview";
import { ScenarioComparison } from "@/components/risk/ScenarioComparison";
import type { RiskInputs } from "@/components/risk/riskShared";

const defaultInputs: RiskInputs = {
  accountBalance: 1000,
  riskPercentage: 1,
  stopLossPips: 30,
  pipValuePerStandardLot: 10,
  rewardRatio: 2,
  winRate: 50,
  numberOfTrades: 20,
  consecutiveLosses: 5,
  recoveryTarget: 1000,
  monthlyContribution: 0,
  currency: "USD",
  compounding: false,
};

export function RiskManager() {
  const [inputs, setInputs] = useState<RiskInputs>(defaultInputs);

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-5 overflow-x-hidden p-4 md:p-6" aria-labelledby="risk-manager-title">
      <RiskOverview inputs={inputs} />
      <PositionSizeCalculator inputs={inputs} setInputs={setInputs} />
      <DrawdownSimulator inputs={inputs} setInputs={setInputs} />
      <ProfitProjectionWorkspace inputs={inputs} setInputs={setInputs} />
      <ScenarioComparison inputs={inputs} />
      <RiskHealthPanel inputs={inputs} />
      <RiskDisclosure />
    </main>
  );
}
