"""Crypto perpetual-contract backtest engine.

Market rules:
  - 24/7 trading, no restrictions on direction
  - Maker/Taker fee separation
  - Funding fee settlement every 8 hours (00:00/08:00/16:00 UTC)
  - Forced liquidation when maintenance margin ratio <= 100%
  - Fractional position sizes allowed
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.engines._market_hooks import (
    calc_crypto_funding_fee,
    check_crypto_liquidation,
)
from backtest.perpetual_evidence import (
    SCHEMA_VERSION,
    build_perpetual_summary,
    write_perpetual_evidence,
)
from backtest.perpetual_risk import (
    AccountState,
    CrossMarginRiskModel,
    ExecutionFrame,
    MaintenanceSchedule,
    MarketRiskFrame,
    PositionState,
    RiskSnapshot,
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
        self._validate_strict_resolution(config)
        self.terminal_status = "active"
        self._perpetual_events: list[dict[str, Any]] = []
        self._run_interval = str(config.get("interval", "1D"))
        self._maintenance_bracket_versions: dict[str, str] = {}
        self._market_risk_sources: set[str] = set()
        self._liquidation_price_source: str | None = None
        self._strict_funding_applied: set[tuple[str, pd.Timestamp]] = set()
        self._isolated_margins: dict[str, float] = {}
        self._schedule_cache: dict[tuple[str, str], MaintenanceSchedule] = {}
        self._risk_frames: dict[str, MarketRiskFrame] = {}
        self._blocked_symbols: set[str] = set()
        self._funding_applied: set = set()   # (symbol, date, hour) — per-slot dedup
        self._funding_daily_done: set = set()  # (symbol, date) — daily fallback dedup

    def _validate_strict_resolution(self, config: dict[str, Any]) -> None:
        if not self.perpetual_strict or self.default_leverage < 100:
            return
        interval = str(config.get("interval", "1D")).strip().lower()
        if interval not in {"1m", "5m", "15m", "30m", "1h"}:
            raise ValueError(
                "strict 100x requires a supported interval <= 1H "
                "(1m/5m/15m/30m/1H); 1H is only a resolution boundary, "
                "not a liquidation-sequence guarantee"
            )

    def run_backtest(
        self,
        config: dict[str, Any],
        loader: Any,
        signal_engine: Any,
        run_dir: Path,
        bars_per_year: int = 252,
    ) -> dict[str, Any]:
        self._validate_strict_resolution(config)
        self._run_interval = str(config.get("interval", "1D"))
        return super().run_backtest(config, loader, signal_engine, run_dir, bars_per_year)

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
        previous = self._maintenance_bracket_versions.setdefault(symbol, version)
        if previous != version:
            raise ValueError(f"maintenance bracket version changed for {symbol}")
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
            self._market_risk_sources.add(risks[symbol].source)
        self._risk_frames = risks

    def _record_event(self, timestamp: pd.Timestamp, event_type: str, **details: Any) -> None:
        if not self.perpetual_strict:
            return
        self._perpetual_events.append(
            {
                "schema_version": SCHEMA_VERSION,
                "sequence": len(self._perpetual_events) + 1,
                "timestamp": pd.Timestamp(timestamp).isoformat(),
                "event_type": event_type,
                **details,
            }
        )

    def _record_risk_snapshot(
        self,
        timestamp: pd.Timestamp,
        price_field: str,
        snapshot: RiskSnapshot,
    ) -> None:
        self._record_event(
            timestamp,
            "risk_snapshot",
            phase="pre_fill" if price_field == "mark_open" else "post_fill",
            price_source=("mark_open" if price_field == "mark_open" else "adverse_mark_extrema"),
            status=snapshot.status,
            margin_balance=snapshot.margin_balance,
            initial_margin=snapshot.initial_margin,
            maintenance_margin=snapshot.maintenance_margin,
            available_balance=snapshot.available_balance,
            liquidation_targets=list(snapshot.liquidation_targets),
            fidelity_flags=list(snapshot.fidelity_flags),
            positions=[
                {
                    "symbol": risk.symbol,
                    "mark_price": risk.mark_price,
                    "notional": risk.notional,
                    "unrealized_pnl": risk.unrealized_pnl,
                    "initial_margin": risk.initial_margin,
                    "maintenance_margin": risk.maintenance_margin,
                    "margin_balance": risk.margin_balance,
                }
                for risk in snapshot.per_position
            ],
        )

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
            self._record_event(
                settlement,
                "funding_settlement",
                symbol=symbol,
                signed_quantity=position.direction * position.size,
                mark_price=frame.mark_open,
                price_source="mark_open",
                funding_rate=frame.funding_rate,
                funding_pnl=-payment,
            )

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
        self._record_risk_snapshot(timestamp, price_field, snapshot)
        if snapshot.status == "healthy":
            return False
        prices = {risk.symbol: risk.mark_price for risk in snapshot.per_position}
        price_source = "mark_open" if price_field == "mark_open" else "adverse_mark_extrema"
        liquidation_details = []
        for symbol in snapshot.liquidation_targets:
            position = self.positions[symbol]
            price = prices[symbol]
            fee = position.size * price * self.liquidation_fee_rate
            self._liquidation_price_source = price_source
            try:
                self._close_position(symbol, price, timestamp, snapshot.status)
                self.capital -= fee
            finally:
                self._liquidation_price_source = None
            liquidation_details.append((symbol, price, fee))
        if snapshot.status == "account_liquidation":
            self.terminal_status = "account_liquidation"
            self._record_event(
                timestamp,
                "account_liquidation",
                symbols=sorted(symbol for symbol, _, _ in liquidation_details),
                liquidation_prices={symbol: price for symbol, price, _ in liquidation_details},
                price_source=price_source,
                liquidation_fee=sum(fee for _, _, fee in liquidation_details),
                fidelity_flags=list(snapshot.fidelity_flags),
            )
            return True
        for symbol, price, fee in liquidation_details:
            self._record_event(
                timestamp,
                "position_liquidation",
                symbol=symbol,
                liquidation_price=price,
                price_source=price_source,
                liquidation_fee=fee,
                fidelity_flags=list(snapshot.fidelity_flags),
            )
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
        if self.perpetual_strict:
            self._record_event(
                timestamp,
                "market_fill",
                action="open",
                symbol=order.symbol,
                side="buy" if order.direction == 1 else "sell",
                signed_quantity=order.direction * order.size,
                execution_price=order.price,
                execution_price_source="execution_open",
                trading_fee=order.commission,
                reason="signal",
            )
        if self.perpetual_strict and self.margin_mode == "isolated":
            self._isolated_margins[order.symbol] = order.margin

    def _close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: pd.Timestamp,
        reason: str,
    ) -> None:
        position = self.positions.get(symbol)
        super()._close_position(symbol, exit_price, exit_time, reason)
        if self.perpetual_strict and position is not None:
            trade = self.trades[-1]
            price_source = self._liquidation_price_source
            if price_source is None:
                price_source = "mark_close" if reason == "end_of_backtest" else "execution_open"
            self._record_event(
                exit_time,
                "market_fill",
                action="close",
                symbol=symbol,
                side="sell" if position.direction == 1 else "buy",
                signed_quantity=-position.direction * position.size,
                execution_price=exit_price,
                execution_price_source=price_source,
                trading_fee=trade.commission - position.entry_commission,
                reason=reason,
            )
        self._isolated_margins.pop(symbol, None)

    def _write_artifacts(
        self,
        run_dir: Path,
        data_map: dict[str, pd.DataFrame],
        dates: pd.DatetimeIndex,
        equity_series: pd.Series,
        bench_equity: pd.Series,
        bench_ret: pd.Series,
        target_pos: pd.DataFrame,
        metrics: dict,
        codes: list[str],
    ) -> None:
        summary = None
        if self.perpetual_strict:
            summary = build_perpetual_summary(
                config={**self.config, "interval": self._run_interval},
                events=self._perpetual_events,
                trades=self.trades,
                terminal_status=self.terminal_status,
                maintenance_bracket_versions=self._maintenance_bracket_versions,
                market_risk_sources=sorted(self._market_risk_sources),
            )
            metrics.update(
                {
                    "perpetual_funding_settlements": summary["funding_settlement_count"],
                    "perpetual_funding_pnl": summary["total_funding_pnl"],
                    "perpetual_liquidation_events": summary["liquidation_event_count"],
                    "perpetual_liquidated_positions": summary["liquidated_position_count"],
                    "perpetual_trading_fees": summary["total_trading_fee"],
                    "perpetual_liquidation_fees": summary["total_liquidation_fee"],
                }
            )
        super()._write_artifacts(
            run_dir,
            data_map,
            dates,
            equity_series,
            bench_equity,
            bench_ret,
            target_pos,
            metrics,
            codes,
        )
        if summary is not None:
            write_perpetual_evidence(run_dir, self._perpetual_events, summary)

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
