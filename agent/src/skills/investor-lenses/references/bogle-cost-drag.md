---
name: bogle-cost-drag
lens: Cost Drag and Mean Reversion
attributed_to: John Bogle
style: allocation
markets: Any market; the lens is about the activity and its costs, not about a security
description: Subtract every cost from the gross return before judging any strategy, assume returns revert toward their long-run drivers, and ask whether the activity beats the passive alternative after all frictions.
---

# Cost Drag Lens

> **Framework, not investment advice.** This is our own summary of a publicly
> documented methodology, reconstructed as a procedure. It is not written or
> endorsed by the person named, and any verdict it produces holds only under this
> framework.

## What this lens optimizes for

Keeping the return that the underlying asset actually produces. Its one structural
claim is that costs are certain and compounding while excess return is uncertain
and mean-reverting, so the cost side deserves the first and most precise
examination. It is the lens that asks whether the *whole exercise* is worth doing.

## Market-fit note

- Cost structures differ sharply by market and must be enumerated locally: A-share
  stamp duty on sales, exchange and settlement fees, and the bid-ask on small caps;
  HK stamp duty on both sides plus trading and settlement levies; US commission-free
  equity trading where the cost has moved into spread and order routing; crypto
  taker fees, funding and slippage that can dwarf everything else.
- Turnover is the multiplier on all of it. A strategy's cost is a function of how
  often it trades, not of its headline fee.

## Priority signals (walk in this order)

1. **Enumerate every cost, not just the visible one.**
   - explicit: management fee, performance fee, custody, commission
   - transaction: bid-ask spread, market impact, exchange and clearing fees
   - statutory: stamp duty, transaction tax, withholding on dividends
   - hidden: cash drag, turnover-induced tax realization, borrow cost, financing
     spread on leverage, currency conversion
2. **Convert cost to an annual drag** using actual turnover. Gross return minus the
   annualized all-in drag is the only number worth comparing.
3. **Name the passive benchmark** the activity must beat: the cheapest reachable
   broad exposure to the same risk. Every comparison in this lens is against that
   alternative, net of its own costs.
4. **Compound the drag over the holding horizon.** A drag that looks trivial per
   year is not trivial over a decade; state the terminal-value difference, not the
   annual one.
5. **Discount past outperformance toward the mean.** Assume a large part of any
   historical excess return is unrepeatable. Ask what would remain if the excess
   halved — is the activity still worth its cost?
6. **Decompose the return into its sources.** For equities: dividend yield, earnings
   growth, and change in valuation multiple. The multiple-change component is the
   speculative part and should not be extrapolated.
7. **Behavioural cost.** Estimate the gap between the strategy's time-weighted
   return and the investor's likely money-weighted return. Strategies that invite
   trading at the wrong moments carry a real cost that never appears in a fee table.

## Disqualifiers (hard vetoes)

- **Gross returns compared to a net benchmark**, or costs quoted as a headline fee
  with turnover-driven costs omitted.
- **No passive alternative named.** Without the alternative there is no test.
- **Excess return extrapolated at its historical rate** with no mean-reversion
  haircut applied.
- **Return attributed mostly to multiple expansion** and then projected forward.
- **All-in drag exceeding the plausible excess return** — under this lens that is a
  decisive no, independent of how attractive the strategy looks.

## Scoring rubric

| Item | Value |
| --- | --- |
| Gross expected return | stated |
| All-in annual drag (turnover-adjusted) | stated |
| Net expected return | gross − drag |
| Passive alternative, net | stated |
| Net advantage | difference |
| Net advantage after halving the excess | difference |

If the last row is not positive, the lens returns no.

## Typical misuse

- **Used to evaluate a single security.** It has nothing to say about whether a
  company is good; it evaluates activities, strategies and vehicles.
- **Read as "indexing always wins".** The lens is an arithmetic test. In markets or
  segments with high dispersion and low-cost access to skill, the test can pass.
  Run the arithmetic; do not assume the conclusion.
- **Cost minimization at the expense of exposure correctness.** The cheapest vehicle
  tracking the wrong exposure is worse than a costlier one tracking the right
  exposure. Fix the exposure first, then minimize its cost.
- **Ignoring capacity and liquidity.** A cheap fund in an illiquid segment pays its
  cost through tracking error and spread instead of through the fee line.
- **Applied to genuinely uncorrelated return streams as if they were substitutes.**
  A hedge that reduces portfolio risk can be worth a negative expected return; this
  lens's arithmetic does not price that and will reject it wrongly.

## Falsifiers

- The measured all-in drag comes in materially below the estimate after a full year
  of real turnover → the cost model was wrong and the verdict must be recomputed.
- The excess return persists at full magnitude across an independent later period,
  with the same process → the mean-reversion haircut was too severe for this case.
- The passive alternative fails to track its own exposure → the benchmark was not
  actually reachable and the comparison is void.

## Output contract

Report under the skill-level output contract. State the verdict as "under a
cost-drag framework, …", show the full cost enumeration with turnover, name the
passive alternative, and report both the net advantage and the net advantage after
halving the assumed excess. This is analysis, not investment advice.
