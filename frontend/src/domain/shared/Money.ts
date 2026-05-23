/** Value object: monetary amount. Always use, never raw number. */
export interface Money {
  readonly amount: number;
  readonly currency: string; // e.g., "USD", "CNY", "BTC"
}

export function Money(amount: number, currency = "USD"): Money {
  if (!Number.isFinite(amount)) throw new Error("Money amount must be finite");
  return { amount, currency };
}

export function formatMoney(money: Money): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: money.currency,
  }).format(money.amount);
}
