import { describe, expect, it } from "vitest";
import { calculateBreakEvenWinRate, calculateCompoundedProjection, calculateDrawdown, calculatePositionSize, calculateProfitProjection, calculateRecoveryTarget, calculateRiskAmount, classifyRiskHealth, compareRiskScenarios } from "../calculators";

describe("calculators", () => {
  it("handles standard valid profit projection inputs", () => {
    const result = calculateProfitProjection({ accountBalance: 10000, riskPercentage: 1, rewardRatio: 2, winRate: 50, numberOfTrades: 10 });
    expect(result.riskAmount).toBe(100);
    expect(result.profitPerWin).toBe(200);
    expect(result.grossProfit).toBe(1000);
    expect(result.grossLoss).toBe(500);
    expect(result.endingBalance).toBe(10500);
  });

  it("allows zero risk", () => {
    expect(calculateRiskAmount(10000, 0)).toBe(0);
    expect(calculateProfitProjection({ accountBalance: 10000, riskPercentage: 0, rewardRatio: 2, winRate: 50, numberOfTrades: 10 }).netOutcome).toBe(0);
  });

  it("rejects invalid negative values", () => {
    expect(() => calculateRiskAmount(-1, 1)).toThrow();
    expect(() => calculateProfitProjection({ accountBalance: 10000, riskPercentage: -1, rewardRatio: 2, winRate: 50, numberOfTrades: 10 })).toThrow();
  });

  it("handles win rate 0%", () => {
    const result = calculateProfitProjection({ accountBalance: 10000, riskPercentage: 1, rewardRatio: 2, winRate: 0, numberOfTrades: 4 });
    expect(result.estimatedWins).toBe(0);
    expect(result.netOutcome).toBe(-400);
  });

  it("handles win rate 100%", () => {
    const result = calculateProfitProjection({ accountBalance: 10000, riskPercentage: 1, rewardRatio: 2, winRate: 100, numberOfTrades: 4 });
    expect(result.estimatedLosses).toBe(0);
    expect(result.netOutcome).toBe(800);
  });

  it("classifies excessive risk", () => {
    expect(classifyRiskHealth(2.5)).toBe("Elevated");
    expect(classifyRiskHealth(6)).toBe("High Risk");
    expect(classifyRiskHealth(11)).toBe("Critical Exposure");
  });

  it("supports decimal values", () => {
    expect(calculateRiskAmount(12345.67, 1.25)).toBeCloseTo(154.320875);
    expect(calculatePositionSize({ accountBalance: 5000, riskPercentage: 0.5, stopLossPips: 12.5, pipValuePerStandardLot: 10 }).standardLots).toBeCloseTo(0.2);
  });

  it("calculates drawdown after consecutive losses and recovery percentage", () => {
    const result = calculateDrawdown(10000, 2, 3);
    expect(result.endingBalance).toBeCloseTo(9411.92);
    expect(result.drawdownPercentage).toBeCloseTo(5.8808);
    expect(result.recoveryRequired).toBeCloseTo(6.2487);
  });

  it("prevents division by zero", () => {
    expect(() => calculatePositionSize({ accountBalance: 10000, riskPercentage: 1, stopLossPips: 0, pipValuePerStandardLot: 10 })).toThrow();
    expect(() => calculateDrawdown(0, 2, 3)).toThrow();
  });

  it("rejects NaN and Infinity", () => {
    expect(() => calculateRiskAmount(Number.NaN, 1)).toThrow();
    expect(() => calculateRiskAmount(10000, Number.POSITIVE_INFINITY)).toThrow();
  });
});


describe("phase 4 risk calculator extensions", () => {
  it("calculates break-even win rates", () => {
    expect(calculateBreakEvenWinRate(1)).toBeCloseTo(0.5);
    expect(calculateBreakEvenWinRate(2)).toBeCloseTo(1 / 3);
    expect(calculateBreakEvenWinRate(3)).toBeCloseTo(0.25);
  });

  it("handles compounding with zero trades and zero risk", () => {
    expect(calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: 1, rewardRatio: 2, winRate: 50, numberOfTrades: 0 }).endingBalance).toBe(1000);
    expect(calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: 0, rewardRatio: 2, winRate: 50, numberOfTrades: 10 }).netOutcome).toBe(0);
  });

  it("handles compounding with 0% and 100% win rate", () => {
    expect(calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: 1, rewardRatio: 2, winRate: 0, numberOfTrades: 2 }).endingBalance).toBeCloseTo(980.1);
    expect(calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: 1, rewardRatio: 2, winRate: 100, numberOfTrades: 2 }).endingBalance).toBeCloseTo(1040.4);
  });

  it("handles monthly contributions and rejects invalid negative contributions", () => {
    expect(calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: 0, rewardRatio: 2, winRate: 50, numberOfTrades: 0, monthlyContribution: 100 }).endingBalance).toBe(1100);
    expect(() => calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: 1, rewardRatio: 2, winRate: 50, numberOfTrades: 1, monthlyContribution: -1 })).toThrow();
  });

  it("guards extreme risk and invalid values", () => {
    expect(classifyRiskHealth(25)).toBe("Critical Exposure");
    expect(() => calculateBreakEvenWinRate(0)).toThrow();
    expect(() => calculateCompoundedProjection({ accountBalance: 1000, riskPercentage: Number.POSITIVE_INFINITY, rewardRatio: 2, winRate: 50, numberOfTrades: 1 })).toThrow();
  });

  it("compares scenarios and preserves ordering", () => {
    const result = compareRiskScenarios([
      { name: "Conservative", accountBalance: 1000, riskPercentage: 0.5, rewardRatio: 1.5, winRate: 55, numberOfTrades: 20 },
      { name: "Balanced", accountBalance: 1000, riskPercentage: 1, rewardRatio: 2, winRate: 50, numberOfTrades: 20 },
      { name: "Aggressive", accountBalance: 1000, riskPercentage: 3, rewardRatio: 2.5, winRate: 45, numberOfTrades: 20 },
    ]);
    expect(result.map((item) => item.name)).toEqual(["Conservative", "Balanced", "Aggressive"]);
    expect(result[2].riskClassification).toBe("Elevated");
  });

  it("handles recovery target infinity and decimal rounding stability", () => {
    expect(calculateRecoveryTarget(1000, 0)).toBe(Infinity);
    expect(calculateRecoveryTarget(1000, 500)).toBeCloseTo(100);
    expect(calculateCompoundedProjection({ accountBalance: 1234.56, riskPercentage: 1.25, rewardRatio: 1.75, winRate: 52.5, numberOfTrades: 7 }).endingBalance).toBeCloseTo(1283.3007, 3);
  });
});
