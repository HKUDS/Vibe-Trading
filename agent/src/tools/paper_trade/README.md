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

A market order fills at the first continuous bar whose fill gates pass. A
resting limit follows JoinQuant's bar matching: a buy triggers only when
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
a bar's volume. `order_volume_ratio` defaults to `1.0` (no reduction) and is
accepted only with `fill_model="volume_share"`. A market order caps on the full
continuous-session volume, fills what fits and cancels the residual immediately
with `canceled_after_volume_cap`; a limit order caps per bar, keeps the residual
resting while `filled` (active), and its day-end cancel still reports
`canceled_after_failed_match`. A zero-volume bar never fills. Each fill is
booked and charged separately, so a two-fill order pays two minimum
commissions.

A pt-v1.3 result adds `order_states`: one row per submitted order, in
submission order, with exactly `order_id`, `status`, `add_time`, `amount`,
`filled`, `price` and `side`. `add_time` is the cn_a session open
(`YYYY-MM-DDT09:30:00+08:00`), `amount` is the requested quantity, `filled` is
the executed quantity and `price` is `0.0` when nothing filled.

Order statuses use JoinQuant's `OrderStatus` vocabulary for both intervals:
`filled` means partially filled and still active, so the residual stays in
`open_orders()` and can be canceled, settled or matched by a later bar; `held`
means fully filled and terminal. `canceled` and `rejected` are also terminal;
`new`, `open` and `pending_cancel` are not.

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
an order waits while its side is blocked by a price limit. Zero-volume bars
cannot fill. Corporate actions remain fail-closed.

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

### Compatibility and the PR A caveat

The committed v1.1/v1.2 JSON contracts and fixtures are byte-identical, and a
1d call that omits the new fields is byte-identical. PR A intentionally changes
a v1.2 5m resting-limit call: the fill now executes at the 委托价 instead of
the bar reference, so its recorded fill price changes. `engine_fingerprint`
hashes the interval, path model, fill model, rules version and bar fingerprint
(plus `order_volume_ratio` for pt-v1.3), not the matching code, so a fill
recorded before and after PR A can carry the same fingerprint. That is an
accepted provenance gap, not a replay guarantee.

### Parity backlog

Five platform gaps remain, plus one disclosed fee divergence:

1. **Price-limit market-order status.** JoinQuant cancels a market order blocked
   by the daily price limit; this engine rejects it. Aligning the status is a
   separate behavior change.
2. **Slippage.** No spread, market impact, latency or queue-position model; a
   fill uses the bar reference or the 委托价.
3. **Cancel API.** A caller cannot submit a cancel request; cancels are
   engine-driven (day end or volume cap).
4. **Platform-generated order IDs.** IDs are `pt-0`, `pt-1`, ...; JoinQuant uses
   platform order IDs.
5. **`pending_cancel`.** JoinQuant exposes the state between a cancel request
   and its confirmation; this engine never emits or exposes it.

Disclosed fee divergence: the cited PDF charges one commission per completed
order, while this engine books and charges every fill separately, so a two-fill
order pays two minimum commissions. The per-fill charge keeps cash and position
accounting exact and never lets cash go negative.

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
- **The engine fingerprint does not cover the matching rule.** A pt-v1.2
  `engine_fingerprint` hashes the interval, path model, fill model, rules
  version and bar fingerprint; a pt-v1.3 fingerprint also covers
  `order_volume_ratio`, but neither covers the matching code. The resting-limit
  fill-price rule changed here without a `RULES_VERSION` bump, so a 5m limit
  fill recorded before and after the change can carry the same fingerprint.
  Treat the fingerprint as provenance for its declared tuple, not as proof that
  two engines produced identical fills.

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
