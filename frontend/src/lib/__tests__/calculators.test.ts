import { describe, expect, it } from "vitest";
import { calculateDrawdown, calculatePositionSize, calculateProfitProjection, calculateRiskAmount, classifyRiskHealth } from "../calculators";

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
