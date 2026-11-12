# OpenAlgo read-only boundary

[OpenAlgo](https://github.com/marketcalls/openalgo) is a self-hosted server that
puts one REST API in front of the Indian broker account it is logged in to. This
connector talks to that server, not to a broker directly. It sends only `POST`
requests to a fixed set of read endpoints under `/api/v1/`: `ping`, `analyzer`
(status only), `funds`, `positionbook`, `holdings`, `orderbook`, `tradebook`,
`quotes` and `history`. Every order endpoint and `analyzer/toggle` are outside
that set. Both order entry points refuse before any network call, and the curated
classification map pins them as writes.

## Why there are no writes, paper included

OpenAlgo's analyzer mode is a sandbox that simulates fills, and the server reports
it. It is not a safe paper boundary for this connector: the mode is application
wide, any client or the web UI can change it, and the placement and cancellation
services read it again while handling the write. A status check made before an
order therefore cannot guarantee where the order goes. Remote paper execution
would need a server-enforced sandbox-only credential or endpoint, or an atomic
expected-mode condition that rejects before broker dispatch. Neither exists at the
pinned version, so the profile is read-only.

## Provenance

In analyzer mode OpenAlgo answers account reads from its sandbox and adds
`"mode": "analyze"` to each response; live broker responses have no `mode` key.
Each returned book carries `openalgo_mode` (`analyze` or `live`) and `provenance`
(`analyzer_sandbox` or `live_broker`) taken from the response that produced it. A
read that combines two books (net positions with holdings, orders with trades)
fails instead of mixing a sandbox book with a live one. Any other `mode` value
fails closed. Quotes and history always come from the broker's market data and are
labelled `source: broker_market_data`. The connection test also reports the
server's `analyze_mode` from `POST /api/v1/analyzer`.

## Valuation limits

Holdings and net positions remain separate books: a delivery position can appear
in both, and their overlap is not inferred. Funds are margin limits, not cash or
net liquidation. The profile therefore withholds `account.read` and is not
eligible for portfolio aggregation, as with mStock. Funds remain inspectable
through `trading_account` or
`vibe-trading connector account openalgo-live-rest-readonly --connection-id <id>`.

## Pinned contract

OpenAlgo 2.0.3.3, upstream commit
[`7ba5267f`](https://github.com/marketcalls/openalgo/tree/7ba5267f7d5d15c352606b3aea6b12ab20223428)
(`restx_api/`, `services/`, `sandbox/` and `docs/api/`). OpenAlgo does not report
its version over the API, so this is a documented contract, not a runtime check.
Responses also carry `openalgo_contract` with this pin.

## Field mapping and units

Numbers may arrive as JSON numbers or numeric strings; both are parsed. A missing
or non-numeric value becomes `null`, never zero. Unmapped keys are kept under
`extra` on the row. Prices and P&L on NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX,
NCO and the Indian index exchanges are rupees (`currency: "INR"`); `GLOBAL_INDEX`
and `CRYPTO` rows carry `currency: null` because OpenAlgo reports no currency.
Quantities are units (shares or contract units), not lots.

| OpenAlgo endpoint and field | Connector field | Unit / notes |
| --- | --- | --- |
| `funds.availablecash` | `funds.available_cash` | account currency, margin limit |
| `funds.collateral` | `funds.collateral` | account currency |
| `funds.m2mrealized` / `m2munrealized` | `funds.realized_mtm` / `unrealized_mtm` | account currency, today |
| `funds.utiliseddebits` | `funds.utilised_debits` | account currency |
| `positionbook[].quantity` | `net_positions[].quantity` | signed units; 0 is a closed position |
| `positionbook[].average_price`, `ltp` | `average_price`, `ltp` | price per unit |
| `positionbook[].pnl` | `pnl` | currency; broker-normalized, can include realized day P&L |
| `positionbook[].average_price_basis` | `average_price_basis` | present when `average_price` is not entry cost |
| `holdings.holdings[].quantity` | `holdings[].quantity` | units |
| `holdings.holdings[].pnl`, `pnlpercent` | `pnl`, `pnl_percent` | currency; percent |
| `holdings.statistics.*` | `holdings_statistics.total_holding_value`, `total_investment_value`, `total_pnl`, `total_pnl_percent` | currency; percent |
| `orderbook.orders[].orderid`, `action`, `pricetype`, `order_status` | `order_id`, `side` (lower case), `order_type`, `status` | `open_orders` keeps `open`, `pending` and `trigger pending` |
| `orderbook.orders[].price`, `trigger_price`, `quantity` | same names | price per unit; units |
| `orderbook.orders[].timestamp` | `timestamp` | broker string, IST; format varies by broker |
| `tradebook[].average_price`, `trade_value`, `tradeid` | `average_price`, `trade_value`, `trade_id` | price per unit; currency; `trade_id` only when the broker supplies it |
| `quotes.ltp`, `open`, `high`, `low`, `prev_close`, `bid`, `ask` | `quote.*` | price per unit; a missing or zero `ltp` is an error |
| `quotes.volume`, `oi` | `quote.volume`, `quote.oi` | units |
| `history[].timestamp` | `bars[].time` | epoch seconds; daily-bar alignment is defined by the broker adapter |
| `history[].volume`, `oi` | `bars[].volume`, `bars[].oi` | units |

`get_quote` and `get_historical_bars` take `EXCHANGE:SYMBOL` in OpenAlgo symbol
format (for example `NSE:RELIANCE` or `NFO:NIFTY25NOV2624000CE`); a bare symbol
is read on NSE. History supports the intervals OpenAlgo documents for every
broker: `1m`, `3m`, `5m`, `10m`, `15m`, `30m`, `1h` and `1d`.

## Errors

HTTP 403 (invalid API key), 429 (OpenAlgo or broker rate limit), any other
non-200 status, a redirect, a non-JSON body, `status` other than `success` and
an unexpected `data` shape all fail with a fixed message. Response bodies and
exception text are never echoed, because the request body carries the API key.

## Transport security

The API key authorizes orders on the OpenAlgo server, so plain `http` is accepted
only for a loopback host (`localhost`, `127.0.0.0/8`, `::1`). Any other host must
use `https`. URLs with user info, a query or a fragment are rejected. Redirects are
not followed.

## Verification

Tests replay redacted fixtures (`agent/tests/fixtures/openalgo/`) built from the
pinned documentation samples and sandbox source through the real HTTP client.
They were not captured from a real broker account, and no live or analyzer-mode
OpenAlgo server was contacted.
