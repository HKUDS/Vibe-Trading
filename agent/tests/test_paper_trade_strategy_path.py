"""T7 gate: strategy_path execution — B1 frozen semantics + AM-8 blocking surface.

Covers the Step-7 contract surfaces:

* the golden sample strategy (fixture ``strategies/golden_sample_sma.py``)
  runs through the hardened executor and wires ``fills[].reason`` (VD-15/B2);
* the optional module-level ``UNIVERSE`` literal (strategy-universe
  convention): ``strategy_universe`` extracts it by pure AST read (the source
  is never executed), ``run_strategy_path`` unions it into the child's
  ``ctx.symbols``, and every convention/path violation degrades to the served
  universe (positions ∪ fetched symbols) as the fallback;
* multi-day single-call chaining, the T4 split detector in strategy mode, and
  note-2 (a lookback-window split never fires);
* B1: per-day timeout (busy loop AND blocked sleep — the SIGKILL really
  interrupts) / per-day exception → the WHOLE call is in-band
  ``INVALID_REQUEST`` with the frozen message
  ``strategy_execution_timeout:{date}`` / ``strategy_execution_error:{date}:
  {ExceptionClassName}``, and a day-k failure never returns days 1..k-1;
* the executor blocking surface (socket / subprocess / os.system / eval /
  unsafe open / broker-layer imports) rejected BEFORE execution — the source
  never runs (canary file assertion); allowed math/pandas/quantlib imports
  still run;
* path policy (strategies-root containment, symlink escape, suffix, size cap,
  sanitized syntax errors), AM-9 readiness outranking strategy failures, and
  cross-run reproducibility (sha256 over the canonical outcome dump).

Offline: fixture-backed fake loader; strategy execution runs in a spawned
child (no network anywhere — the AST sandbox rejects it in strategy code).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import pytest

from src.config.paths import get_runtime_root
from src.tools.paper_trade import engine, strategy_exec
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import parse_request

_FIXTURES = Path(__file__).parent / "fixtures" / "paper_trade"
_SPLIT_FIXTURE = _FIXTURES / "market" / "synthetic_split_4to1.json"
_GOLDEN_STRATEGY = _FIXTURES / "strategies" / "golden_sample_sma.py"
_SYM = "SYNTH-4TO1"
_MARKET = "us"
_ACCOUNT = "pa_strategy"
_DAY = "2026-02-27"  # fixture index 39: close 128.5, sma5 127.5, sma20 123.75

# §4 us default fee matrix, injected explicitly (AM-4-3).
_FEE_MODEL = {"commission_per_share": 0.0049, "commission_min": 0.99, "sec_fee_rate": 0.0}


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


def _fixture_frame() -> pd.DataFrame:
    document = json.loads(_SPLIT_FIXTURE.read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _fetch(from_date: str, to_date: str, frame: pd.DataFrame | None = None):
    return fetch_market_data(_MARKET, [_SYM], from_date, to_date,
                             loader=FakeLoader({_SYM: _fixture_frame() if frame is None else frame}))


def _install_strategy(name: str, source: str) -> str:
    # The path policy only admits <runtime_root>/strategies — the conftest HOME
    # sandbox makes that a per-session temp dir (VIBE_TRADING_HOME is popped).
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _install_golden() -> str:
    return _install_strategy("golden_sample_sma.py", _GOLDEN_STRATEGY.read_text(encoding="utf-8"))


def _request(strategy_path: str, *, from_date: str = _DAY, to_date: str = _DAY,
             cash: float = 50000.0, positions: tuple[dict, ...] = (), market: str = _MARKET):
    return parse_request({
        "account_id": _ACCOUNT, "market": market,
        "account_state": {"cash": cash, "positions": list(positions)},
        "from_date": from_date, "to_date": to_date,
        "strategy_path": strategy_path, "fee_model": dict(_FEE_MODEL),
    })


def _canonical(outcome) -> dict:
    return {
        "fills": [dataclasses.astuple(fill) for fill in outcome.fills],
        "rejected": [dataclasses.astuple(item) for item in outcome.rejected_orders],
        "nav": [dataclasses.astuple(point) for point in outcome.nav_series],
        "skipped": [dataclasses.astuple(item) for item in outcome.skipped_days],
        "end_state": dataclasses.astuple(outcome.end_state),
        "warnings": list(outcome.warnings),
        "provenance": dataclasses.astuple(outcome.data_provenance),
        "fee_model": outcome.effective_fee_model,
        "error": dataclasses.astuple(outcome.error) if outcome.error is not None else None,
    }


def _canonical_sha(outcome) -> str:
    # test_run_card.py:330-353 instrument: byte-level determinism via sha256
    # over the canonical JSON dump.
    text = json.dumps(_canonical(outcome), sort_keys=True, default=str,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_whole_call_failure(outcome, message: str, request) -> None:
    # B1: the WHOLE call failed in-band — frozen message verbatim, empty
    # arrays, the input state untouched (no partial day 1..k-1 output).
    assert outcome.error is not None
    assert outcome.error.code == "INVALID_REQUEST"
    assert outcome.error.message == message
    assert outcome.fills == ()
    assert outcome.rejected_orders == ()
    assert outcome.nav_series == ()
    assert outcome.skipped_days == ()
    assert outcome.end_state == request.account_state


_SCHEDULE_SOURCE = '''"""Date-keyed schedule strategy (3-day chaining form)."""

_SCHEDULE = {
    "2026-02-05": [{"symbol": "SYNTH-4TO1", "side": "buy", "qty": 100, "reason": "schedule day 1"}],
    "2026-02-06": [
        {"symbol": "SYNTH-4TO1", "side": "sell", "qty": 50, "reason": "schedule day 2 exit"},
        {"symbol": "SYNTH-4TO1", "side": "buy", "qty": 20, "reason": "schedule day 2 re-entry"},
    ],
    "2026-02-09": [{"symbol": "SYNTH-4TO1", "side": "sell", "qty": 70, "reason": "schedule day 3"}],
}


class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        return _SCHEDULE.get(trade_date, [])
'''

_HANG_SOURCE = '''"""Busy-loop hang strategy."""
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        while True:
            pass
'''

_SLEEP_SOURCE = '''"""Blocked-sleep hang strategy."""
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        import time
        time.sleep(300)
        return []
'''


def test_golden_sample_strategy_runs_and_wires_reason() -> None:
    day = "2026-03-02"
    outcome = strategy_exec.run_strategy_path(
        request=_request(_install_golden(), from_date=day, to_date=day), market_data=_fetch(day, day))
    assert outcome.error is None
    # Hand-computed: close 129.0, sma5 127.5 > sma20 123.75 → buy 100;
    # us fee max(100×0.0049, 0.99) = 0.99; cash 50000 − 12850.00 − 0.99.
    assert [(f.trade_date, f.symbol, f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [
        (day, _SYM, "buy", 100, 129.0, 0.99)]
    # VD-15/B2 strategy mode: the strategy's reason text reaches the fill.
    assert outcome.fills[0].reason == "golden sma5 127.5000 > sma20 123.7500"
    assert len(outcome.fills[0].reason) <= 200
    assert outcome.end_state.cash == 37099.01
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [(_SYM, 100, 129.0)]
    assert [(n.date, n.nav) for n in outcome.nav_series] == [(day, 49999.01)]
    assert outcome.rejected_orders == ()


def test_three_day_single_call_chains_the_ledger() -> None:
    path = _install_strategy("schedule_3day.py", _SCHEDULE_SOURCE)
    outcome = strategy_exec.run_strategy_path(
        request=_request(path, from_date="2026-02-05", to_date="2026-02-09"),
        market_data=_fetch("2026-02-05", "2026-02-09"))
    assert outcome.error is None
    # Closes 120.5/121.0/121.5; the weekend (02-07/08) is implicit for us —
    # no skip vocabulary, nav continues across it.  Hand-computed chain:
    # d1 −12050.99 → 37949.01; d2 +6049.01 −2420.99 → 41577.03 (70 @ 120.6429);
    # d3 +8504.01 → 50081.04, position closed.
    assert [(f.trade_date, f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [
        ("2026-02-05", "buy", 100, 120.5, 0.99),
        ("2026-02-06", "sell", 50, 121.0, 0.99),
        ("2026-02-06", "buy", 20, 121.0, 0.99),
        ("2026-02-09", "sell", 70, 121.5, 0.99),
    ]
    assert [f.reason for f in outcome.fills] == [
        "schedule day 1", "schedule day 2 exit", "schedule day 2 re-entry", "schedule day 3"]
    assert outcome.end_state.cash == 50081.04
    assert outcome.end_state.positions == ()
    assert [(n.date, n.nav) for n in outcome.nav_series] == [
        ("2026-02-05", 49999.01), ("2026-02-06", 50047.03), ("2026-02-09", 50081.04)]
    assert outcome.skipped_days == ()
    # Note 2: the 4:1 cliff (2026-02-02) sits inside the K=120 lookback and
    # must never fire — no events, no rejections, no warnings.
    assert outcome.data_provenance.corporate_actions == ()
    assert outcome.rejected_orders == ()
    assert not any("corporate action" in w for w in outcome.warnings)


def test_t4_split_detection_applies_in_strategy_mode() -> None:
    # Position 100 @ 476 held across the 2026-02-02 ex-date (clean 4:1): the
    # detector adjusts to 400 @ 119.0 BEFORE the day's orders, so the
    # strategy's sell of 400 on 02-03 can only fill if T4 ran in this mode.
    source = '''"""Post-split exit strategy."""
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        if trade_date == "2026-02-03":
            return [{"symbol": "SYNTH-4TO1", "side": "sell", "qty": 400, "reason": "post-split exit"}]
        return []
'''
    path = _install_strategy("split_exit.py", source)
    outcome = strategy_exec.run_strategy_path(
        request=_request(path, from_date="2026-01-30", to_date="2026-02-03", cash=1000.0,
                         positions=({"symbol": _SYM, "qty": 100, "avg_cost": 476.0},)),
        market_data=_fetch("2026-01-30", "2026-02-03"))
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert outcome.end_state.positions[0].qty == 100
    assert outcome.fills == ()
    assert outcome.nav_series == ()


@pytest.mark.parametrize("kind", ["busy_loop", "blocked_sleep"])
def test_per_day_timeout_really_interrupts_and_freezes_the_message(kind: str) -> None:
    source = _HANG_SOURCE if kind == "busy_loop" else _SLEEP_SOURCE
    path = _install_strategy(f"hang_{kind}.py", source)
    request = _request(path, from_date="2026-02-05", to_date="2026-02-05")
    started = time.monotonic()
    outcome = strategy_exec.run_strategy_path(
        request=request, market_data=_fetch("2026-02-05", "2026-02-05"), timeout_seconds=1.0)
    elapsed = time.monotonic() - started
    # SIGKILL, not a cooperative unwind: the blocked sleep(300) child dies at
    # the 1s budget, so the call returns in startup + budget, never ~300s.
    assert elapsed < 60.0
    _assert_whole_call_failure(outcome, "strategy_execution_timeout:2026-02-05", request)


def test_day_two_exception_never_returns_day_one_results() -> None:
    source = '''"""Day-2 exception strategy."""
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        if trade_date == "2026-02-05":
            return [{"symbol": "SYNTH-4TO1", "side": "buy", "qty": 100, "reason": "day 1 would fill"}]
        if trade_date == "2026-02-06":
            raise ZeroDivisionError("boom")
        return []
'''
    path = _install_strategy("exc_day2.py", source)
    request = _request(path, from_date="2026-02-05", to_date="2026-02-09")
    outcome = strategy_exec.run_strategy_path(
        request=request, market_data=_fetch("2026-02-05", "2026-02-09"))
    # B1: day k fails → the whole call errors; day 1's fill/nav are NOT returned.
    _assert_whole_call_failure(
        outcome, "strategy_execution_error:2026-02-06:ZeroDivisionError", request)


_BLOCKED_BODIES = [
    ("socket_import", ["        import socket", "        return [{'symbol': socket.gethostname(), 'side': 'buy', 'qty': 1}]"]),
    ("subprocess_run", ["        import subprocess", "        return [] if subprocess.run(['true']) else []"]),
    ("os_system", ["        import os", "        return [] if os.system('true') == 0 else []"]),
    ("os_environ", ["        import os", "        return [] if os.environ else []"]),
    ("eval_call", ["        return [] if eval('1+1') == 2 else []"]),
    ("open_write", ["        open('evil.txt', 'w').write('x')", "        return []"]),
    ("open_abs_read", ["        return open('/etc/passwd').read()"]),
    ("broker_service", ["        from src.trading.service import place_order", "        return []"]),
    ("broker_connector", ["        import src.trading.connectors.okx.sdk", "        return []"]),
    ("dunder_import", ["        return __import__('os').getcwd()"]),
]


@pytest.mark.parametrize("case_id,body", _BLOCKED_BODIES, ids=[c[0] for c in _BLOCKED_BODIES])
def test_executor_blocking_surface_rejects_before_execution(case_id, body) -> None:
    # AM-8 regression, mirroring test_backtest_runner_security.py bodies: the
    # validator rejects in the PARENT (no child is ever spawned), so nothing
    # runs — the canary file assertion proves it for the write payload.
    source = "\n".join(['"""Blocked strategy."""', "class SignalEngine:",
                        "    def generate_signals(self, ctx, trade_date):", *body])
    path = _install_strategy(f"blocked_{case_id}.py", source)
    request = _request(path)
    outcome = strategy_exec.run_strategy_path(request=request, market_data=_fetch(_DAY, _DAY))
    _assert_whole_call_failure(outcome, f"strategy_execution_error:{_DAY}:ValueError", request)
    assert not (Path.cwd() / "evil.txt").exists()
    assert not (Path.home() / "evil.txt").exists()


def test_allowed_math_pandas_quantlib_strategy_still_runs() -> None:
    source = '''"""Allowed imports strategy."""
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        import math
        import pandas as pd
        from src.quantlib.fixedincome import bond_price
        symbol = ctx.symbols[0]
        close = ctx.history(symbol)["close"]
        if math.isfinite(float(close.iloc[-1])) and pd is not None and bond_price is not None:
            return [{"symbol": symbol, "side": "buy", "qty": 1, "reason": "allowed imports ran"}]
        return []
'''
    path = _install_strategy("allowed_imports.py", source)
    outcome = strategy_exec.run_strategy_path(
        request=_request(path), market_data=_fetch(_DAY, _DAY))
    assert outcome.error is None
    assert [(f.side, f.qty, f.reason) for f in outcome.fills] == [("buy", 1, "allowed imports ran")]


def test_cross_run_reproducibility_is_byte_identical() -> None:
    path = _install_golden()
    first = strategy_exec.run_strategy_path(request=_request(path), market_data=_fetch(_DAY, _DAY))
    second = strategy_exec.run_strategy_path(request=_request(path), market_data=_fetch(_DAY, _DAY))
    assert first.error is None and second.error is None
    # Same file + same state + same day = same orders, across separate child
    # processes (no cross-run state): sha256 over the canonical dump.
    assert _canonical_sha(first) == _canonical_sha(second)
    assert first.fills == second.fills
    assert first.end_state == second.end_state
    assert first.nav_series == second.nav_series


def _reasons_source(reasons: list) -> str:
    return "\n".join([
        '"""Reason boundary strategy."""',
        f"_REASONS = {reasons!r}",
        "",
        "class SignalEngine:",
        "    def generate_signals(self, ctx, trade_date):",
        "        orders = []",
        "        for reason in _REASONS:",
        '            orders.append({"symbol": "SYNTH-4TO1", "side": "buy", "qty": 1, "reason": reason})',
        "        return orders",
    ])


def test_fill_reason_boundaries_are_utf8_safe_and_capped_at_200() -> None:
    emoji_reason = "🎯" * 199 + "y" * 50
    reasons = ["r" * 200, "x" * 250, emoji_reason, None]
    path = _install_strategy("reason_bounds.py", _reasons_source(reasons))
    outcome = strategy_exec.run_strategy_path(request=_request(path), market_data=_fetch(_DAY, _DAY))
    assert outcome.error is None
    got = [f.reason for f in outcome.fills]
    assert got == ["r" * 200, "x" * 200, emoji_reason[:200], ""]
    for reason in got:
        assert len(reason) <= 200
        reason.encode("utf-8")  # never a split multi-byte character
    assert got[2] == "🎯" * 199 + "y"  # code-point slice kept the 4-byte char whole


_MALFORMED_BODIES = [
    ("non_list_return", ["        return 42"]),
    ("bad_side", ['        return [{"symbol": "SYNTH-4TO1", "side": "hold", "qty": 1}]']),
    ("nan_qty", ['        return [{"symbol": "SYNTH-4TO1", "side": "buy", "qty": float("nan")}]']),
    ("non_str_reason", ['        return [{"symbol": "SYNTH-4TO1", "side": "buy", "qty": 1, "reason": 42}]']),
    ("non_dict_entry", ['        return ["SYNTH-4TO1"]']),
]


@pytest.mark.parametrize("case_id,body", _MALFORMED_BODIES, ids=[c[0] for c in _MALFORMED_BODIES])
def test_malformed_strategy_output_is_a_frozen_strategy_order_error(case_id, body) -> None:
    source = "\n".join(['"""Malformed output strategy."""', "class SignalEngine:",
                        "    def generate_signals(self, ctx, trade_date):", *body])
    path = _install_strategy(f"malformed_{case_id}.py", source)
    request = _request(path)
    outcome = strategy_exec.run_strategy_path(request=request, market_data=_fetch(_DAY, _DAY))
    _assert_whole_call_failure(
        outcome, f"strategy_execution_error:{_DAY}:StrategyOrderError", request)


def test_path_policy_rejects_before_any_read_or_execute(tmp_path) -> None:
    valid = _GOLDEN_STRATEGY.read_text(encoding="utf-8")
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    runtime_root = get_runtime_root()
    (runtime_root / "escape.py").write_text(valid, encoding="utf-8")
    (runtime_root / "outside_target.py").write_text(valid, encoding="utf-8")
    (root / "strategy.txt").write_text(valid, encoding="utf-8")
    (root / "dir.py").mkdir(exist_ok=True)
    (root / "big.py").write_text("a" * (strategy_exec._MAX_STRATEGY_BYTES + 1), encoding="utf-8")
    (root / "broken.py").write_text("SECRET_MARKER = (\n", encoding="utf-8")
    (tmp_path / "outside.py").write_text(valid, encoding="utf-8")
    symlink_case = {}
    try:
        (root / "link.py").symlink_to(runtime_root / "outside_target.py")
        symlink_case = {"symlink_escape": str(root / "link.py")}
    except OSError:
        pass  # symlink creation privileges (Windows) — case skipped, not failed

    cases = {
        "traversal": str(root / ".." / "escape.py"),
        "absolute_outside": str(tmp_path / "outside.py"),
        "wrong_suffix": str(root / "strategy.txt"),
        "missing_file": str(root / "nope.py"),
        "directory_named_py": str(root / "dir.py"),
        "oversize": str(root / "big.py"),
        "empty_path": "",
        **symlink_case,
    }
    market_data = _fetch(_DAY, _DAY)
    for label, strategy_path in cases.items():
        request = _request(strategy_path)
        outcome = strategy_exec.run_strategy_path(request=request, market_data=market_data)
        assert outcome.error is not None, label
        assert outcome.error.code == "INVALID_REQUEST", label
        assert outcome.error.message == f"strategy_execution_error:{_DAY}:StrategyPathError", label
        assert outcome.fills == () and outcome.nav_series == (), label
        assert outcome.end_state == request.account_state, label

    # Syntax errors never echo source text (the target may be a non-strategy
    # file whose contents must not leak into the wire message).
    outcome = strategy_exec.run_strategy_path(
        request=_request(str(root / "broken.py")), market_data=market_data)
    assert outcome.error is not None
    assert outcome.error.message == f"strategy_execution_error:{_DAY}:StrategyPathError"
    assert "SECRET_MARKER" not in outcome.error.message


def test_readiness_gate_outranks_a_hanging_strategy() -> None:
    # AM-9 runs BEFORE validation/execution: a retryable data fact is never
    # masked by the non-retryable timeout of a strategy that never runs.
    truncated = _fixture_frame().loc[: pd.Timestamp("2026-02-20")]
    path = _install_strategy("hang_notready.py", _HANG_SOURCE)
    request = _request(path, from_date="2026-02-20", to_date="2026-02-23")
    started = time.monotonic()
    outcome = strategy_exec.run_strategy_path(
        request=request, market_data=_fetch("2026-02-20", "2026-02-23", frame=truncated))
    assert time.monotonic() - started < 30.0  # no spawn, no 1s budget wait
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert outcome.fills == () and outcome.nav_series == ()


class FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class FakeCalendarClient:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"), "is_open": 0,
             "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def test_no_matching_days_validates_but_never_runs_the_strategy() -> None:
    # cn_a calendar truth closes the whole range: the strategy is validated
    # (contract enforcement) but never executed — a raise-if-called body
    # proves it, and the call succeeds with two non_trading_day skips.
    source = '''"""Must-not-run strategy."""
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        raise RuntimeError("must not run on a closed calendar")
'''
    path = _install_strategy("must_not_run.py", source)
    frame = pd.DataFrame(
        [{"trade_date": "2026-02-06", "open": 10.0, "high": 10.0, "low": 10.0,
          "close": 10.0, "volume": 1000.0}]).set_index(pd.to_datetime(["2026-02-06"]))
    market_data = fetch_market_data(
        "cn_a", ["600519.SH"], "2026-02-07", "2026-02-08",
        loader=FakeLoader({"600519.SH": frame}, name="tencent"), ch_client=FakeChClient())
    request = _request(path, from_date="2026-02-07", to_date="2026-02-08", market="cn_a")
    outcome = strategy_exec.run_strategy_path(
        request=request, market_data=market_data, calendar_client=FakeCalendarClient())
    assert outcome.error is None
    assert [(s.date, s.reason) for s in outcome.skipped_days] == [
        ("2026-02-07", "non_trading_day"), ("2026-02-08", "non_trading_day")]
    assert outcome.fills == () and outcome.nav_series == ()


def test_seam_misuse_and_bad_timeout_raise_transport_class() -> None:
    market_data = _fetch(_DAY, _DAY)
    orders_only = parse_request({
        "account_id": _ACCOUNT, "market": _MARKET,
        "account_state": {"cash": 50000.0, "positions": []},
        "from_date": _DAY, "to_date": _DAY,
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}], "fee_model": {},
    })
    with pytest.raises(ValueError, match="strategy_path"):
        strategy_exec.run_strategy_path(request=orders_only, market_data=market_data)

    both = parse_request({
        "account_id": _ACCOUNT, "market": _MARKET,
        "account_state": {"cash": 50000.0, "positions": []},
        "from_date": _DAY, "to_date": _DAY,
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}],
        "strategy_path": _install_golden(), "fee_model": {},
    })
    with pytest.raises(ValueError, match="orders must be absent"):
        strategy_exec.run_strategy_path(request=both, market_data=market_data)

    mismatch = _request(_install_golden(), market="hk")
    with pytest.raises(ValueError, match="market_data was fetched for"):
        strategy_exec.run_strategy_path(request=mismatch, market_data=market_data)

    good = _request(_install_golden())
    for bad in (0, -1.0, float("nan"), float("inf"), "5", True):
        with pytest.raises(ValueError, match="finite positive"):
            strategy_exec.run_strategy_path(
                request=good, market_data=market_data, timeout_seconds=bad)


def test_orders_mode_fill_reason_stays_empty() -> None:
    # VD-15/B2 contrast half: the orders mode keeps "" (goldens pin the wire
    # bytes; this pins the engine boundary the strategy mode shares).
    request = parse_request({
        "account_id": _ACCOUNT, "market": _MARKET,
        "account_state": {"cash": 50000.0, "positions": []},
        "from_date": _DAY, "to_date": _DAY,
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}], "fee_model": dict(_FEE_MODEL),
    })
    outcome = engine.match_orders(request, market_data=_fetch(_DAY, _DAY))
    assert outcome.error is None
    assert [f.reason for f in outcome.fills] == [""]


# ── the optional UNIVERSE declaration (strategy_universe: pure AST read) ──


def test_strategy_universe_extracts_literal_tuple_and_list() -> None:
    tuple_path = _install_strategy("universe_tuple.py", 'UNIVERSE = ("SYM-B", "SYM-A", "SYM-B")\n')
    assert strategy_exec.strategy_universe(tuple_path) == ("SYM-A", "SYM-B")  # sorted, deduped
    list_path = _install_strategy("universe_list.py", 'UNIVERSE = ["SYM-X", "SYM-Y"]\n')
    assert strategy_exec.strategy_universe(list_path) == ("SYM-X", "SYM-Y")
    annotated = _install_strategy("universe_ann.py", 'UNIVERSE: tuple = ("SYM-Z",)\n')
    assert strategy_exec.strategy_universe(annotated) == ("SYM-Z",)
    # The golden fixture declares the synthetic symbol the T6/T7 gates serve.
    assert strategy_exec.strategy_universe(_install_golden()) == (_SYM,)


_UNIVERSE_REJECTIONS = {
    "absent": 'OTHER = ("SYM",)\n',
    "call": 'UNIVERSE = tuple("SYM")\n',
    "expression": 'UNIVERSE = ("SYM",) * 2\n',
    "bare_string": 'UNIVERSE = "SYM"\n',
    "dict": 'UNIVERSE = {"SYM": 1}\n',
    "non_string_entry": 'UNIVERSE = ("SYM", 42)\n',
    "empty_string_entry": 'UNIVERSE = ("SYM", "")\n',
    "invalid_syntax": "UNIVERSE = (\n",
}


@pytest.mark.parametrize("case_id", sorted(_UNIVERSE_REJECTIONS))
def test_strategy_universe_convention_violations_degrade_to_empty(case_id) -> None:
    path = _install_strategy(f"universe_bad_{case_id}.py", _UNIVERSE_REJECTIONS[case_id])
    assert strategy_exec.strategy_universe(path) == ()


def test_strategy_universe_path_policy_rejections_degrade_to_empty(tmp_path) -> None:
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.py"
    outside.write_text('UNIVERSE = ("SYM",)\n', encoding="utf-8")
    wrong_suffix = root / "universe_policy.txt"
    wrong_suffix.write_text('UNIVERSE = ("SYM",)\n', encoding="utf-8")
    cases = {
        "outside_root": str(outside),
        "missing_file": str(root / "universe_nope.py"),
        "wrong_suffix": str(wrong_suffix),
        "empty_path": "",
        "blank_path": "   ",
    }
    for label, path in cases.items():
        assert strategy_exec.strategy_universe(path) == (), label


def test_strategy_universe_never_executes_the_source() -> None:
    # No-execution proof: an exec/import would fire the canary write and
    # propagate the raise; the pure AST read returns the declaration untouched
    # (the raise sits BEFORE the assignment, so only a parse can see it).
    source = (
        "import pathlib\n"
        "pathlib.Path('universe_canary.txt').write_text('executed')\n"
        "raise RuntimeError('strategy_universe must never execute the source')\n"
        'UNIVERSE = ("SYM-A", "SYM-B")\n'
    )
    path = _install_strategy("universe_noexec.py", source)
    assert strategy_exec.strategy_universe(path) == ("SYM-A", "SYM-B")
    assert not (Path.cwd() / "universe_canary.txt").exists()
    assert not (Path.home() / "universe_canary.txt").exists()


def test_declared_universe_joins_ctx_symbols_without_child_io() -> None:
    # run_strategy_path unions the declared UNIVERSE into the child's
    # ctx.symbols (sorted union with the served universe); a declared symbol
    # with no served data reads an empty history — the child never fetches.
    source = '''"""Universe-declaring strategy (ctx union probe)."""
UNIVERSE = ("SYNTH-4TO1", "NO-DATA-SYM")


class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        if tuple(ctx.symbols) != ("NO-DATA-SYM", "SYNTH-4TO1"):
            raise AssertionError("ctx.symbols must be the sorted served+declared union")
        if not ctx.history("NO-DATA-SYM").empty:
            raise AssertionError("a declared symbol without served data reads an empty history")
        return [{"symbol": "SYNTH-4TO1", "side": "buy", "qty": 1,
                 "reason": "+".join(ctx.symbols)}]
'''
    path = _install_strategy("universe_ctx.py", source)
    outcome = strategy_exec.run_strategy_path(
        request=_request(path), market_data=_fetch(_DAY, _DAY))
    assert outcome.error is None
    assert [(f.side, f.qty, f.reason) for f in outcome.fills] == [
        ("buy", 1, "NO-DATA-SYM+SYNTH-4TO1")]


def test_strategy_uses_prior_bars_and_receives_previous_fills():
    path = _install_strategy("causal_state.py", '''
class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        history = ctx.history(ctx.symbols[0])
        if str(history.index[-1].date()) >= trade_date:
            raise AssertionError("execution bar leaked")
        if ctx.account_state.positions:
            if ctx.account_state.cash >= 50000:
                raise AssertionError("stale cash")
            return [{"symbol": ctx.symbols[0], "side": "sell",
                     "qty": ctx.account_state.positions[0].qty}]
        return [{"symbol": ctx.symbols[0], "side": "buy", "qty": 10}]
''')
    request = _request(path, from_date="2026-02-05", to_date="2026-02-06")
    outcome = strategy_exec.run_strategy_path(
        request=request, market_data=_fetch(request.from_date, request.to_date))
    assert outcome.error is None
    assert [(fill.trade_date, fill.side, fill.qty) for fill in outcome.fills] == [
        ("2026-02-05", "buy", 10), ("2026-02-06", "sell", 10)]
    assert outcome.end_state.positions == ()
