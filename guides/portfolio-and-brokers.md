# Portfolio and broker connections

### Import an extraETF holdings export

Open **Portfolio → Manage accounts → Import extraETF Investments**, choose the official Investments CSV, confirm the number of holdings in extraETF, and choose the maximum file age you accept. Add the imported source, save, and refresh. Transactions, dividends and X-Ray exports are not holdings and are refused. Imports are local file evidence, separate from broker connections; no extraETF login or browser scraping is used.

```bash
vibe-trading portfolio import-extraetf ~/Downloads/Investments.csv \
  --label "extraETF export" --expected-positions 27 --max-age-days 7 --select
vibe-trading portfolio refresh
vibe-trading portfolio show
```

The row count and age above are examples to replace with your own. The entire import fails on an unreadable row, count mismatch, missing price, future file time or expired freshness policy. File mtime is labelled as file mtime, never as a price observation; copying a file can change it. `Portfolio ID` keeps accounts separate even when they hold the same ISIN. Imported totals are quantity × exported price and **exclude cash and other assets absent from the export**. Select disjoint sources: an extraETF view can include accounts already selected through broker connections.

USD, CNY, HKD and EUR display values use [Frankfurter reference rates](https://frankfurter.dev/) with the rate date separate from fetch time; they are not intraday quotes. An unavailable currency fails valuation. Cached rates are labelled stale and cannot produce a rebalancing proposal. An ISIN identifies a security but not its trading venue: imported holdings remain excluded from historical risk-series tools until that identity is resolved.

**Allocation proposal** accepts user-defined percentages totalling 100% and shows value changes for review. It creates no orders, quantities, taxes or fee estimates. The same operation is available through `POST /api/portfolio/rebalance`, `portfolio_summary(snapshot_id=..., target_weights=...)`, or:

```bash
# targets.json maps the snapshot's holdings canonical_id (or CASH) to fractions.
vibe-trading portfolio rebalance --snapshot-id <snapshot-id> --targets targets.json
```

### Portfolio connector compatibility

| Badge | Meaning |
|-------|---------|
| **Native adapter** | Dedicated portfolio normalization and valuation behavior exists for the connector. |
| **Contract-tested** | Recorded connector-shaped fixtures pass the common account/position contract, but this is not a promise that every broker account variant has been live-tested. |
| **Experimental** | The profile is structurally read-only and can be selected, but its currencies, account totals, or instrument semantics still need broker-specific verification. |

Every position row must provide a symbol and quantity. Portfolio can display totals in USD, HKD, CNY or EUR when the required FX rate is available. An unsupported position currency fails the source. IBKR, Longbridge and Binance have native adapters. Alpaca and OKX have common-contract coverage. OKX includes spot balances alongside open positions.

For Robinhood, pick an account from the broker's list with `vibe-trading connector select-account <id>` or the connection center. Each eligible equity position uses the more recent regular-hours or extended-hours trade and shows its quote time. An unusable quote leaves the row unpriced. Accounts with non-zero or unreported options, crypto, futures, event-contract, mutual-fund or fixed-income values fail the source because an equity-only view would be incomplete.

### AI-friendly connector onboarding

Built-in SDK connectors publish one machine-readable onboarding contract: authentication type, required credential fields, optional dependency, install command, and the read-only operation used for verification. `trading_connections` exposes the same contract to MCP clients, while the Portfolio connection center renders it as a generic form. The contract contains field names only — never credential values.

For a terminal-first setup, let the CLI collect secrets locally instead of putting them in a prompt or shell arguments:

```bash
vibe-trading connector setup okx-live-sdk-readonly \
  --connection-id main-okx \
  --label "Main OKX"
```

The CLI prompts in the local terminal, stores values under that connection id in the OS keyring, and runs the connector's read-only check. The equivalent Web flow is **Portfolio → Manage accounts → Open connection center → choose a template → save to keyring → test connection**. MCP read tools may use `connection_id`; the process resolves its credentials from the vault, so keys never travel through MCP. Existing `~/.vibe-trading/<connector>.json` and environment configurations remain a compatibility fallback until a connection has a complete vault credential set.

For local IBKR and Futu connections, edit **Host / Port** in that connection's
card, then click **Test** to save the address and check it. The CLI equivalent
uses the same saved endpoint:

```bash
vibe-trading connector setup ibkr-paper-local --connection-id my-gateway --host 127.0.0.1 --port 4002 --skip-check
```

The address is scoped to that connection and is also used by agent reads with
its `connection_id`.

Do not paste broker API keys into an AI chat. Let the AI choose the connector, install the declared dependency, and interpret diagnostics; enter secrets only in the local hidden terminal prompt or local connection form.

## Full broker permissions

<!-- BEGIN GENERATED broker-capability-matrix -->

Declared built-in profiles, generated from `agent/src/trading/profiles.py`.
Each row keeps its own environment and permissions; a paper order capability
never grants live trading. These are declarations, not successful runtime or
broker verification. Local plugins and user connection settings are excluded.

The quote column shows the declared transport, not a verified endpoint or
pricing coverage. Order kinds (market, limit, etc.) are not declared in the
registry and are therefore not inferred here. The placement column reports
the declared mandate requirement only; it does not attest to cancellation,
flattening, copy-trading, or other runtime guard coverage. Paper placement can
use a broker sandbox or local simulation. See each profile's notes and the
[broker bring-up checklist](../CONTRIBUTING.md#broker-bring-up-checklist).

| Profile | Connector | Environment | Transport | Mode | Read capabilities | Quote path (declared) | Other capabilities | Placement requirement (declared) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `alpaca-live-sdk-readonly` | alpaca | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `alpaca-live-trade` | alpaca | live | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place.requires_mandate` | mandate required |
| `alpaca-paper-sdk` | alpaca | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `alpaca-paper-trade` | alpaca | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `binance-live-sdk-readonly` | binance | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `binance-live-trade` | binance | live | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place.requires_mandate` | mandate required |
| `binance-paper-sdk` | binance | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `binance-paper-trade` | binance | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `dhan-live-sdk-readonly` | dhan | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `dhan-paper-sdk` | dhan | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `dhan-paper-trade` | dhan | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `etoro-live-sdk-readonly` | etoro | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `etoro-live-trade` | etoro | live | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `copy.close`, `copy.poll`, `copy.precheck`, `copy.start`, `orders.cancel`, `orders.cancel_close`, `orders.place.requires_mandate`, `positions.close`, `positions.edit` | mandate required |
| `etoro-paper-sdk` | etoro | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `etoro-paper-trade` | etoro | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.cancel`, `orders.cancel_close`, `orders.place`, `positions.close`, `positions.edit` | no mandate declared |
| `futu-live-sdk-readonly` | futu | live | broker_sdk | read-only | `acc_cash_flow.read`, `account.read`, `capital_distribution.read`, `capital_flow.read`, `earnings_calendar.read`, `financials.read`, `history.read`, `history_deals.read`, `orders.read`, `positions.read`, `quotes.read`, `rehab.read` | broker_sdk | none declared | disabled (read-only) |
| `futu-live-trade` | futu | live | broker_sdk | write-enabled | `acc_cash_flow.read`, `account.read`, `capital_distribution.read`, `capital_flow.read`, `earnings_calendar.read`, `financials.read`, `history.read`, `history_deals.read`, `orders.read`, `positions.read`, `quotes.read`, `rehab.read` | broker_sdk | `orders.place.requires_mandate` | mandate required |
| `futu-paper-sdk` | futu | paper | broker_sdk | read-only | `acc_cash_flow.read`, `account.read`, `capital_distribution.read`, `capital_flow.read`, `earnings_calendar.read`, `financials.read`, `history.read`, `history_deals.read`, `orders.read`, `positions.read`, `quotes.read`, `rehab.read` | broker_sdk | none declared | disabled (read-only) |
| `futu-paper-trade` | futu | paper | broker_sdk | write-enabled | `acc_cash_flow.read`, `account.read`, `capital_distribution.read`, `capital_flow.read`, `earnings_calendar.read`, `financials.read`, `history.read`, `history_deals.read`, `orders.read`, `positions.read`, `quotes.read`, `rehab.read` | broker_sdk | `orders.place` | no mandate declared |
| `ibkr-live-local-readonly` | ibkr | live | local_tws | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | local_tws | none declared | disabled (read-only) |
| `ibkr-live-official-mcp-readonly` | ibkr | live | remote_mcp | read-only | `account.read`, `positions.read` | none declared | none declared | disabled (read-only) |
| `ibkr-paper-local` | ibkr | paper | local_tws | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | local_tws | none declared | disabled (read-only) |
| `kis-live-sdk-readonly` | kis | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `kis-paper-sdk` | kis | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `kis-paper-trade` | kis | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `longbridge-live-sdk-readonly` | longbridge | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `longbridge-paper-sdk` | longbridge | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `longbridge-paper-trade` | longbridge | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `mstock-live-rest-readonly` | mstock | live | broker_sdk | read-only | `positions.read` | none declared | none declared | disabled (read-only) |
| `mt5-live-sdk-readonly` | mt5 | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `mt5-live-trade` | mt5 | live | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place.requires_mandate` | mandate required |
| `mt5-paper-sdk` | mt5 | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `mt5-paper-trade` | mt5 | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `okx-live-sdk-readonly` | okx | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `okx-live-trade` | okx | live | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place.requires_mandate` | mandate required |
| `okx-paper-sdk` | okx | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `okx-paper-trade` | okx | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `robinhood-live-mcp` | robinhood | live | remote_mcp | write-enabled | `account.read`, `orders.read`, `positions.read`, `quotes.read` | remote_mcp | `orders.place.requires_mandate`, `runner.manage.requires_mandate` | mandate required |
| `robinhood-live-mcp-readonly` | robinhood | live | remote_mcp | read-only | `account.read`, `positions.read`, `quotes.read` | remote_mcp | none declared | disabled (read-only) |
| `scalable-live-mcp-readonly` | scalable | live | remote_mcp | read-only | `quotes.read` | remote_mcp | none declared | disabled (read-only) |
| `shoonya-live-sdk-readonly` | shoonya | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `shoonya-paper-sdk` | shoonya | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `shoonya-paper-trade` | shoonya | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `tiger-live-sdk-readonly` | tiger | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `tiger-live-trade` | tiger | live | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place.requires_mandate` | mandate required |
| `tiger-paper-sdk` | tiger | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `tiger-paper-trade` | tiger | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `toss-live-sdk-readonly` | toss | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `trading212-live-sdk-readonly` | trading212 | live | broker_sdk | read-only | `account.read`, `instruments.read`, `order_history.read`, `orders.read`, `positions.read` | none declared | none declared | disabled (read-only) |
| `trading212-paper-sdk` | trading212 | paper | broker_sdk | read-only | `account.read`, `instruments.read`, `order_history.read`, `orders.read`, `positions.read` | none declared | none declared | disabled (read-only) |
| `upbit-live-sdk-readonly` | upbit | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `upbit-paper-sdk` | upbit | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `upbit-paper-trade` | upbit | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |
| `zerodha-live-sdk-readonly` | zerodha | live | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `zerodha-paper-sdk` | zerodha | paper | broker_sdk | read-only | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | none declared | disabled (read-only) |
| `zerodha-paper-trade` | zerodha | paper | broker_sdk | write-enabled | `account.read`, `history.read`, `orders.read`, `positions.read`, `quotes.read` | broker_sdk | `orders.place` | no mandate declared |

<!-- END GENERATED broker-capability-matrix -->

Read-only connectors you install yourself stay outside the checkout, in `~/.vibe-trading/connectors/<name>/`: a `connector.json` manifest plus an `adapter.py` implementing `check_status` / `get_account_snapshot` / `get_positions`. A manifest declaring any write capability is rejected.

```bash
vibe-trading connector init my-broker --destination /tmp
vibe-trading connector validate /tmp/my-broker
vibe-trading connector install /tmp/my-broker
```

Their credentials go to the OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service) with `pip install "vibe-trading-ai[keyring]"`, never into the config files. Nothing on this path can place or cancel an order.

### MetaTrader 5 (Exness and other MT5 brokers)

Connects to a **locally running MT5 terminal** through the official `MetaTrader5` package (**Windows only**):

```bash
pip install "vibe-trading-ai[mt5]"
```

Configure `~/.vibe-trading/mt5.json` (create it yourself; `chmod 600` where supported):

```json
{
  "login": 12345678,
  "password": "...",
  "server": "Exness-MT5Trial8",
  "symbol_suffix": "m",
  "max_order_volume": 1.0,
  "max_order_notional_usd": 10000
}
```

For broker-confirmed `search_symbol` results, set `terminal_path` in this file
to the selected terminal executable. Symbol search reads only `symbol_info`
and `symbols_get`, passes no login credentials, and does not read account or
position data or alter Market Watch. Without an explicit path it returns no
MT5 candidate.

If several broker aliases match, specify the exact native symbol (for example,
`EURUSDm`) or configure `symbol_suffix`; search never chooses an alias arbitrarily
or substitutes a web-search result. Backtest sandboxes receive only a validated
`terminal_path` and positive finite `timeout`, not account credentials.

Then:

```bash
vibe-trading connector use mt5-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector quote EURUSD
vibe-trading connector history EURUSD
```

| Profile | Account | Orders |
|---------|---------|--------|
| `mt5-paper-sdk` | demo | read-only |
| `mt5-live-sdk-readonly` | real | read-only |
| `mt5-paper-trade` | demo | direct placement (connector per-order size guards apply) |
| `mt5-live-trade` | real | mandate + kill-switch gated |

Safety boundary: **"paper" means the broker's own demo account**, re-verified on every call — the terminal reports `account_info().trade_mode` and the logged-in account number, so pointing a paper profile at a real-money account (or the reverse) is refused outright. MT5 sizes orders in **lots** (1 lot EURUSD = 100,000 EUR); the live mandate gate prices lots through the connector's USD hook, and the connector's own `max_order_volume` / `max_order_notional_usd` guards apply on demo as well as live, failing closed when a notional cannot be priced. On hedging accounts (the Exness default), note that an opposing order **opens a hedge position** — close by ticket instead (pass the position ticket to `trading_cancel_order`) so the fill is pinned to that position and can only reduce exposure. Rollback / halt path: the kill switch blocks new live orders, while cancellation stays available and is written to the audit log. Mandate limits are denominated in USD; a non-USD account currency is margined by the broker in its own currency.

The `mt5` market-data loader — the head of the forex fallback chain — shares this same `mt5.json`. With no such file it attaches read-only to the most recently used terminal that is already logged in.

---

## 🔌 eToro Public API Connector

Connects to [eToro's Public API](https://builders.etoro.com/) for demo and real accounts via API key pair (`x-api-key` + `x-user-key`). Demo and real environments are separated structurally: demo keys only reach `/demo` API paths.

Configure `~/.vibe-trading/etoro.json` (create it yourself; `chmod 600` where supported):

```json
{
  "api_key": "YOUR_PUBLIC_API_KEY",
  "user_key": "YOUR_USER_KEY",
  "profile": "paper"
}
```

Alternatively set `ETORO_API_KEY` and `ETORO_USER_KEY` in `~/.vibe-trading/.env`.

Then:

```bash
vibe-trading connector use etoro-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector quote BTC
```

| Profile | Account | Orders |
|---------|---------|--------|
| `etoro-paper-sdk` | demo | read-only |
| `etoro-live-sdk-readonly` | real | read-only |
| `etoro-paper-trade` | demo | direct placement on demo paths |
| `etoro-live-trade` | real | mandate + kill-switch gated |

Symbol lookup uses eToro's `internalSymbolFull` search (e.g. `BTC` → instrument id `100000`). Use the `etoro_search_instruments` agent tool to resolve tickers before trading.

Safety boundary: demo and real are path-separated and key-bound (`paper_guard: path_separated_key_bound`). Live risk-increasing actions (open and copy-start/increase) require an authorized mandate, a clear halt state, and a verified USD account for copy-notional enforcement. Validated full and partial position closes, open-order cancellation, and copy close remain available when halted and are audit-logged. Cancelling a pending close or editing position stops is paper-only: the live path fails closed because those operations can increase exposure or transfer extra margin without enough API data to quantify the incremental USD risk. Copy amounts are denominated in the eToro account currency, and every copy start/adjust requires a caller-supplied 1-35 character URL-safe reference id for polling. eToro-specific write tools (`etoro_close_position`, `etoro_copy_*`, etc.) are agent tools only — not exposed via MCP or CLI. Rollback: revert the connector commit(s) or disable profiles; halt blocks new live risk-increasing actions.

### Trading connectors: fastest path

For users who cannot wait for IBKR OAuth client approval, connect to a local
TWS or IB Gateway session. Credentials stay inside IBKR's desktop app; Vibe-
Trading only connects to `127.0.0.1` and exposes it as a connector profile.

Install the optional SDK:

```bash
pip install "vibe-trading-ai[ibkr]"
```

Open TWS paper trading or IB Gateway paper, enable API socket clients, then run:

```bash
vibe-trading connector list
vibe-trading connector use ibkr-paper-local
vibe-trading connector configure ibkr-paper-local --yes
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector orders
vibe-trading connector quote AAPL
vibe-trading connector history AAPL --duration "30 D" --bar-size "1 day"
```

Default local ports:

| App | Paper | Live read-only |
|-----|-------|----------------|
| TWS | `7497` | `7496` |
| IB Gateway | `4002` | `4001` |

The agent exposes connector-scoped tools named `trading_connections`,
`trading_select_connection`, `trading_check`, `trading_account`,
`trading_positions`, `trading_orders`, `trading_quote`, and `trading_history`.
Live-broker raw MCP tools are not registered directly as `mcp_<broker>_*`.
No IBKR order-placement tool is registered.

### Live runner model spending

Model calls are billed even when a mandate permits only one trade or the agent
places no orders. The runner checks safety every minute, but defaults to a model
decision every **15 minutes**, at most **26 decisions / 1,000,000 reported tokens
per UTC day**. Each decision starts a fresh conversation and reconstructs broker
state under the existing mandate gate.

Configure cadence, a once-daily wall-clock time/timezone, and daily budgets in
**Runtime → Model schedule and spending limits**, or the chat runner panel.
Stop the runner before editing. The CLI uses the same authenticated API:

```bash
vibe-trading connector runner-settings --profile robinhood-live-mcp
vibe-trading connector runner-settings --profile robinhood-live-mcp --file runner-settings.json
```

The JSON accepts `interval_seconds`, optional `daily_at` (`HH:MM`) and `timezone`
(IANA, default `America/New_York`), `max_daily_turns`, `max_daily_tokens`, and
optional `max_daily_cost_usd`, `input_usd_per_million`, `output_usd_per_million`.
Both prices are required for a dollar limit. Use the highest applicable input or
cache-write price; estimates ignore cache discounts and auxiliary model calls.
Daily projections need measured usage and configured prices; unknown costs stay
unknown. The same settings are exposed by `GET` / `PUT /live/runner/settings?broker=robinhood`.

Spending history survives restarts. Limits are checked **after each provider
response**, so a response can overshoot a token or estimated-dollar budget.
Exhaustion or missing usage trips the existing kill switch and cancels the active
decision before its tool calls. Existing halt/cancel/flatten behavior applies;
inspect the broker and usage before resuming. An unfinished decision after a
crash is blocked for inspection, never silently counted as free.

### 🔐 TAP Mode — full credential isolation & human-approved writes

**Opt-in, off by default.** If the `TAP_*` variables below are unset, the
connector behaves exactly as before (direct broker SDK) — nothing changes.

[TAP](https://tap.human.tech) (Tool Authorization Protocol) is a credential
proxy: the agent never holds the raw broker API secret, and consequential writes
are gated on **human approval**. With TAP mode on, **every** Alpaca call — order
placement, cancel, and the reads (account/positions/orders/quote/bars) — is sent
to the TAP proxy's `/forward` endpoint instead of the broker SDK; TAP injects the
real key server-side, then forwards upstream.

- The agent process holds **no Alpaca key at all** — and doesn't even need
  `alpaca-py` — because the whole egress goes through TAP. The secret is
  referenced by name (`<CREDENTIAL:alpaca.key_id>`) and TAP substitutes it.
- **Writes block on human approval.** An order or cancel cannot reach the broker
  without a human approving it; even a prompt-injected "buy now" is held, and
  denying it means it never reaches Alpaca. Orders carry a deterministic
  `client_order_id`, so an approval-race retry is deduplicated rather than
  double-placed.
- **Reads auto-approve.** Account/positions/orders/quote/bars are GETs that TAP
  forwards without a human step — this is credential *isolation* (no key in the
  process), not a gate, so there's ~zero added friction.
- `allowed_hosts` on the TAP credential pins where the key may be sent, so a
  tampered target is rejected (403) before injection.

**Enable it:**

1. In the TAP dashboard, create a **multi-secret** credential named `alpaca`
   holding your Alpaca key pair as fields `key_id` and `secret_key`, assigned to
   your agent, with allowed hosts `paper-api.alpaca.markets` (or the live host
   `api.alpaca.markets`) **and** `data.alpaca.markets` (the market-data host used
   by quote/bars). Use **separate TAP credentials for paper and live** (e.g.
   `alpaca-paper` / `alpaca-live`, selected via `TAP_ALPACA_CREDENTIAL`), each
   with `allowed_hosts` pinned to its own API host — TAP then structurally
   refuses to send the paper key to the live host and vice versa, keeping the
   paper/live separation crisp end to end.
2. Add to `agent/.env`:

| Variable | Required | Description |
|----------|:--------:|-------------|
| `TAP_PROXY_URL` | Yes | TAP proxy base URL (e.g. `https://proxy.tap.human.tech`) |
| `TAP_AGENT_KEY` | Yes | Your TAP agent API key (secret) |
| `TAP_ALPACA_CREDENTIAL` | No | TAP credential name for Alpaca (default `alpaca`) |
| `TAP_APPROVAL_TIMEOUT` | No | Seconds to wait for a human decision (default `300`) |

When a write is placed, approve or deny it in your TAP channel (Telegram /
dashboard). An approved order/cancel is forwarded to Alpaca; a denied or
timed-out one returns an error and is **never sent**.

> **Known limitation — approval race.** If the human approves right at the
> `TAP_APPROVAL_TIMEOUT` boundary, TAP may forward the order while the poll has
> already given up: the gate then reports an error even though the order reached
> the broker, and the `max_trades_per_day` counter under-counts by one. The
> deterministic `client_order_id` keeps a retry from double-placing that order;
> if you rely on a tight trades-per-day cap, check open orders after a TAP
> timeout error before retrying.

**Scope:** covers Alpaca **order placement, cancel, and all five reads** — the
full connector egress, so the process holds no key on any path. HMAC-signed
brokers (Binance/OKX) are follow-ups (client-side signing doesn't fit pure egress
injection). The hooks are additive — they live inside the Alpaca connector and
leave the live mandate gate unchanged.
