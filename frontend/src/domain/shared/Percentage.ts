/** Value object: percentage. Internal storage: 0.47 = 47%. */
export interface Percentage {
  readonly value: number; // 0.0 ~ 1.0
}

export function Percentage(value: number): Percentage {
  if (!Number.isFinite(value) || value < -1 || value > 1) {
    throw new Error("Percentage must be between -100% and 100%");
  }
  return { value };
}

export function formatPercentage(pct: Percentage): string {
  return `${(pct.value * 100).toFixed(2)}%`;
}
