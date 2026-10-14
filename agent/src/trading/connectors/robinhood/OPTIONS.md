# Robinhood options orders (#1435)

**Status: not supported. Options orders are blocked before they reach Robinhood.**

## What the broker exposes

Robinhood's Agentic MCP server lists an options surface in its unfiltered
`tools/list`. It includes `place_option_order`, `review_option_order`,
`cancel_option_order`, `get_option_orders`, `get_option_positions`,
`get_option_chains`, `get_option_instruments`, `get_option_quotes`,
`exercise_option` and `cancel_option_exercise`. The read-side shapes of
`get_option_chains`, `get_option_instruments` and `get_option_positions` were
posted on #1435. The contract multiplier is `trade_value_multiplier`, sent as a
string.

## What blocks it

Nobody has posted the **argument schema** of `place_option_order` or
`review_option_order`. Without it we don't know how a contract is identified
(an instrument id, or strike, expiry and call/put), whether quantity counts
contracts, or how a multi-leg order is sent. Is it one atomic call or one call
per leg? The gate can only price an order from fields it knows. Guessing the
mapping would be fake support, so:

- `OPTIONS_ORDERS_SUPPORTED = False` in
  `agent/src/trading/connectors/robinhood/mcp.py`;
- `place_option_order` stays classified WRITE and has no intent extractor, so
  the order guard refuses it ("order intent could not be parsed") with no broker
  call;
- an options intent sent through `place_equity_order` (`type="option"`) is
  refused by `check_mandate`, which prices shares, not contracts.

## What is ready (groundwork)

- **Mandate.** `Mandate.option_limits` (`OptionLimits`) sets the per-order and
  per-day caps on premium and on max loss, plus `allow_naked_short`. It is
  `None` by default, so options are disabled. `commit_mandate(...,
  option_limits=...)` writes it only from an explicit argument from the consent
  surface, never from the agent-authored proposal profile. Options also need
  `"option"` in `allowed_instruments`.
- **Gate.** `src.live.options.check_option_order` is a pure, fail-closed check
  that uses the same `BreachEvent` routing as the equity gate: structural limits
  DENY, quantitative limits PAUSE. Premium and max loss include the contract
  multiplier. Max loss is the worst expiry payoff of all legs together. A short
  call with no long call to cover it has unbounded loss and is always refused.
  A naked short put is refused unless `allow_naked_short` is set. A multi-leg
  order must be atomic and use a single expiry.

## To finish

1. Get the argument schemas (names and types only) of `place_option_order` and
   `review_option_order`.
2. Write a Robinhood options extractor that maps them to `OptionOrderIntent`.
   Take the multiplier from `get_option_instruments`, never from a default of
   100.
3. Route `place_option_order` in `LiveOrderGuardTool` through
   `check_option_order`. Require a `review_option_order` preview first, persist
   the day's premium and max-loss totals next to the daily count, and add an
   options field to the commit endpoint and UI.
4. Map `get_option_orders` so order status, fills, cancellations and broker
   errors are visible. Keep `exercise_option` and `cancel_option_exercise` out of
   the autonomous path.
