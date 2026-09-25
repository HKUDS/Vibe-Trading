"""Tests for baostock_loader: code format handling and bounded failures.

Ensures both baostock native (sh.601398) and tushare-style (601398.SH) codes work.
"""

import multiprocessing
import os
import socket
import sys
import threading
import importlib

import pandas as pd
import pytest

from backtest.loaders.baostock_loader import _is_a_share


def _run_market_data_case(port: int, mode: str, fake_module_dir: str, result_queue) -> None:
    import backtest.loaders.baostock_loader as module
    from backtest.loaders.baostock_loader import DataLoader
    from src.market_data import fetch_market_data

    module.BAOSTOCK_FETCH_TIMEOUT_SECONDS = 0.2

    sys.path.insert(0, fake_module_dir)
    sys.modules.pop("baostock", None)
    sys.modules["baostock"] = importlib.import_module("baostock")
    os.environ["FAKE_BAOSTOCK_PORT"] = str(port)
    os.environ["FAKE_BAOSTOCK_MODE"] = mode
    os.environ["PYTHONPATH"] = fake_module_dir + os.pathsep + os.environ.get("PYTHONPATH", "")

    class FallbackLoader:
        def fetch(self, codes, start_date, end_date, *, interval="1D"):
            frame = pd.DataFrame(
                {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
                index=pd.to_datetime(["2024-01-01"]),
            )
            return {codes[0]: frame}

    original_get_context = module.multiprocessing.get_context
    if os.name != "nt":
        fork_context = multiprocessing.get_context("fork")
        module.multiprocessing.get_context = lambda *args: fork_context
    try:
        result = fetch_market_data(
            codes=["999999.SH"],
            start_date="2024-01-01",
            end_date="2024-01-02",
            source="baostock",
            loader_resolver=lambda source: DataLoader if source == "baostock" else FallbackLoader,
            fallback_chain_provider=lambda source: ["baostock", "fallback"],
            max_fallback_attempts=2,
        )
        result_queue.put(result)
    except BaseException as exc:
        result_queue.put({"error": repr(exc)})
    finally:
        module.multiprocessing.get_context = original_get_context


@pytest.mark.parametrize("mode", ["silent", "closed"])
@pytest.mark.skipif(os.name == "nt", reason="fake module cannot cross the spawn boundary")
def test_baostock_server_failure_is_bounded_and_falls_back(mode, tmp_path, monkeypatch):
    (tmp_path / "baostock.py").write_text(
        "import os\n"
        "import socket\n\n"
        "def login():\n"
        "    return type('Login', (), {'error_code': '0', 'error_msg': 'success'})()\n\n"
        "def logout():\n"
        "    return None\n\n"
        "def query_history_k_data_plus(*args, **kwargs):\n"
        "    connection = socket.create_connection(('127.0.0.1', int(os.environ['FAKE_BAOSTOCK_PORT'])))\n"
        "    if os.environ['FAKE_BAOSTOCK_MODE'] == 'closed':\n"
        "        connection.close()\n"
        "        while True:\n"
        "            pass\n"
        "    else:\n"
        "        connection.recv(1)\n"
        "    return type('Result', (), {'error_code': '0', 'error_msg': 'success'})()\n"
    )
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    accepted = threading.Event()

    def accept_connection():
        connection, _ = server.accept()
        accepted.set()
        if mode == "silent":
            connection.recv(1)
        connection.close()

    accept_thread = threading.Thread(target=accept_connection, daemon=True)
    accept_thread.start()
    result_queue = multiprocessing.get_context("fork").Queue()
    process = multiprocessing.get_context("fork").Process(
        target=_run_market_data_case,
        args=(port, mode, str(tmp_path), result_queue),
    )
    process.start()
    process.join(timeout=2)
    try:
        result = result_queue.get(timeout=1)
        assert accepted.wait(timeout=1), f"fake server was not reached (exit={process.exitcode}, result={result})"
        assert process.exitcode == 0, "loader did not finish within the deadline"
        assert result["999999.SH"]
    finally:
        if process.is_alive():
            process.kill()
        process.join(timeout=1)
        server.close()
        accept_thread.join(timeout=1)


class TestIsAShareCodeFormat:
    """Verify _is_a_share accepts both baostock native and tushare-style codes."""

    def test_baostock_native_sh_format(self):
        """sh.601398 is the baostock-native format and should be recognized."""
        assert _is_a_share("sh.601398") is True
        assert _is_a_share("sh.600036") is True

    def test_baostock_native_sz_format(self):
        """sz.000001 is the baostock-native format and should be recognized."""
        assert _is_a_share("sz.000001") is True
        assert _is_a_share("sz.002594") is True

    def test_tushare_style_sh_suffix(self):
        """600036.SH is the tushare-style format and should be recognized."""
        assert _is_a_share("600036.SH") is True
        assert _is_a_share("601398.SH") is True

    def test_tushare_style_sz_suffix(self):
        """000001.SZ is the tushare-style format and should be recognized."""
        assert _is_a_share("000001.SZ") is True
        assert _is_a_share("002594.SZ") is True

    def test_case_insensitive(self):
        """Code format detection should be case-insensitive."""
        assert _is_a_share("SH.601398") is True
        assert _is_a_share("sh.601398") is True
        assert _is_a_share("601398.sh") is True
        assert _is_a_share("601398.SH") is True

    def test_rejects_non_a_share(self):
        """Non-A-share codes should be rejected."""
        assert _is_a_share("AAPL") is False
        assert _is_a_share("BRK.B") is False
        assert _is_a_share("BTC-USD") is False
        assert _is_a_share("") is False
        assert _is_a_share("just_random_text") is False

    def test_rejects_hk_and_us_codes(self):
        """Hong Kong (5-digit) and US stock codes should not match."""
        assert _is_a_share("00700") is False
        assert _is_a_share("AAPL") is False
        assert _is_a_share("TSLA") is False


class TestFetchOneCodeHandling:
    """Verify _fetch_one handles both baostock native and tushare-style codes.

    These tests are unit-level only — they don't make real network calls.
    """

    def test_baostock_native_passthrough(self):
        """baostock native format (sh.601398) should pass through unchanged."""
        from unittest.mock import MagicMock
        from backtest.loaders.baostock_loader import DataLoader

        loader = DataLoader()
        bs_mock = MagicMock()
        mock_rs = MagicMock()
        mock_rs.error_code = "0"
        mock_rs.error_msg = "success"
        mock_rs.next.side_effect = [False]
        bs_mock.query_history_k_data_plus.return_value = mock_rs

        loader._fetch_one(bs_mock, "sh.601398", "2024-01-01", "2024-01-31")
        call_args = bs_mock.query_history_k_data_plus.call_args
        assert call_args[0][0] == "sh.601398"

    def test_tushare_style_converted(self):
        """tushare-style format (601398.SH) should be converted to sh.601398."""
        from unittest.mock import MagicMock
        from backtest.loaders.baostock_loader import DataLoader

        loader = DataLoader()
        bs_mock = MagicMock()
        mock_rs = MagicMock()
        mock_rs.error_code = "0"
        mock_rs.error_msg = "success"
        mock_rs.next.side_effect = [False]
        bs_mock.query_history_k_data_plus.return_value = mock_rs

        loader._fetch_one(bs_mock, "601398.SH", "2024-01-01", "2024-01-31")
        call_args = bs_mock.query_history_k_data_plus.call_args
        assert call_args[0][0] == "sh.601398"

    def test_tushare_sz_style_converted(self):
        """tushare-style SZ (000001.SZ) should be converted to sz.000001."""
        from unittest.mock import MagicMock
        from backtest.loaders.baostock_loader import DataLoader

        loader = DataLoader()
        bs_mock = MagicMock()
        mock_rs = MagicMock()
        mock_rs.error_code = "0"
        mock_rs.error_msg = "success"
        mock_rs.next.side_effect = [False]
        bs_mock.query_history_k_data_plus.return_value = mock_rs

        loader._fetch_one(bs_mock, "000001.SZ", "2024-01-01", "2024-01-31")
        call_args = bs_mock.query_history_k_data_plus.call_args
        assert call_args[0][0] == "sz.000001"


class TestVolumeUnitNormalization:
    """BaoStock native shares are normalized to board lots (#1062)."""

    def test_volume_shares_normalized_to_lots(self):
        from unittest.mock import MagicMock
        from backtest.loaders.baostock_loader import DataLoader

        loader = DataLoader()
        bs_mock = MagicMock()
        mock_rs = MagicMock()
        mock_rs.error_code = "0"
        mock_rs.error_msg = "success"
        mock_rs.next.side_effect = [True, False]
        mock_rs.get_row_data.return_value = [
            "2024-01-02",
            "10.0",
            "10.5",
            "9.8",
            "10.2",
            "5512800",
            "7400000000",
        ]
        bs_mock.query_history_k_data_plus.return_value = mock_rs

        df = loader._fetch_one(bs_mock, "601398.SH", "2024-01-01", "2024-01-31")

        assert df["volume"].iloc[-1] == 55128.0

    def test_odd_lot_volume_keeps_fractional_lots(self):
        from unittest.mock import MagicMock
        from backtest.loaders.baostock_loader import DataLoader

        loader = DataLoader()
        bs_mock = MagicMock()
        mock_rs = MagicMock()
        mock_rs.error_code = "0"
        mock_rs.error_msg = "success"
        mock_rs.next.side_effect = [True, False]
        mock_rs.get_row_data.return_value = [
            "2024-01-02",
            "10.0",
            "10.5",
            "9.8",
            "10.2",
            "5512753",
            "7400000000",
        ]
        bs_mock.query_history_k_data_plus.return_value = mock_rs

        df = loader._fetch_one(bs_mock, "601398.SH", "2024-01-01", "2024-01-31")

        assert abs(df["volume"].iloc[-1] - 55127.53) < 1e-9
