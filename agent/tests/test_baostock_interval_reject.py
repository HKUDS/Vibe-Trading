"""BaoStock must reject non-daily intervals instead of silently returning day bars."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backtest.loaders.baostock_loader import DataLoader


def test_unsupported_interval_does_not_login_or_fetch() -> None:
    """Runner ``1H`` must not fall through to baostock frequency=d."""
    loader = DataLoader()
    with patch.dict("sys.modules", {"baostock": MagicMock()}) as modules:
        fake_bs = modules["baostock"]
        out = loader.fetch(["601398.SH"], "2024-01-01", "2024-01-31", interval="1H")
    assert out == {}
    fake_bs.login.assert_not_called()


def test_daily_interval_still_attempts_login() -> None:
    loader = DataLoader()
    fake_bs = MagicMock()
    fake_lg = MagicMock()
    fake_lg.error_code = "1"
    fake_lg.error_msg = "login failed in test"
    fake_bs.login.return_value = fake_lg
    with patch.dict("sys.modules", {"baostock": fake_bs}):
        out = loader.fetch(["601398.SH"], "2024-01-01", "2024-01-31", interval="1D")
    assert out == {}
    fake_bs.login.assert_called_once()
