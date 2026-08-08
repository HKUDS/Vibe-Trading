"""Regression: CSI300 bench prices must be corporate-action adjusted.

``pro.daily`` returns raw prices, so a close-to-close return taken across an
ex-date spans the mechanical drop of a split or bonus issue. Measured against
Tushare's own ``pct_chg`` over 2020-2024: 300750.SZ on 2023-04-26 reads -41.82%
raw against a true +5.40%, 300124.SZ -34.26% against -1.01%, 601012.SH -24.21%
against +6.46%. The error is always negative, so every cross-sectional IC the
bench reports carried a systematic contaminant, not noise.

These tests are offline; the live validation (adjusted return vs ``pct_chg``
within 1e-5, VWAP/close ratio preserved to 2e-16) is recorded in the audit doc.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.alpha_bench_tool import _apply_qfq

_DATES = pd.to_datetime(["2023-04-24", "2023-04-25", "2023-04-26", "2023-04-27"])


def _bars(closes):
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0, 1000.0, 2000.0, 2000.0],
            "amount": [100.0, 100.0, 100.0, 100.0],
        },
        index=_DATES,
    )


def _factors(values):
    return pd.DataFrame(
        {
            "trade_date": ["20230424", "20230425", "20230426", "20230427"],
            "adj_factor": values,
        }
    )


class TestAdjustmentRemovesTheExDateJump:
    """A 2-for-1 split halves the raw price without changing the return."""

    # Price halves on the third bar. Tushare's adj_factor is cumulative and
    # rises across a corporate action (verified on 600519.SH 2022-06-30:
    # 7.4740 -> 7.5546), so a 2-for-1 split doubles it.
    _SPLIT_CLOSES = [200.0, 200.0, 100.0, 100.0]
    _SPLIT_FACTORS = [1.0, 1.0, 2.0, 2.0]

    def test_raw_prices_show_a_fabricated_fifty_percent_drop(self):
        raw = _bars(self._SPLIT_CLOSES)["close"].pct_change()

        assert raw.iloc[2] == pytest.approx(-0.5)

    def test_adjusted_prices_show_no_return_on_the_ex_date(self):
        adjusted = _apply_qfq(_bars(self._SPLIT_CLOSES), _factors(self._SPLIT_FACTORS))

        assert adjusted["close"].pct_change().iloc[2] == pytest.approx(0.0, abs=1e-12)

    def test_the_latest_bar_keeps_its_traded_price(self):
        # 前复权: the most recent bar is the anchor, so it is untouched.
        adjusted = _apply_qfq(_bars(self._SPLIT_CLOSES), _factors(self._SPLIT_FACTORS))

        assert adjusted["close"].iloc[-1] == pytest.approx(100.0)

    def test_ohlc_are_scaled_by_the_same_ratio(self):
        bars = _bars(self._SPLIT_CLOSES)
        adjusted = _apply_qfq(bars, _factors(self._SPLIT_FACTORS))

        for column in ("open", "high", "low"):
            assert adjusted[column].iloc[0] == pytest.approx(bars[column].iloc[0] * 0.5)

    def test_volume_is_put_on_the_same_basis_as_price(self):
        # Pre-split bars are restated into post-split shares, so the count doubles.
        bars = _bars(self._SPLIT_CLOSES)
        adjusted = _apply_qfq(bars, _factors(self._SPLIT_FACTORS))

        assert adjusted["volume"].iloc[0] == pytest.approx(bars["volume"].iloc[0] * 2.0)

    def test_amount_is_cash_and_is_left_alone(self):
        bars = _bars(self._SPLIT_CLOSES)
        adjusted = _apply_qfq(bars, _factors(self._SPLIT_FACTORS))

        assert adjusted["amount"].tolist() == bars["amount"].tolist()

    def test_vwap_keeps_its_relationship_to_close(self):
        # The bench derives vwap from amount/volume, so an adjustment that moved
        # close without moving volume would silently decouple the two.
        bars = _bars(self._SPLIT_CLOSES)
        adjusted = _apply_qfq(bars, _factors(self._SPLIT_FACTORS))

        raw_ratio = (bars["amount"] * 1000 / (bars["volume"] * 100)) / bars["close"]
        adj_ratio = (
            adjusted["amount"] * 1000 / (adjusted["volume"] * 100)
        ) / adjusted["close"]
        pd.testing.assert_series_equal(raw_ratio, adj_ratio)


class TestUnusableFactorsAreRefused:
    """Missing factors must drop the symbol, never fall back to raw prices."""

    _CLOSES = [100.0, 100.0, 100.0, 100.0]

    def test_none_is_refused(self):
        assert _apply_qfq(_bars(self._CLOSES), None) is None

    def test_an_empty_frame_is_refused(self):
        assert _apply_qfq(_bars(self._CLOSES), pd.DataFrame()) is None

    def test_a_frame_without_the_factor_column_is_refused(self):
        bad = pd.DataFrame({"trade_date": ["20230424"], "something_else": [1.0]})

        assert _apply_qfq(_bars(self._CLOSES), bad) is None

    def test_a_non_positive_factor_is_refused(self):
        assert _apply_qfq(_bars(self._CLOSES), _factors([1.0, 0.0, 1.0, 1.0])) is None

    def test_a_short_factor_series_is_forward_filled_not_refused(self):
        # Tushare returns one row per trading day; a trailing gap is normal and
        # must not cost the symbol its whole history.
        partial = pd.DataFrame(
            {"trade_date": ["20230424", "20230425"], "adj_factor": [2.0, 2.0]}
        )

        adjusted = _apply_qfq(_bars(self._CLOSES), partial)

        assert adjusted is not None
        assert adjusted["close"].notna().all()
