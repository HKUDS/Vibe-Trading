"""Output delays must be distinguished from legitimate indicator lookbacks."""

import json

import pytest

from backtest.signal_timing import output_delays, validate_signal_timing
from backtest.runner import BacktestConfigSchema


def _source(lines):
    return "import pandas as pd\nclass SignalEngine:\n    def generate(self, data_map):\n" + "\n".join("        " + line for line in lines)


@pytest.mark.parametrize("expression", [
    "signal.shift(1)", "signal.shift().fillna(0).astype(float)",
    "signal.shift(periods=1).clip(0, 1)", "0.5 * signal.shift(1)",
])
def test_direct_output_shift_rejected(tmp_path, expression):
    source = _source(["signal = pd.Series([0, 1, 0])", f"return {{'SPY.US': {expression}}}"])
    path = tmp_path / "signal_engine.py"
    path.write_text(source)
    with pytest.raises(ValueError, match="signal_timing_double_delay"):
        validate_signal_timing(path)
    validate_signal_timing(path, intentional_delay=1)
    with pytest.raises(ValueError, match="signal_timing_double_delay"):
        validate_signal_timing(path, intentional_delay=2)


def test_shift_alias_forwarded_through_output_dictionary():
    source = _source([
        "out = {}", "for code, df in data_map.items():",
        "    state = [0, 1, 0]", "    sig = pd.Series(state, index=df.index).shift(1)",
        "    out[code] = sig.fillna(0)", "return out",
    ])
    assert output_delays(source) == {1}


def test_lagged_state_index_forwarded_to_signal():
    source = _source([
        "state = [0, 1, 0]", "signal = [0, 0, 0]", "for i in range(1, 3):",
        "    signal[i] = state[i - 1]", "return {'SPY.US': pd.Series(signal)}",
    ])
    assert output_delays(source) == {1}


@pytest.mark.parametrize("lookback", [
    "close.rolling(20).max().shift(1)", "close.shift(1).rolling(20).max()",
])
def test_donchian_indicator_lookback_is_allowed(lookback):
    source = _source([
        "out = {}", "for code, df in data_map.items():", "    close = df['close']",
        f"    upper = {lookback}", "    out[code] = (close > upper).astype(float)", "return out",
    ])
    assert output_delays(source) == set()


def test_overwritten_intermediate_shift_is_not_returned():
    assert output_delays(_source([
        "signal = pd.Series([0, 1, 0]).shift(1)",
        "signal = pd.Series([0, 1, 0])", "return {'SPY.US': signal}",
    ])) == set()


@pytest.mark.parametrize("bad", [-1, True, 0.5, "1"])
def test_intentional_delay_must_be_nonnegative_integer(bad):
    with pytest.raises(ValueError):
        BacktestConfigSchema(codes=["SPY.US"], start_date="2026-01-01", end_date="2026-02-01",
                             intentional_signal_delay_bars=bad)


def test_bad_syntax_is_a_recoverable_source_error(tmp_path):
    path = tmp_path / "signal_engine.py"
    path.write_text("class SignalEngine:\n this is invalid !")
    with pytest.raises(ValueError, match="Invalid signal_engine.py syntax"):
        validate_signal_timing(path)


def test_intentional_delay_is_disclosed_in_run_card(tmp_path):
    from backtest.run_card import write_run_card

    config = {"engine": "daily", "codes": ["SPY.US"], "intentional_signal_delay_bars": 1}
    card = write_run_card(tmp_path, config, {})
    assert card["signal_timing"] == {"engine_delay_bars": 1, "intentional_signal_delay_bars": 1}
    assert any("intentional extra signal-delay" in w for w in card["warnings"])


@pytest.mark.parametrize("interval", ["1D", "1H"])
def test_runner_refuses_extra_shift_before_any_data_fetch(tmp_path, monkeypatch, capsys, interval):
    import backtest.runner as runner

    (tmp_path / "code").mkdir()
    (tmp_path / "code/signal_engine.py").write_text(_source([
        "signal = pd.Series([0, 1, 0])", "return {'SPY.US': signal.shift(1)}",
    ]))
    (tmp_path / "config.json").write_text(json.dumps({
        "codes": ["SPY.US"], "start_date": "2026-01-01", "end_date": "2026-02-01",
        "source": "local", "engine": "daily", "interval": interval,
    }))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    def unexpected_fetch(*args, **kwargs):
        pytest.fail("The timing guard must run before fetching data")

    monkeypatch.setattr(runner, "fetch_data_map", unexpected_fetch)
    with pytest.raises(SystemExit) as exc:
        runner.main(tmp_path)
    assert exc.value.code == 1
    assert "signal_timing_double_delay" in capsys.readouterr().out
