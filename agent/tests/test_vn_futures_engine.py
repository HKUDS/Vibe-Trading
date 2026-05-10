"""Tests for VNFuturesEngine market rules.

Validates:
  - Symbol detection (VN30F prefix, optional .HNX suffix)
  - Contract multiplier (100k VND/point)
  - Price band +/-7%, position limit 5000, expired/liquidation gates
  - Daily mark-to-market via _after_bar_close
  - Margin call simulation
  - Cash settlement at expiry
  - Composite routing (VN futures vs VN equity vs A-share)
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backtest.engines.vn_futures import (
    VNFuturesEngine,
    _is_vn30f,
    _third_thursday,
    _contract_month,
)
from backtest.engines.composite import _detect_market
from backtest.models import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar_with_pct(close: float, pre_close: float) -> pd.Series:
    """Build a bar where pct_change can be derived from close/pre_close."""
    return pd.Series({"close": close, "pre_close": pre_close})


def _mtm_bar(
    close: float,
    *,
    symbol: str = "VN30F1M",
    when: date | None = None,
) -> pd.Series:
    """Build the per-symbol close-price Series the _after_bar_close hook gets.

    Per BaseEngine._execute_bars, the hook receives a Series indexed by symbol
    with close prices, and bar.name = timestamp.
    """
    s = pd.Series({symbol: close})
    s.name = pd.Timestamp(when or date.today())
    return s


def _make_position(
    symbol: str,
    *,
    direction: int = 1,
    size: float = 1.0,
    entry_price: float = 1200.0,
    days_ago: int = 1,
    leverage: float = 1.0 / 0.17,
) -> Position:
    return Position(
        symbol=symbol,
        direction=direction,
        size=size,
        entry_price=entry_price,
        entry_time=pd.Timestamp.now() - timedelta(days=days_ago),
        leverage=leverage,
    )


def _make_engine(**overrides) -> VNFuturesEngine:
    config = {"initial_cash": 1_000_000_000}
    config.update(overrides)
    return VNFuturesEngine(config)


# ---------------------------------------------------------------------------
# Group A — Module helpers
# ---------------------------------------------------------------------------


class TestModuleHelpers:
    @pytest.mark.parametrize(
        "symbol",
        ["VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"],
    )
    def test_is_vn30f_known_contracts(self, symbol: str) -> None:
        assert _is_vn30f(symbol) is True

    def test_is_vn30f_with_hnx_suffix(self) -> None:
        assert _is_vn30f("VN30F1M.HNX") is True
        assert _is_vn30f("VN30F2Q.HNX") is True

    @pytest.mark.parametrize(
        "symbol",
        ["VNM", "SHB.HNX", "VN30", "VN30FUT", "", "VN30F3M", "FOO"],
    )
    def test_is_vn30f_rejects_non_vn30f(self, symbol: str) -> None:
        assert _is_vn30f(symbol) is False

    def test_is_vn30f_rejects_none(self) -> None:
        assert _is_vn30f(None) is False  # type: ignore[arg-type]

    def test_third_thursday_known_dates(self) -> None:
        assert _third_thursday(2024, 5) == date(2024, 5, 16)
        assert _third_thursday(2024, 12) == date(2024, 12, 19)
        assert _third_thursday(2025, 2) == date(2025, 2, 20)
        assert _third_thursday(2025, 8) == date(2025, 8, 21)

    @pytest.mark.parametrize(
        "symbol, today, expected",
        [
            ("VN30F1M", date(2024, 5, 10), (2024, 5)),
            ("VN30F1M", date(2024, 5, 17), (2024, 6)),
            ("VN30F2M", date(2024, 5, 10), (2024, 6)),
            ("VN30F1Q", date(2024, 5, 10), (2024, 6)),
            ("VN30F1Q", date(2024, 7, 10), (2024, 9)),
            ("VN30F2Q", date(2024, 5, 10), (2024, 9)),
        ],
    )
    def test_contract_month_decoding(
        self, symbol: str, today: date, expected: tuple[int, int],
    ) -> None:
        assert _contract_month(symbol, today) == expected


# ---------------------------------------------------------------------------
# Group B — Constructor + config
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_default_config(self) -> None:
        engine = _make_engine()
        assert engine.margin_rate == pytest.approx(0.17)
        assert engine.maintenance_ratio == pytest.approx(0.80)
        assert engine.commission_per_contract == pytest.approx(2700.0)
        assert engine.tax_rate == pytest.approx(0.001)
        assert engine.price_band == pytest.approx(0.07)
        assert engine.position_limit == 5000

    def test_config_overrides(self) -> None:
        engine = _make_engine(
            margin_rate=0.20,
            maintenance_ratio=0.85,
            commission_per_contract=3000.0,
            tax_rate=0.0005,
            price_band=0.05,
            position_limit=200,
            slippage=0.0001,
        )
        assert engine.margin_rate == pytest.approx(0.20)
        assert engine.maintenance_ratio == pytest.approx(0.85)
        assert engine.commission_per_contract == pytest.approx(3000.0)
        assert engine.tax_rate == pytest.approx(0.0005)
        assert engine.price_band == pytest.approx(0.05)
        assert engine.position_limit == 200
        assert engine.slippage_rate == pytest.approx(0.0001)

    def test_leverage_derived_from_margin(self) -> None:
        engine = _make_engine(margin_rate=0.17)
        assert engine.default_leverage == pytest.approx(1.0 / 0.17)

    def test_leverage_with_custom_margin(self) -> None:
        engine = _make_engine(margin_rate=0.20)
        assert engine.default_leverage == pytest.approx(5.0)

    def test_invalid_margin_rate_rejected(self) -> None:
        with pytest.raises(ValueError):
            _make_engine(margin_rate=0.0)
        with pytest.raises(ValueError):
            _make_engine(margin_rate=-0.1)

    def test_initial_state(self) -> None:
        engine = _make_engine()
        assert engine._prior_settle == {}
        assert engine._pending_liquidation == set()
        assert engine._expired == set()
        assert engine.settlements == []


# ---------------------------------------------------------------------------
# Group C — Multiplier
# ---------------------------------------------------------------------------


class TestMultiplier:
    @pytest.mark.parametrize(
        "symbol", ["VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"],
    )
    def test_multiplier_known_contract(self, symbol: str) -> None:
        engine = _make_engine()
        assert engine.get_contract_multiplier(symbol) == 100_000.0

    def test_multiplier_with_hnx_suffix(self) -> None:
        engine = _make_engine()
        assert engine.get_contract_multiplier("VN30F1M.HNX") == 100_000.0

    @pytest.mark.parametrize("symbol", ["VNM", "XYZ", "IF2406.CFFEX", ""])
    def test_multiplier_unknown_raises(self, symbol: str) -> None:
        engine = _make_engine()
        with pytest.raises(ValueError):
            engine.get_contract_multiplier(symbol)


# ---------------------------------------------------------------------------
# Group D — can_execute symbol filtering
# ---------------------------------------------------------------------------


class TestCanExecuteSymbol:
    @pytest.mark.parametrize(
        "symbol", ["VNM", "BTC-USDT", "IF2406.CFFEX", "SHB.HNX", "000001.SZ"],
    )
    def test_rejects_non_vn30f(self, symbol: str) -> None:
        engine = _make_engine()
        bar = _bar_with_pct(close=100, pre_close=100)
        assert engine.can_execute(symbol, 1, bar) is False

    def test_accepts_vn30f(self) -> None:
        engine = _make_engine()
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, bar) is True

    def test_accepts_vn30f_with_hnx_suffix(self) -> None:
        engine = _make_engine()
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M.HNX", 1, bar) is True


# ---------------------------------------------------------------------------
# Group E — can_execute price band
# ---------------------------------------------------------------------------


class TestCanExecutePriceBand:
    def test_buy_at_band_blocked(self) -> None:
        engine = _make_engine()
        bar = _bar_with_pct(close=106.95, pre_close=100)  # +6.95%
        assert engine.can_execute("VN30F1M", 1, bar) is False

    def test_buy_below_band_allowed(self) -> None:
        engine = _make_engine()
        bar = _bar_with_pct(close=105, pre_close=100)  # +5%
        assert engine.can_execute("VN30F1M", 1, bar) is True

    def test_sell_at_lower_band_blocked(self) -> None:
        engine = _make_engine()
        engine.positions["VN30F1M"] = _make_position("VN30F1M", direction=1)
        bar = _bar_with_pct(close=93.05, pre_close=100)  # -6.95%
        assert engine.can_execute("VN30F1M", 0, bar) is False

    def test_short_at_lower_band_blocked(self) -> None:
        engine = _make_engine()
        bar = _bar_with_pct(close=93.05, pre_close=100)  # -6.95%
        assert engine.can_execute("VN30F1M", -1, bar) is False

    def test_cover_short_at_upper_band_blocked(self) -> None:
        engine = _make_engine()
        engine.positions["VN30F1M"] = _make_position("VN30F1M", direction=-1)
        bar = _bar_with_pct(close=106.95, pre_close=100)  # +6.95%
        assert engine.can_execute("VN30F1M", 0, bar) is False

    def test_normal_pct_no_block(self) -> None:
        engine = _make_engine()
        engine.positions["VN30F1M"] = _make_position("VN30F1M", direction=1)
        bar = _bar_with_pct(close=102, pre_close=100)  # +2%
        assert engine.can_execute("VN30F1M", 1, bar) is True
        assert engine.can_execute("VN30F1M", -1, bar) is True
        assert engine.can_execute("VN30F1M", 0, bar) is True

    def test_band_check_skipped_when_pct_undefined(self) -> None:
        """Bar without pre_close (no derivable pct) should not block."""
        engine = _make_engine()
        bar = pd.Series({"close": 1200})
        assert engine.can_execute("VN30F1M", 1, bar) is True


# ---------------------------------------------------------------------------
# Group F — can_execute position limit
# ---------------------------------------------------------------------------


class TestCanExecutePositionLimit:
    def test_position_limit_blocks_open(self) -> None:
        engine = _make_engine()
        # Pre-populate with positions whose total abs(size) = 5000
        for i in range(5):
            engine.positions[f"VN30F1M_slot{i}"] = _make_position(
                "VN30F1M", direction=1, size=1000.0,
            )
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, bar) is False
        assert engine.can_execute("VN30F1M", -1, bar) is False

    def test_position_limit_allows_close(self) -> None:
        engine = _make_engine()
        for i in range(5):
            engine.positions[f"VN30F1M_slot{i}"] = _make_position(
                "VN30F1M", direction=1, size=1000.0,
            )
        # Place an actual closeable position under the right key
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0,
        )
        bar = _bar_with_pct(close=1200, pre_close=1200)
        # Closing leg does not check the limit branch
        assert engine.can_execute("VN30F1M", 0, bar) is True

    def test_below_position_limit_allows_open(self) -> None:
        engine = _make_engine()
        for i in range(4):
            engine.positions[f"VN30F1M_slot{i}"] = _make_position(
                "VN30F1M", direction=1, size=1000.0,
            )
        # Add a smaller fifth slot — total = 4900, under 5000
        engine.positions["VN30F1M_slot4"] = _make_position(
            "VN30F1M", direction=1, size=900.0,
        )
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, bar) is True

    def test_position_limit_exact_threshold_blocks(self) -> None:
        """At exactly 5000 contracts, opening another lot is blocked."""
        engine = _make_engine(position_limit=5000)
        engine.positions["VN30F1M_slot"] = _make_position(
            "VN30F1M", direction=1, size=5000.0,
        )
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, bar) is False


# ---------------------------------------------------------------------------
# Group G — can_execute expiry rejection
# ---------------------------------------------------------------------------


class TestCanExecuteExpiry:
    def test_expired_contract_rejected(self) -> None:
        engine = _make_engine()
        engine._expired.add("VN30F1M")
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, bar) is False
        assert engine.can_execute("VN30F1M", -1, bar) is False
        assert engine.can_execute("VN30F1M", 0, bar) is False

    def test_expired_contract_rejected_with_hnx_suffix(self) -> None:
        engine = _make_engine()
        engine._expired.add("VN30F1M")
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M.HNX", 1, bar) is False


# ---------------------------------------------------------------------------
# Group H — can_execute pending liquidation
# ---------------------------------------------------------------------------


class TestCanExecutePendingLiquidation:
    def test_pending_liquidation_blocks_opens(self) -> None:
        engine = _make_engine()
        engine.positions["VN30F1M"] = _make_position("VN30F1M", direction=1)
        engine._pending_liquidation.add("VN30F1M")
        bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, bar) is False
        assert engine.can_execute("VN30F1M", -1, bar) is False
        # Closing the existing position is allowed
        assert engine.can_execute("VN30F1M", 0, bar) is True

    def test_pending_liquidation_close_without_pos_blocked(self) -> None:
        engine = _make_engine()
        engine._pending_liquidation.add("VN30F1M")
        bar = _bar_with_pct(close=1200, pre_close=1200)
        # No position to close — even direction=0 returns False
        assert engine.can_execute("VN30F1M", 0, bar) is False


# ---------------------------------------------------------------------------
# Group I — round_size
# ---------------------------------------------------------------------------


class TestRoundSize:
    def test_round_size_floors_abs(self) -> None:
        engine = _make_engine()
        assert engine.round_size(5.7, 1200.0) == 5
        assert engine.round_size(5.0, 1200.0) == 5
        assert engine.round_size(0.4, 1200.0) == 0

    def test_round_size_negative_to_abs(self) -> None:
        engine = _make_engine()
        assert engine.round_size(-3.2, 1200.0) == 3
        assert engine.round_size(-7.9, 1200.0) == 7

    def test_round_size_zero(self) -> None:
        engine = _make_engine()
        assert engine.round_size(0.0, 1200.0) == 0


# ---------------------------------------------------------------------------
# Group J — calc_commission
# ---------------------------------------------------------------------------


class TestCalcCommission:
    def test_commission_open_one_contract(self) -> None:
        engine = _make_engine()
        # 1 * 2700 + 1 * 1200 * 100_000 * 0.001 = 2700 + 120_000 = 122_700
        comm = engine.calc_commission(1, 1200.0, direction=1, is_open=True)
        assert comm == pytest.approx(122_700.0)

    def test_commission_close_same_formula(self) -> None:
        engine = _make_engine()
        comm = engine.calc_commission(1, 1200.0, direction=-1, is_open=False)
        assert comm == pytest.approx(122_700.0)

    def test_commission_multi_contract(self) -> None:
        engine = _make_engine()
        # 5 * 2700 + 5 * 1200 * 100_000 * 0.001 = 13_500 + 600_000 = 613_500
        comm = engine.calc_commission(5, 1200.0, direction=1, is_open=True)
        assert comm == pytest.approx(613_500.0)

    def test_custom_commission_per_contract(self) -> None:
        engine = _make_engine(commission_per_contract=5000)
        # 1 * 5000 + 1 * 1200 * 100_000 * 0.001 = 5000 + 120_000 = 125_000
        comm = engine.calc_commission(1, 1200.0, direction=1, is_open=True)
        assert comm == pytest.approx(125_000.0)

    def test_custom_tax_rate(self) -> None:
        engine = _make_engine(tax_rate=0.0005)
        # 1 * 2700 + 1 * 1200 * 100_000 * 0.0005 = 2700 + 60_000 = 62_700
        comm = engine.calc_commission(1, 1200.0, direction=1, is_open=True)
        assert comm == pytest.approx(62_700.0)

    def test_commission_negative_size_uses_abs(self) -> None:
        engine = _make_engine()
        comm = engine.calc_commission(-3, 1200.0, direction=-1, is_open=True)
        # 3 * 2700 + 3 * 1200 * 100_000 * 0.001 = 8100 + 360_000 = 368_100
        assert comm == pytest.approx(368_100.0)


# ---------------------------------------------------------------------------
# Group K — Daily mark-to-market via _after_bar_close
# ---------------------------------------------------------------------------


class TestDailyMarkToMarket:
    def test_mtm_long_profit(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        prev = engine.capital
        bar = _mtm_bar(1210.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital - prev == pytest.approx(1_000_000.0)
        # Verify settlement record
        mtm_recs = [s for s in engine.settlements if s["type"] == "mtm"]
        assert len(mtm_recs) == 1
        assert mtm_recs[0]["pnl"] == pytest.approx(1_000_000.0)

    def test_mtm_long_loss(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        prev = engine.capital
        bar = _mtm_bar(1180.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital - prev == pytest.approx(-2_000_000.0)

    def test_mtm_short_profit(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=-1, size=1.0, entry_price=1200.0,
        )
        prev = engine.capital
        bar = _mtm_bar(1180.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital - prev == pytest.approx(2_000_000.0)

    def test_mtm_short_loss(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=-1, size=1.0, entry_price=1200.0,
        )
        prev = engine.capital
        bar = _mtm_bar(1210.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital - prev == pytest.approx(-1_000_000.0)

    def test_mtm_updates_prior_settle(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        bar = _mtm_bar(1210.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine._prior_settle["VN30F1M"] == pytest.approx(1210.0)

    def test_mtm_subsequent_uses_prior_settle(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        # Day 1: close = 1210 → +1M
        bar1 = _mtm_bar(1210.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar1)
        cap_after_day1 = engine.capital
        # Day 2: close = 1220 → P&L versus prior settle (1210), not entry (1200)
        bar2 = _mtm_bar(1220.0, when=date(2024, 5, 13))
        engine._after_bar_close(bar2)
        assert engine.capital - cap_after_day1 == pytest.approx(1_000_000.0)

    def test_mtm_skips_non_vn30f(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        # Inject a non-VN30F position; engine should ignore it.
        engine.positions["VNM.HOSE"] = _make_position(
            "VNM.HOSE", direction=1, size=100.0, entry_price=100.0,
        )
        prev = engine.capital
        bar = pd.Series({"VNM.HOSE": 110.0})
        bar.name = pd.Timestamp(date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital == prev
        assert engine.settlements == []

    def test_mtm_handles_missing_symbol_in_bar(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        prev = engine.capital
        # Bar with a different symbol — VN30F1M missing
        bar = pd.Series({"VN30F2M": 1300.0})
        bar.name = pd.Timestamp(date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital == prev

    def test_mtm_skips_nan_close(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        prev = engine.capital
        bar = pd.Series({"VN30F1M": float("nan")})
        bar.name = pd.Timestamp(date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital == prev

    def test_mtm_no_op_when_no_positions(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        prev = engine.capital
        bar = _mtm_bar(1210.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert engine.capital == prev


# ---------------------------------------------------------------------------
# Group L — Margin call simulation
# ---------------------------------------------------------------------------


class TestMarginCall:
    def test_margin_call_triggered_on_breach(self) -> None:
        # Small initial capital so a moderate loss breaches maintenance.
        # 1 contract @ 1200 → notional = 120_000_000, margin = 20_400_000,
        # maintenance = 16_320_000. Start with capital = 18_000_000 (ample
        # margin), then take a 5_000_000 loss → capital = 13_000_000 < 16.32M.
        engine = _make_engine(initial_cash=18_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        # Close = 1150 → 1 * 100_000 * (1150 - 1200) = -5_000_000
        bar = _mtm_bar(1150.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert "VN30F1M" in engine._pending_liquidation

    def test_margin_call_logs_event(self) -> None:
        engine = _make_engine(initial_cash=18_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        bar = _mtm_bar(1150.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        mc_recs = [s for s in engine.settlements if s["type"] == "margin_call"]
        assert len(mc_recs) == 1
        assert mc_recs[0]["symbol"] == "VN30F1M"
        assert mc_recs[0]["date"] == date(2024, 5, 10)

    def test_no_margin_call_when_safe(self) -> None:
        # Plenty of capital — small loss does not breach.
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        bar = _mtm_bar(1199.0, when=date(2024, 5, 10))
        engine._after_bar_close(bar)
        assert "VN30F1M" not in engine._pending_liquidation
        assert not [s for s in engine.settlements if s["type"] == "margin_call"]


# ---------------------------------------------------------------------------
# Group M — Expiry settlement
# ---------------------------------------------------------------------------


class TestExpirySettlement:
    def test_expiry_marks_position_expired(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        # 2024-05-16 is the third Thursday of May 2024
        bar = _mtm_bar(1210.0, when=date(2024, 5, 16))
        engine._after_bar_close(bar)
        assert "VN30F1M" in engine._expired
        assert "VN30F1M" not in engine.positions
        expiry_recs = [
            s for s in engine.settlements if s["type"] == "expiry_settlement"
        ]
        assert len(expiry_recs) == 1
        assert expiry_recs[0]["settle_price"] == pytest.approx(1210.0)

    def test_expiry_no_double_count(self) -> None:
        """MTM realises P&L to close; expiry releases margin only.

        Final capital change vs initial = MTM P&L + released margin.
        For 1 contract @ entry 1200, settle 1210, leverage 1/0.17:
          mtm = 100_000 * (1210 - 1200) = 1_000_000
          margin released = 1 * 1200 * 100_000 / (1/0.17) = 20_400_000
        So total capital should change by exactly +21_400_000 — never
        the position notional itself (which would imply double-count).
        """
        initial = 1_000_000_000
        engine = _make_engine(initial_cash=initial)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
            leverage=1.0 / 0.17,
        )
        bar = _mtm_bar(1210.0, when=date(2024, 5, 16))
        engine._after_bar_close(bar)
        # Expected delta: 1_000_000 (MTM) + 20_400_000 (margin release)
        expected_delta = 1_000_000.0 + (1.0 * 1200.0 * 100_000.0 * 0.17)
        assert engine.capital - initial == pytest.approx(expected_delta)

    def test_after_expiry_executions_blocked(self) -> None:
        engine = _make_engine(initial_cash=1_000_000_000)
        engine.positions["VN30F1M"] = _make_position(
            "VN30F1M", direction=1, size=1.0, entry_price=1200.0,
        )
        bar = _mtm_bar(1210.0, when=date(2024, 5, 16))
        engine._after_bar_close(bar)
        # Now post-expiry, can_execute returns False for any direction.
        check_bar = _bar_with_pct(close=1200, pre_close=1200)
        assert engine.can_execute("VN30F1M", 1, check_bar) is False
        assert engine.can_execute("VN30F1M", -1, check_bar) is False
        assert engine.can_execute("VN30F1M", 0, check_bar) is False


# ---------------------------------------------------------------------------
# Group N — Composite routing
# ---------------------------------------------------------------------------


class TestCompositeRouting:
    def test_routing_vn30f_bare(self) -> None:
        assert _detect_market("VN30F1M") == "vn_futures"
        assert _detect_market("VN30F2Q") == "vn_futures"

    def test_routing_vn30f_hnx(self) -> None:
        assert _detect_market("VN30F1M.HNX") == "vn_futures"
        assert _detect_market("VN30F2Q.HNX") == "vn_futures"

    def test_routing_equity_hnx_unaffected(self) -> None:
        # Plain equity ticker on HNX must NOT be routed to vn_futures.
        assert _detect_market("SHB.HNX") == "vn_equity"
        assert _detect_market("ACB.HNX") == "vn_equity"

    def test_routing_a_share_unaffected(self) -> None:
        assert _detect_market("000001.SZ") == "a_share"
        assert _detect_market("600519.SH") == "a_share"
