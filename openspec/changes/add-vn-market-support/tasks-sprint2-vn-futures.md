# Sprint 2.1 — VNFuturesEngine Implementation Checklist

> Replaces the coarse "Sprint 2 / 5. Futures Engine" section in `tasks.md` with detailed, dependency-ordered tasks. Each task = 15-45 min.

## 1. Engine scaffold (foundations first)

- [ ] 1.1 Add `VNFuturesEngine` skeleton at `agent/backtest/engines/vn_futures.py` extending `FuturesBaseEngine`. Module docstring + class signature only, raise `NotImplementedError` in methods.
- [ ] 1.2 Module-level constants: `KNOWN_CONTRACTS = ("VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q")`, `CONTRACT_MULTIPLIER = 100_000.0`
- [ ] 1.3 Helper `_is_vn30f(symbol)` regex match `^VN30F[12][MQ](\.HNX)?$`
- [ ] 1.4 Helper `_strip_hnx(symbol)` → returns canonical bare form (`VN30F1M`)
- [ ] 1.5 Helper `_contract_month(symbol, current_date)` → returns the calendar month/year the contract expires in (decode F1M/F2M = current/next month, F1Q/F2Q = current/next quarter)
- [ ] 1.6 Helper `_third_thursday(year, month)` → `datetime.date`

## 2. Constructor + config

- [ ] 2.1 `__init__(config)` sets: `margin_rate=0.17`, `maintenance_ratio=0.80`, `commission_per_contract=2700.0`, `tax_rate=0.001`, `price_band=0.07`, `position_limit=5000`
- [ ] 2.2 Pass `leverage = 1 / margin_rate` to super so `_calc_margin` works correctly
- [ ] 2.3 `get_contract_multiplier(symbol)` returns the constant (single product family)
- [ ] 2.4 Validate symbol via `_is_vn30f`; raise `ValueError` for unknown contracts

## 3. Market rule overrides

- [ ] 3.1 `can_execute(symbol, direction, bar)`:
    - Return False if not `_is_vn30f(symbol)`
    - Price band check (use existing `_calc_pct_change` pattern from china_a)
    - Position limit check on opens (skip on closes)
    - Allow shorts (no T+2)
- [ ] 3.2 `round_size(raw_size, price)` → `max(int(abs(raw_size)), 0)` (1-contract granularity)
- [ ] 3.3 `calc_commission(size, price, direction, is_open)`:
    - per-contract commission: `abs(size) * commission_per_contract`
    - per-side tax: `abs(size) * price * MULT * tax_rate`
    - return sum

## 4. Daily mark-to-market

- [ ] 4.1 In `BaseEngine`, add `_after_bar_close(bar)` hook (default no-op). Wire it in `run_backtest` after each bar's standard processing. Verify no regression in existing engines (run full pytest).
- [ ] 4.2 Override `_after_bar_close` in `VNFuturesEngine`:
    - For each open position, compute `daily_pnl = direction * size * MULT * (close - prior_settle)`
    - Update `self.cash` with `daily_pnl`
    - Update each `position.entry_price = close` (re-mark) — OR maintain separate `prior_settle` field on position
    - Append to `self.settlements: list[SettlementRecord]`
- [ ] 4.3 Margin call check after settle:
    - Compute position notional = `size × close × MULT`
    - Required margin = `notional × margin_rate × maintenance_ratio`
    - If `cash + unrealized_pnl < required` → set `_pending_liquidation[symbol] = True`
- [ ] 4.4 In `can_execute`, if `_pending_liquidation` flag is set for symbol, force close at next bar open

## 5. Expiry handling

- [ ] 5.1 Override new method `_check_expiry(symbol, bar)`:
    - Determine contract month/year via `_contract_month`
    - If `bar.trade_date == third_thursday(year, month)` → trigger expiry settlement
- [ ] 5.2 Expiry settlement logic:
    - Use `bar.close` as final settle (minute-bar avg deferred — note in code comment)
    - Realize remaining P&L vs entry/prior_settle
    - Mark position as `expired`, remove from active positions
    - Append `ExpirySettlement` event to settlements log
- [ ] 5.3 Subsequent bars for expired contract → `can_execute` returns False, no further P&L

## 6. Composite engine routing

- [ ] 6.1 Edit `agent/backtest/engines/composite.py` `_MARKET_PATTERNS`:
    - Insert `(re.compile(r"^VN30F[12][MQ](\.HNX)?$"), "vn_futures")` BEFORE the generic `.HOSE/.HNX/.UPCOM` rule
    - Verify ordering: VN30F1M → vn_futures, ABC.HNX → vn_equity, VNM → a_share
- [ ] 6.2 Add `elif market == "vn_futures":` branch in `_build_rule_engines`:
    ```python
    from backtest.engines.vn_futures import VNFuturesEngine
    engines["vn_futures"] = VNFuturesEngine(config)
    ```
- [ ] 6.3 Update `agent/backtest/engines/__init__.py` docstring

## 7. Loader extension for derivatives

- [ ] 7.1 In `vnstock_loader.py`, extend `fetch()` to detect VN30F symbols (use `_is_vn30f` helper imported from engine OR re-define in loader)
- [ ] 7.2 vnstock derivatives API verification: spike `Quote(symbol='VN30F1M', source='VCI').history(...)`. Document actual columns returned. If `time` column maps cleanly, no extra logic needed; if column shape differs, add a `_normalize_derivative_bars` helper.
- [ ] 7.3 Fallback: if vnstock VCI/TCBS/MSN all fail for derivatives, log a clear "VN30F not available via vnstock" warning. Do NOT add a TCBS-direct HTTP client this sprint — defer.

## 8. Tests

- [ ] 8.1 `agent/tests/test_vn_futures_engine.py` — Group A: helpers
    - `_is_vn30f` true/false matrix (5+ cases)
    - `_third_thursday` for known months (2024-2025)
- [ ] 8.2 Group B: config defaults + overrides
- [ ] 8.3 Group C: `get_contract_multiplier` returns 100_000 for any known contract
- [ ] 8.4 Group D: `can_execute` price band — block at +6.95% buy, allow at +5%, etc.
- [ ] 8.5 Group E: `can_execute` position limit — assert open of 5001th contract blocked
- [ ] 8.6 Group F: `can_execute` allows shorts (direction=-1) unconditionally apart from band/limit
- [ ] 8.7 Group G: `round_size` — 1-contract granularity, 2.7 → 2, -3 → 3
- [ ] 8.8 Group H: `calc_commission` — verify formula on opens (commission only) and closes (commission + tax)
- [ ] 8.9 Group I: daily mark-to-market PnL — long 1 @ 1200, settle @ 1210 → cash += 1,000,000 VND
- [ ] 8.10 Group J: margin call simulator — set up scenario: balance 50M, lose 40M+ → assert `_pending_liquidation` flag set
- [ ] 8.11 Group K: expiry settlement — backtest VN30F1M for May 2024, hold to 3rd Thursday (2024-05-16) → assert position expired with correct realized P&L
- [ ] 8.12 Group L: composite routing — `_detect_market("VN30F1M")`, `_detect_market("VN30F1M.HNX")` → `vn_futures`
- [ ] 8.13 Group M: regression — full pytest suite remains green (913+ tests) after `_after_bar_close` hook is added to BaseEngine

## 9. Hook safety verification

- [ ] 9.1 After Task 4.1, run `pytest agent/tests/test_china_a_engine.py agent/tests/test_crypto_engine.py agent/tests/test_global_equity_engine.py agent/tests/test_china_futures_engine.py -q` — ALL must pass with no behavior change
- [ ] 9.2 Inspect that the default `_after_bar_close` is truly no-op (returns None, no state mutation)

## 10. Smoke + commit

- [ ] 10.1 End-to-end smoke:
    ```python
    .venv/bin/python -c "
    import sys; sys.path.insert(0, 'agent')
    from backtest.engines.vn_futures import VNFuturesEngine, _is_vn30f
    from backtest.engines.composite import _detect_market
    e = VNFuturesEngine({})
    print('multiplier:', e.get_contract_multiplier('VN30F1M'))
    print('margin_rate:', e.margin_rate)
    print('routing F1M:', _detect_market('VN30F1M'))
    print('routing F1M.HNX:', _detect_market('VN30F1M.HNX'))
    print('routing equity HNX:', _detect_market('SHB.HNX'))
    print('vn30f? F1M:', _is_vn30f('VN30F1M'))
    print('vn30f? VNM:', _is_vn30f('VNM'))
    "
    ```
- [ ] 10.2 Run full pytest, expect all green
- [ ] 10.3 Commit with message:
    ```
    feat(engines): add VN30F futures engine

    - VNFuturesEngine extends FuturesBaseEngine with VN30 multiplier 100k
    - 4 contracts: VN30F1M/F2M/F1Q/F2Q
    - Daily mark-to-market via new _after_bar_close hook
    - Margin call simulator with configurable maintenance ratio
    - Cash settlement at expiry (3rd Thursday of contract month)
    - Composite routing prioritizes VN30F prefix over .HNX equity rule
    - Position limit (5000) and price band (±7%) enforced

    Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
    ```

## Out-of-scope explicit list (do NOT do this sprint)

- Auto-rolling at expiry (strategy concern)
- Basis arbitrage helper (Sprint 3 skill)
- Minute-bar 30-min average for final settle (defer)
- Per-broker margin tier tables (single config field)
- Night session (no night session in VN derivatives)
- Options on VN30F (don't exist in market)

## Definition of done

1. `pytest agent/tests/test_vn_futures_engine.py` — all green
2. `pytest agent/tests/` — all 913+ existing tests still green
3. End-to-end smoke prints all 6 expected values
4. One commit on `feat/vn-market-support` (no fixups)
5. Engine file ≤ 250 LOC
