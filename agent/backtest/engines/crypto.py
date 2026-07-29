"""Crypto perpetual-contract backtest engine.

Market rules:
  - 24/7 trading, no restrictions on direction
  - Maker/Taker fee separation
  - Funding fee settlement every 8 hours (00:00/08:00/16:00 UTC)
  - Forced liquidation when maintenance margin ratio <= 100%
  - Fractional position sizes allowed
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.engines._market_hooks import (
    calc_crypto_funding_fee,
    check_crypto_liquidation,
)
from backtest.perpetual_risk import (
    ExecutionFrame,
    MaintenanceSchedule,
    MarketRiskFrame,
)


class CryptoEngine(BaseEngine):
    """Crypto perpetual contract engine.

    Config keys:
      - leverage: default 1.0
      - maker_rate: default 0.0002
      - taker_rate: default 0.0005
      - slippage: default 0.0005
      - margin_mode: "isolated" (default) or "cross"
      - funding_rate: fixed rate per settlement, default 0.0001
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.maker_rate: float = config.get("maker_rate", 0.0002)
        self.taker_rate: float = config.get("taker_rate", 0.0005)
        self.slippage_rate: float = config.get("slippage", 0.0005)
        self.funding_rate: float = config.get("funding_rate", 0.0001)
        self.perpetual_strict = bool(config.get("perpetual_strict", False))
        self.funding_mode = str(config.get("funding_mode", "fixed"))
        self.margin_mode = str(config.get("margin_mode", "isolated"))
        if self.perpetual_strict and self.funding_mode != "data":
            raise ValueError("perpetual_strict requires funding_mode='data'")
        if self.perpetual_strict and self.margin_mode not in {"isolated", "cross"}:
            raise ValueError("margin_mode must be 'isolated' or 'cross'")
        self.terminal_status = "active"
        self._strict_funding_applied: set[tuple[str, pd.Timestamp]] = set()
        self._isolated_margins: dict[str, float] = {}
        self._schedule_cache: dict[tuple[str, str], MaintenanceSchedule] = {}
        self._execution_frames: dict[str, ExecutionFrame] = {}
        self._risk_frames: dict[str, MarketRiskFrame] = {}
        self._current_mark_prices: dict[str, float] = {}
        self._funding_applied: set = set()   # (symbol, date, hour) — per-slot dedup
        self._funding_daily_done: set = set()  # (symbol, date) — daily fallback dedup

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Crypto: 24/7, long/short/close all allowed."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Crypto supports fractional sizes, round to 6 decimals."""
        return round(max(raw_size, 0.0), 6)

    def calc_commission(self, size: float, price: float, _direction: int, is_open: bool) -> float:
        """Maker/Taker separated. Opens typically hit taker, closes hit maker.

        ``_direction`` is unused — reserved for future funding-rate asymmetry
        between long/short legs on perp swaps.
        """
        rate = self.taker_rate if self.perpetual_strict or is_open else self.maker_rate
        return size * price * rate

    def apply_slippage(self, price: float, direction: int) -> float:
        """Slippage: unfavourable direction."""
        return price * (1 + direction * self.slippage_rate)

    def execution_open(self, bar: pd.Series) -> float:
        if not self.perpetual_strict:
            return super().execution_open(bar)
        return ExecutionFrame(bar.name, float(bar["execution_open"])).execution_open

    def valuation_open(self, bar: pd.Series) -> float:
        if not self.perpetual_strict:
            return super().valuation_open(bar)
        return float(bar["mark_open"])

    def _schedule(self, symbol: str, bar: pd.Series) -> MaintenanceSchedule:
        version = str(bar["maintenance_bracket_version"])
        key = (symbol, version)
        if key not in self._schedule_cache:
            self._schedule_cache[key] = MaintenanceSchedule.from_loader_columns(
                symbol, bar["maintenance_brackets"], version
            )
        return self._schedule_cache[key]

    def _build_strict_frames(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> None:
        executions: dict[str, ExecutionFrame] = {}
        risks: dict[str, MarketRiskFrame] = {}
        for symbol in codes:
            frame = data_map.get(symbol)
            if frame is None or timestamp not in frame.index:
                raise ValueError(f"missing synchronized frame for {symbol} at {timestamp}")
            bar = frame.loc[timestamp]
            if not isinstance(bar, pd.Series):
                raise ValueError(f"duplicate frame timestamp for {symbol} at {timestamp}")
            executions[symbol] = ExecutionFrame(
                timestamp, float(bar["execution_open"])
            )
            rate = bar["funding_rate"]
            settlement = bar["funding_settlement_time"]
            if pd.isna(rate):
                raise ValueError(f"missing funding rate for {symbol} at {timestamp}")
            if pd.isna(settlement):
                if float(rate) != 0.0:
                    raise ValueError(
                        f"funding rate without settlement for {symbol} at {timestamp}"
                    )
                funding_rate = funding_time = None
            else:
                funding_rate = float(rate)
                funding_time = pd.Timestamp(settlement)
            risks[symbol] = MarketRiskFrame(
                timestamp=timestamp,
                mark_open=float(bar["mark_open"]),
                mark_high=float(bar["mark_high"]),
                mark_low=float(bar["mark_low"]),
                mark_close=float(bar["mark_close"]),
                funding_rate=funding_rate,
                funding_settlement_time=funding_time,
                schedule=self._schedule(symbol, bar),
                source=str(self.config.get("market_risk_source", "ccxt:binanceusdm")),
            )
        self._execution_frames = executions
        self._risk_frames = risks

    def _apply_data_funding(self) -> None:
        for symbol, position in self.positions.items():
            frame = self._risk_frames[symbol]
            settlement = frame.funding_settlement_time
            if settlement is None or position.entry_time >= settlement:
                continue
            key = (symbol, settlement)
            if key in self._strict_funding_applied:
                continue
            payment = (
                position.direction
                * position.size
                * frame.mark_open
                * float(frame.funding_rate)
            )
            self.capital -= payment
            if self.margin_mode == "isolated":
                self._isolated_margins[symbol] -= payment
            self._strict_funding_applied.add(key)

    def before_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> bool:
        if not self.perpetual_strict:
            return super().before_rebalance_bar(timestamp, data_map, codes)
        self._build_strict_frames(timestamp, data_map, codes)
        self._current_mark_prices = {
            symbol: frame.mark_open for symbol, frame in self._risk_frames.items()
        }
        self._apply_data_funding()
        return False

    def after_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> bool:
        if not self.perpetual_strict:
            return super().after_rebalance_bar(timestamp, data_map, codes)
        self._current_mark_prices = {
            symbol: frame.mark_close for symbol, frame in self._risk_frames.items()
        }
        return False

    def _execute_bars(self, dates, data_map, close_df, target_pos, codes) -> None:
        if self.perpetual_strict:
            try:
                close_df = pd.DataFrame(
                    {symbol: data_map[symbol]["mark_close"] for symbol in codes},
                    index=dates,
                )
            except KeyError as exc:
                raise ValueError(f"missing strict mark-close data: {exc}") from exc
        super()._execute_bars(dates, data_map, close_df, target_pos, codes)
        if self.perpetual_strict and self.terminal_status == "active":
            self.terminal_status = "completed"

    def _execute_open_order(self, order, timestamp: pd.Timestamp) -> None:
        super()._execute_open_order(order, timestamp)
        if self.perpetual_strict and self.margin_mode == "isolated":
            self._isolated_margins[order.symbol] = order.margin

    def _close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: pd.Timestamp,
        reason: str,
    ) -> None:
        super()._close_position(symbol, exit_price, exit_time, reason)
        self._isolated_margins.pop(symbol, None)

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Crypto per-bar hooks: funding fee + liquidation check."""
        fee = calc_crypto_funding_fee(
            symbol, bar, timestamp, self.positions,
            self.funding_rate, self._funding_applied, self._funding_daily_done,
        )
        self.capital -= fee

        if check_crypto_liquidation(symbol, bar, self.positions):
            pos = self.positions.get(symbol)
            if pos is not None:
                mark_price = float(bar.get("close", pos.entry_price))
                liq_price = self.apply_slippage(mark_price, -pos.direction)
                self._close_position(symbol, liq_price, timestamp, "liquidation")
