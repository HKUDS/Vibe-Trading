# Validate finite bond schedule and accrual inputs

## Context

The fixed-income module has one finite-input validator, but the cashflow schedule omits frequency and accrued interest omits all numeric inputs. Infinite frequency produces a plausible par price instead of rejecting an undefined payment schedule. Accrual's zero-at-coupon shortcut can mask invalid face/rate data. These public functions are reachable through the read-only quantlib tool.

## Decision

Extend the existing schedule validator to frequency and use that same owner for accrued face, coupon and frequency before shortcuts or arithmetic. Preserve finite-input range behavior and existing pricing formulas.

## Alternatives

Validate only the final price, which cannot detect a plausible100 returned from infinite frequency, or add ad-hoc checks in every derived sensitivity. Schedule admission already owns the common pricing/sensitivity path; the existing validator avoids another policy.

## Consequences

Undefined payment frequencies and accrual inputs raise field-specific errors; finite schedules, zero coupons and existing fractional-frequency behavior retain their previous semantics. No new integer-only restriction or trading/account boundary is introduced.

## Validation

Frozen main300c6aa6989fcf2ec1cb052c89237b48fabdb524 with new cases:21 failures,3 existing controls passed,149 deselected. Candidate full fixed-income suite173 passed, covering pricing, sensitivity finite-difference references, dates and curve fits. Compile and diff whitespace checks passed. Actual pure QuantlibCallTool replay uses valid JSON freq:1e309: baseline returns ok=true/price100; candidate returns ok=false naming the non-finite frequency. Own merged PRs and all four open PR file inventories have no implementation/test overlap; merged1659 supplies the analogous finite-input contract in a different quantlib module. Synthetic inputs only; no provider, market-data, broker, wallet, credentials or live-order execution. Full application checks and other OS hosts were not run.
