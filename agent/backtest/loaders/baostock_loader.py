"""BaoStock loader: free, no-auth A-share data via TCP protocol.

BaoStock (http://baostock.com) uses its own TCP protocol (not HTTP),
bypassing CDN IP blocks that affect HTTP-based data sources like
eastmoney.com.  Completely free, no API token required.

Covers: A-shares (SH/SZ), does NOT cover HK/US/crypto.
"""

from __future__ import annotations

import logging
import math
import os
import socket
import threading
import time
import zlib
from contextlib import contextmanager
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

# Per-message deadline for baostock socket IO (#1492). baostock 0.9.3
# reads with no timeout and spins at 100% CPU when the peer closes the
# connection, so every loader call goes through the guard below.
_READ_TIMEOUT_ENV = "VIBE_TRADING_BAOSTOCK_TIMEOUT"
_DEFAULT_READ_TIMEOUT = 30.0
# BaoStock owns one process-global socket and user context, even across instances.
_BAOSTOCK_LOCK = threading.Lock()


def _read_timeout() -> float:
    raw = os.getenv(_READ_TIMEOUT_ENV)  # noqa: env-gate — generic env var helper
    if raw:
        try:
            value = float(raw)
            if math.isfinite(value) and value > 0:
                return value
        except ValueError:
            pass
        logger.warning("ignoring invalid %s=%r", _READ_TIMEOUT_ENV, raw)
    return _DEFAULT_READ_TIMEOUT


def _bounded_send_msg(msg: str, timeout: float) -> Optional[str]:
    """baostock's send_msg with a whole-message deadline and EOF detection.

    Byte-compatible with baostock 0.9.3 on a healthy server. Returns None on
    timeout, closed connection, or a malformed reply; every baostock caller
    maps None to BSERR_RECVSOCK_FAIL, so a dead server becomes an ordinary
    fetch failure instead of a hang or a 100% CPU spin.
    """
    import baostock.common.contants as cons
    import baostock.common.context as context

    default_socket = getattr(context, "default_socket", None)
    if default_socket is None:
        logger.warning("baostock send before login or after a failed connect")
        return None
    try:
        previous_timeout = default_socket.gettimeout()
        deadline = time.monotonic() + timeout
        default_socket.settimeout(timeout)
        try:
            default_socket.sendall(bytes(msg + "\n", encoding="utf-8"))
            receive = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("baostock message deadline exceeded")
                default_socket.settimeout(remaining)
                chunk = default_socket.recv(8192)
                if not chunk:
                    raise ConnectionError("baostock server closed the connection mid-reply")
                receive += chunk
                if receive[-13:] == b"<![CDATA[]]>\n":
                    break
        finally:
            default_socket.settimeout(previous_timeout)
        receive = bytes(receive)
        head_bytes = receive[0 : cons.MESSAGE_HEADER_LENGTH]
        head_str = bytes.decode(head_bytes)
        head_arr = head_str.split(cons.MESSAGE_SPLIT)
        if head_arr[1] in cons.COMPRESSED_MESSAGE_TYPE_TUPLE:
            body_length = int(head_arr[2])
            body_str = bytes.decode(
                zlib.decompress(receive[cons.MESSAGE_HEADER_LENGTH : cons.MESSAGE_HEADER_LENGTH + body_length])
            )
            return head_str + body_str
        return bytes.decode(receive)
    except Exception as exc:
        logger.warning("baostock read failed: %s", exc)
        # A late or partial reply must never be consumed by a subsequent query.
        default_socket.close()
        if getattr(context, "default_socket", None) is default_socket:
            context.default_socket = None
        return None


def _connect_with_timeout(self, timeout: float) -> None:
    """SocketUtil.connect with a deadline and no unbound-socket NameError."""
    import baostock.common.contants as cons
    import baostock.common.context as context

    try:
        sock = socket.create_connection((cons.BAOSTOCK_SERVER_IP, cons.BAOSTOCK_SERVER_PORT), timeout=timeout)
    except OSError as exc:
        logger.warning("baostock connect failed: %s", exc)
        sock = None
    setattr(context, "default_socket", sock)


@contextmanager
def _baostock_socket_guard(timeout: float):
    """Bound all baostock socket IO for the lifetime of one fetch."""
    import baostock

    if not _BAOSTOCK_LOCK.acquire(timeout=timeout):
        logger.warning("baostock session busy; falling back")
        yield False
        return
    # Serialize the entire login/query/logout session, not just the patch itself.
    # Attribute chains also keep the existing sys.modules test doubles usable.
    socketutil = baostock.util.socketutil
    context = baostock.common.context
    original_send_msg = socketutil.send_msg
    original_connect = socketutil.SocketUtil.connect
    previous_socket = getattr(context, "default_socket", None)
    context.default_socket = None
    socketutil.send_msg = lambda msg: _bounded_send_msg(msg, timeout)
    socketutil.SocketUtil.connect = lambda util: _connect_with_timeout(util, timeout)
    try:
        yield True
    finally:
        try:
            current_socket = getattr(context, "default_socket", None)
            if current_socket is not None:
                current_socket.close()
        finally:
            context.default_socket = previous_socket
            socketutil.send_msg = original_send_msg
            socketutil.SocketUtil.connect = original_connect
            _BAOSTOCK_LOCK.release()


def _is_a_share(code: str) -> bool:
    # Support both baostock native format (sh.601398) and tushare-style suffix (601398.SH)
    code_lower = code.lower()
    return code_lower.startswith(("sh.", "sz.")) or code.upper().endswith((".SZ", ".SH"))


@register
class DataLoader:
    """BaoStock A-share OHLCV loader (free, TCP protocol, no auth)."""

    name = "baostock"
    markets = {"a_share"}
    # BaoStock natively reports volume in single shares; fetch() normalizes
    # to board lots — the A-share canonical unit shared by tencent/eastmoney/
    # akshare/mootdx/tushare (HKUDS/Vibe-Trading#1062).
    volume_units = {"a_share": "lots"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available if baostock is installed."""
        try:
            import baostock  # noqa: F401

            return True
        except ImportError:
            return False

    def __init__(self) -> None:
        pass

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV data via BaoStock.

        Args:
            codes: Symbol list (e.g. ["601595.SH", "000001.SZ"]).
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: Bar size (only 1D supported).
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        # Daily-only API; do not silently return day bars for runner ``1H``/``4H``.
        if str(interval).strip().lower() not in {"1d", "d", "day", "daily"}:
            logger.warning(
                "baostock supports daily bars only; rejecting interval=%r",
                interval,
            )
            return {}

        import baostock as bs

        with _baostock_socket_guard(_read_timeout()) as acquired:
            if not acquired:
                return {}
            lg = bs.login()
            if lg.error_code != "0":
                logger.error("baostock login failed: %s", lg.error_msg)
                return {}

            result: Dict[str, pd.DataFrame] = {}
            try:
                for code in codes:
                    try:
                        df = cached_loader_fetch(
                            source=self.name,
                            symbol=code,
                            timeframe=interval,
                            start_date=start_date,
                            end_date=end_date,
                            fields=None,
                            fetch=lambda code=code: self._fetch_one(bs, code, start_date, end_date),
                        )
                        if df is not None and not df.empty:
                            result[code] = df
                    except Exception as exc:
                        logger.warning("baostock failed for %s: %s", code, exc)
            finally:
                bs.logout()

        return result

    def _fetch_one(
        self,
        bs,
        code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single A-share symbol."""
        if not _is_a_share(code):
            return None

        # Support baostock native format (sh.601398 / sz.000001)
        # and tushare-style suffix (601398.SH / 000001.SZ)
        code_lower = code.lower()
        if code_lower.startswith("sh.") or code_lower.startswith("sz."):
            bs_code = code_lower
        else:
            parts = code.upper().split(".")
            symbol = parts[0]
            suffix = parts[1] if len(parts) > 1 else ""
            if suffix == "SH":
                bs_code = f"sh.{symbol}"
            elif suffix == "SZ":
                bs_code = f"sz.{symbol}"
            else:
                return None

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",  # 前复权
        )

        if rs.error_code != "0":
            logger.warning("baostock query failed for %s: %s", code, rs.error_msg)
            return None

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # BaoStock reports volume in single shares; normalize to board lots
        # (1 lot = 100 shares) to match every other A-share source
        # (HKUDS/Vibe-Trading#1062). Fractional lots are valid — odd-lot
        # trades exist — so no rounding is applied.
        df["volume"] = df["volume"] / 100.0

        df = df.rename(columns={"date": "trade_date"})
        df = df.set_index("trade_date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["open", "high", "low", "close"])
        return df
