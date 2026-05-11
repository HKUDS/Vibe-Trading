# Sprint 2.2 — VN Broker Journal Readers

> 5 brokers (SSI, HSC, VNDirect, TCBS, DNSE), reuse `TradeRecord` schema + `load_dataframe` from existing `trade_journal_parsers.py`.

## Architecture

Sub-package `agent/src/tools/journal_parsers_vn/` with auto-registry. Each broker = 1 module. Pattern mirrors `backtest.loaders.registry`:

```
journal_parsers_vn/
├── __init__.py      # registry + detect_vn_format + parse_vn dispatch
├── _common.py       # _qualify_vn_symbol, side normalization, encoding helpers
├── ssi.py           # SSI iBoard parser
├── hsc.py           # HSC parser
├── vndirect.py      # VNDirect parser
├── tcbs.py          # TCBS parser
└── dnse.py          # DNSE LightSpeed parser
```

`trade_journal_parsers.py` `detect_format()` falls back to `detect_vn_format(df)` when none of the existing 4 formats match. `parse_file()` dispatches VN formats via `parse_vn(name, df)`.

## Phase 1 — Foundation (single agent, blocking)

- [ ] 1.1 Create `agent/src/tools/journal_parsers_vn/__init__.py` with:
    - `BrokerParser` Protocol (`name: str`, `detect(df) -> bool`, `parse(df) -> list[TradeRecord]`)
    - `VN_PARSER_REGISTRY: dict[str, BrokerParser]`
    - `register_vn_parser(parser)` decorator/function
    - `_ensure_registered()` lazy-imports `ssi`, `hsc`, `vndirect`, `tcbs`, `dnse` submodules
    - `detect_vn_format(df) -> str | None` iterates registry calling `.detect()`
    - `parse_vn(name, df) -> list[TradeRecord]`
    - `__all__` exports
- [ ] 1.2 Create `agent/src/tools/journal_parsers_vn/_common.py`:
    - `_qualify_vn_symbol(code, exchange_hint=None) -> str` — bare ticker → `VNM.HOSE`. Bank tickers → HOSE. Mid-cap with known HNX → HNX. Default HOSE.
    - `_normalize_vn_side(raw) -> str` — accepts: "Mua"/"MUA"/"BUY"/"B" → "buy"; "Bán"/"BÁN"/"SELL"/"S" → "sell"
    - `_parse_vn_date(raw) -> str` — supports DD/MM/YYYY and YYYY-MM-DD, returns ISO8601
    - `_to_float_vn(val, default=0.0)` — handles VN number format `1.234.567,89` AND US `1,234,567.89` AND bare numbers
- [ ] 1.3 Modify `agent/src/tools/trade_journal_parsers.py`:
    - In `detect_format()`, after existing branches return `"unknown"`, instead delegate to `detect_vn_format(df)` and return its result (or `"unknown"` if None)
    - In `_PARSER_BY_FORMAT`, NO direct entries for VN (handled via dispatcher)
    - In `parse_file()`, route VN formats (anything in `journal_parsers_vn.VN_PARSER_REGISTRY`) to `parse_vn()`
    - Keep existing 4 parsers untouched
- [ ] 1.4 Add 5 placeholder modules `ssi.py` / `hsc.py` / `vndirect.py` / `tcbs.py` / `dnse.py` each containing a stub class with `name`, `detect()` returning `False`, `parse()` raising `NotImplementedError("Sprint 2.2")`. This ensures Phase 1 commits cleanly without breaking imports while Phase 2 agents fill in the implementations in parallel.
- [ ] 1.5 Smoke check:
    ```bash
    .venv/bin/python -c "
    import sys; sys.path.insert(0, 'agent')
    from src.tools.journal_parsers_vn import VN_PARSER_REGISTRY, _ensure_registered, detect_vn_format
    _ensure_registered()
    print('registered:', sorted(VN_PARSER_REGISTRY.keys()))
    import pandas as pd
    df = pd.DataFrame([{'date': '2024-01-01', 'symbol': 'VNM'}])
    print('detect_vn:', detect_vn_format(df))
    "
    ```
    Expected: `registered: ['dnse', 'hsc', 'ssi', 'tcbs', 'vndirect']`, `detect_vn: None`
- [ ] 1.6 Run full regression: 999 tests still pass (no impact on existing parsers)
- [ ] 1.7 Commit: `feat(journals): scaffold VN broker journal parser registry`

## Phase 2 — 5 broker parsers (parallel, 5 agents)

Each agent owns ONE module file + ONE fixture file + ONE test file. Zero file overlap.

### Per-broker contract

Each broker module MUST export a class implementing `BrokerParser`:

```python
from src.tools.trade_journal_parsers import TradeRecord
from src.tools.journal_parsers_vn import register_vn_parser
from src.tools.journal_parsers_vn._common import (
    _qualify_vn_symbol, _normalize_vn_side, _parse_vn_date, _to_float_vn,
)

class <Broker>Parser:
    name = "<broker>"
    
    def detect(self, df) -> bool:
        # Match by column-name signature
        ...
    
    def parse(self, df) -> list[TradeRecord]:
        ...

register_vn_parser(<Broker>Parser())
```

### Tasks for each broker (replicate 5×)

- [ ] 2.X.1 Implement `agent/src/tools/journal_parsers_vn/<broker>.py`:
    - `detect(df)`: column signature match (use canonical header names per broker — see column hints below)
    - `parse(df)`: row-by-row to `TradeRecord` (datetime, symbol, name, side, quantity, price, amount, fee, market="vn_equity")
    - Tax field: VN brokers usually report tax separately; combine `fee + tax` into the single `fee` field of `TradeRecord` (with a comment noting this)
    - Skip rows where qty=0 or symbol is empty
- [ ] 2.X.2 Create fixture `agent/tests/fixtures/journal_<broker>.csv` with 5-8 representative rows including: 2 buys (different symbols), 2 sells (one matching a buy, one independent), 1 row to skip (0-qty or header-like), Vietnamese column headers if applicable to the broker
- [ ] 2.X.3 Create `agent/tests/test_journal_<broker>.py`:
    - `test_<broker>_detect_positive`: load fixture → `detect()` returns True
    - `test_<broker>_detect_negative`: pass a Tonghuashun-shaped df → returns False (no false positive)
    - `test_<broker>_parse_count`: parse fixture → expected number of TradeRecord (skipping the bad row)
    - `test_<broker>_parse_field_mapping`: spot-check 1 buy and 1 sell row — assert datetime ISO8601, symbol qualified (e.g. `VNM.HOSE`), side normalized, qty/price/amount/fee floats
    - `test_<broker>_parse_via_parse_file`: call top-level `parse_file()` on the fixture, assert format detected = `"<broker>"` and records non-empty
- [ ] 2.X.4 Verify `.venv/bin/python -m pytest agent/tests/test_journal_<broker>.py -x -q` is green
- [ ] 2.X.5 Commit: `feat(journals): <BROKER> broker journal parser + fixture + tests`

### Column hints per broker (best-known public schemas; agents adapt if real samples exist)

| Broker | Likely column headers |
|--------|----------------------|
| **SSI** | `Ngày GD`, `Mã CK`, `Loại GD` (Mua/Bán), `KL khớp`, `Giá khớp`, `Giá trị`, `Phí GD`, `Thuế` |
| **HSC** | `Trade Date`, `Symbol`, `Side` (BUY/SELL), `Quantity`, `Matched Price`, `Net Amount`, `Fee`, `Tax` |
| **VNDirect** | `Ngày`, `Mã`, `Loại lệnh` (Mua/Bán), `Khối lượng`, `Giá`, `Giá trị`, `Phí`, `Thuế` |
| **TCBS** | `Ngày giao dịch`, `Mã CK`, `Loại GD`, `Khối lượng`, `Giá khớp`, `Giá trị giao dịch`, `Phí`, `Thuế` |
| **DNSE** | `Trade Date`, `Symbol`, `Side`, `Volume`, `Price`, `Net Value`, `Fee` |

Each parser's `detect()` should require ≥3 distinctive column names. If broker has both EN and VN exports, support BOTH via OR-matching on column sets.

## Phase 3 — Integration & wrap-up (single agent)

- [ ] 3.1 End-to-end smoke: call `parse_file()` on each of the 5 fixtures → assert correct format detected and records returned
- [ ] 3.2 Cross-broker false-positive test: load each fixture, call `detect_vn_format()` and `detect_format()` (top-level), confirm exactly one match per fixture (no broker matches multiple)
- [ ] 3.3 Update `agent/src/skills/trade-journal/SKILL.md` to document the 5 new VN broker formats in the "Supported formats" section
- [ ] 3.4 Run full regression: 999 + (≈5 brokers × 5 tests) = ~1024 total
- [ ] 3.5 Commit: `feat(journals): wire 5 VN broker formats end-to-end + skill doc`
- [ ] 3.6 Update `.cm/CONTINUITY.md` for Sprint 2.2 completion

## Out-of-scope explicit

- **No real broker exports** — agents synthesize fixtures based on public column documentation
- **No P&L matching** — that's the existing `analyze_trade_journal` tool's job, not the parser's
- **No CW (covered warrant) parsing** — VN-specific derivative; defer
- **No futures journal** — VN30F journal format defer (different schema)
- **No tax breakdown** — combine fee+tax into single `fee` field per `TradeRecord` schema

## Definition of Done

1. `pytest agent/tests/test_journal_*.py` — all 5 broker test files green
2. `pytest agent/tests/` — full regression green (1020+ tests)
3. End-to-end: `parse_file('fixtures/journal_ssi.csv')` returns format `"ssi"` and ≥4 TradeRecord
4. No false positives across brokers (each fixture detects exactly its own broker)
5. SKILL.md updated with VN section
6. 5+ commits on `feat/vn-market-support` (one per phase / broker)
