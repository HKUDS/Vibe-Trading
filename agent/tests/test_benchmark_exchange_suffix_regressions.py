import pandas as pd
import pytest
from backtest.benchmark import resolve_benchmark


@pytest.mark.parametrize("symbol", ["600000.SH", "600000.SS", "000001.SZ", "830799.BJ"])
@pytest.mark.parametrize("source", ["local", "baostock", "yfinance"])
def test_explicit_ashare_suffix_selects_csi300_benchmark(symbol, source):
    seen = []

    class Loader:
        name = source

        def fetch(self, codes, *args, **kwargs):
            seen.extend(codes)
            return {
                codes[0]: pd.DataFrame(
                    {"close": [100.0, 110.0]},
                    index=pd.date_range("2025-01-01", periods=2),
                )
            }

    result = resolve_benchmark(
        [symbol], source, "2025-01-01", "2025-01-02", loader=Loader()
    )
    assert seen == ["000300.SH"]
    assert result is not None
    assert result.ticker == "000300.SH"
    assert result.total_ret == pytest.approx(0.1)


@pytest.mark.parametrize(("codes", "ticker"), [
    (["VOD.L"], "^FTSE"), (["GGAL.BA"], "^MERV"), (["005930.KS"], "^KS11"),
    (["7203.T"], None), (["EURUSD=X"], None), (["VIC.VN"], None),
    (["IF2406.CFFEX"], None), (["AAPL.US", "0700.HK"], None),
    (["local:VOD.L", "SHEL.L"], "^FTSE"),
])
def test_auto_requires_a_shared_identified_market(codes, ticker):
    from backtest.benchmark import default_benchmark

    assert default_benchmark(codes, "local") == ticker
