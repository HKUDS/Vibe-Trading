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
one completed session and matches against that session's single assembled bar,
built from the 48 continuous five-minute bars. The 09:30 opening-auction print is
excluded, as is any label inside 09:15-09:25 or 14:57-15:00; an excluded auction
label is reported as an `auction_window` event. A symbol with no continuous bar
on a calendar-open day is `halted` (its position is valued carry-forward), and an
order on it is rejected `suspended` with one `canceled_after_failed_match` row.

| Field | Values | Default | Meaning |
| --- | --- | --- | --- |
| `interval` | `1d`, `5m` | `1d` | `5m` is cn_a-only and accepts one date per step |
| `session` | `auto`, `cn_a` | `auto` | `cn_a` requires `market="cn_a"` |
| `path_model` | `bar_median`, `bar_close` | `bar_median` | reference price from the session bar |
| `fill_model` | `all_or_none` | `all_or_none` | no partial fills |

The 5m leg uses Tushare `stk_mins` and is resolved separately from the daily
chain: Tencent's raw loader serves daily bars only. The measured provider limit
is one symbol per step (2 calls/day, 1/minute), so a 5m step with two order
symbols is refused; split the orders across steps or use `interval="1d"`. Orders
mode derives the 5m universe from the order symbols; strategy mode requires a
non-empty `UNIVERSE` and refuses any order outside it. When no 5m-capable loader
is configured, the step returns `PAPER_DATA_NOT_READY` naming the loader instead
of reading the daily source as a 5m source.

The daily close still anchors price-limit bands and NAV; `path_model` selects the
5m fill reference only. Corporate actions remain fail-closed.

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

Matching is all-or-none, with simplified fees, price limits, board lots and T+1
checks. HK lot fallback is disclosed. Invalid OHLC prevents fills; valuation
uses a finite prior close or the disclosed average-cost fallback. This is not
broker-execution simulation. Settlement, margin, options and cross-market phases
in #1938 remain follow-up work, as does the intraday order lifecycle (partial
fills, resting orders across bars).
