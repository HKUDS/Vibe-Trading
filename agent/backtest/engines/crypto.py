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
    AccountState,
    CrossMarginRiskModel,
    ExecutionFrame,
    MaintenanceSchedule,
    MarketRiskFrame,
    PositionState,
    evaluate_isolated,
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
        self.liquidation_fee_rate = float(config.get("liquidation_fee_rate", 0.0))
        if self.perpetual_strict and self.funding_mode != "data":
            raise ValueError("perpetual_strict requires funding_mode='data'")
        if self.perpetual_strict and self.margin_mode not in {"isolated", "cross"}:
            raise ValueError("margin_mode must be 'isolated' or 'cross'")
        if self.perpetual_strict and not 0 <= self.liquidation_fee_rate < 1:
            raise ValueError("liquidation_fee_rate must be between zero and one")
        self.terminal_status = "active"
        self._strict_funding_applied: set[tuple[str, pd.Timestamp]] = set()
        self._isolated_margins: dict[str, float] = {}
        self._schedule_cache: dict[tuple[str, str], MaintenanceSchedule] = {}
        self._risk_frames: dict[str, MarketRiskFrame] = {}
        self._blocked_symbols: set[str] = set()
        self._funding_applied: set = set()   # (symbol, date, hour) — per-slot dedup
        self._funding_daily_done: set = set()  # (symbol, date) — daily fallback dedup

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Crypto: 24/7, long/short/close all allowed."""
        return not (self.perpetual_strict and symbol in self._blocked_symbols)

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
        version = bar["maintenance_bracket_version"]
        if pd.isna(version):
            raise ValueError(f"missing maintenance bracket version for {symbol}")
        version = str(version)
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
        risks: dict[str, MarketRiskFrame] = {}
        for symbol in codes:
            frame = data_map.get(symbol)
            if frame is None or timestamp not in frame.index:
                raise ValueError(f"missing synchronized frame for {symbol} at {timestamp}")
            bar = frame.loc[timestamp]
            if not isinstance(bar, pd.Series):
                raise ValueError(f"duplicate frame timestamp for {symbol} at {timestamp}")
            ExecutionFrame(timestamp, float(bar["execution_open"]))
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
                position.direction * position.size * frame.mark_open
                * float(frame.funding_rate)
            )
            self.capital -= payment
            if self.margin_mode == "isolated":
                self._isolated_margins[symbol] -= payment
            self._strict_funding_applied.add(key)

    def _account_state(self) -> AccountState:
        positions = tuple(
            PositionState(
                symbol=symbol,
                quantity=position.direction * position.size,
                entry_price=position.entry_price,
                leverage=position.leverage,
                accumulated_entry_fee=position.entry_commission,
                isolated_margin=self._isolated_margins.get(symbol),
            )
            for symbol, position in self.positions.items()
        )
        locked_margin = sum(
            self._calc_margin(
                position.symbol, position.size, position.entry_price, position.leverage
            )
            for position in self.positions.values()
        )
        return AccountState(
            wallet_balance=self.capital + locked_margin,
            positions=positions,
            margin_mode=self.margin_mode,
            terminal_status=self.terminal_status,
        )

    def _evaluate_and_liquidate(
        self, timestamp: pd.Timestamp, price_field: str
    ) -> bool:
        if not self.positions:
            return False
        account = self._account_state()
        snapshot = (
            evaluate_isolated(account, self._risk_frames, price_field)
            if self.margin_mode == "isolated"
            else CrossMarginRiskModel().evaluate(account, self._risk_frames, price_field)
        )
        if snapshot.status == "healthy":
            return False
        prices = {risk.symbol: risk.mark_price for risk in snapshot.per_position}
        for symbol in snapshot.liquidation_targets:
            position = self.positions[symbol]
            price = prices[symbol]
            fee = position.size * price * self.liquidation_fee_rate
            self._close_position(symbol, price, timestamp, snapshot.status)
            self.capital -= fee
        if snapshot.status == "account_liquidation":
            self.terminal_status = "account_liquidation"
            return True
        self._blocked_symbols.update(snapshot.liquidation_targets)
        return False

    def before_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> bool:
        if not self.perpetual_strict:
            return super().before_rebalance_bar(timestamp, data_map, codes)
        self._blocked_symbols.clear()
        self._build_strict_frames(timestamp, data_map, codes)
        self._apply_data_funding()
        return self._evaluate_and_liquidate(timestamp, "mark_open")

    def after_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> bool:
        if not self.perpetual_strict:
            return super().after_rebalance_bar(timestamp, data_map, codes)
        return self._evaluate_and_liquidate(timestamp, "adverse")

    def _execute_bars(self, dates, data_map, close_df, target_pos, codes) -> None:
        if self.perpetual_strict:
            try:
                close_df = pd.DataFrame(
                    {symbol: data_map[symbol]["mark_close"] for symbol in codes}, index=dates
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
