"""Vietnam VN30 index futures backtest engine (HNX).

Contracts: VN30F1M, VN30F2M, VN30F1Q, VN30F2Q (multiplier 100k VND/point).
Initial margin 17% (exchange min 13%), maintenance 80% of initial. Daily MTM
at bar close, cash settlement at expiry (3rd Thursday of contract month).
Price band +/-7%; tax 0.1% per side on notional (MoF 100/2017/TT-BTC); position
limit 5000 per individual; T+0; long/short symmetric.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd

from backtest.engines.futures_base import FuturesBaseEngine


_VN30F_RE = re.compile(r"^VN30F[12][MQ](\.HNX)?$", re.IGNORECASE)
_KNOWN_CONTRACTS = ("VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q")
_QUARTER_MONTHS = (3, 6, 9, 12)


def _is_vn30f(symbol: str) -> bool:
    return bool(_VN30F_RE.match(symbol or ""))


def _strip_hnx(symbol: str) -> str:
    s = (symbol or "").upper()
    return s[:-4] if s.endswith(".HNX") else s


def _third_thursday(year: int, month: int) -> date:
    """3rd Thursday of given month -- VN30F expiry day."""
    first = date(year, month, 1)
    offset = (3 - first.weekday()) % 7  # Thursday is weekday 3
    return first + timedelta(days=offset + 14)


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (y, m) for ``year/month + delta``."""
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, (idx % 12) + 1


def _contract_month(symbol: str, current_date: date) -> tuple[int, int]:
    """Decode a VN30F code into (year, month) of expiry on *current_date*.

    F1M: this month if today <= 3rd Thu else next month. F2M: F1M + 1m.
    F1Q: nearest quarter (Mar/Jun/Sep/Dec) >= this month; advance one quarter
    if today > 3rd Thu of a quarter month. F2Q: F1Q + 3m.
    """
    code = _strip_hnx(symbol)[len("VN30"):]
    y, m = current_date.year, current_date.month
    if code == "F1M":
        return (y, m) if current_date <= _third_thursday(y, m) else _add_months(y, m, 1)
    if code == "F2M":
        return _add_months(*_contract_month("VN30F1M", current_date), 1)
    if code == "F1Q":
        eff_y, eff_m = (y, m)
        if m in _QUARTER_MONTHS and current_date > _third_thursday(y, m):
            eff_y, eff_m = _add_months(y, m, 1)
        for qm in _QUARTER_MONTHS:
            if qm >= eff_m:
                return eff_y, qm
        return eff_y + 1, _QUARTER_MONTHS[0]
    if code == "F2Q":
        return _add_months(*_contract_month("VN30F1Q", current_date), 3)
    raise ValueError(f"Unknown VN30F code: {symbol!r}")


def _bar_date(bar) -> date | None:
    """Extract date from a bar Series (OHLCV row OR close-only row)."""
    if bar is None:
        return None
    if hasattr(bar, "name") and hasattr(bar.name, "date"):
        try:
            return bar.name.date()
        except Exception:
            pass
    for col in ("trade_date", "date"):
        try:
            if col in bar.index:
                val = bar[col]
                return val.date() if hasattr(val, "date") else pd.Timestamp(val).date()
        except Exception:
            pass
    return None


def _calc_pct_change(bar: pd.Series):
    """Bar pct-change; None if not derivable."""
    try:
        if "pct_chg" in bar.index and pd.notna(bar["pct_chg"]):
            return float(bar["pct_chg"]) / 100.0
    except Exception:
        pass
    close = bar.get("close") if hasattr(bar, "get") else None
    pre_close = bar.get("pre_close") if hasattr(bar, "get") else None
    if close is not None and pre_close is not None and float(pre_close) > 0:
        return (float(close) - float(pre_close)) / float(pre_close)
    return None


class VNFuturesEngine(FuturesBaseEngine):
    """VN30 index futures engine (HNX). See module docstring for spec.

    Config keys: ``margin_rate`` (0.17), ``maintenance_ratio`` (0.80),
    ``commission_per_contract`` (2700 VND), ``tax_rate`` (0.001),
    ``price_band`` (0.07), ``position_limit`` (5000), ``slippage`` (0.0).
    """

    CONTRACT_MULTIPLIER: float = 100_000.0
    KNOWN_CONTRACTS: tuple[str, ...] = _KNOWN_CONTRACTS

    def __init__(self, config: dict):
        margin_rate = float(config.get("margin_rate", 0.17))
        if margin_rate <= 0:
            raise ValueError("margin_rate must be positive")
        super().__init__({**config, "leverage": 1.0 / margin_rate})
        self.margin_rate = margin_rate
        self.maintenance_ratio = float(config.get("maintenance_ratio", 0.80))
        self.commission_per_contract = float(config.get("commission_per_contract", 2700.0))
        self.tax_rate = float(config.get("tax_rate", 0.001))
        self.price_band = float(config.get("price_band", 0.07))
        self.position_limit = int(config.get("position_limit", 5000))
        self.slippage_rate = float(config.get("slippage", 0.0))
        self._prior_settle: dict[str, float] = {}
        self._pending_liquidation: set[str] = set()
        self._expired: set[str] = set()
        self.settlements: list[dict] = []

    def get_contract_multiplier(self, symbol: str) -> float:
        if not _is_vn30f(symbol):
            raise ValueError(f"Unknown VN30F contract: {symbol!r}")
        return self.CONTRACT_MULTIPLIER

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """T+0, long/short symmetric, +/-7% band, expiry/margin-call gates."""
        if not _is_vn30f(symbol):
            return False
        canonical = _strip_hnx(symbol)
        if canonical in self._expired:
            return False
        # Margin call: only allow closing leg.
        if canonical in self._pending_liquidation:
            if direction != 0 or self.positions.get(symbol) is None:
                return False
        pct_chg = _calc_pct_change(bar)
        if pct_chg is not None:
            band = self.price_band
            if direction == 1 and pct_chg >= band - 0.001:
                return False
            if direction == -1 and pct_chg <= -band + 0.001:
                return False
            if direction == 0:
                pos = self.positions.get(symbol)
                if pos is not None:
                    if pos.direction == 1 and pct_chg <= -band + 0.001:
                        return False
                    if pos.direction == -1 and pct_chg >= band - 0.001:
                        return False
        # Position limit on opens.
        if direction in (1, -1):
            total = sum(abs(p.size) for p in self.positions.values() if _is_vn30f(p.symbol))
            if total >= self.position_limit:
                return False
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        return float(max(int(abs(raw_size)), 0))

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool,
    ) -> float:
        """Per-contract commission + 0.1% tax on notional (per side)."""
        contracts = abs(size)
        notional = contracts * price * self.CONTRACT_MULTIPLIER
        return contracts * self.commission_per_contract + notional * self.tax_rate

    def apply_slippage(self, price: float, direction: int) -> float:
        return price * (1 + direction * self.slippage_rate)

    def _after_bar_close(self, bar) -> None:
        """Daily MTM, margin-call check, and expiry handling.

        ``bar`` is a Series of close prices indexed by symbol (``bar.name`` =
        timestamp), or ``None``.
        """
        if bar is None or not self.positions:
            return
        bar_date = _bar_date(bar)
        if bar_date is None:
            return

        for symbol, pos in list(self.positions.items()):
            if not _is_vn30f(symbol):
                continue
            canonical = _strip_hnx(symbol)
            if canonical in self._expired:
                continue
            try:
                close_val = bar[symbol]
            except (KeyError, IndexError):
                continue
            if pd.isna(close_val):
                continue
            close = float(close_val)
            if close <= 0:
                continue

            # Daily MTM: realise PnL vs prior settle (or entry on first day).
            prior = self._prior_settle.get(symbol, pos.entry_price)
            daily_pnl = (
                pos.direction * pos.size * self.CONTRACT_MULTIPLIER * (close - prior)
            )
            self.capital += daily_pnl
            self._prior_settle[symbol] = close
            self.settlements.append({
                "type": "mtm", "symbol": symbol, "date": bar_date,
                "close": close, "prior_settle": prior, "pnl": daily_pnl,
            })

            # Margin call: free capital below maintenance threshold.
            notional = abs(pos.size) * close * self.CONTRACT_MULTIPLIER
            required = notional * self.margin_rate * self.maintenance_ratio
            if self.capital < required:
                self._pending_liquidation.add(canonical)
                self.settlements.append({
                    "type": "margin_call", "symbol": symbol, "date": bar_date,
                    "capital": self.capital, "required": required,
                })

            # Expiry: cash-settle and remove position. Daily MTM above already
            # realised P&L to *close*; release margin back to capital.
            y, m = _contract_month(symbol, bar_date)
            if bar_date >= _third_thursday(y, m):
                self._expired.add(canonical)
                self.settlements.append({
                    "type": "expiry_settlement", "symbol": symbol,
                    "date": bar_date, "settle_price": close,
                })
                margin = self._calc_margin(
                    symbol, pos.size, pos.entry_price, pos.leverage,
                )
                self.capital += margin
                del self.positions[symbol]
                self._prior_settle.pop(symbol, None)
                self._pending_liquidation.discard(canonical)
