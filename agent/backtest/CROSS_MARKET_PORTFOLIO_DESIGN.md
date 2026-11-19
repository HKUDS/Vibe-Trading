# Proposal: one US / India / Hong Kong portfolio

Authors: @Jampip, @Joshuaamm7, @james-mulyono, @jaz024, @prs-016.

**Status:** design proposal; no new multicurrency execution mode is implemented.
The existing single-currency guard stays in force. India/HK calendar, FX and cost
contracts need coordinated review before becoming a shared implementation base.

## Existing upstream behavior audited

Source base: `d4bce9b28205d61a81e5a5346bd659433312069c`, plus the HK market-layer changes.
Reviewed locally on November 19, 2026.

- `backtest/engines/composite.py::CompositeEngine` uses one capital pool and
  routes symbols to market-specific rule engines. `_reject_mixed_currency`
  rejects a US/IN/HK currency mix before data acquisition. This is essential:
  simply deleting the guard would add USD, INR and HKD as interchangeable units.
- `CompositeEngine.can_execute` calls `india_can_execute` with the composite's
  positions/data and India's rule parameters. That preserves India's T+1 and
  price-band checks in composite runs; do not replace this state-aware routing
  with a stateless delegate. `test_composite_market_rules.py` covers it.
- Lot rounding and execution fees/slippage already dispatch by active symbol;
  P&L, margin and raw sizing dispatch by the relevant market. B3 synchronizes the
  execution timestamp before fee dispatch so dated HK duty is applied correctly.
- The engine has no cross-currency cash accounts, historical FX ledger,
  executable FX conversion, market-level risk parity or hedge book.
- `src.portfolio.fx` already establishes local-units-per-USD direction for a
  separate portfolio quote/valuation path. It is not a historical backtest FX
  feed and must not be used to value an old run with today's display quote.
- The gateway has XHKG and XNYS calendar validation. B3 adds sourced pre-2024 HK
  weather exceptions, retains lunch/half-days, and does not impose the obsolete
  typhoon closure policy on post-September-23-2024 sessions. India calendar and
  its evidenced special sessions remain Jamal's B3 contribution.

## Proposed book and execution contract

One run declares `base_currency: USD`, the three market universes, calendar
policies, native-currency cost schedules, dated lot inputs, historical FX close
and availability timestamps, and `fx_hedging: unhedged|hedged`. This is a proposed
configuration contract, not an accepted CLI/API extension.

1. Keep positions, native prices and costs in their actual instrument currency.
   Keep separate USD/INR/HKD cash accounts, settlement/unavailable cash and an
   explicit timestamped FX conversion ledger. A USD presentation currency does
   not imply every execution is a USD transaction.
2. Build a union of exchange events in UTC. Only execute orders while that
   instrument's own session permits them, with no HK lunch fills and no execution
   on holidays or before an evidenced delayed opening. Missing/suspended prices
   remain nonexecutable; the last observed mark is labeled stale rather than
   synthesizing a fresh close or filling orders at an old price.
3. Route India through the existing state-aware T+1/price-band rules. Reuse its
   engine cost stack. Route HK through B3's dated bilateral duty and lot sizes,
   with current-lot historical assumptions explicitly disclosed. Calendar
   acceptance never overrides settlement, borrow or execution eligibility.
4. Value to USD with the last prior FX close available at the valuation instant,
   retaining both `close_at` and `available_at`. For HKD-per-USD, divide. The same
   direction applies to INR-per-USD. Never infer availability from a date label.
   Missing/stale FX prevents a USD valuation; it does not silently use7.8 or1.
5. Publish one daily portfolio valuation at a documented UTC reporting instant,
   plus market-native value/return paths and selected FX timestamps. A closed
   market's unchanged mark and a missing valuation have different statuses.
   Compare B4/B5 metrics only over an explicitly matched period/horizon and
   document mixed adjustment bases and non-point-in-time membership.

## Market risk parity

Estimate market sleeve risk from past observations only, with the lookback,
minimum history, rebalance schedule, volatility floor, caps and covariance
method frozen in configuration before testing. A first supported contract is
inverse-volatility market weights normalized across eligible sleeves, with no
leverage and cash retained when a sleeve is unavailable. Do not call this exact
covariance-aware equal-risk contribution without implementing/validating that
solver. A covariance-aware alternative requires an explicit method decision.

Compute weights at a common information cutoff, then schedule each sleeve's
orders for its next eligible session. Later US closes must not influence the
same calendar day's earlier India/HK orders. Store allocation decisions,
information timestamps and actual fills separately for audit. Universe-level
risk budgets do not bypass single-name lots/costs or capacity constraints.

## Hedged and unhedged modes

Unhedged mode contains the native book's FX exposure and translates equity using
the historical rate contract. Hedged mode additionally requires real hedge
instruments (or a separately labeled synthetic research hedge), hedge notional,
quote/availability times, financing/carry, bid/ask, roll schedule, trading
calendar and collateral accounting. It must not merely subtract FX returns or
freeze the conversion rate. Initially reject `hedged` until a reviewed hedge
model and data contract exist; discuss the supported instrument choice with
Prakhar/upstream maintainers. Report hedge P&L and costs separately.

## Staged implementation and acceptance tests

1. Complete/review joint B3: combine India/HK calendar, FX and cost contracts;
   keep source-provenance and historical-data limitations visible.
2. Add a multicurrency ledger behind an explicit mode, retaining the existing
   single-currency guard/default path. Test cash conservation, fees in the native
   currency, FX direction, rounding and failure on missing rates.
3. Add the UTC event/session clock and asynchronous target execution. Test HK
   lunch, a holiday, evidenced HK late open, India special sessions/T+1/bands,
   US daylight-saving boundaries and stale/absent bars.
4. Add the frozen market allocation rule and causal volatility estimates. Test
   that changing future prices/FX cannot alter earlier orders or weights; test
   caps, zero/insufficient volatility, missing sleeves and lot residual cash.
5. Add unhedged valuation/reporting, with a hand-computed USD/INR/HKD book and
   reconciliation to three independent native-engine runs using identical fills.
6. Add hedge support only after its data/accounting contract is reviewed. Until
   then hedged mode fails clearly. Test carry/roll/collateral instead of labeling
   an FX-neutral arithmetic result as an executable hedge.

All tests use fixtures/mocked acquisition. Empirical strategy evaluations remain
separate from these accounting tests and must record every trial. This proposal
needs coordinated maintainer review before implementation. No AWS deployment is needed to review or implement it.

## Decisions for coordinated review

Confirm the common daily valuation instant, inverse-vol versus full covariance
risk parity, accepted FX close/publication policy, maximum quote age, and hedge
instruments/model. The existing calendar dependency can be reused. The proposed
configuration/CLI shape and relationship between composite execution and B4/B5
parallel single-market evaluation need maintainer review before implementation.
