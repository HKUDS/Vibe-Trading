## get_options_chain (agent tool)

----

Tool: `get_options_chain`
Backed by: `src.data_gateway.get_gateway().options_chain` (Cboe delayed snapshots, then the existing Yahoo client)
Description: Read-only agent/CLI tool that returns the US-listed options ladder
(calls and puts) for a single expiration, plus the list of available
expirations. Use it for an options snapshot — strike, bid/ask, last price,
volume, open interest, implied volatility, and the in/out-of-money flag. Use
`offset` to page the complete source expiration when nearby rows are insufficient.

Each side is capped at 60 nearby contracts so a deep chain cannot blow up the model
payload.

<br>
<br>

**Input parameters**

Name | Type | Required | Description
---- | ---- | -------- | -----------
ticker | str | Y | US underlying, `AAPL` or `AAPL.US` (the `.US` suffix is stripped).
expiration | int | N | Expiration as Unix epoch seconds (a value from the returned `expirations`). Omit for the nearest expiration.

<br>
<br>

**Output**

A JSON-string envelope.

On success:

```json
{"ok": true, "market": "us", "source": "yahoo", "data": {...}}
```

`data` fields:

Field | Type | Description
----- | ---- | -----------
ticker | str | Canonical underlying without `.US`.
expiration | int | The returned expiration as Unix epoch seconds.
expirations | list[int] | All available expirations as Unix epoch seconds.
calls_count | int | Number of call rows returned (≤ 60).
puts_count | int | Number of put rows returned (≤ 60).
calls | list[dict] | Call contracts (see fields below).
puts | list[dict] | Put contracts (same shape).

Per-contract fields (snake_case): `contract_symbol`, `strike`, `last_price`,
`bid`, `ask`, `volume`, `open_interest`, `implied_volatility`, `in_the_money`,
`expiration`, `delta` (nullable), `usable_quote`, `multiplier`, `last_trade_time`.

The additive `gateway` object records cache state (`miss`, `fresh`, `stale`),
acquisition time, source timestamp when supplied, quality and source attempts.
A fresh cache is not a live quote. `executable` is always false; missing Delta
is not estimated. Repeated reads share the same gateway as the API and CLI.

`last_trade_time` is the last execution time, **not** the bid/ask quote timestamp.
When `quote_time_known=false`, report quote time as unavailable, including in
any table column labelled quote time. `fetched_at` is gateway retrieval time.
Preserve source timestamp strings without inventing their timezone; an unzoned
Cboe timestamp must not be labelled Eastern/UTC or converted between zones.

On failure:

```json
{"ok": false, "error": "<message>"}
```

Failures are returned as an envelope (never raised) — e.g. a missing/blank
`ticker`, a non-integer `expiration`, or unavailable/malformed source snapshots. Empty chains are failures, not successful data.

<br>
<br>

**Example**

```text
get_options_chain(ticker="AAPL")
get_options_chain(ticker="AAPL.US", expiration=1718236800)
```

<br>
<br>

**Data example**

```json
{
  "ok": true, "market": "us", "source": "yahoo",
  "data": {
    "ticker": "AAPL",
    "expiration": 1718236800,
    "expirations": [1718236800, 1718841600],
    "calls_count": 2, "puts_count": 2,
    "calls": [{"contract_symbol": "AAPL240613C00190000", "strike": 190.0,
               "last_price": 4.05, "bid": 3.95, "ask": 4.10, "volume": 1203,
               "open_interest": 8821, "implied_volatility": 0.224,
               "in_the_money": true, "expiration": 1718236800}],
    "puts": [{"contract_symbol": "AAPL240613P00190000", "strike": 190.0,
              "last_price": 1.85, "bid": 1.80, "ask": 1.90, "volume": 642,
              "open_interest": 5104, "implied_volatility": 0.231,
              "in_the_money": false, "expiration": 1718236800}]
  }
}
```


For full-expiration research, request `offset=0`, then follow `data.next_offset`.
Each page contains up to 60 rows per side in strike order. Verify the acquisition
time remains the same across pages; restart collection if it changes. The
HTTP gateway also offers `GET /data/options?full=true` for a bounded full snapshot.
Continuous subscription events are available at `/data/stream` and through
`python -m src.data_gateway watch options:AAPL`. A continuous subscription to a
delayed source still carries delayed prices.
