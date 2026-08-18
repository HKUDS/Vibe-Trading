"""Regression tests for the composite engine's single-currency requirement.

``CompositeEngine`` keeps one shared capital pool: a single cash scalar and one
equity curve. Before this guard a code set spanning CNY, USD, HKD, INR, KRW and CAD
was summed into that curve as if the units matched, and every metric derived
from it was reported without a warning. There is no FX translation layer, so
the engine refuses the run instead.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import code_currency
from backtest.engines.composite import CompositeEngine, _reject_mixed_currency


class TestCodeCurrency:
    """Every supported market maps to the currency it settles in."""

    @pytest.mark.parametrize(
        ("code", "currency"),
        [
            ("600519.SH", "CNY"),
            ("AAPL.US", "USD"),
            ("00700.HK", "HKD"),
            ("RELIANCE.NS", "INR"),
            ("005930.KS", "KRW"),
            ("TD.TO", "CAD"),
            ("PNG.V", "CAD"),
            ("VIC.VN", "VND"),
            ("IF2406.CFFEX", "CNY"),
        ],
    )
    def test_equity_and_cn_futures_currencies(self, code, currency):
        assert code_currency(code) == currency

    def test_global_futures_default_to_usd(self):
        # The GlobalFuturesEngine's margin, commission and multiplier tables are
        # USD throughout and carry no non-USD product.
        assert code_currency("ESZ4") == "USD"
        assert code_currency("ES.CME") == "USD"

    def test_a_non_usd_futures_venue_is_not_called_usd(self):
        assert code_currency("FDAX.EUREX") == "EUR"

    def test_forex_resolves_to_the_quote_currency(self):
        assert code_currency("EUR/USD") == "USD"
        assert code_currency("USDJPY.FX") == "JPY"

    def test_usdt_is_carried_at_its_usd_peg(self):
        assert code_currency("BTC-USDT") == "USD"


class TestRejectMixedCurrency:
    """The guard separates a genuinely mixed book from a merely cross-market one."""

    def test_one_currency_across_two_markets_is_allowed(self):
        _reject_mixed_currency(["AAPL.US", "ESZ4", "BTC-USDT"])

    def test_a_single_market_is_allowed(self):
        _reject_mixed_currency(["600519.SH", "000001.SZ"])

    def test_empty_and_single_code_sets_are_allowed(self):
        _reject_mixed_currency([])
        _reject_mixed_currency(["AAPL.US"])

    def test_cny_mixed_with_usd_is_refused(self):
        with pytest.raises(ValueError, match="one settlement currency"):
            _reject_mixed_currency(["600519.SH", "AAPL.US"])

    def test_canadian_and_us_equities_are_not_summed_without_fx(self):
        with pytest.raises(ValueError, match="one settlement currency"):
            _reject_mixed_currency(["TD.TO", "AAPL.US"])

    def test_vnd_is_named_rather_than_marked_unknown(self):
        # A market with no entry in the table degrades to 'UNKNOWN:<market>',
        # which still fails closed but names nothing useful in the error.
        with pytest.raises(ValueError) as excinfo:
            _reject_mixed_currency(["VIC.VN", "AAPL.US"])
        message = str(excinfo.value)
        assert "VND" in message
        assert "UNKNOWN" not in message

    def test_two_hose_symbols_are_one_currency(self):
        _reject_mixed_currency(["VIC.VN", "FPT.VN"])

    def test_the_error_names_every_currency_and_its_codes(self):
        with pytest.raises(ValueError) as excinfo:
            _reject_mixed_currency(["600519.SH", "AAPL.US", "005930.KS"])
        message = str(excinfo.value)
        for fragment in ("CNY", "USD", "KRW", "600519.SH", "AAPL.US", "005930.KS"):
            assert fragment in message


class TestRunBacktestFailsClosed:
    """A mixed run must stop before it fetches data or reports a metric."""

    class _RecordingLoader:
        def __init__(self):
            self.fetched = False

        def fetch(self, *args, **kwargs):
            self.fetched = True
            return {}

    def test_mixed_currency_run_raises_before_fetching(self):
        codes = ["600519.SH", "AAPL.US"]
        engine = CompositeEngine({"initial_cash": 1_000_000, "codes": codes}, codes)
        loader = self._RecordingLoader()

        with pytest.raises(ValueError, match="one settlement currency"):
            engine.run_backtest(
                {"initial_cash": 1_000_000, "codes": codes},
                loader,
                signal_engine=None,
                run_dir=None,
            )
        assert loader.fetched is False

    def test_constructing_a_mixed_engine_is_still_allowed(self):
        # Rule-book routing across markets is a legitimate use; only the shared
        # equity curve is unsound, so construction must not raise.
        codes = ["IF2406.CFFEX", "ESZ4"]
        engine = CompositeEngine({"initial_cash": 1_000_000, "codes": codes}, codes)
        assert engine._rule_for("IF2406.CFFEX") is not engine._rule_for("ESZ4")
