"""Tests for the #1541 additive -> multiplicative caliber conversion.

A-share qfq from Tencent/Eastmoney/AKShare is dividend-additive: returns
computed on it are not total returns. The loaders now convert to the
multiplicative convention when the raw companion supports it, and stamp the
frame ``split_dividend`` so provenance stops warning.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.loaders.additive_conversion import convert_additive_to_multiplicative


def _frame(closes, volumes=None, start="2024-01-01"):
    n = len(closes)
    index = pd.date_range(start, periods=n, freq="B", name="trade_date")
    volumes = volumes if volumes is not None else [1000.0] * n
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def _two_action_series():
    """Raw closes with two 2-per-share dividends at bar 3 and bar 6.

    Trend rises 1 per bar; each ex-date drops the price by the dividend (2),
    and the additive qfq subtracts each dividend from every earlier bar, so
    its offsets are -4 / -2 / 0 in three plateaus.
    """
    raw = [100.0, 101.0, 102.0, 99.0, 100.0, 101.0, 98.0, 99.0]
    additive = [96.0, 97.0, 98.0, 97.0, 98.0, 99.0, 98.0, 99.0]
    return _frame(raw), _frame(additive)


class TestConvertAdditiveToMultiplicative:
    def test_two_dividends_convert_to_multiplicative(self):
        raw, additive = _two_action_series()
        converted = convert_additive_to_multiplicative(raw, additive)
        assert converted is not None

        # Factors: (102-2)/102 and (101-2)/101; anchored at the last bar.
        f1 = 100.0 / 102.0
        f2 = 99.0 / 101.0
        expected = [
            100.0 * f1 * f2,
            101.0 * f1 * f2,
            102.0 * f1 * f2,
            99.0 * f2,
            100.0 * f2,
            101.0 * f2,
            98.0,
            99.0,
        ]
        assert converted["close"].tolist() == pytest.approx(expected, rel=1e-9)

        # The converted close-to-close return across each ex-date matches the
        # (prev - dividend)/prev convention the reference series use, while
        # the additive series distorts it.
        r_before = raw["close"].iloc[2]
        r_after = raw["close"].iloc[3]
        c_before = converted["close"].iloc[2]
        c_after = converted["close"].iloc[3]
        conventional_return = r_after / (r_before - 2.0) - 1
        assert c_after / c_before - 1 == pytest.approx(conventional_return, rel=1e-9)
        assert additive["close"].iloc[3] / additive["close"].iloc[2] - 1 != pytest.approx(conventional_return, abs=1e-6)

    def test_volume_scales_inversely_and_columns_untouched(self):
        raw, additive = _two_action_series()
        converted = convert_additive_to_multiplicative(raw, additive)
        assert converted is not None
        f1 = 100.0 / 102.0
        f2 = 99.0 / 101.0
        assert converted["volume"].iloc[-1] == 1000.0
        assert converted["volume"].iloc[0] == pytest.approx(1000.0 / (f1 * f2), rel=1e-9)

    def test_no_actions_keeps_todays_series(self):
        raw = _frame([10.0, 11.0, 12.0])
        additive = _frame([10.0, 11.0, 12.0])
        # No in-window corporate action means nothing to convert; the caller
        # keeps the served series and its static stamp rather than relabeling
        # an identical frame as multiplicative.
        assert convert_additive_to_multiplicative(raw, additive) is None

    def test_wobble_bar_folds_into_its_level(self):
        # One quote-glitch bar sits inside an otherwise constant offset: the
        # structural rule folds it and the two real dividends still convert.
        raw, additive = _two_action_series()
        additive.iloc[4, additive.columns.get_loc("close")] += 0.03
        for col in ("open", "high", "low"):
            additive.iloc[4, additive.columns.get_loc(col)] += 0.03
        converted = convert_additive_to_multiplicative(raw, additive)
        assert converted is not None
        f1 = 100.0 / 102.0
        f2 = 99.0 / 101.0
        assert converted["close"].iloc[0] == pytest.approx(100.0 * f1 * f2, rel=1e-9)
        assert converted["close"].iloc[-1] == pytest.approx(99.0, rel=1e-9)

    def test_unclassifiable_one_bar_plateau_refuses(self):
        # A one-bar plateau whose neighbors disagree with each other is a step
        # pair we cannot classify as noise or dividend; the window is refused
        # rather than shipped as a clean multiplicative series.
        raw = _frame([100.0, 100.0, 100.0, 100.0, 100.0])
        additive = _frame([95.0, 95.0, 98.0, 96.0, 96.0])
        assert convert_additive_to_multiplicative(raw, additive) is None

    def test_dividend_on_the_last_bar_refuses_the_window(self):
        # Dividends of 0.30 at bar 50 and 0.03 on the final bar of a flat
        # 10.00 series. The final bar is its own offset plateau, and with no
        # successor to classify it against the fold cannot tell it from a
        # wobble; converting would silently drop the 0.03.
        raw = _frame([10.0] * 50 + [9.7] * 49 + [9.67])
        additive = _frame([9.67] * 100)
        assert convert_additive_to_multiplicative(raw, additive) is None

    def test_dividend_on_the_second_bar_refuses_the_window(self):
        # The mirror at the window start: dividends of 0.03 at bar 1 and 0.30
        # at bar 50 leave bar 0 as a one-bar plateau with no predecessor.
        raw = _frame([10.0] + [9.97] * 49 + [9.67] * 50)
        additive = _frame([9.67] * 100)
        assert convert_additive_to_multiplicative(raw, additive) is None

    def test_misaligned_calendars_fail_closed(self):
        raw, additive = _two_action_series()
        converted = convert_additive_to_multiplicative(raw.iloc[:-1], additive)
        assert converted is None

    def test_non_plateau_offsets_fail_closed(self):
        raw = _frame([100.0, 100.0, 100.0, 100.0])
        additive = _frame([95.0, 95.5, 96.0, 96.5])  # drifts bar to bar
        assert convert_additive_to_multiplicative(raw, additive) is None

    def test_dividend_at_or_above_price_fails_closed(self):
        # dividend 1.1 >= price 1.0
        raw = _frame([1.0, 1.0, 0.5, 0.5])
        additive = _frame([-0.6, -0.6, 0.5, 0.5])
        assert convert_additive_to_multiplicative(raw, additive) is None

    def test_empty_or_missing_inputs_fail_closed(self):
        raw, additive = _two_action_series()
        assert convert_additive_to_multiplicative(None, additive) is None
        assert convert_additive_to_multiplicative(raw, None) is None
        assert convert_additive_to_multiplicative(raw.iloc[:0], additive) is None


class TestLoaderWiring:
    """Each stamped-additive loader converts and tags the frame when the raw
    companion is consistent, and serves the additive frame untouched when it
    is not."""

    def _patch_fetch_pair(self, monkeypatch, loader_mod, raw, additive):
        monkeypatch.setattr(
            loader_mod,
            "cached_loader_fetch",
            lambda source, symbol, timeframe, start_date, end_date, fields, fetch: (
                raw if fields == ["raw"] else additive
            ),
        )

    def test_tencent_converts_and_stamps(self, monkeypatch):
        from backtest.loaders import tencent_loader

        raw, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, tencent_loader, raw, additive)
        out = tencent_loader.DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-10")
        df = out["600519.SH"]
        assert df.attrs["adjustment"] == "split_dividend"
        assert df["close"].iloc[-1] == pytest.approx(99.0, abs=1e-9)

    def test_tencent_keeps_additive_when_raw_missing(self, monkeypatch):
        from backtest.loaders import tencent_loader

        _, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, tencent_loader, None, additive)
        out = tencent_loader.DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-10")
        df = out["600519.SH"]
        assert df["close"].tolist() == additive["close"].tolist()

    def test_eastmoney_converts_and_stamps(self, monkeypatch):
        from backtest.loaders import eastmoney_loader

        raw, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, eastmoney_loader, raw, additive)
        out = eastmoney_loader.DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-10")
        df = out["600519.SH"]
        assert df.attrs["adjustment"] == "split_dividend"

    def test_akshare_converts_and_stamps(self, monkeypatch):
        from backtest.loaders import akshare_loader

        raw, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, akshare_loader, raw, additive)
        out = akshare_loader.DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-10")
        df = out["600519.SH"]
        assert df.attrs["adjustment"] == "split_dividend"

    def test_akshare_skips_etf_codes(self, monkeypatch):
        from backtest.loaders import akshare_loader

        _, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, akshare_loader, None, additive)
        out = akshare_loader.DataLoader().fetch(["510300.SH"], "2024-01-01", "2024-01-10")
        # ETF path is not converted; the additive frame passes through.
        assert out["510300.SH"]["close"].tolist() == additive["close"].tolist()

    def test_tencent_skips_etf_codes(self, monkeypatch):
        from backtest.loaders import tencent_loader

        _, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, tencent_loader, None, additive)
        out = tencent_loader.DataLoader().fetch(["510300.SH"], "2024-01-01", "2024-01-10")
        assert out["510300.SH"]["close"].tolist() == additive["close"].tolist()

    def test_eastmoney_skips_etf_codes(self, monkeypatch):
        from backtest.loaders import eastmoney_loader

        _, additive = _two_action_series()
        self._patch_fetch_pair(monkeypatch, eastmoney_loader, None, additive)
        out = eastmoney_loader.DataLoader().fetch(["510300.SH"], "2024-01-01", "2024-01-10")
        assert out["510300.SH"]["close"].tolist() == additive["close"].tolist()


class TestProvenancePrefersFrameStamp:
    def test_frame_adjustment_wins_over_static_table(self, monkeypatch):
        from backtest.loaders import registry
        from src.market_data import fetch_market_data

        _, additive = _two_action_series()

        class Serving:
            name = "tencent"
            markets = {"a_share"}
            volume_units = {}

            def is_available(self):
                return True

            def fetch(self, codes, start, end, interval="1D"):
                df = additive.copy()
                df.attrs = {"adjustment": "split_dividend"}
                return {code: df for code in codes}

        monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
        monkeypatch.setattr(registry, "LOADER_REGISTRY", {"tencent": Serving})
        monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"a_share": ["tencent"]})
        out = fetch_market_data(
            codes=["600519.SH"],
            start_date="2024-01-01",
            end_date="2024-01-10",
            source="tencent",
            include_provenance=True,
        )
        # The static table says tencent a_share is additive; the frame stamp
        # from the converted loader must win.
        assert out["_provenance"]["600519.SH"]["adjustment"] == "split_dividend"


class TestRawFetchFailureDegrades:
    def test_tencent_raw_failure_serves_additive(self, monkeypatch):
        from backtest.loaders import tencent_loader

        _, additive = _two_action_series()

        def flaky(source, symbol, timeframe, start_date, end_date, fields, fetch):
            if fields == ["raw"]:
                raise ConnectionError("throttled")
            return additive

        monkeypatch.setattr(tencent_loader, "cached_loader_fetch", flaky)
        out = tencent_loader.DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-10")
        df = out["600519.SH"]
        assert df["close"].tolist() == additive["close"].tolist()

    def test_akshare_raw_failure_serves_additive(self, monkeypatch):
        from backtest.loaders import akshare_loader

        _, additive = _two_action_series()

        def flaky(source, symbol, timeframe, start_date, end_date, fields, fetch):
            if fields == ["raw"]:
                raise ConnectionError("throttled")
            return additive

        monkeypatch.setattr(akshare_loader, "cached_loader_fetch", flaky)
        out = akshare_loader.DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-01-10")
        df = out["600519.SH"]
        assert df["close"].tolist() == additive["close"].tolist()
