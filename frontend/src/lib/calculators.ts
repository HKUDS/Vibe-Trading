export type RiskHealth = "Conservative" | "Controlled" | "Elevated" | "High Risk" | "Critical Exposure";

function finite(value: number): boolean {
  return Number.isFinite(value) && !Number.isNaN(value);
}

function assertFiniteNonNegative(value: number, label: string) {
  if (!finite(value) || value < 0) throw new Error(`${label} must be a finite non-negative number`);
}

function assertFinitePositive(value: number, label: string) {
  if (!finite(value) || value <= 0) throw new Error(`${label} must be a finite positive number`);
}

export function calculateRiskAmount(accountBalance: number, riskPercentage: number): number {
  assertFiniteNonNegative(accountBalance, "Account balance");
  assertFiniteNonNegative(riskPercentage, "Risk percentage");
  return accountBalance * (riskPercentage / 100);
}

export interface ProfitProjectionInput {
  accountBalance: number;
  riskPercentage: number;
  rewardRatio: number;
  winRate: number;
  numberOfTrades: number;
}

export interface ProfitProjectionResult {
  riskAmount: number;
  profitPerWin: number;
  lossPerLoss: number;
  estimatedWins: number;
  estimatedLosses: number;
  grossProfit: number;
  grossLoss: number;
  netOutcome: number;
  endingBalance: number;
  percentageChange: number;
}

export function calculateProfitProjection(input: ProfitProjectionInput): ProfitProjectionResult {
  const { accountBalance, riskPercentage, rewardRatio, winRate, numberOfTrades } = input;
  assertFiniteNonNegative(accountBalance, "Account balance");
  assertFiniteNonNegative(riskPercentage, "Risk percentage");
  assertFinitePositive(rewardRatio, "Risk-to-reward ratio");
  if (!finite(winRate) || winRate < 0 || winRate > 100) throw new Error("Win rate must be between 0 and 100");
  if (!Number.isInteger(numberOfTrades) || numberOfTrades <= 0) throw new Error("Number of trades must be a positive whole number");
  if (accountBalance === 0) throw new Error("Account balance must be greater than 0 for projections");

  const riskAmount = calculateRiskAmount(accountBalance, riskPercentage);
  const profitPerWin = riskAmount * rewardRatio;
  const estimatedWins = numberOfTrades * (winRate / 100);
  const estimatedLosses = numberOfTrades - estimatedWins;
  const grossProfit = estimatedWins * profitPerWin;
  const grossLoss = estimatedLosses * riskAmount;
  const netOutcome = grossProfit - grossLoss;
  const endingBalance = accountBalance + netOutcome;
  const percentageChange = (netOutcome / accountBalance) * 100;

  return { riskAmount, profitPerWin, lossPerLoss: riskAmount, estimatedWins, estimatedLosses, grossProfit, grossLoss, netOutcome, endingBalance, percentageChange };
}

export interface PositionSizeInput {
  accountBalance: number;
  riskPercentage: number;
  stopLossPips: number;
  pipValuePerStandardLot: number;
}

export function calculatePositionSize(input: PositionSizeInput) {
  const { accountBalance, riskPercentage, stopLossPips, pipValuePerStandardLot } = input;
  const riskAmount = calculateRiskAmount(accountBalance, riskPercentage);
  assertFinitePositive(stopLossPips, "Stop-loss distance");
  assertFinitePositive(pipValuePerStandardLot, "Pip value per standard lot");
  const standardLots = riskAmount / (stopLossPips * pipValuePerStandardLot);
  return { riskAmount, standardLots, miniLots: standardLots * 10, microLots: standardLots * 100 };
}

export function calculateDrawdown(startingBalance: number, riskPercentage: number, consecutiveLosses: number) {
  assertFinitePositive(startingBalance, "Starting balance");
  assertFiniteNonNegative(riskPercentage, "Risk percentage");
  if (!Number.isInteger(consecutiveLosses) || consecutiveLosses < 0) throw new Error("Consecutive losses must be a whole number of zero or more");
  const endingBalance = startingBalance * (1 - riskPercentage / 100) ** consecutiveLosses;
  if (!finite(endingBalance) || endingBalance <= 0) throw new Error("Drawdown result is outside a finite recoverable range");
  const drawdownPercentage = ((startingBalance - endingBalance) / startingBalance) * 100;
  const recoveryRequired = ((startingBalance / endingBalance) - 1) * 100;
  return { endingBalance, drawdownPercentage, recoveryRequired };
}

export function classifyRiskHealth(riskPercentage: number): RiskHealth {
  assertFiniteNonNegative(riskPercentage, "Risk percentage");
  if (riskPercentage > 10) return "Critical Exposure";
  if (riskPercentage > 5) return "High Risk";
  if (riskPercentage > 2) return "Elevated";
  if (riskPercentage > 1) return "Controlled";
  return "Conservative";
}

export function calculateBreakEvenWinRate(rewardRatio: number): number {
  assertFinitePositive(rewardRatio, "Risk-to-reward ratio");
  return 1 / (1 + rewardRatio);
}

export function calculateRecoveryTarget(startingBalance: number, endingBalance: number): number {
  assertFinitePositive(startingBalance, "Starting balance");
  if (!finite(endingBalance) || endingBalance < 0) throw new Error("Ending balance must be a finite non-negative number");
  if (endingBalance === 0) return Infinity;
  return ((startingBalance / endingBalance) - 1) * 100;
}

export interface CompoundedProjectionInput extends ProfitProjectionInput {
  monthlyContribution?: number;
}

export interface CompoundedProjectionResult extends ProfitProjectionResult {
  breakEvenWinRate: number;
  balanceProjection: number[];
  contributionTotal: number;
}

export function calculateCompoundedProjection(input: CompoundedProjectionInput): CompoundedProjectionResult {
  const { accountBalance, riskPercentage, rewardRatio, winRate, numberOfTrades, monthlyContribution = 0 } = input;
  assertFiniteNonNegative(accountBalance, "Account balance");
  assertFiniteNonNegative(riskPercentage, "Risk percentage");
  assertFinitePositive(rewardRatio, "Risk-to-reward ratio");
  if (!finite(winRate) || winRate < 0 || winRate > 100) throw new Error("Win rate must be between 0 and 100");
  if (!Number.isInteger(numberOfTrades) || numberOfTrades < 0) throw new Error("Number of trades must be a whole number of zero or more");
  if (!finite(monthlyContribution) || monthlyContribution < 0) throw new Error("Monthly contribution must be a finite non-negative number");
  if (accountBalance === 0) throw new Error("Account balance must be greater than 0 for projections");

  let balance = accountBalance;
  let grossProfit = 0;
  let grossLoss = 0;
  const balanceProjection = [balance];
  const expectedWinRate = winRate / 100;

  for (let i = 0; i < numberOfTrades; i += 1) {
    const riskAmount = balance * (riskPercentage / 100);
    const expectedProfit = expectedWinRate * riskAmount * rewardRatio;
    const expectedLoss = (1 - expectedWinRate) * riskAmount;
    grossProfit += expectedProfit;
    grossLoss += expectedLoss;
    balance += expectedProfit - expectedLoss;
    if (!finite(balance) || balance < 0) throw new Error("Compounded projection produced an invalid balance");
    balanceProjection.push(balance);
  }

  const contributionTotal = monthlyContribution;
  balance += contributionTotal;
  if (contributionTotal > 0) balanceProjection.push(balance);
  const riskAmount = accountBalance * (riskPercentage / 100);
  const profitPerWin = riskAmount * rewardRatio;
  const estimatedWins = numberOfTrades * expectedWinRate;
  const estimatedLosses = numberOfTrades - estimatedWins;
  const netOutcome = grossProfit - grossLoss;
  const endingBalance = balance;
  const percentageChange = ((endingBalance - accountBalance) / accountBalance) * 100;
  return { riskAmount, profitPerWin, lossPerLoss: riskAmount, estimatedWins, estimatedLosses, grossProfit, grossLoss, netOutcome: netOutcome + contributionTotal, endingBalance, percentageChange, breakEvenWinRate: calculateBreakEvenWinRate(rewardRatio), balanceProjection, contributionTotal };
}

export interface RiskScenarioInput {
  name: string;
  accountBalance: number;
  riskPercentage: number;
  rewardRatio: number;
  winRate: number;
  numberOfTrades: number;
}

export interface RiskScenarioComparison {
  name: string;
  endingBalance: number;
  netOutcome: number;
  drawdownWarning: string;
  breakEvenWinRate: number;
  riskClassification: RiskHealth;
}

export function compareRiskScenarios(scenarios: RiskScenarioInput[]): RiskScenarioComparison[] {
  return scenarios.map((scenario) => {
    const projection = calculateProfitProjection(scenario);
    const riskClassification = classifyRiskHealth(scenario.riskPercentage);
    const drawdownWarning = scenario.riskPercentage > 10
      ? "Critical exposure"
      : scenario.riskPercentage > 5
        ? "High risk"
        : scenario.riskPercentage > 2
          ? "Elevated caution"
          : "Controlled range";
    return { name: scenario.name, endingBalance: projection.endingBalance, netOutcome: projection.netOutcome, drawdownWarning, breakEvenWinRate: calculateBreakEvenWinRate(scenario.rewardRatio), riskClassification };
  });
}
