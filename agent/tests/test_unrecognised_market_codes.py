"""A backtest refuses a code no market rule recognises.

The engine applies one market's trading rules, picked from the code. A code no
routing rule matched (``BHP.AX``, ``7203.T``, ``BRK.B``, a bare HK ``00700``)
used to fall through to the A-share default: a local dataset ran under T+1,
the +/-10% band, 100-share lots and CNY, and under ``yfinance`` the same codes
ran on US rules. Both runs succeeded, so nothing told the user.

A bare six-digit code and Yahoo's ``.SS`` Shanghai spelling stay accepted:
both are mainland listings, and the loaders and the benchmark resolve them
(``.SS`` since fbf7e2f59). The first version of this check refused ``.SS``.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest.runner import BacktestConfigSchema

_DATES = {"start_date": "2026-01-01", "end_date": "2026-03-01"}

# Every example the refusal message offers must itself be accepted.
_MESSAGE_EXAMPLES = (
    "600519.SH", "000001.SZ", "AAPL", "BRK-B.US", "00700.HK", "VOD.L", "TD.TO",
    "RELIANCE.NS", "005930.KS", "PETR4.SA", "GGAL.BA", "VNM.VN", "BTC-USDT",
    "EURUSD", "^GSPC", "IF2406.CFFEX",
)


@pytest.mark.parametrize(
    "codes, refused",
    [
        (["BHP.AX"], "BHP.AX"),
        (["local:7203.T"], "local:7203.T"),
        (["AAPL.US", "BRK.B"], "BRK.B"),
        (["00700"], "00700"),
        (["60051.SS"], "60051.SS"),
    ],
)
def test_an_unrecognised_code_is_refused(codes: list[str], refused: str) -> None:
    with pytest.raises(ValueError, match="no market rule recognises") as caught:
        BacktestConfigSchema(codes=codes, **_DATES)
    assert refused in str(caught.value)


@pytest.mark.parametrize(
    "code", ["600519", "local:000001", " 600519.SH ", "600519.SS", "local:601857.ss"]
)
def test_mainland_spellings_and_padded_codes_are_accepted(code: str) -> None:
    assert BacktestConfigSchema(codes=[code], **_DATES).codes == [code]


@pytest.mark.parametrize("code", ["CF501", "MA501", "ta501", "local:SR501"])
def test_bare_three_digit_china_futures_are_accepted(code: str) -> None:
    """Zhengzhou's bare month code is the same contract as CF501.ZCE."""
    assert BacktestConfigSchema(codes=[code], **_DATES).codes == [code]


@pytest.mark.parametrize(
    "code", ["CL501", "IF501", "RB501", "CS501", "C2412"]
)
def test_a_non_zce_three_digit_code_is_still_refused(code: str) -> None:
    with pytest.raises(ValueError, match=f"no market rule recognises {code}"):
        BacktestConfigSchema(codes=[code], **_DATES)


def test_every_example_in_the_refusal_is_accepted() -> None:
    with pytest.raises(ValueError) as caught:
        BacktestConfigSchema(codes=["BHP.AX"], **_DATES)
    for code in _MESSAGE_EXAMPLES:
        assert code in str(caught.value), code
        BacktestConfigSchema(codes=[code], **_DATES)


def test_a_local_dataset_under_an_unrecognised_code_is_refused_before_any_run(
    tmp_path, monkeypatch, capsys
) -> None:
    """End to end: this dataset used to load and run under China A-share rules."""
    import dotenv

    import backtest.loaders.local_loader as local_loader
    from backtest import runner

    dates = pd.date_range("2026-01-01", periods=40, freq="B")
    prices = tmp_path / "prices.csv"
    pd.DataFrame(
        {"date": dates, "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": 1e9}
    ).to_csv(prices, index=False)
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps({"sources": [{"symbol": "BHP.AX", "type": "csv", "path": str(prices)}]}))
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", bridge)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    run = tmp_path / "run"
    (run / "code").mkdir(parents=True)
    (run / "code" / "signal_engine.py").write_text(
        "import pandas as pd\nclass SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {code: pd.Series(1.0, index=frame.index) for code, frame in data_map.items()}\n"
    )
    (run / "config.json").write_text(
        json.dumps(
            {
                "source": "local",
                "codes": ["local:BHP.AX"],
                "start_date": str(dates[0].date()),
                "end_date": str(dates[-1].date()),
            }
        )
    )

    with pytest.raises(SystemExit) as exited:
        runner.main(run)

    assert exited.value.code == 1
    error = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["error"]
    assert "no market rule recognises local:BHP.AX" in error
    assert not (run / "artifacts").exists()
