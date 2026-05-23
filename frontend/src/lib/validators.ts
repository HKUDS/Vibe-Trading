import { z } from "zod";

/** Entity ID validator. */
export const EntityIdSchema = z.string().uuid();

/** Percentage validator (0.0 ~ 1.0). */
export const PercentageSchema = z.number().min(-1).max(1);

/** Money validator. */
export const MoneySchema = z.object({
  amount: z.number().finite(),
  currency: z.string().min(1).max(3),
});

/** Strategy template parameter validators. */
export const MovingAverageParamsSchema = z.object({
  symbol: z.string().min(1).max(20),
  shortPeriod: z.number().int().min(1).max(100),
  longPeriod: z.number().int().min(1).max(200),
  positionSize: PercentageSchema,
  stopLoss: PercentageSchema.optional(),
  takeProfit: PercentageSchema.optional(),
});

export type MovingAverageParams = z.infer<typeof MovingAverageParamsSchema>;
