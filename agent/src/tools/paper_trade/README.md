# Daily paper trading

Open **Paper trading** in the Web sidebar (`/paper-trading`). Create an account
with initial cash and positions, choose today or the next session, then settle
completed daily bars with explicit orders or a strategy file. The page displays
cash, positions, fills, rejections, data provenance, warnings and NAV history.
It supports every registered UI language. No broker order is sent.

Saved accounts start no earlier than creation in the market's time zone.
“Next session” sets the earliest eligible date after today; weekends are skipped
and holidays wait for available session data. Settlement waits until 30 minutes
after the regular local close (conservative on early-close days). There is no
background scheduler. Failure leaves the ledger unchanged. Revision checks
prevent concurrent requests from committing the same step. Ledger and history
live in `<runtime_root>/paper-trading/accounts.db`.

## CLI

Create `initial-state.json` with your simulated ledger:

```json
{"cash": 100000, "positions": [{"symbol": "AAPL.US", "qty": 10, "avg_cost": 330}]}
```

```bash
vibe-trading paper create --label 'US research' --market us --state initial-state.json --start today
vibe-trading paper list
vibe-trading paper show ACCOUNT_ID
vibe-trading paper advance ACCOUNT_ID --revision 0 --to-date YYYY-MM-DD --orders orders.json
vibe-trading paper history ACCOUNT_ID
```

`orders.json` is an array, e.g. `[{"symbol":"AAPL.US","side":"buy","qty":10}]`.
Use `[]` for valuation only. Replace `--orders` with `--strategy-path PATH` to run
a strategy. Explicit orders execute on `--to-date`; all intervening dates are
checked and valued. The revision is returned by `show` and changes on commit.
A nonzero CLI exit indicates an error or a step that did not commit.

## API

All routes require the existing API authentication policy. POST routes also use
the browser-origin and local/authenticated write gate.

| Method and path | Purpose |
| --- | --- |
| `GET /api/paper-accounts` | List accounts |
| `POST /api/paper-accounts` | Create: `label`, `market`, `account_state`, optional `start` (`today` / `next_session`) and `fee_model` |
| `GET /api/paper-accounts/{id}` | Read ledger and revision |
| `GET /api/paper-accounts/{id}/history` | Read committed results |
| `POST /api/paper-accounts/{id}/advance` | `expected_revision`, `to_date`, and exactly one of `orders` / `strategy_path` |
| `POST /api/paper-trade/step` | Pure caller-owned payload; no saved account |

Advance returns `{account, result, committed}`. Data/strategy errors return
`committed: false`; HTTP 409 means the account changed and must be reloaded.
After a network timeout, read the account before retrying: the server may have
committed. The Web client reloads it automatically on a request error.

The pure `paper_trade_step` agent/MCP tool and `vibe-trading paper step payload.json`
remain stateless and accept historical dates for reproducible research. Their
orders mode requires a single date. Saved accounts enforce forward-only dates.

## Strategy contract

Place a Python file under `<runtime_root>/strategies/`. The `SignalEngine` class
is required; `UNIVERSE` supplies symbols for cash-only accounts.

```python
UNIVERSE = ("AAPL.US",)

class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        history = ctx.history("AAPL.US")
        if len(history) < 20 or ctx.account_state.positions:
            return []
        if history["close"].iloc[-1] > history["close"].iloc[-20:].mean():
            return [{"symbol": "AAPL.US", "side": "buy", "qty": 1}]
        return []
```

History contains **only dates strictly before execution**. Orders fill at that
day's close. The strategy receives the private ledger after previous days'
fills. The spawned child receives no current/future bars and retains its instance
across dates in one call. Source validation and process timeouts apply. Any
strategy failure discards the whole call, including earlier uncommitted results.

## Five-minute cn_a steps

`paper_trade_step` accepts `interval="5m"` for A-shares. One step covers exactly
one completed session and matches bar by bar against its 48 continuous
five-minute bars. The 09:30 label is the opening
call-auction print, single-priced on 4 of 5 probed days, and is excluded by
policy without an event. A label in 09:15-09:25 or from 14:57 up to but not
including 15:00 is an auction-window anomaly, excluded from matching and
reported as an `auction_window` event; the 15:00 label is a continuous bar.

A symbol with 5m rows but no continuous session bar on a calendar-open day is
`halted`: its position is valued at the last available close (carry-forward),
and an order on it is rejected `suspended` with one
`canceled_after_failed_match` row. A requested 5m symbol whose response carried
no row at all while its daily bar exists is a provider omission and returns
`PAPER_DATA_NOT_READY`, not a halt.

| Field | Values | Default | Meaning |
| --- | --- | --- | --- |
| `interval` | `1d`, `5m` | `1d` | `5m` is cn_a-only and accepts one date per step |
| `session` | `auto`, `cn_a` | `auto` | coherence selector only: `cn_a` requires `market="cn_a"` and does not change the day boundary |
| `path_model` | `bar_median`, `bar_close` | `bar_median` | reference price from each bar |
| `fill_model` | `all_or_none`, `volume_share` | `all_or_none` | `volume_share` opts into pt-v1.3 per-order partial fills |
| `order_volume_ratio` | number in `(0, 1]` | `1.0` | per-order share of matched volume; only with `fill_model="volume_share"` |

A market order fills at the first continuous bar whose fill gates pass. If a
buy is blocked at the upper price limit or a sell at the lower limit, it is
canceled immediately and cannot fill on a later bar even if the price reopens.
The result contains one `canceled_orders` entry with the existing
`canceled_after_failed_match` reason and a detail naming `limit_up` or
`limit_down`, plus a `price_limit` event; it is not a rejected order. A limit
order blocked by the price band instead stays open until it fills or expires at
the end of the session ([JoinQuant API guide, order processing](https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf)).
The default daily pt-v1.1 contract is unchanged and
continues to report its established rejection reasons.

A resting limit follows JoinQuant's bar matching: a buy triggers only when
`bar.low < limit` (its 委托价 above the bar's low) and a sell only when
`bar.high > limit` (its 委托价 below the bar's high), and a triggered fill
executes at the order's 委托价 rather than the bar reference. Equality does not
fill, so a bar that only touches the limit leaves the order resting, and a limit
that never triggers is canceled at session end (15:00 on a complete session). On
the first bar with volume, an already-marketable reference (`ref < limit` for a
buy, `ref > limit` for a sell) fills at that strictly better price instead,
which wins over the 委托价 even when the bar also crosses. By default every fill
is all-or-none.

`fill_model="volume_share"` is the opt-in pt-v1.3 policy (5m cn_a only). Each
order is capped independently at `floor(volume × order_volume_ratio / lot) × lot`
shares — never against a shared bar budget — so two orders may together exceed
a bar's volume. The accepted ratio keeps its `Decimal(str(value))` precision;
neither the ratio nor the volume product is separately rounded before the lot
floor. `order_volume_ratio` defaults to `1.0` (no reduction) and is accepted
only with `fill_model="volume_share"`. A market order caps on the full
continuous-session volume, fills what fits and cancels the residual immediately
with `canceled_after_volume_cap`. A zero-cap market order still checks price
bands at the first live bar; if unblocked, its residual is canceled there
without a zero-quantity fill or cash/position gate. A limit order caps per bar,
waits through zero-cap bars, keeps the residual resting while `filled` (active),
and its day-end cancel still reports `canceled_after_failed_match`. A
zero-volume bar never fills. Each fill is booked and charged separately, so a
two-fill order pays two minimum commissions.

A pt-v1.3 result adds `order_states`: one row per submitted order, in
submission order, with exactly `order_id`, `status`, `add_time`, `amount`,
`filled`, `price` and `side`. `add_time` is the cn_a session open
(`YYYY-MM-DDT09:30:00+08:00`), `amount` is the requested quantity, `filled` is
the executed quantity and `price` is `0.0` when nothing filled.

Inside the five-minute session (the daily path builds no order book), order
statuses use JoinQuant's `OrderStatus` vocabulary: `held` means fully filled
and terminal, `canceled` and `rejected` are also terminal, and `new`, `open`
and `pending_cancel` are not. JoinQuant's `filled` (partially filled, residual
still in `open_orders()`) is reachable under `fill_model="volume_share"`; with
the default all-or-none path it is not reached. A pt-v1.3 result exposes these
states in `order_states`; the daily path keeps them internal.

The matcher walks a shared chronological timeline across the supplied symbol
frames, so later proceeds cannot fund an earlier order. At a shared timestamp,
orders are evaluated in caller submission order, including the cash check;
there is no implicit sell-first priority. Each symbol tracks its own first
positive-volume bar for the better-price rule. This engine behavior does not
relax the public tool's single-symbol provider limit below.

The 5m leg uses Tushare `stk_mins` and is resolved separately from the daily
chain: Tencent's raw loader serves daily bars only. The measured provider limit
is one symbol per step (1 call/minute, 1 call/hour and 2 calls/day; a refused
call still consumes the daily budget), so a 5m step with two order symbols is
refused before any fetch. Split the orders across steps or use `interval="1d"`.
Orders mode derives the 5m universe from the order symbols; strategy mode
requires a non-empty `UNIVERSE` and refuses any order outside it. When no
5m-capable loader is configured, the step returns `PAPER_DATA_NOT_READY` naming
the loader instead of reading the daily source as a 5m source.

A step with `"orders": []` issues no `stk_mins` request. Its NAV comes from the
daily leg and follows the `interval="1d"` contract exactly: without the target
daily bar it returns the same `PAPER_DATA_NOT_READY`; with the target daily bar
it produces the NAV row from that day's closes.

The 5m leg is stateless. It is exposed through the agent/MCP step tool,
`POST /api/paper-trade/step` and `vibe-trading paper step`; saved accounts
remain daily-only. The persistent v1.2 runner/account/store layer is a follow-up
branch (`paper-trade-v12-persistence`) and is not wired to any CLI, API or MCP
surface in this PR.

Daily data supplies the prior close for price-limit bands and the final NAV.
The band and cash gates check the price the fill would execute at, so a 5m
market order is gated at its bar reference and a resting limit at its 委托价;
a limit order waits while its side is blocked by a price limit, while a blocked
market order is canceled immediately. Zero-volume bars cannot fill. Corporate
actions remain fail-closed.

## JoinQuant parity

Reference: the official JoinQuant API guide,
<https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf>, sections `订单处理`
(order handling) and `OrderStatus`, pp. 12-13. "Our reading" below marks
behavior inferred from that material, not a verbatim quote.

| Area | JoinQuant | This engine (pt-v1.3) | Status |
| --- | --- | --- | --- |
| Request surface | `set_option('order_volume_ratio')` sets a per-order share of matched volume; the cited PDF's example uses `0.25` and states no default | Opt-in `fill_model="volume_share"` plus `order_volume_ratio`; a ratio without that model is `INVALID_REQUEST`; `volume_share` is 5m cn_a only | Aligned; default differs by design |
| Default ratio | The cited 2018 PDF states no default; its example uses 0.25, and live JoinQuant docs may state 0.25 | `1.0`, meaning no reduction; an absent field and an explicit `null` both mean 1.0 | Deliberate opt-in default, not an official default |
| Domain | A ratio is a positive share of volume | `0 < r <= 1`; `0`, negatives, `NaN`, `Infinity`, booleans and strings are rejected | Stricter, fail-closed |
| Cap basis | Each order is limited independently by its own ratio | `floor(volume × order_volume_ratio / lot) × lot` per order; never a shared bar budget, so two orders may together exceed one bar's volume | Aligned; per-order independence is intentional |
| Market order | A market order completes against available session volume | Caps on the full continuous-session volume, fills what fits, cancels the residual immediately as `canceled_after_volume_cap`; this residual cancel is our reading of synchronous completion, not a verbatim PDF quote; a zero-volume bar never fills | Our reading, disclosed |
| Limit order | A buy fills when `委托价 > bar 的最低价`, a sell when `委托价 < bar 的最高价`, and `成交价为委托价`; an unfinished order is canceled at day end | Strict `bar.low < limit` for a buy and `bar.high > limit` for a sell; equality rests; a triggered fill executes at its 委托价; the residual rests and is canceled at session end (`canceled_after_failed_match`); on the first bar with volume, an already-marketable reference may fill better | Aligned, strict equality |
| Status names | `filled = 1` means "订单未完成, 部分成交"; `held = 4` means "订单完成, 全部成交" | `filled` is a partial that stays active; `held` is a full fill and terminal; `canceled` and `rejected` are terminal; `new`, `open` and `pending_cancel` are not emitted | Aligned |
| Order state | `OrderStatus` exposes the order's status, amount, filled quantity, price and side | `order_states` has exactly `order_id`, `status`, `add_time`, `amount`, `filled`, `price`, `side`, in submission order; `add_time` is `YYYY-MM-DDT09:30:00+08:00`; `price` is `0.0` when unfilled | Aligned shape, pinned time |
| Session volume | JoinQuant matches within its served trading session | The market cap uses the served continuous session: the 09:30 opening call-auction print is excluded (single-priced on 4 of 5 probed days), and a short session caps at its served volume with an `N/48` warning; a zero-volume session is a halt | Disclosed source boundary |

The exact quoted basis is:

- `OrderStatus`: `filled = 1`, "订单未完成, 部分成交"; `held = 4`,
  "订单完成, 全部成交, Order.filled 等于 Order.amount".
- 订单处理: buy `委托价 > bar 的最低价`, sell `委托价 < bar 的最高价`,
  `成交价为委托价`; `一天结束后, 所有未完成的订单会被取消`.
- `set_option('order_volume_ratio')`: the option limits each order
  independently; the cited PDF gives `0.25` in its example and states no
  default.

The market-order residual cancel has no verbatim sentence in the cited PDF.
It is our reading of a market order completing synchronously: whatever the
served session volume cannot fill is returned immediately instead of resting.

### Compatibility and rule versioning

The committed v1.1/v1.2 JSON contracts and fixtures are byte-identical, and a
1d call that omits the new fields is byte-identical. The corrected full/partial
statuses and 5m limit-fill prices are `pt-rules-v2`; the immediate price-limit
market cancel is `pt-rules-v3`; shared-timeline matching is `pt-rules-v4`; and
the opt-in volume-share policy is `pt-rules-v5`. Each version has a distinct
`engine_fingerprint`, which also covers `order_volume_ratio` for a
`volume_share` call, so archived results retain the rule set that produced
them.

### Parity backlog

Four platform gaps remain, plus one disclosed fee divergence:

1. **Slippage.** No spread, market impact, latency or queue-position model; a
   fill uses the bar reference or the 委托价.
2. **Cancel API.** A caller cannot submit a cancel request; cancels are
   engine-driven (day end or volume cap).
3. **Platform-generated order IDs.** IDs are `pt-0`, `pt-1`, ...; JoinQuant uses
   platform order IDs.
4. **`pending_cancel`.** JoinQuant exposes the state between a cancel request
   and its confirmation; this engine never emits or exposes it.

Disclosed fee divergence: the cited PDF charges one commission per completed
order, while this engine books and charges every fill separately, so a two-fill
order pays two minimum commissions. The per-fill charge keeps cash and position
accounting exact. Under `fill_model="volume_share"`, a sell is rejected
`insufficient_cash` before booking when its quantized notional minus that fill's
fee would make cash negative; projected cash exactly zero is allowed. Legacy
`all_or_none` behavior is unchanged.

## Independent ledger reconciliation

The `paper_trade_reconcile` agent and MCP tool accepts the initial
`{cash, positions}` ledger and a successful `paper_trade_step` document. It
replays the returned fills with Decimal arithmetic, independently checks the
per-fill fee schedule, cash, position quantities and fee-exclusive average
costs, cn_a T+1 availability, `end_state`, and each NAV row's cash and
`nav = cash + position_value` identity. A valid result with discrepancies returns
`reconciled: false` and field-level issues; malformed input returns a stable
JSON error envelope.

A position fully sold by the replay must be absent from `end_state.positions`.
A nonzero residual is a quantity mismatch even if the symbol appeared in the
initial ledger; an explicit zero-quantity ending row is reported separately.

This is a ledger audit, not a second market replay. The step document does not
contain the bars behind `position_value`, so that market value is not
recomputed. `received_state_hash` and `engine_fingerprint` are not recomputed
either, and duplicate fills cannot be detected without stable order ids. These
limits are listed in `not_verified`. The tool fetches no data, reads no broker
state and writes nothing.

## Known limits

- **Zero-calendar markets (HK/US).** A mid-range candidate weekday with no bar
  for any symbol is inferred closed: the day is recorded as
  `market_closed_inferred` with a warning, no NAV row is produced for it, its
  orders are rejected `suspended` and positions carry the last available close
  forward. An all-market zero bar
  on the target day is `PAPER_DATA_NOT_READY` (retryable), because a provider
  outage looks identical; a saved-account advance then returns `committed:
  false` and leaves the account unchanged, since a result with an empty
  `nav_series` is never committed. A single-symbol zero bar on a day another
  symbol traded is `suspended` with carry-forward valuation.
- **5m payload integrity.** A zero-volume 48-bar session is a halt: the day is
  dropped with a warning, orders are rejected `suspended` and positions are
  valued at the last available close. Off-grid continuous labels (for example a
  1m payload served as 5m) and continuous bars that are all NaN are provider
  faults, so the step returns `PAPER_DATA_NOT_READY` instead of a session.
- **The provider's bar count is authoritative.** There is no 48-bar gate: a
  session assembled from fewer bars still fills, and the `N/48 continuous bars`
  warning is returned in the step's `warnings`. Run a same-day step only after
  the session has settled, or the step prices a partial-session bar.
- **5m halt detection needs 5m evidence.** A requested 5m symbol with no row at
  all while its daily bar exists is a provider omission and returns
  `PAPER_DATA_NOT_READY`. A symbol that produced any 5m row (the 09:30 auction
  print counts) but no continuous session is `halted`, not data-not-ready.
- **5m strategy UNIVERSE is strict.** An order on a position outside the
  declared `UNIVERSE` fails the whole call, so such a position cannot be reduced
  by a 5m strategy step; use the 1d step for that.
- **Matching changes are versioned.** `pt-rules-v5` identifies the opt-in
  per-order volume-share policy. `pt-rules-v4` identifies chronological
  matching across symbols and submission order at shared timestamps.
  `pt-rules-v3` identified the immediate price-limit market cancellation;
  `pt-rules-v2` identified the corrected
  full/partial order statuses and 5m limit-fill rules. Each rule version has a
  different engine fingerprint even with identical bars and model settings;
  archived results retain their original version.

## Data and model limits

Execution requires raw prices. Tencent's unadjusted endpoint serves A-shares/HK;
raw-capable providers such as Sina serve US stocks. These paths are separate
from adjusted backtest feeds. Adjusted/unknown price calibers are rejected.
A-shares also require an available, complete ClickHouse trading calendar;
missing dates return `PAPER_DATA_NOT_READY`, not guessed holidays. ClickHouse
historical bars retain priority on overlapping dates.

Price/volume ratios cannot establish a split. Split-like discontinuities return
`PAPER_DATA_NOT_READY` without multiplying holdings. Other unresolved
discontinuities reject affected orders and disclose the issue. Automatic action
reconciliation and cash dividends are not implemented. NAV is not total return.
A-shares are included in the raw-price discontinuity checks.

Matching is all-or-none by default, with simplified fees, price limits, board
lots and T+1 checks; `fill_model="volume_share"` opts into the per-order partial
fills described above. HK lot fallback is disclosed. Invalid OHLC prevents
fills; valuation uses a finite prior close or the disclosed average-cost
fallback. This is not broker-execution simulation. Settlement, margin, options
and cross-market phases in #1938 remain follow-up work.
