# Hong Kong quote data

This package supplies current quote snapshots to Vibe Trading and optionally
records them in SQLite. Each installation makes its own provider requests.
The contribution consists of the fetcher, collector, tool integration and tests;
it does not depend on a contributor's CSV archive or computer staying online.

## Start from a checkout

Install the project as described in the repository README, then run:

```bash
python -m src.hk_data --once
python -m src.hk_data --symbols 0700.HK 0005.HK 1299.HK 0941.HK 0388.HK
python -m src.hk_data --latest
```

The first command records one poll and exits. The second polls every 60 seconds
until interrupted; restarting resumes the same database. The third reads the
most recent stored quotes and poll health without requesting the providers.
From an uninstalled checkout, run these commands inside `agent/` instead.

`--symbols-file` accepts a newline-separated list or a CSV with `ticker`,
`yahoo_ticker` or `symbol` column. That supports any selected Hong Kong stocks,
including a current HSI roster, without hardcoding index constituents into the
provider. A maximum of 100 symbols is accepted per collector process.
Aliases such as `700`, `0700.HK`, `00700.HK` and `HK.00700` normalize to
`00700.HK`. Genuine five-digit currency counters remain distinct.

```bash
python -m src.hk_data --symbols-file hk_symbols.csv --interval-seconds 60
python -m src.hk_data --source tencent --once
python -m src.hk_data --cycles 3 --db ./data/hk_quotes.sqlite3
```

## Providers and delay

- `auto`: Yahoo, then Tencent for unavailable or stale symbols. The newer
  valid provider timestamp wins for those fallback symbols.
- `yahoo`: raw regular-market quote metadata from the chart endpoint.
  [Yahoo lists a 15-minute delay for HKEX equities](https://help.yahoo.com/kb/finance/article-exchanges-data-delays-sln2310.html).
  A one-minute polling interval does not remove this delay.
- `tencent`: uses the faster `r_hk` public batch endpoint. The older `hk`
  endpoint was about 15 minutes delayed. A 10-minute test on November 12, 2026
  returned all 95 HSI stocks on all 120 polls: median last-trade age 10.6 seconds,
  p95 86.6 seconds, 90.9% under one minute. This is observed timestamp age,
  not a provider latency guarantee. Quiet stocks can have older last trades.
  Cumulative volume is retained with its unit unverified.
  To use it, explicitly select `--source tencent --interval-seconds 5`.
- `futu`: explicit quote-only access to an already running FutuOpenD at
  `127.0.0.1:11111`. Install `futu-api` separately and obtain the appropriate
  Hong Kong quote entitlement. This module never opens a trade context or
  starts a broker login. The SDK runs in a subprocess with a 20-second timeout.
  [Futu snapshots](https://openapi.futunn.com/futu-api-doc/en/quote/get-market-snapshot.html)
  are requested in batches of 20. Delay stays unknown because snapshot success
  alone does not establish the account's real-time rights.

Explicit sources never switch to another provider. Public provider availability
is best effort; HTTP errors and incomplete data produce per-symbol failures.
Use licensed [HKEX data services](https://www.hkex.com.hk/Services/Market-Data-Services/Real-Time-Data-Services/Overview?sc_lang=en)
or an entitled broker quote feed when verified exchange real-time data is needed.
Review the providers' data-use terms before redistributing data publicly.

## Use from Vibe Trading

The research agent discovers `get_hk_quotes` automatically; the MCP server
exposes the same tool. Example tool arguments:

```json
{"symbols": ["0700.HK", "0005.HK"], "source": "auto", "max_age_seconds": 1200}
```

Equivalent Python call:

```python
from src.hk_data.service import fetch_quotes

result = fetch_quotes(["0700.HK", "0005.HK"], source="auto")
for quote in result["quotes"]:
    print(quote["symbol"], quote["price"], quote["currency"],
          quote["provider_time"], quote["age_seconds"], quote["delay_status"])
```

The quote tool fetches on demand. It does not require the collector. The
collector is for building a local history and for external consumers that read
SQLite. Historical `get_market_data` OHLCV loading is a separate interface.
These snapshots are not complete trade ticks, order books, adjusted historical
bars or guaranteed execution prices.

Yahoo requests share the existing per-host throttle. Fetching a broad universe
can take more than a minute; the interval is a minimum target rather than a
guarantee for every symbol. Three consecutive Yahoo HTTP failures skip its
remaining symbols for that poll, allowing the fallback to run promptly.
Tencent requests the symbols in one batch.

## Timestamp and currency contract

Each quote carries `provider_time` and `observed_at_utc` separately, in UTC.
`price` is raw and belongs to `provider_time`; a fresh retrieval never changes
that time. `age_seconds` is recomputed from the provider timestamp.
`status=fresh` only means the age is within `max_age_seconds` (default 1200).
It does not mean zero delay. Known delay is in `declared_delay_seconds`; unknown
delay remains null, never zero. Invalid prices, missing timestamps and future
timestamps are rejected rather than replaced with invented values.

Yahoo supplies the quote currency. Tencent and Futu use the repository's shared
HKEX counter-currency mapping, preserving CNY and USD counters rather than
assuming every Hong Kong counter trades in HKD. Available volume uses shares
and is session cumulative; do not sum repeated snapshots into trading volume.

Yahoo's `session_state=regular_window` describes the provider's broad daily
regular-market window. It does not implement a holiday calendar or exclude the
lunch break. Other providers may report `unknown`. Quote age remains the
freshness control after the close, during holidays and when feeds stall.

## Storage and operation

The default store is `~/.vibe-trading/data/hk_quotes.sqlite3`, resolved through
the project's runtime-root helper. `VIBE_TRADING_HOME` relocates runtime state;
`--db` selects an explicit database. Runtime databases belong outside Git.

The collector persists quote revisions and poll health. Identical snapshots
are deduplicated across process restarts, while price/volume corrections at the
same provider timestamp are retained. A latest read reports cached data age
and the latest poll result separately, so a failed poll cannot make an older
quote appear newly live. SQLite WAL allows readers while the collector writes.

The store retains 30 days by default. `--retain-days 0` keeps all history and
allows growth over time. A finite retention removes older records and reuses
pages; polling does not produce one giant CSV. For historical experiments,
back up the database or choose an explicit archival policy before pruning.

`Ctrl-C` stops collection. Provider outages are logged and retried with bounded
backoff. The process must remain running to collect data. A service supervisor
can restart it after crashes or machine restarts. For example, adapt this Linux
systemd unit to the installation paths and an existing unprivileged user:

```ini
[Unit]
Description=Vibe Trading Hong Kong quote collector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vibetrading
Environment=VIBE_TRADING_HOME=/var/lib/vibe-trading
ExecStart=/opt/vibe-trading/.venv/bin/python -m src.hk_data --source auto --symbols-file /etc/vibe-trading/hk-symbols.txt
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Create the runtime directory with permissions for that user before enabling a
service. This repository does not enable a system service during installation.

## Contribution checks

```bash
python -m pytest agent/tests/test_hk_quotes.py agent/tests/test_hk_collector.py -q
git diff --check
```

Tests use synthetic responses and temporary stores. Live provider checks are
separate, opt-in commands such as `python -m src.hk_data --once`; CI does not
depend on provider uptime or real broker credentials.


## Faster HSI collection

The agent/MCP tool and CLI default to `tencent`; freshness defaults to 60
seconds, and the CLI polls every five seconds. Use `--hsi-snapshot` for the
dated 95-stock 2026-11-04 roster without a personal CSV. Update the roster after
index reviews, or pass `--symbols-file` with your own list. The direct Python
`fetch_quotes()` API and explicit `auto` retain the legacy Yahoo-first policy.
For a fast Python call, select `source="tencent", max_age_seconds=60`.

The SQLite archive collector does not schedule market sessions itself. The
local IndicatorLab operational collector has XHKG session gating and minute
Parquet; that separate research service is not bundled into this package.
