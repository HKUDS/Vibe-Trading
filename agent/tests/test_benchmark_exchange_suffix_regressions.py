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
